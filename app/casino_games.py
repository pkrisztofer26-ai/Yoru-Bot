from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Iterable

from app import casino_config as cfg


# ---------------------------------------------------------------------------
# Slots V2 pure engine
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SlotLineWin:
    line_index: int
    symbol: str
    count: int
    multiplier: float


@dataclass(slots=True)
class SlotSpin:
    grid: list[list[str]]
    line_wins: list[SlotLineWin]
    scatter_count: int
    multiplier: float
    payout: int
    free_spins_awarded: int = 0
    is_free_spin: bool = False
    spin_number: int = 0


def generate_slot_grid(rng=None) -> list[list[str]]:
    # Runtime calls normally do not inject an RNG. Fall back to the module-level
    # random generator; tests/simulations can still pass a seeded Random instance.
    rng = random if rng is None else rng
    flat = rng.choices(cfg.SLOTS_V2_SYMBOLS, weights=cfg.SLOTS_V2_WEIGHTS, k=15)
    return [flat[row * 5:(row + 1) * 5] for row in range(3)]


def _payline_target(sequence: list[str]) -> str | None:
    # Scatter never participates in a payline. Wild substitutes for normal
    # symbols and can also form an all-wild line.
    for symbol in sequence:
        if symbol == cfg.SLOTS_V2_SCATTER:
            return None
        if symbol != cfg.SLOTS_V2_WILD:
            return symbol
    return cfg.SLOTS_V2_WILD


def evaluate_slot_grid(grid: list[list[str]]) -> tuple[list[SlotLineWin], int, float, int]:
    line_wins: list[SlotLineWin] = []
    total_multiplier = 0.0
    line_count = len(cfg.SLOTS_V2_PAYLINES)

    for line_index, line in enumerate(cfg.SLOTS_V2_PAYLINES, start=1):
        sequence = [grid[line[column]][column] for column in range(5)]
        target = _payline_target(sequence)
        if target is None:
            continue
        count = 0
        for symbol in sequence:
            if symbol == cfg.SLOTS_V2_SCATTER:
                break
            if symbol == target or symbol == cfg.SLOTS_V2_WILD:
                count += 1
            else:
                break
        if count < 3:
            continue
        table = cfg.SLOTS_V2_PAYTABLE.get(target)
        if not table:
            continue
        raw_multiplier = float(table[min(count, 5)])
        # The command bet is the total spin bet. Payline pays are therefore
        # normalized to one equal share of the total bet.
        normalized = raw_multiplier / line_count
        total_multiplier += normalized
        line_wins.append(SlotLineWin(line_index, target, count, normalized))

    scatter_count = sum(row.count(cfg.SLOTS_V2_SCATTER) for row in grid)
    scatter_key = min(scatter_count, 5)
    if scatter_count >= 3:
        total_multiplier += float(cfg.SLOTS_V2_SCATTER_PAYOUT.get(scatter_key, 0.0))
    free_spins = int(cfg.SLOTS_V2_FREE_SPINS.get(scatter_key, 0)) if scatter_count >= 3 else 0
    return line_wins, scatter_count, total_multiplier, free_spins


def run_slot_spin(
    bet: int,
    *,
    rng=None,
    is_free_spin: bool = False,
    spin_number: int = 0,
) -> SlotSpin:
    grid = generate_slot_grid(rng)
    line_wins, scatter_count, multiplier, free_spins = evaluate_slot_grid(grid)
    payout = max(0, int(round(int(bet) * multiplier)))
    return SlotSpin(
        grid=grid,
        line_wins=line_wins,
        scatter_count=scatter_count,
        multiplier=multiplier,
        payout=payout,
        free_spins_awarded=free_spins,
        is_free_spin=is_free_spin,
        spin_number=spin_number,
    )


def run_slots_feature(
    bet: int,
    *,
    rng=None,
    max_free_spins: int | None = None,
) -> list[SlotSpin]:
    max_free_spins = cfg.SLOTS_V2_MAX_FREE_SPINS if max_free_spins is None else max(0, int(max_free_spins))
    spins: list[SlotSpin] = [run_slot_spin(bet, rng=rng)]
    pending = min(spins[0].free_spins_awarded, max_free_spins)
    awarded_total = pending
    number = 0

    while pending > 0:
        pending -= 1
        number += 1
        spin = run_slot_spin(bet, rng=rng, is_free_spin=True, spin_number=number)
        spins.append(spin)
        if spin.free_spins_awarded and awarded_total < max_free_spins:
            extra = min(spin.free_spins_awarded, max_free_spins - awarded_total)
            pending += extra
            awarded_total += extra
    return spins


def simulate_slots_rtp(spins: int, *, seed: int = 3190) -> float:
    if spins <= 0:
        raise ValueError("A szimulált spin számának pozitívnak kell lennie.")
    rng = random.Random(seed)
    total_payout = 0
    # Fixed stake avoids float accumulation and includes the value of free spins.
    stake = 100_000
    for _ in range(int(spins)):
        total_payout += sum(spin.payout for spin in run_slots_feature(stake, rng=rng))
    return total_payout / (int(spins) * stake)


# ---------------------------------------------------------------------------
# Roulette V2 pure rules
# ---------------------------------------------------------------------------


ROULETTE_RED_NUMBERS = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})


@dataclass(slots=True, frozen=True)
class RouletteBet:
    kind: str
    amount: int
    number: int | None = None

    @property
    def label(self) -> str:
        labels = {
            "red": "🔴 Piros",
            "black": "⚫ Fekete",
            "even": "Páros",
            "odd": "Páratlan",
            "low": "1–18",
            "high": "19–36",
            "dozen1": "1. tucat",
            "dozen2": "2. tucat",
            "dozen3": "3. tucat",
            "column1": "1. oszlop",
            "column2": "2. oszlop",
            "column3": "3. oszlop",
            "number": f"Szám {self.number}",
        }
        return labels.get(self.kind, self.kind)


ROULETTE_ALIASES = {
    "piros": "red", "red": "red", "r": "red",
    "fekete": "black", "black": "black", "b": "black",
    "páros": "even", "paros": "even", "even": "even",
    "páratlan": "odd", "paratlan": "odd", "odd": "odd",
    "alacsony": "low", "low": "low", "1-18": "low", "1–18": "low",
    "magas": "high", "high": "high", "19-36": "high", "19–36": "high",
    "1st dozen": "dozen1", "dozen1": "dozen1", "1. tucat": "dozen1", "1tucat": "dozen1",
    "2nd dozen": "dozen2", "dozen2": "dozen2", "2. tucat": "dozen2", "2tucat": "dozen2",
    "3rd dozen": "dozen3", "dozen3": "dozen3", "3. tucat": "dozen3", "3tucat": "dozen3",
    "1st column": "column1", "column1": "column1", "1. oszlop": "column1", "1oszlop": "column1",
    "2nd column": "column2", "column2": "column2", "2. oszlop": "column2", "2oszlop": "column2",
    "3rd column": "column3", "column3": "column3", "3. oszlop": "column3", "3oszlop": "column3",
    # Backwards compatibility: old green bet means a straight-up zero bet.
    "zöld": "zero", "zold": "zero", "green": "zero", "g": "zero",
}


def parse_roulette_choice(value: str) -> tuple[str, int | None]:
    raw = str(value).strip().lower()
    if raw.isdigit() and 0 <= int(raw) <= 36:
        return "number", int(raw)
    kind = ROULETTE_ALIASES.get(raw)
    if kind == "zero":
        return "number", 0
    if kind:
        return kind, None
    raise ValueError(
        "Válassz: piros/fekete, páros/páratlan, 1-18/19-36, 1-3. tucat, 1-3. oszlop, vagy 0–36 közötti szám."
    )


def roulette_color(number: int) -> str:
    if number == 0:
        return "green"
    return "red" if number in ROULETTE_RED_NUMBERS else "black"


def roulette_result_emoji(number: int) -> str:
    color = roulette_color(number)
    return "🟢" if color == "green" else ("🔴" if color == "red" else "⚫")


def roulette_bet_wins(bet: RouletteBet, number: int) -> bool:
    kind = bet.kind
    if kind == "number":
        return number == bet.number
    if number == 0:
        return False
    if kind == "red":
        return number in ROULETTE_RED_NUMBERS
    if kind == "black":
        return number not in ROULETTE_RED_NUMBERS
    if kind == "even":
        return number % 2 == 0
    if kind == "odd":
        return number % 2 == 1
    if kind == "low":
        return 1 <= number <= 18
    if kind == "high":
        return 19 <= number <= 36
    if kind == "dozen1":
        return 1 <= number <= 12
    if kind == "dozen2":
        return 13 <= number <= 24
    if kind == "dozen3":
        return 25 <= number <= 36
    if kind == "column1":
        return number >= 1 and number % 3 == 1
    if kind == "column2":
        return number >= 1 and number % 3 == 2
    if kind == "column3":
        return number >= 1 and number % 3 == 0
    return False


def roulette_total_payout(kind: str) -> float:
    if kind == "number":
        return cfg.ROULETTE_V2_SINGLE_TOTAL_PAYOUT
    if kind.startswith("dozen") or kind.startswith("column"):
        return cfg.ROULETTE_V2_DOZEN_COLUMN_TOTAL_PAYOUT
    return cfg.ROULETTE_V2_EVEN_TOTAL_PAYOUT


def evaluate_roulette_bets(bets: Iterable[RouletteBet], number: int, *, payout_scale: float = 1.0) -> tuple[int, list[RouletteBet]]:
    payout = 0
    wins: list[RouletteBet] = []
    for bet in bets:
        if not roulette_bet_wins(bet, number):
            continue
        wins.append(bet)
        base_total = roulette_total_payout(bet.kind)
        scaled_total = 1.0 + (base_total - 1.0) * float(payout_scale)
        payout += int(round(bet.amount * scaled_total))
    return payout, wins
