from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from app import betting_config as cfg
from app.database import Database
from app.services.server_settings import ServerSettingsService


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _seed_int(*parts: object) -> int:
    raw = "|".join(str(x) for x in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def _poisson_pmf(lmbda: float, k: int) -> float:
    return math.exp(-lmbda) * (lmbda ** k) / math.factorial(k)


def _poisson_sample(rng: random.Random, lmbda: float) -> int:
    # Knuth sampler is perfectly adequate for football-sized lambdas.
    limit = math.exp(-lmbda)
    product = 1.0
    k = 0
    while product > limit and k < 16:
        k += 1
        product *= rng.random()
    return max(0, k - 1)


def _decimal_odds(probability: float, *, margin: float = 1.07, maximum: float = 50.0) -> float:
    # Preserve the intended house edge even on heavy favourites/longshots.
    # The previous 0.8% probability floor + 1.02 minimum odds created both
    # punitive longshots and a tiny >100% RTP edge on extreme handicap picks.
    probability = max(0.001, min(0.99, probability))
    return round(max(1.01, min(maximum, 1.0 / (probability * margin))), 2)


def _horse_odds(probability: float, *, margin: float, maximum: float) -> float:
    probability=max(0.008,min(0.985,probability))
    return round(max(1.02,min(maximum,1.0/(probability*margin))),2)


def _score_distribution(home_xg: float, away_xg: float, max_goals: int = 8) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = {}
    total = 0.0
    for h in range(max_goals + 1):
        hp = _poisson_pmf(home_xg, h)
        for a in range(max_goals + 1):
            p = hp * _poisson_pmf(away_xg, a)
            out[(h, a)] = p
            total += p
    if total > 0:
        for key in list(out):
            out[key] /= total
    return out



def _plackett_luce_top_probabilities(weights: list[float]) -> list[tuple[float, float, float]]:
    """Exact win/top2/top3 probabilities for weighted sampling without replacement."""
    n=len(weights); out=[[0.0,0.0,0.0] for _ in range(n)]
    for perm in itertools.permutations(range(n)):
        remaining=sum(weights); mass=1.0
        for idx in perm:
            mass*=weights[idx]/remaining; remaining-=weights[idx]
        for pos,idx in enumerate(perm[:3]):
            if pos==0: out[idx][0]+=mass
            if pos<=1: out[idx][1]+=mass
            if pos<=2: out[idx][2]+=mass
    return [(x[0],x[1],x[2]) for x in out]

def _market_option(key: str, label: str, odds: float) -> dict[str, Any]:
    return {"selection_key": key, "label": label, "odds": round(float(odds), 2)}


def build_market_odds(home: str, away: str, home_rating: int, away_rating: int) -> dict[str, list[dict[str, Any]]]:
    diff = int(home_rating) - int(away_rating)
    home_xg = max(0.45, min(3.25, 1.48 + diff / 52.0))
    away_xg = max(0.35, min(2.85, 1.12 - diff / 62.0))
    dist = _score_distribution(home_xg, away_xg)

    p_home = sum(p for (h, a), p in dist.items() if h > a)
    p_draw = sum(p for (h, a), p in dist.items() if h == a)
    p_away = max(0.001, 1.0 - p_home - p_draw)
    p_btts = sum(p for (h, a), p in dist.items() if h > 0 and a > 0)

    groups: dict[str, list[dict[str, Any]]] = {}
    groups["1x2"] = [
        _market_option("H", f"{home} győz", _decimal_odds(p_home)),
        _market_option("D", "Döntetlen", _decimal_odds(p_draw)),
        _market_option("A", f"{away} győz", _decimal_odds(p_away)),
    ]
    groups["double"] = [
        _market_option("1X", "Hazai vagy döntetlen", _decimal_odds(p_home + p_draw, margin=1.055, maximum=8)),
        _market_option("X2", "Döntetlen vagy vendég", _decimal_odds(p_draw + p_away, margin=1.055, maximum=8)),
        _market_option("12", "Nem lesz döntetlen", _decimal_odds(p_home + p_away, margin=1.055, maximum=8)),
    ]
    goal_options: list[dict[str, Any]] = []
    for line in (1.5, 2.5, 3.5, 4.5):
        threshold = int(math.floor(line))
        p_over = sum(p for (h, a), p in dist.items() if h + a > threshold)
        goal_options.append(_market_option(f"O{line}", f"Over {line}", _decimal_odds(p_over, maximum=12)))
        goal_options.append(_market_option(f"U{line}", f"Under {line}", _decimal_odds(1 - p_over, maximum=12)))
    groups["goals"] = goal_options
    groups["btts"] = [
        _market_option("Y", "Mindkét csapat szerez gólt: Igen", _decimal_odds(p_btts, maximum=10)),
        _market_option("N", "Mindkét csapat szerez gólt: Nem", _decimal_odds(1 - p_btts, maximum=10)),
    ]
    non_draw = max(0.001, p_home + p_away)
    groups["dnb"] = [
        _market_option("H", f"{home} • DNB", _decimal_odds(p_home / non_draw, margin=1.055, maximum=50)),
        _market_option("A", f"{away} • DNB", _decimal_odds(p_away / non_draw, margin=1.055, maximum=50)),
    ]

    ht_dist = _score_distribution(max(0.2, home_xg * 0.46), max(0.18, away_xg * 0.46), 5)
    ht_home = sum(p for (h, a), p in ht_dist.items() if h > a)
    ht_draw = sum(p for (h, a), p in ht_dist.items() if h == a)
    ht_away = max(0.001, 1 - ht_home - ht_draw)
    groups["half"] = [
        _market_option("H", "Félidő: hazai", _decimal_odds(ht_home, maximum=30)),
        _market_option("D", "Félidő: döntetlen", _decimal_odds(ht_draw, maximum=30)),
        _market_option("A", "Félidő: vendég", _decimal_odds(ht_away, maximum=30)),
    ]

    p_home_cover = sum(p for (h, a), p in dist.items() if h - a >= 2)
    p_away_cover = 1 - p_home_cover
    groups["handicap"] = [
        _market_option("H-1.5", f"{home} -1.5", _decimal_odds(p_home_cover, maximum=60)),
        _market_option("A+1.5", f"{away} +1.5", _decimal_odds(p_away_cover, maximum=60)),
    ]

    score_options: list[dict[str, Any]] = []
    for h in range(5):
        for a in range(5):
            probability=dist.get((h,a),0.0)
            # Do not offer absurd near-impossible scores at fake 50x odds.
            # Offered correct-score selections target ~90.9% RTP; truly tiny
            # probabilities are omitted instead of being silently underpaid.
            if probability < 0.004:
                continue
            score_options.append(_market_option(f"{h}-{a}", f"Pontos eredmény: {h}-{a}", _decimal_odds(probability, margin=1.10, maximum=250)))
    groups["score"] = score_options
    return groups


def evaluate_leg(market_key: str, selection_key: str, h: int, a: int, ht_h: int, ht_a: int) -> str:
    if market_key == "1x2":
        outcome = "H" if h > a else "A" if a > h else "D"
        return "win" if selection_key == outcome else "loss"
    if market_key == "double":
        ok = (selection_key == "1X" and h >= a) or (selection_key == "X2" and a >= h) or (selection_key == "12" and h != a)
        return "win" if ok else "loss"
    if market_key == "goals":
        try:
            line = float(selection_key[1:])
        except ValueError:
            return "loss"
        total = h + a
        ok = total > line if selection_key.startswith("O") else total < line
        return "win" if ok else "loss"
    if market_key == "btts":
        yes = h > 0 and a > 0
        return "win" if ((selection_key == "Y") == yes) else "loss"
    if market_key == "dnb":
        if h == a:
            return "void"
        outcome = "H" if h > a else "A"
        return "win" if selection_key == outcome else "loss"
    if market_key == "half":
        outcome = "H" if ht_h > ht_a else "A" if ht_a > ht_h else "D"
        return "win" if selection_key == outcome else "loss"
    if market_key == "handicap":
        if selection_key == "H-1.5":
            return "win" if h - a >= 2 else "loss"
        return "win" if a + 1.5 > h else "loss"
    if market_key == "score":
        return "win" if selection_key == f"{h}-{a}" else "loss"
    return "loss"


@dataclass(frozen=True, slots=True)
class TicketSettlement:
    ticket_id: int
    guild_id: int
    user_id: int
    status: str
    total_stake: int
    payout: int
    bet_type: str


@dataclass(frozen=True, slots=True)
class HorseSettlement:
    bet_id: int
    race_id: int
    guild_id: int
    user_id: int
    status: str
    stake: int
    payout: int
    horse_name: str
    market: str


class BettingService:
    def __init__(self, db: Database, statistics=None) -> None:
        self.db = db
        self.settings = ServerSettingsService(db)
        self.statistics = statistics

    async def enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.BETTING_ENABLED_KEY, True)

    async def tippmix_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.BETTING_TIPPMIX_ENABLED_KEY, True)

    async def horse_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.BETTING_HORSE_ENABLED_KEY, True)

    async def dm_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.BETTING_DM_ENABLED_KEY, True)

    async def min_stake(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.BETTING_MIN_STAKE_KEY)
        return max(1_000, int(value if value is not None else cfg.DEFAULT_MIN_STAKE))

    async def max_legs(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.BETTING_MAX_LEGS_KEY)
        return max(1, min(20, int(value if value is not None else cfg.DEFAULT_MAX_LEGS)))

    async def max_payout(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.BETTING_MAX_PAYOUT_KEY)
        return max(100_000, int(value if value is not None else cfg.DEFAULT_MAX_PAYOUT))

    async def daily_match_count(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.BETTING_DAILY_MATCHES_KEY)
        return max(cfg.MIN_DAILY_MATCHES, min(cfg.MAX_DAILY_MATCHES, int(value if value is not None else cfg.DEFAULT_DAILY_MATCHES)))

    async def horse_interval_hours(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.BETTING_HORSE_INTERVAL_KEY)
        return max(1, min(24, int(value if value is not None else cfg.DEFAULT_HORSE_INTERVAL_HOURS)))

    async def horse_close_minutes(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.BETTING_HORSE_CLOSE_MINUTES_KEY)
        return max(1, min(30, int(value if value is not None else cfg.DEFAULT_HORSE_CLOSE_MINUTES)))

    async def ensure_daily_matches(self, guild_id: int, *, now: datetime | None = None) -> str:
        now = now or utcnow()
        cycle_key = now.strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM betting_matches WHERE guild_id=? AND cycle_key=?", (guild_id, cycle_key))
            if int((await cur.fetchone())[0]) > 0:
                return cycle_key

        count = await self.daily_match_count(guild_id)
        rng = random.Random(_seed_int("tippmix", guild_id, cycle_key))
        leagues = list(cfg.LEAGUES.items())
        generated: list[tuple] = []
        league_cursor = 0
        used_pairs: set[tuple[str, str, str]] = set()
        day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        # Slots span the day; if a schedule is first opened late, already-started games
        # are still useful as today's results and are settled by the worker immediately.
        slots = [day_start + timedelta(minutes=10 * 60 + i * 25) for i in range(34)]
        rng.shuffle(slots)

        attempts = 0
        while len(generated) < count and attempts < count * 30:
            attempts += 1
            league, teams = leagues[league_cursor % len(leagues)]
            league_cursor += 1
            home, away = rng.sample(list(teams), 2)
            pair = (league, home.name, away.name)
            reverse = (league, away.name, home.name)
            if pair in used_pairs or reverse in used_pairs:
                continue
            used_pairs.add(pair)
            kickoff = slots[len(generated) % len(slots)] + timedelta(minutes=(len(generated) // len(slots)) * 7)
            odds = build_market_odds(home.name, away.name, home.rating, away.rating)
            seed = hashlib.sha256(f"{guild_id}|{cycle_key}|{league}|{home.name}|{away.name}".encode()).hexdigest()[:24]
            generated.append((guild_id, cycle_key, league, home.name, away.name, home.rating, away.rating, iso(kickoff), json.dumps(odds, ensure_ascii=False, separators=(",", ":")), seed))

        async with aiosqlite.connect(self.db.path) as conn:
            await conn.executemany(
                """INSERT OR IGNORE INTO betting_matches
                   (guild_id,cycle_key,league,home,away,home_rating,away_rating,kickoff_at,odds_json,seed)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                generated,
            )
            await conn.commit()
        return cycle_key

    async def leagues_for_cycle(self, guild_id: int, cycle_key: str) -> list[tuple[str, int]]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT league,COUNT(*) FROM betting_matches WHERE guild_id=? AND cycle_key=? GROUP BY league ORDER BY league",
                (guild_id, cycle_key),
            )
            return [(str(r[0]), int(r[1])) for r in await cur.fetchall()]

    async def matches(self, guild_id: int, cycle_key: str, *, league: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM betting_matches WHERE guild_id=? AND cycle_key=?"
        params: list[Any] = [guild_id, cycle_key]
        if league:
            sql += " AND league=?"; params.append(league)
        sql += " ORDER BY kickoff_at,match_id"
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(sql, tuple(params))
            rows = [dict(r) for r in await cur.fetchall()]
        for row in rows:
            row["odds"] = json.loads(row.pop("odds_json") or "{}")
        return rows

    async def get_match(self, guild_id: int, match_id: int) -> dict[str, Any]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute("SELECT * FROM betting_matches WHERE guild_id=? AND match_id=?", (guild_id, match_id))
            row = await cur.fetchone()
        if row is None:
            raise ValueError("Ez a meccs már nem elérhető.")
        data = dict(row); data["odds"] = json.loads(data.pop("odds_json") or "{}")
        return data

    async def draft(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                """SELECT d.*,m.home,m.away,m.league,m.kickoff_at,m.status match_status
                   FROM betting_draft_legs d JOIN betting_matches m ON m.match_id=d.match_id
                   WHERE d.guild_id=? AND d.user_id=? ORDER BY d.added_at,d.match_id""",
                (guild_id, user_id),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def add_draft_leg(self, guild_id: int, user_id: int, match_id: int, market_key: str, selection_key: str) -> dict[str, Any]:
        if not await self.enabled(guild_id) or not await self.tippmix_enabled(guild_id):
            raise ValueError("A Tippmix ezen a szerveren ki van kapcsolva.")
        match = await self.get_match(guild_id, match_id)
        if match["status"] != "open" or utcnow() >= parse_dt(match["kickoff_at"]):
            raise ValueError("Erre a meccsre már lezárult a fogadás.")
        group = match["odds"].get(market_key)
        if not isinstance(group, list):
            raise ValueError("Ismeretlen piac.")
        option = next((x for x in group if str(x.get("selection_key")) == str(selection_key)), None)
        if option is None:
            raise ValueError("Ismeretlen fogadási opció.")
        legs = await self.draft(guild_id, user_id)
        if len(legs) >= await self.max_legs(guild_id) and all(int(x["match_id"]) != match_id for x in legs):
            raise ValueError("A szelvény elérte a maximális tippszámot.")
        now = iso(utcnow())
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                """INSERT INTO betting_draft_legs(guild_id,user_id,match_id,market_key,selection_key,label,odds,added_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(guild_id,user_id,match_id) DO UPDATE SET
                   market_key=excluded.market_key,selection_key=excluded.selection_key,label=excluded.label,odds=excluded.odds,added_at=excluded.added_at""",
                (guild_id,user_id,match_id,market_key,selection_key,str(option["label"]),float(option["odds"]),now),
            )
            await conn.commit()
        return {"match": match, "market_key": market_key, "selection_key": selection_key, "label": option["label"], "odds": float(option["odds"])}

    async def remove_draft_leg(self, guild_id: int, user_id: int, match_id: int) -> bool:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute("DELETE FROM betting_draft_legs WHERE guild_id=? AND user_id=? AND match_id=?", (guild_id,user_id,match_id))
            await conn.commit(); return int(cur.rowcount or 0) > 0

    async def clear_draft(self, guild_id: int, user_id: int) -> None:
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("DELETE FROM betting_draft_legs WHERE guild_id=? AND user_id=?", (guild_id,user_id))
            await conn.commit()

    async def _reserve_funds(self, conn: aiosqlite.Connection, guild_id: int, user_id: int, amount: int, reason: str) -> tuple[int, int]:
        now = iso(utcnow())
        starting = await self.db.get_starting_balance(guild_id, conn)
        await conn.execute(
            "INSERT OR IGNORE INTO users(guild_id,user_id,wallet,bank,created_at,last_daily,last_work) VALUES(?,?,?,?,?,?,?)",
            (guild_id,user_id,starting,0,now,None,None),
        )
        cur = await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id))
        row = await cur.fetchone(); wallet = max(0, int(row[0]))
        if wallet < amount:
            raise ValueError("Nincs elég pénzed a walletedben ehhez a fogadáshoz. A banki pénzt Yoru nem használja tétként.")
        await conn.execute("UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?", (amount,amount,guild_id,user_id))
        await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id,user_id,-amount,reason,now))
        return amount, 0

    async def place_ticket(self, guild_id: int, user_id: int, *, stake_unit: int, bet_type: str = "combo", system_k: int | None = None) -> dict[str, Any]:
        if not await self.enabled(guild_id) or not await self.tippmix_enabled(guild_id):
            raise ValueError("A Tippmix ezen a szerveren ki van kapcsolva.")
        stake_unit = int(stake_unit)
        if stake_unit < await self.min_stake(guild_id):
            raise ValueError(f"A minimum tét {await self.min_stake(guild_id):,}.")
        legs = await self.draft(guild_id, user_id)
        if not legs:
            raise ValueError("A szelvényed üres.")
        if len(legs) > await self.max_legs(guild_id):
            raise ValueError("Túl sok tipp van a szelvényen.")
        now = utcnow()
        for leg in legs:
            if str(leg["match_status"]) != "open" or now >= parse_dt(str(leg["kickoff_at"])):
                raise ValueError("Van olyan meccs a szelvényen, amelyre már lezárult a fogadás. Töröld és próbáld újra.")

        bet_type = str(bet_type).lower()
        if bet_type not in {"single", "combo", "system"}:
            raise ValueError("Ismeretlen szelvénytípus.")
        odds_values = [float(x["odds"]) for x in legs]
        max_payout = await self.max_payout(guild_id)
        if bet_type == "single":
            total_stake = stake_unit * len(legs)
            combined = 0.0
            potential = sum(round(stake_unit * o) for o in odds_values)
            system_k = None
        elif bet_type == "combo":
            total_stake = stake_unit
            combined = math.prod(odds_values)
            potential = round(total_stake * combined)
            system_k = None
        else:
            if len(legs) < 3:
                raise ValueError("Rendszerfogadáshoz legalább 3 tipp kell.")
            k = int(system_k or max(2, len(legs)-1))
            if not 2 <= k < len(legs):
                raise ValueError("A rendszerkötés 2 és N-1 között legyen.")
            combos = list(itertools.combinations(odds_values, k))
            if len(combos) > 1000:
                raise ValueError("Ez a rendszer túl sok kombinációt hozna létre.")
            total_stake = stake_unit * len(combos)
            combined = 0.0
            potential = sum(round(stake_unit * math.prod(c)) for c in combos)
            system_k = k
        raw_potential=max(0,int(potential))
        if raw_potential > max_payout:
            raise ValueError(
                f"A szelvény várható kifizetése ({raw_potential:,}) meghaladja a szerver max payoutját ({max_payout:,}). "
                "Csökkentsd a tétet vagy a kötésszámot."
            )
        potential=raw_potential

        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cur = await conn.execute(
                    """INSERT INTO betting_tickets(guild_id,user_id,bet_type,system_k,stake_unit,total_stake,combined_odds,potential_payout,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (guild_id,user_id,bet_type,system_k,stake_unit,total_stake,float(combined),potential,iso(now)),
                )
                ticket_id = int(cur.lastrowid)
                await self._reserve_funds(conn,guild_id,user_id,total_stake,f"betting_ticket:{ticket_id}")
                await conn.executemany(
                    """INSERT INTO betting_ticket_legs(ticket_id,leg_index,match_id,market_key,selection_key,label,odds)
                       VALUES(?,?,?,?,?,?,?)""",
                    [(ticket_id,i,int(x["match_id"]),str(x["market_key"]),str(x["selection_key"]),str(x["label"]),float(x["odds"])) for i,x in enumerate(legs)],
                )
                await conn.execute("DELETE FROM betting_draft_legs WHERE guild_id=? AND user_id=?", (guild_id,user_id))
                await conn.commit()
            except Exception:
                await conn.rollback(); raise
        if self.statistics:
            await self.statistics.increment(guild_id,user_id,"betting.tickets")
            await self.statistics.add(guild_id,user_id,"betting.staked",total_stake)
        return {"ticket_id":ticket_id,"bet_type":bet_type,"system_k":system_k,"stake_unit":stake_unit,"total_stake":total_stake,"potential_payout":potential,"legs":legs,"combined_odds":combined}

    async def ticket_history(self, guild_id: int, user_id: int, limit: int = 15) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute("SELECT * FROM betting_tickets WHERE guild_id=? AND user_id=? ORDER BY ticket_id DESC LIMIT ?", (guild_id,user_id,max(1,min(30,int(limit)))))
            rows = [dict(r) for r in await cur.fetchall()]
            for row in rows:
                cur = await conn.execute(
                    """SELECT l.*,m.home,m.away,m.home_score,m.away_score,m.kickoff_at FROM betting_ticket_legs l
                       JOIN betting_matches m ON m.match_id=l.match_id WHERE l.ticket_id=? ORDER BY l.leg_index""",
                    (row["ticket_id"],),
                )
                row["legs"] = [dict(x) for x in await cur.fetchall()]
        return rows

    async def _settle_match(self, conn: aiosqlite.Connection, row: aiosqlite.Row) -> dict[str, Any]:
        rng = random.Random(_seed_int("result", row["seed"]))
        diff = int(row["home_rating"]) - int(row["away_rating"])
        home_xg = max(0.45, min(3.25, 1.48 + diff / 52.0))
        away_xg = max(0.35, min(2.85, 1.12 - diff / 62.0))
        # Odds and settlement must share the SAME model. Generate first half
        # and second half independently; their Poisson sums preserve the full
        # match xG while HT markets exactly match the advertised probabilities.
        ht_h = _poisson_sample(rng, max(0.20, home_xg*0.46))
        ht_a = _poisson_sample(rng, max(0.18, away_xg*0.46))
        h = ht_h + _poisson_sample(rng, max(0.0, home_xg-max(0.20, home_xg*0.46)))
        a = ht_a + _poisson_sample(rng, max(0.0, away_xg-max(0.18, away_xg*0.46)))
        now = iso(utcnow())
        await conn.execute(
            "UPDATE betting_matches SET status='settled',home_score=?,away_score=?,ht_home=?,ht_away=?,settled_at=? WHERE match_id=? AND status='open'",
            (h,a,ht_h,ht_a,now,int(row["match_id"])),
        )
        cur = await conn.execute("SELECT ticket_id,leg_index,market_key,selection_key FROM betting_ticket_legs WHERE match_id=? AND result='pending'", (int(row["match_id"]),))
        for leg in await cur.fetchall():
            result = evaluate_leg(str(leg[2]),str(leg[3]),h,a,ht_h,ht_a)
            await conn.execute("UPDATE betting_ticket_legs SET result=? WHERE ticket_id=? AND leg_index=?", (result,int(leg[0]),int(leg[1])))
        return {"match_id":int(row["match_id"]),"league":str(row["league"]),"home":str(row["home"]),"away":str(row["away"]),"home_score":h,"away_score":a,"ht_home":ht_h,"ht_away":ht_a}

    async def _settle_ready_tickets(self, conn: aiosqlite.Connection, guild_id: int) -> list[TicketSettlement]:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM betting_tickets WHERE guild_id=? AND status='open' ORDER BY ticket_id", (guild_id,))
        settlements: list[TicketSettlement] = []
        max_payout = await self.max_payout(guild_id)
        for ticket in await cur.fetchall():
            legs_cur = await conn.execute("SELECT * FROM betting_ticket_legs WHERE ticket_id=? ORDER BY leg_index", (int(ticket["ticket_id"]),))
            legs = [dict(r) for r in await legs_cur.fetchall()]
            if not legs or any(str(x["result"]) == "pending" for x in legs):
                continue
            bet_type = str(ticket["bet_type"]); stake_unit=int(ticket["stake_unit"]); payout=0
            if bet_type == "single":
                for leg in legs:
                    if leg["result"] == "win": payout += round(stake_unit*float(leg["odds"]))
                    elif leg["result"] == "void": payout += stake_unit
            elif bet_type == "combo":
                if all(x["result"] != "loss" for x in legs):
                    effective = math.prod(float(x["odds"]) if x["result"] == "win" else 1.0 for x in legs)
                    payout = round(stake_unit*effective)
            else:
                k=int(ticket["system_k"] or 2)
                for combo in itertools.combinations(legs,k):
                    if any(x["result"] == "loss" for x in combo): continue
                    effective=math.prod(float(x["odds"]) if x["result"] == "win" else 1.0 for x in combo)
                    payout += round(stake_unit*effective)
            payout=min(max_payout,max(0,int(payout)))
            status="won" if payout>int(ticket["total_stake"]) else "push" if payout==int(ticket["total_stake"]) else "partial" if payout>0 else "lost"
            now=iso(utcnow())
            # Idempotent: ticket status and payout are committed in the same transaction as wallet credit.
            upd=await conn.execute("UPDATE betting_tickets SET status=?,payout=?,settled_at=? WHERE ticket_id=? AND status='open'", (status,payout,now,int(ticket["ticket_id"])))
            if int(upd.rowcount or 0) != 1: continue
            if payout:
                await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?", (payout,payout,guild_id,int(ticket["user_id"])))
                await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id,int(ticket["user_id"]),payout,f"betting_payout:{ticket['ticket_id']}",now))
            settlements.append(TicketSettlement(int(ticket["ticket_id"]),guild_id,int(ticket["user_id"]),status,int(ticket["total_stake"]),payout,bet_type))
        return settlements

    async def ensure_next_race(self, guild_id: int, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or utcnow(); hours = await self.horse_interval_hours(guild_id); seconds=hours*3600
        start_ts = ((int(now.timestamp()) // seconds) + 1) * seconds
        starts = datetime.fromtimestamp(start_ts,tz=timezone.utc)
        close_minutes = await self.horse_close_minutes(guild_id)
        race_key = str(start_ts)
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row
            cur=await conn.execute("SELECT * FROM horse_races WHERE guild_id=? AND race_key=?",(guild_id,race_key)); row=await cur.fetchone()
            if row is None:
                rng=random.Random(_seed_int("horse",guild_id,race_key)); names=rng.sample(list(cfg.HORSE_NAMES),6)
                ratings=[rng.randint(68,96) for _ in names]
                weights=[math.exp((r-80)/14) for r in ratings]
                probs=_plackett_luce_top_probabilities(weights)
                horses=[]
                for idx,(name,rating) in enumerate(zip(names,ratings)):
                    p_win,p_top2,p_top3=probs[idx]
                    # Keep longshots fair too: caps are high enough that every
                    # generated horse market stays close to its target RTP.
                    horses.append({"index":idx,"name":name,"rating":rating,"weight":weights[idx],"win":_horse_odds(p_win,margin=1.09,maximum=35),"top2":_horse_odds(p_top2,margin=1.08,maximum=15),"top3":_horse_odds(p_top3,margin=1.07,maximum=10)})
                cur=await conn.execute("INSERT INTO horse_races(guild_id,race_key,starts_at,closes_at,horses_json) VALUES(?,?,?,?,?)",(guild_id,race_key,iso(starts),iso(starts-timedelta(minutes=close_minutes)),json.dumps(horses,ensure_ascii=False,separators=(",",":"))))
                await conn.commit(); race_id=int(cur.lastrowid)
                return {"race_id":race_id,"guild_id":guild_id,"race_key":race_key,"starts_at":iso(starts),"closes_at":iso(starts-timedelta(minutes=close_minutes)),"horses":horses,"status":"open"}
            data=dict(row); data["horses"]=json.loads(data.pop("horses_json") or "[]"); return data

    async def current_or_next_race(self, guild_id: int) -> dict[str, Any]:
        now=utcnow()
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row
            cur=await conn.execute("SELECT * FROM horse_races WHERE guild_id=? AND status IN ('open','closed') AND starts_at>? ORDER BY starts_at LIMIT 1",(guild_id,iso(now)))
            row=await cur.fetchone()
        if row is None: return await self.ensure_next_race(guild_id,now=now)
        data=dict(row); data["horses"]=json.loads(data.pop("horses_json") or "[]"); return data

    async def place_horse_bet(self,guild_id:int,user_id:int,race_id:int,horse_index:int,market:str,stake:int)->dict[str,Any]:
        if not await self.enabled(guild_id) or not await self.horse_enabled(guild_id): raise ValueError("A Kincsem fogadás ki van kapcsolva.")
        stake=int(stake)
        if stake < await self.min_stake(guild_id): raise ValueError(f"A minimum tét {await self.min_stake(guild_id):,}.")
        if market not in {"win","top2","top3"}: raise ValueError("Ismeretlen lóverseny piac.")
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row; await conn.execute("BEGIN IMMEDIATE")
            try:
                cur=await conn.execute("SELECT * FROM horse_races WHERE race_id=? AND guild_id=?",(race_id,guild_id)); row=await cur.fetchone()
                if row is None: raise ValueError("A futam nem található.")
                if str(row["status"])!='open' or utcnow()>=parse_dt(str(row["closes_at"])): raise ValueError("Erre a futamra már lezárult a fogadás.")
                horses=json.loads(row["horses_json"] or "[]")
                if not 0<=horse_index<len(horses): raise ValueError("Ismeretlen ló.")
                horse=horses[horse_index]; odds=float(horse[market])
                potential=round(stake*odds); max_payout=await self.max_payout(guild_id)
                if potential>max_payout:
                    raise ValueError(
                        f"Ez a tét {potential:,} várható kifizetést adna, ami meghaladja a szerver {max_payout:,} max payoutját. "
                        "Csökkentsd a tétet."
                    )
                cur=await conn.execute("INSERT INTO horse_bets(race_id,guild_id,user_id,horse_index,market,odds,stake,created_at) VALUES(?,?,?,?,?,?,?,?)",(race_id,guild_id,user_id,horse_index,market,odds,stake,iso(utcnow())))
                bet_id=int(cur.lastrowid); await self._reserve_funds(conn,guild_id,user_id,stake,f"horse_bet:{bet_id}"); await conn.commit()
            except Exception: await conn.rollback(); raise
        if self.statistics:
            await self.statistics.increment(guild_id,user_id,"betting.horse_bets"); await self.statistics.add(guild_id,user_id,"betting.staked",stake)
        return {"bet_id":bet_id,"race_id":race_id,"horse":horse,"market":market,"odds":odds,"stake":stake}

    async def horse_history(self,guild_id:int,user_id:int,limit:int=15)->list[dict[str,Any]]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row
            cur=await conn.execute("SELECT b.*,r.horses_json,r.starts_at,r.result_json FROM horse_bets b JOIN horse_races r ON r.race_id=b.race_id WHERE b.guild_id=? AND b.user_id=? ORDER BY b.bet_id DESC LIMIT ?",(guild_id,user_id,max(1,min(30,limit))))
            rows=[]
            for r in await cur.fetchall():
                x=dict(r); horses=json.loads(x.pop("horses_json") or "[]"); x["horse_name"]=horses[int(x["horse_index"])]["name"] if horses else "?"; rows.append(x)
            return rows

    async def _settle_due_races(self,conn:aiosqlite.Connection,guild_id:int,now:datetime)->tuple[list[dict[str,Any]],list[HorseSettlement]]:
        conn.row_factory=aiosqlite.Row
        cur=await conn.execute("SELECT * FROM horse_races WHERE guild_id=? AND status!='settled' AND starts_at<=? ORDER BY starts_at",(guild_id,iso(now)))
        race_results=[]; bet_results=[]; max_payout=await self.max_payout(guild_id)
        for race in await cur.fetchall():
            horses=json.loads(race["horses_json"] or "[]"); rng=random.Random(_seed_int("horse-result",guild_id,race["race_key"]))
            remaining=list(range(len(horses))); order=[]
            while remaining:
                weights=[float(horses[i].get("weight", math.exp((float(horses[i]["rating"])-80)/14))) for i in remaining]
                pick=rng.choices(remaining,weights=weights,k=1)[0]; order.append(pick); remaining.remove(pick)
            now_iso=iso(now)
            upd=await conn.execute("UPDATE horse_races SET status='settled',result_json=?,settled_at=? WHERE race_id=? AND status!='settled'",(json.dumps(order),now_iso,int(race["race_id"])))
            if int(upd.rowcount or 0)!=1: continue
            race_results.append({"race_id":int(race["race_id"]),"order":order,"horses":horses,"starts_at":str(race["starts_at"])})
            bcur=await conn.execute("SELECT * FROM horse_bets WHERE race_id=? AND status='open'",(int(race["race_id"]),))
            pos={horse_idx:i+1 for i,horse_idx in enumerate(order)}
            for bet in await bcur.fetchall():
                place=pos.get(int(bet["horse_index"]),99); market=str(bet["market"])
                won=(market=='win' and place==1) or (market=='top2' and place<=2) or (market=='top3' and place<=3)
                payout=min(max_payout,round(int(bet["stake"])*float(bet["odds"]))) if won else 0; status='won' if won else 'lost'
                await conn.execute("UPDATE horse_bets SET status=?,payout=?,settled_at=? WHERE bet_id=? AND status='open'",(status,payout,now_iso,int(bet["bet_id"])))
                if payout:
                    await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?",(payout,payout,guild_id,int(bet["user_id"])))
                    await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(guild_id,int(bet["user_id"]),payout,f"horse_payout:{bet['bet_id']}",now_iso))
                name=horses[int(bet["horse_index"])]["name"]
                bet_results.append(HorseSettlement(int(bet["bet_id"]),int(race["race_id"]),guild_id,int(bet["user_id"]),status,int(bet["stake"]),payout,str(name),market))
        return race_results,bet_results

    async def process_due(self,guild_id:int,*,now:datetime|None=None)->dict[str,Any]:
        now=now or utcnow(); await self.ensure_daily_matches(guild_id,now=now); await self.ensure_next_race(guild_id,now=now)
        match_results=[]; ticket_results=[]; race_results=[]; horse_results=[]
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row; await conn.execute("BEGIN IMMEDIATE")
            try:
                cur=await conn.execute("SELECT * FROM betting_matches WHERE guild_id=? AND status='open' AND kickoff_at<=? ORDER BY kickoff_at",(guild_id,iso(now)))
                for row in await cur.fetchall(): match_results.append(await self._settle_match(conn,row))
                ticket_results=await self._settle_ready_tickets(conn,guild_id)
                race_results,horse_results=await self._settle_due_races(conn,guild_id,now)
                await conn.commit()
            except Exception: await conn.rollback(); raise
        if self.statistics:
            for t in ticket_results:
                await self.statistics.add(t.guild_id,t.user_id,"betting.payout",t.payout)
                if t.status=='won': await self.statistics.increment(t.guild_id,t.user_id,"betting.wins")
            for b in horse_results:
                await self.statistics.add(b.guild_id,b.user_id,"betting.payout",b.payout)
                if b.status=='won': await self.statistics.increment(b.guild_id,b.user_id,"betting.horse_wins")
        return {"matches":match_results,"tickets":ticket_results,"races":race_results,"horse_bets":horse_results}

    async def recent_results(self,guild_id:int,limit:int=20)->list[dict[str,Any]]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row
            cur=await conn.execute("SELECT * FROM betting_matches WHERE guild_id=? AND status='settled' ORDER BY settled_at DESC LIMIT ?",(guild_id,max(1,min(50,limit))))
            return [dict(r) for r in await cur.fetchall()]

    async def user_stats(self,guild_id:int,user_id:int)->dict[str,int]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur=await conn.execute("SELECT COUNT(*),COALESCE(SUM(total_stake),0),COALESCE(SUM(payout),0),COALESCE(MAX(payout),0) FROM betting_tickets WHERE guild_id=? AND user_id=?",(guild_id,user_id)); t=await cur.fetchone()
            cur=await conn.execute("SELECT COUNT(*),COALESCE(SUM(stake),0),COALESCE(SUM(payout),0),COALESCE(MAX(payout),0) FROM horse_bets WHERE guild_id=? AND user_id=?",(guild_id,user_id)); h=await cur.fetchone()
        staked=int(t[1])+int(h[1]); payout=int(t[2])+int(h[2])
        return {"bets":int(t[0])+int(h[0]),"staked":staked,"payout":payout,"profit":payout-staked,"biggest":max(int(t[3]),int(h[3]))}
