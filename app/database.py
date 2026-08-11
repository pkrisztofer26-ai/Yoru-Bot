from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import aiosqlite

from app import economy_config as eco


class Database:
    def __init__(self, path: str, starting_balance: int) -> None:
        self.path = path
        self.starting_balance = starting_balance

    async def _ensure_user_column(self, db: aiosqlite.Connection, name: str, definition: str) -> None:
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = {str(row[1]) for row in await cursor.fetchall()}
        if name not in columns:
            await db.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")

    async def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    wallet INTEGER NOT NULL DEFAULT 0,
                    bank INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_daily TEXT,
                    last_work TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            for name, definition in [
                ("last_beg", "TEXT"),
                ("last_search", "TEXT"),
                ("last_slut", "TEXT"),
                ("last_crime", "TEXT"),
                ("last_rob", "TEXT"),
                ("last_role_income", "TEXT"),
                ("work_count", "INTEGER NOT NULL DEFAULT 0"),
                ("crime_success", "INTEGER NOT NULL DEFAULT 0"),
                ("crime_failed", "INTEGER NOT NULL DEFAULT 0"),
                ("rob_success", "INTEGER NOT NULL DEFAULT 0"),
                ("rob_failed", "INTEGER NOT NULL DEFAULT 0"),
                ("rob_profit", "INTEGER NOT NULL DEFAULT 0"),
                ("gambling_profit", "INTEGER NOT NULL DEFAULT 0"),
                ("game_wins", "INTEGER NOT NULL DEFAULT 0"),
                ("daily_streak", "INTEGER NOT NULL DEFAULT 0"),
                ("best_daily_streak", "INTEGER NOT NULL DEFAULT 0"),
                ("daily_count", "INTEGER NOT NULL DEFAULT 0"),
                ("beg_count", "INTEGER NOT NULL DEFAULT 0"),
                ("search_count", "INTEGER NOT NULL DEFAULT 0"),
                ("money_earned", "INTEGER NOT NULL DEFAULT 0"),
                ("money_lost", "INTEGER NOT NULL DEFAULT 0"),
                ("jail_until", "TEXT"),
                ("last_weekly", "TEXT"),
                ("last_monthly", "TEXT"),
                ("last_interest", "TEXT"),
                ("weekly_count", "INTEGER NOT NULL DEFAULT 0"),
                ("monthly_count", "INTEGER NOT NULL DEFAULT 0"),
                ("scratch_count", "INTEGER NOT NULL DEFAULT 0"),
                ("chicken_wins", "INTEGER NOT NULL DEFAULT 0"),
                ("xp_points", "INTEGER NOT NULL DEFAULT 0"),
                ("selected_title", "TEXT NOT NULL DEFAULT 'Kezdő'"),
                ("investment_profit", "INTEGER NOT NULL DEFAULT 0"),
                ("last_invest", "TEXT"),
                ("jackpot_wins", "INTEGER NOT NULL DEFAULT 0"),
                ("lottery_wins", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                await self._ensure_user_column(db, name, definition)

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS role_income (
                    guild_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    hourly_amount INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, role_id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS shop_items (
                    item_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    emoji TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, item_id),
                    FOREIGN KEY (item_id) REFERENCES shop_items(item_id)
                )
                """
            )
            await db.executemany(
                """
                INSERT OR IGNORE INTO shop_items
                    (item_id, name, description, price, emoji, active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                [
                    ("chicken", "Chicken", "Szükséges a Chicken Fighthoz. Vereségnél a Chicken meghal és elvész.", eco.SHOP_PRICES["chicken"], "🐔"),
                    ("lottery_ticket", "Sorsjegy", "Kapard le a !scratch paranccsal véletlen nyereményért.", eco.SHOP_PRICES["lottery_ticket"], "🎟️"),
                    ("mystery_box", "Mystery Box", "Nyisd ki a !use mystery_box paranccsal véletlen jutalomért.", eco.SHOP_PRICES["mystery_box"], "📦"),
                    ("rob_shield", "Rablásvédelem", "Egyszer automatikusan megvéd egy sikeres rablástól.", eco.SHOP_PRICES["rob_shield"], "🛡️"),
                    ("lucky_charm", "Szerencsehozó", "A következő ládanyitás +15% bónuszt kap, legfeljebb $500k értékben.", eco.SHOP_PRICES["lucky_charm"], "🍀"),
                ],
            )
            await db.execute("UPDATE shop_items SET active = 0 WHERE item_id IN ('safe_key', 'bomb_shield')")
            await db.execute("UPDATE shop_items SET description = ? WHERE item_id = 'chicken'", ("Szükséges a Chicken Fighthoz. Vereségnél a Chicken meghal és elvész.",))
            await db.execute("UPDATE shop_items SET description = ? WHERE item_id = 'lottery_ticket'", ("Kapard le a !scratch paranccsal véletlen nyereményért.",))

            # Yoru v2 progression / event tables
            await db.execute(
                """CREATE TABLE IF NOT EXISTS achievements (
                    guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, achievement_id TEXT NOT NULL,
                    unlocked_at TEXT NOT NULL, PRIMARY KEY (guild_id, user_id, achievement_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS user_badges (
                    guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, badge_id TEXT NOT NULL,
                    unlocked_at TEXT NOT NULL, PRIMARY KEY (guild_id, user_id, badge_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS active_boosters (
                    guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, booster_id TEXT NOT NULL,
                    multiplier REAL NOT NULL, expires_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, booster_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS lottery_entries (
                    guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, tickets INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS guild_state (
                    guild_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY (guild_id, key)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS guild_effects (
                    guild_id INTEGER NOT NULL, effect_id TEXT NOT NULL, multiplier REAL NOT NULL, expires_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, effect_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS market_daily (
                    guild_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    market_date TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    stock INTEGER NOT NULL,
                    starting_stock INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, item_id, market_date)
                )"""
            )
            # Yoru v3 statistics engine. A névtér-alapú kulcsok miatt új stathoz nem kell migráció.
            await db.execute(
                """CREATE TABLE IF NOT EXISTS user_statistics (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    stat_name TEXT NOT NULL,
                    value INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, stat_name)
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_statistics_lookup ON user_statistics(guild_id, stat_name, value DESC)"
            )
            # Yoru v3.2 quest assignments. A start_value miatt a quest progress
            # a kiosztás pillanatától mérhető, külön event-hookok nélkül.
            await db.execute(
                """CREATE TABLE IF NOT EXISTS quest_assignments (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    period TEXT NOT NULL,
                    period_key TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    quest_id TEXT NOT NULL,
                    start_value INTEGER NOT NULL DEFAULT 0,
                    target INTEGER NOT NULL,
                    reward_xp INTEGER NOT NULL,
                    reward_item TEXT,
                    claimed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    claimed_at TEXT,
                    PRIMARY KEY (guild_id, user_id, period, period_key, slot)
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_quest_assignments_current ON quest_assignments(guild_id, user_id, period, period_key)"
            )
            # Yoru v3.3 prestige állapot. A lifetime statok külön megmaradnak a
            # user_statistics táblában; itt csak az endgame ciklus adatai élnek.
            await db.execute(
                """CREATE TABLE IF NOT EXISTS user_prestige (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    prestige_rank INTEGER NOT NULL DEFAULT 0,
                    total_wealth_sacrificed INTEGER NOT NULL DEFAULT 0,
                    first_prestige_at TEXT,
                    last_prestige_at TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_prestige_rank ON user_prestige(guild_id, prestige_rank DESC, total_wealth_sacrificed DESC)"
            )

            # Yoru v3.4 Crew / social economy. Egy játékos szerverenként legfeljebb
            # egy Crew tagja lehet; a meghívók lejárnak és felülírhatók.
            await db.execute(
                """CREATE TABLE IF NOT EXISTS crews (
                    crew_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    bank INTEGER NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 1,
                    total_contributed INTEGER NOT NULL DEFAULT 0,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE (guild_id, normalized_name)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS crew_members (
                    guild_id INTEGER NOT NULL,
                    crew_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member',
                    contributed INTEGER NOT NULL DEFAULT 0,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_crew_members_crew ON crew_members(guild_id, crew_id, role, contributed DESC)"
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS crew_invites (
                    guild_id INTEGER NOT NULL,
                    crew_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    invited_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_crews_leaderboard ON crews(guild_id, level DESC, total_contributed DESC, bank DESC)"
            )

            # A régi, oszlop-alapú statokat egyszer áttöltjük az új rendszerbe.
            # INSERT OR IGNORE: a már v3 alatt frissített értékeket soha nem írjuk felül.
            legacy_stat_map = {
                "work.count": "work_count",
                "crime.success": "crime_success",
                "crime.fail": "crime_failed",
                "rob.success": "rob_success",
                "rob.fail": "rob_failed",
                "rob.profit": "rob_profit",
                "gambling.profit": "gambling_profit",
                "gambling.wins": "game_wins",
                "daily.streak.current": "daily_streak",
                "daily.streak.best": "best_daily_streak",
                "daily.count": "daily_count",
                "beg.count": "beg_count",
                "search.count": "search_count",
                "economy.earned": "money_earned",
                "economy.lost": "money_lost",
                "weekly.count": "weekly_count",
                "monthly.count": "monthly_count",
                "scratch.count": "scratch_count",
                "gambling.chickenfight.wins": "chicken_wins",
                "progression.xp": "xp_points",
                "investment.profit": "investment_profit",
                "community.jackpot.wins": "jackpot_wins",
                "community.lottery.wins": "lottery_wins",
            }
            stat_now = datetime.now(timezone.utc).isoformat()
            for stat_name, column in legacy_stat_map.items():
                await db.execute(
                    f"""INSERT OR IGNORE INTO user_statistics
                        (guild_id, user_id, stat_name, value, updated_at)
                        SELECT guild_id, user_id, ?, {column}, ? FROM users""",
                    (stat_name, stat_now),
                )

            # v2.2 moderation / audit tables
            await db.execute(
                """CREATE TABLE IF NOT EXISTS moderation_warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS moderation_cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )

            # Yoru v3.6 AutoMod.  Rules are sparse: missing rows fall back to
            # app/moderation_config.py defaults, so defaults remain easy to tune.
            await db.execute(
                """CREATE TABLE IF NOT EXISTS automod_rules (
                    guild_id INTEGER NOT NULL,
                    rule TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    threshold INTEGER NOT NULL,
                    timeout_seconds INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, rule)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS automod_exemptions (
                    guild_id INTEGER NOT NULL,
                    rule TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, rule, scope_type, scope_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS automod_domains (
                    guild_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    PRIMARY KEY (guild_id, mode, domain)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS automod_words (
                    guild_id INTEGER NOT NULL,
                    word TEXT NOT NULL,
                    PRIMARY KEY (guild_id, word)
                )"""
            )

            # Yoru v3.7 Welcome & Roles. Persistent panels use dedicated tables so
            # Discord buttons survive restarts and the future web dashboard can edit
            # exactly the same configuration.
            await db.execute(
                """CREATE TABLE IF NOT EXISTS role_panels (
                    panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'toggle',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_role_panels_guild ON role_panels(guild_id, active, panel_id)"
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS role_panel_items (
                    panel_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    emoji TEXT,
                    position INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (panel_id, role_id),
                    FOREIGN KEY (panel_id) REFERENCES role_panels(panel_id) ON DELETE CASCADE
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS verification_panels (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    role_id INTEGER NOT NULL,
                    remove_role_id INTEGER,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    button_label TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS member_role_snapshots (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role_ids TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )"""
            )

            # Yoru v3.8 Community Management. Dedicated tables keep votes,
            # persistent component state and restart-safe timers separate from guild settings.
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_suggestions (
                    suggestion_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    author_id INTEGER NOT NULL,
                    anonymous INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    staff_id INTEGER,
                    staff_note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            # Defensive migration for any partially-created pre-release v3.8 database.
            cursor = await db.execute("PRAGMA table_info(community_suggestions)")
            community_suggestion_cols = {str(row[1]) for row in await cursor.fetchall()}
            if "anonymous" not in community_suggestion_cols:
                await db.execute("ALTER TABLE community_suggestions ADD COLUMN anonymous INTEGER NOT NULL DEFAULT 0")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_community_suggestions_guild ON community_suggestions(guild_id,status,suggestion_id)"
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_suggestion_votes (
                    suggestion_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    vote INTEGER NOT NULL,
                    PRIMARY KEY (suggestion_id,user_id),
                    FOREIGN KEY (suggestion_id) REFERENCES community_suggestions(suggestion_id) ON DELETE CASCADE
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_polls (
                    poll_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    author_id INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    closes_at TEXT NOT NULL,
                    closed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_community_polls_active ON community_polls(guild_id,closed,closes_at)"
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_poll_votes (
                    poll_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    option_index INTEGER NOT NULL,
                    PRIMARY KEY (poll_id,user_id),
                    FOREIGN KEY (poll_id) REFERENCES community_polls(poll_id) ON DELETE CASCADE
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_giveaways (
                    giveaway_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    host_id INTEGER NOT NULL,
                    prize TEXT NOT NULL,
                    winner_count INTEGER NOT NULL,
                    ends_at TEXT NOT NULL,
                    ended INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )"""
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_community_giveaways_active ON community_giveaways(guild_id,ended,ends_at)"
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_giveaway_entries (
                    giveaway_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (giveaway_id,user_id),
                    FOREIGN KEY (giveaway_id) REFERENCES community_giveaways(giveaway_id) ON DELETE CASCADE
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_afk (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    since TEXT NOT NULL,
                    PRIMARY KEY (guild_id,user_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_starboard_posts (
                    guild_id INTEGER NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    source_channel_id INTEGER NOT NULL,
                    starboard_message_id INTEGER NOT NULL,
                    star_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id,source_message_id)
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS community_stickies (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    last_message_id INTEGER,
                    message_counter INTEGER NOT NULL DEFAULT 0,
                    last_posted_at TEXT,
                    created_by INTEGER NOT NULL,
                    PRIMARY KEY (guild_id,channel_id)
                )"""
            )

            # Shop metadata columns are optional and added safely to existing databases.
            cursor = await db.execute("PRAGMA table_info(shop_items)")
            shop_cols = {str(row[1]) for row in await cursor.fetchall()}
            if "rarity" not in shop_cols:
                await db.execute("ALTER TABLE shop_items ADD COLUMN rarity TEXT NOT NULL DEFAULT 'common'")
            if "category" not in shop_cols:
                await db.execute("ALTER TABLE shop_items ADD COLUMN category TEXT NOT NULL DEFAULT 'utility'")

            await db.executemany(
                """INSERT OR IGNORE INTO shop_items
                    (item_id, name, description, price, emoji, active, rarity, category)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                [
                    ("common_crate", "Common Láda", "Olcsó lootbox kisebb jutalmakkal.", eco.SHOP_PRICES["common_crate"], "📦", "common", "lootbox"),
                    ("rare_crate", "Rare Láda", "Jobb esély nagyobb jutalmakra.", eco.SHOP_PRICES["rare_crate"], "🔷", "rare", "lootbox"),
                    ("epic_crate", "Epic Láda", "Ritka és értékes loot.", eco.SHOP_PRICES["epic_crate"], "🟣", "epic", "lootbox"),
                    ("legendary_crate", "Legendary Láda", "Nagyon értékes jutalmak.", eco.SHOP_PRICES["legendary_crate"], "🟡", "legendary", "lootbox"),
                    ("mythic_crate", "Mythic Láda", "A Yoru legdurvább lootboxa.", eco.SHOP_PRICES["mythic_crate"], "🔴", "mythic", "lootbox"),
                    ("work_booster", "Work Booster", "2 órán át +30% Work jutalom.", eco.SHOP_PRICES["work_booster"], "🛠️", "rare", "booster"),
                    ("crime_booster", "Crime Booster", "4 órán át +25% sikeres Crime jutalom.", eco.SHOP_PRICES["crime_booster"], "🕵️", "rare", "booster"),
                    ("luck_booster", "Luck Booster", "1 órán át jobb láda/sorsjegy tier esély.", eco.SHOP_PRICES["luck_booster"], "🍀", "epic", "booster"),
                    ("interest_booster", "Interest Booster", "24 órán át +25% kamatláb és kamatplafon.", eco.SHOP_PRICES["interest_booster"], "🏦", "epic", "booster"),
                    ("rob_booster", "Rob Booster", "1 órán át jobb rablási esély; a steal share marad 60%.", eco.SHOP_PRICES["rob_booster"], "🥷", "epic", "booster")
                ]
            )
            await db.execute("UPDATE shop_items SET rarity='common', category='game' WHERE item_id='chicken'")
            await db.execute("UPDATE shop_items SET rarity='common', category='game' WHERE item_id='lottery_ticket'")
            await db.execute("UPDATE shop_items SET rarity='rare', category='lootbox' WHERE item_id='mystery_box'")
            await db.execute("UPDATE shop_items SET rarity='rare', category='utility' WHERE item_id='rob_shield'")
            await db.execute("UPDATE shop_items SET rarity='epic', category='booster' WHERE item_id='lucky_charm'")

            # v2.1 nagyobb economy + napi árfolyamos értéktárgyak + valódi jutalom itemek.
            # UPSERT-et használunk, így a meglévő adatbázisban is frissülnek az árak/leírások.
            shop_catalog = [
                ("chicken", "Chicken", "Szükséges a Chicken Fighthoz. Vereségnél a Chicken meghal és elvész.", eco.SHOP_PRICES["chicken"], "🐔", "common", "game"),
                ("lottery_ticket", "Sorsjegy", "Kapard le a !scratch paranccsal. A base EV enyhén a vételár alatt marad.", eco.SHOP_PRICES["lottery_ticket"], "🎟️", "common", "game"),
                ("mystery_box", "Mystery Box", "Nagy szórású pénzláda. !use mystery_box", eco.SHOP_PRICES["mystery_box"], "📦", "rare", "lootbox"),
                ("rob_shield", "Rablásvédelem", "Egyszer automatikusan megvéd egy sikeres rablástól. A 60%-os rob miatt értékes védelmi item.", eco.SHOP_PRICES["rob_shield"], "🛡️", "rare", "utility"),
                ("lucky_charm", "Szerencsehozó", "A következő ládanyitás +15% bónuszt kap, legfeljebb $500k értékben.", eco.SHOP_PRICES["lucky_charm"], "🍀", "epic", "booster"),
                ("common_crate", "Common Láda", "Olcsó pénzláda kisebb, kiszámíthatóbb jutalmakkal.", eco.SHOP_PRICES["common_crate"], "📦", "common", "lootbox"),
                ("rare_crate", "Rare Láda", "Nagyobb pénzjutalom és nagyobb szórás.", eco.SHOP_PRICES["rare_crate"], "🔷", "rare", "lootbox"),
                ("epic_crate", "Epic Láda", "Magasabb tétű pénzláda ritka nagy nyereménnyel.", eco.SHOP_PRICES["epic_crate"], "🟣", "epic", "lootbox"),
                ("legendary_crate", "Legendary Láda", "Drága pénzláda komoly jackpot-lehetőséggel.", eco.SHOP_PRICES["legendary_crate"], "🟡", "legendary", "lootbox"),
                ("mythic_crate", "Mythic Láda", "A Yoru legnagyobb pénzládája: brutális szórás, ritka óriásnyeremény.", eco.SHOP_PRICES["mythic_crate"], "🔴", "mythic", "lootbox"),
                ("work_booster", "Work Booster", "2 órán át +30% Work jutalom.", eco.SHOP_PRICES["work_booster"], "🛠️", "rare", "booster"),
                ("crime_booster", "Crime Booster", "4 órán át +25% sikeres Crime jutalom.", eco.SHOP_PRICES["crime_booster"], "🕵️", "rare", "booster"),
                ("luck_booster", "Luck Booster", "1 órán át jobb láda- és sorsjegy-tier esély.", eco.SHOP_PRICES["luck_booster"], "🍀", "epic", "booster"),
                ("interest_booster", "Interest Booster", "24 órán át +25% kamatláb és +25% kamatplafon.", eco.SHOP_PRICES["interest_booster"], "🏦", "epic", "booster"),
                ("rob_booster", "Rob Booster", "1 órán át jobb rablási esélyt ad; a 60%-os lopási share nem változik.", eco.SHOP_PRICES["rob_booster"], "🥷", "epic", "booster"),
                ("silver", "Ezüst", "Napi árfolyamos értéktárgy. Limitált készlet; eladáskor 10% spread.", eco.SHOP_PRICES["silver"], "🥈", "rare", "market"),
                ("gold", "Arany", "Napi árfolyamos értéktárgy. Limitált készlet; napi árfolyam, eladáskor 10% spread.", eco.SHOP_PRICES["gold"], "🪙", "epic", "market"),
                ("diamond", "Gyémánt", "Napi árfolyamos értéktárgy. Limitált készlet; napi árfolyam, eladáskor 10% spread.", eco.SHOP_PRICES["diamond"], "💎", "legendary", "market"),
                ("nitro_basic_1m", "Discord Nitro Basic • 1 hónap", "Valódi jutalom. 30 napos Yoru account + Level 35 kell; max. 1 vásárlás / 30 nap / fő; szerverenként havi 4 db.", eco.SHOP_PRICES["nitro_basic_1m"], "🎁", "legendary", "reward"),
                ("discord_nitro_1m", "Discord Nitro • 1 hónap", "Valódi jutalom. 45 napos Yoru account + Level 45 kell; max. 1 vásárlás / 30 nap / fő; szerverenként havi 2 db.", eco.SHOP_PRICES["discord_nitro_1m"], "💠", "mythic", "reward"),
            ]
            await db.executemany(
                """INSERT INTO shop_items (item_id,name,description,price,emoji,active,rarity,category)
                   VALUES (?,?,?,?,?,1,?,?)
                   ON CONFLICT(item_id) DO UPDATE SET
                     name=excluded.name, description=excluded.description, price=excluded.price,
                     emoji=excluded.emoji, active=1, rarity=excluded.rarity, category=excluded.category""",
                shop_catalog,
            )
            await db.commit()

    async def ensure_user(self, guild_id: int, user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO users
                    (guild_id, user_id, wallet, bank, created_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (guild_id, user_id, self.starting_balance, now),
            )
            await db.commit()

    async def get_balance(self, guild_id: int, user_id: int) -> tuple[int, int]:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("A felhasználó létrehozása sikertelen volt.")
        return int(row[0]), int(row[1])

    async def get_profile(self, guild_id: int, user_id: int) -> dict[str, int | str]:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT wallet, bank, created_at, work_count, crime_success, crime_failed,
                       rob_success, rob_failed, rob_profit, gambling_profit, game_wins,
                       daily_streak, best_daily_streak, daily_count, beg_count, search_count,
                       money_earned, money_lost, jail_until, weekly_count, monthly_count,
                       scratch_count, chicken_wins, xp_points, selected_title, investment_profit,
                       jackpot_wins, lottery_wins
                FROM users WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("A felhasználó nem található.")
        keys = ["wallet", "bank", "created_at", "work_count", "crime_success", "crime_failed",
                "rob_success", "rob_failed", "rob_profit", "gambling_profit", "game_wins",
                "daily_streak", "best_daily_streak", "daily_count", "beg_count", "search_count",
                "money_earned", "money_lost", "jail_until", "weekly_count", "monthly_count",
                "scratch_count", "chicken_wins", "xp_points", "selected_title", "investment_profit",
                "jackpot_wins", "lottery_wins"]
        return dict(zip(keys, row, strict=True))

    async def add_wallet(self, guild_id: int, user_id: int, amount: int, reason: str, *, allow_negative: bool = False) -> int:
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                raise RuntimeError("A felhasználó nem található.")
            new_wallet = int(row[0]) + amount
            # A negatív wallet adósságot jelenthet. Pozitív jóváírást mindig
            # engedünk, még akkor is, ha a jutalom után az egyenleg továbbra
            # is negatív marad. Csak olyan LEVONÁST tiltunk, amely normál
            # műveletnél negatívba vinné a tárcát. A crime/slut és más
            # explicit büntetések allow_negative=True-val továbbra is
            # szándékosan negatívba vihetik.
            if amount < 0 and new_wallet < 0 and not allow_negative:
                await db.rollback()
                raise ValueError("Nincs elég pénz a tárcában.")
            # v3.5: a pénz és a progression XP teljesen külön rendszer.
            # Egy nagy gambling/event/crate payout többé nem ad automatikus szinteket.
            await db.execute("UPDATE users SET wallet = ?, money_earned = money_earned + ?, money_lost = money_lost + ? WHERE guild_id = ? AND user_id = ?", (new_wallet, max(amount, 0), max(-amount, 0), guild_id, user_id))

            # Központi economy statok ugyanabban a tranzakcióban frissülnek.
            stat_updates = []
            if amount > 0:
                stat_updates.append(("economy.earned", amount))
            elif amount < 0:
                stat_updates.append(("economy.lost", -amount))
            for stat_name, stat_amount in stat_updates:
                await db.execute(
                    """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET
                           value = value + excluded.value, updated_at = excluded.updated_at""",
                    (guild_id, user_id, stat_name, stat_amount, now),
                )
            for stat_name, peak_value in (("economy.wallet_peak", new_wallet),):
                await db.execute(
                    """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET
                           value = MAX(value, excluded.value), updated_at = excluded.updated_at""",
                    (guild_id, user_id, stat_name, peak_value, now),
                )

            await db.execute(
                "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, amount, reason, now),
            )
            await db.commit()
        return new_wallet

    async def refund_wallet(self, guild_id: int, user_id: int, amount: int, reason: str) -> int:
        """Visszatérítés korábban levont összeghez, economy/progression farm nélkül.

        A refund visszaállítja a walletet és visszavonja a korábbi ``economy.lost``
        számlálást, de nem ad progression XP-t és nem számít új keresetnek.
        """
        if amount <= 0:
            raise ValueError("A visszatérítés összege pozitív legyen.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """UPDATE users
                   SET wallet = wallet + ?,
                       money_lost = MAX(0, money_lost - ?)
                   WHERE guild_id = ? AND user_id = ?""",
                (amount, amount, guild_id, user_id),
            )
            await db.execute(
                """UPDATE user_statistics
                   SET value = MAX(0, value - ?), updated_at = ?
                   WHERE guild_id = ? AND user_id = ? AND stat_name = 'economy.lost'""",
                (amount, now, guild_id, user_id),
            )
            await db.execute(
                "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, amount, reason, now),
            )
            cursor = await db.execute(
                "SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
            await db.commit()
        return int(row[0]) if row else amount


    async def _add_stat_tx(self, db: aiosqlite.Connection, guild_id: int, user_id: int, stat_name: str, amount: int, now: str) -> None:
        await db.execute(
            """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET
                   value = value + excluded.value, updated_at = excluded.updated_at""",
            (guild_id, user_id, stat_name, amount, now),
        )

    async def _set_stat_max_tx(self, db: aiosqlite.Connection, guild_id: int, user_id: int, stat_name: str, value: int, now: str) -> None:
        await db.execute(
            """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET
                   value = MAX(value, excluded.value), updated_at = excluded.updated_at""",
            (guild_id, user_id, stat_name, value, now),
        )

    async def _record_gamble_stats_tx(
        self, db: aiosqlite.Connection, guild_id: int, user_id: int, game: str, bet: int, profit: int, won: bool, now: str
    ) -> None:
        base = game.removesuffix("_tie")
        tied = game.endswith("_tie") or profit == 0
        for key, amount in (
            ("gambling.plays", 1),
            (f"gambling.{base}.plays", 1),
            ("gambling.wagered", bet),
            (f"gambling.{base}.wagered", bet),
            ("gambling.profit", profit),
            (f"gambling.{base}.profit", profit),
        ):
            await self._add_stat_tx(db, guild_id, user_id, key, amount, now)
        if tied:
            await self._add_stat_tx(db, guild_id, user_id, "gambling.ties", 1, now)
            await self._add_stat_tx(db, guild_id, user_id, f"gambling.{base}.ties", 1, now)
        elif won:
            await self._add_stat_tx(db, guild_id, user_id, "gambling.wins", 1, now)
            await self._add_stat_tx(db, guild_id, user_id, f"gambling.{base}.wins", 1, now)
        else:
            await self._add_stat_tx(db, guild_id, user_id, "gambling.losses", 1, now)
            await self._add_stat_tx(db, guild_id, user_id, f"gambling.{base}.losses", 1, now)
        if profit > 0:
            await self._set_stat_max_tx(db, guild_id, user_id, "gambling.biggest_win", profit, now)
            await self._set_stat_max_tx(db, guild_id, user_id, f"gambling.{base}.biggest_win", profit, now)
            await self._add_stat_tx(db, guild_id, user_id, "economy.earned", profit, now)
        elif profit < 0:
            loss = -profit
            await self._set_stat_max_tx(db, guild_id, user_id, "gambling.biggest_loss", loss, now)
            await self._set_stat_max_tx(db, guild_id, user_id, f"gambling.{base}.biggest_loss", loss, now)
            await self._add_stat_tx(db, guild_id, user_id, "economy.lost", loss, now)

    async def settle_gamble(
        self,
        guild_id: int,
        user_id: int,
        bet: int,
        profit: int,
        game: str,
        won: bool,
    ) -> int:
        """Atomikusan levonja a tétet és elszámolja a játék nettó eredményét.

        A profit nettó változás: nyerésnél pozitív, veszteségnél -bet.
        """
        if bet <= 0:
            raise ValueError("A tétnek pozitívnak kell lennie.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                raise RuntimeError("A felhasználó nem található.")
            wallet = int(row[0])
            if wallet < bet:
                await db.rollback()
                raise ValueError("Nincs elég pénz a tárcádban ehhez a téthez.")
            new_wallet = wallet + profit
            if new_wallet < 0:
                await db.rollback()
                raise ValueError("Nincs elég pénz a tárcádban.")
            await db.execute(
                "UPDATE users SET wallet = ?, gambling_profit = gambling_profit + ?, game_wins = game_wins + ? WHERE guild_id = ? AND user_id = ?",
                (new_wallet, profit, 1 if won else 0, guild_id, user_id),
            )
            await self._record_gamble_stats_tx(db, guild_id, user_id, game, bet, profit, won, now)
            await db.execute(
                "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, profit, f"gamble:{game}", now),
            )
            await db.commit()
        return new_wallet

    async def get_user_stat(self, guild_id: int, user_id: int, stat_name: str) -> int | None:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT value FROM user_statistics WHERE guild_id = ? AND user_id = ? AND stat_name = ?",
                (guild_id, user_id, stat_name),
            )
            row = await cursor.fetchone()
        return None if row is None else int(row[0])

    async def get_user_statistics(self, guild_id: int, user_id: int, prefix: str | None = None) -> dict[str, int]:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            if prefix:
                cursor = await db.execute(
                    "SELECT stat_name, value FROM user_statistics WHERE guild_id = ? AND user_id = ? AND stat_name LIKE ? ORDER BY stat_name",
                    (guild_id, user_id, f"{prefix}%"),
                )
            else:
                cursor = await db.execute(
                    "SELECT stat_name, value FROM user_statistics WHERE guild_id = ? AND user_id = ? ORDER BY stat_name",
                    (guild_id, user_id),
                )
            rows = await cursor.fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    async def add_user_stat(self, guild_id: int, user_id: int, stat_name: str, amount: int) -> int:
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET
                       value = value + excluded.value, updated_at = excluded.updated_at""",
                (guild_id, user_id, stat_name, amount, now),
            )
            cursor = await db.execute(
                "SELECT value FROM user_statistics WHERE guild_id = ? AND user_id = ? AND stat_name = ?",
                (guild_id, user_id, stat_name),
            )
            row = await cursor.fetchone()
            await db.commit()
        return int(row[0]) if row else amount

    async def add_progression_xp(self, guild_id: int, user_id: int, amount: int, source: str) -> int:
        """Aktivitás-alapú progression XP jóváírás, pénztől teljesen függetlenül."""
        amount = int(amount)
        if amount <= 0:
            profile = await self.get_profile(guild_id, user_id)
            return int(profile.get("xp_points", 0))
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE users SET xp_points = xp_points + ? WHERE guild_id = ? AND user_id = ?",
                (amount, guild_id, user_id),
            )
            await self._add_stat_tx(db, guild_id, user_id, "progression.xp", amount, now)
            await self._add_stat_tx(db, guild_id, user_id, f"progression.source.{source}", amount, now)
            cursor = await db.execute(
                "SELECT xp_points FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
            await db.commit()
        return int(row[0]) if row else amount

    async def set_user_stat(self, guild_id: int, user_id: int, stat_name: str, value: int) -> int:
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET
                       value = excluded.value, updated_at = excluded.updated_at""",
                (guild_id, user_id, stat_name, value, now),
            )
            await db.commit()
        return value

    async def set_user_stat_max(self, guild_id: int, user_id: int, stat_name: str, value: int) -> int:
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET
                       value = MAX(value, excluded.value), updated_at = excluded.updated_at""",
                (guild_id, user_id, stat_name, value, now),
            )
            cursor = await db.execute(
                "SELECT value FROM user_statistics WHERE guild_id = ? AND user_id = ? AND stat_name = ?",
                (guild_id, user_id, stat_name),
            )
            row = await cursor.fetchone()
            await db.commit()
        return int(row[0]) if row else value

    async def get_timestamp(self, guild_id: int, user_id: int, column: str) -> datetime | None:
        allowed = {"last_daily", "last_beg", "last_search", "last_slut", "last_work", "last_crime", "last_rob", "last_role_income", "last_weekly", "last_monthly", "last_interest", "last_invest"}
        if column not in allowed:
            raise ValueError("Érvénytelen időbélyeg oszlop.")
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(f"SELECT {column} FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = await cursor.fetchone()
        if not row or not row[0]:
            return None
        return datetime.fromisoformat(str(row[0]))

    async def set_timestamp(self, guild_id: int, user_id: int, column: str, value: datetime) -> None:
        allowed = {"last_daily", "last_beg", "last_search", "last_slut", "last_work", "last_crime", "last_rob", "last_role_income", "last_weekly", "last_monthly", "last_interest", "last_invest"}
        if column not in allowed:
            raise ValueError("Érvénytelen időbélyeg oszlop.")
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE users SET {column} = ? WHERE guild_id = ? AND user_id = ?", (value.isoformat(), guild_id, user_id))
            await db.commit()

    async def increment_stat(self, guild_id: int, user_id: int, column: str, amount: int = 1) -> None:
        allowed = {"work_count", "crime_success", "crime_failed", "rob_success", "rob_failed", "rob_profit", "gambling_profit", "game_wins", "daily_streak", "best_daily_streak", "daily_count", "beg_count", "search_count", "money_earned", "money_lost", "weekly_count", "monthly_count", "scratch_count", "chicken_wins", "xp_points", "investment_profit", "jackpot_wins", "lottery_wins"}
        if column not in allowed:
            raise ValueError("Érvénytelen statisztika.")
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE users SET {column} = {column} + ? WHERE guild_id = ? AND user_id = ?", (amount, guild_id, user_id))
            await db.commit()

    async def rob_wallet(self, guild_id: int, robber_id: int, victim_id: int, amount: int) -> tuple[int, int]:
        if amount <= 0:
            raise ValueError("Az összegnek pozitívnak kell lennie.")
        await self.ensure_user(guild_id, robber_id)
        await self.ensure_user(guild_id, victim_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, victim_id))
            victim = await cursor.fetchone()
            victim_wallet = int(victim[0]) if victim else 0
            stolen = min(amount, victim_wallet)
            if stolen <= 0:
                await db.rollback()
                raise ValueError("A célpont tárcája üres.")
            await db.execute("UPDATE users SET wallet = wallet - ? WHERE guild_id = ? AND user_id = ?", (stolen, guild_id, victim_id))
            await db.execute("UPDATE users SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?", (stolen, guild_id, robber_id))
            await db.executemany(
                "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                [(guild_id, robber_id, stolen, f"rob_from:{victim_id}", now), (guild_id, victim_id, -stolen, f"robbed_by:{robber_id}", now)],
            )
            await db.commit()
        return stolen, victim_wallet - stolen

    async def pay_rob_fine(self, guild_id: int, robber_id: int, victim_id: int, amount: int) -> int:
        """Atomikusan átutalja a sikertelen rablás bírságát progression-XP farm nélkül."""
        if amount <= 0:
            return 0
        if robber_id == victim_id:
            raise ValueError("Saját magadnak nem fizethetsz rablási bírságot.")
        await self.ensure_user(guild_id, robber_id)
        await self.ensure_user(guild_id, victim_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            # A rablási bírság valódi tartozás: akkor is teljes egészében levonjuk,
            # ha a játékos előtte a bankba rakta a pénzét. A tárca ilyenkor
            # negatívba mehet; normál vásárlás/fogadás továbbra sem engedett hitelből.
            paid = int(amount)

            await db.execute(
                "UPDATE users SET wallet = wallet - ? WHERE guild_id = ? AND user_id = ?",
                (paid, guild_id, robber_id),
            )
            await db.execute(
                "UPDATE users SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?",
                (paid, guild_id, victim_id),
            )
            # A bírság játékosok közti transzfer: nem generál economy.earned-et vagy progression XP-t.
            cursor = await db.execute(
                "SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, victim_id),
            )
            victim_row = await cursor.fetchone()
            if victim_row:
                victim_wallet, victim_bank = int(victim_row[0]), int(victim_row[1])
                await self._set_stat_max_tx(db, guild_id, victim_id, "economy.wallet_peak", victim_wallet, now)
                await self._set_stat_max_tx(db, guild_id, victim_id, "economy.net_worth_peak", victim_wallet + victim_bank, now)

            await db.executemany(
                "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                [
                    (guild_id, robber_id, -paid, f"failed_rob:{victim_id}", now),
                    (guild_id, victim_id, paid, f"rob_compensation:{robber_id}", now),
                ],
            )
            await db.commit()
        return paid

    async def set_role_income(self, guild_id: int, role_id: int, hourly_amount: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            if hourly_amount <= 0:
                await db.execute("DELETE FROM role_income WHERE guild_id = ? AND role_id = ?", (guild_id, role_id))
            else:
                await db.execute(
                    """INSERT INTO role_income (guild_id, role_id, hourly_amount) VALUES (?, ?, ?)
                       ON CONFLICT(guild_id, role_id) DO UPDATE SET hourly_amount = excluded.hourly_amount""",
                    (guild_id, role_id, hourly_amount),
                )
            await db.commit()

    async def get_role_incomes(self, guild_id: int) -> list[tuple[int, int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT role_id, hourly_amount FROM role_income WHERE guild_id = ? ORDER BY hourly_amount DESC", (guild_id,))
            rows = await cursor.fetchall()
        return [(int(r[0]), int(r[1])) for r in rows]

    async def list_shop_items(self) -> list[tuple[str, str, str, int, str]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT item_id, name, description, price, emoji FROM shop_items WHERE active = 1 ORDER BY price ASC")
            rows = await cursor.fetchall()
        return [(str(r[0]), str(r[1]), str(r[2]), int(r[3]), str(r[4])) for r in rows]

    async def count_shop_purchases_since(
        self, guild_id: int, item_id: str, since: datetime, user_id: int | None = None
    ) -> int:
        """Sikeres normál shop vásárlások száma egy időpont óta.

        Prémium reward stock/cooldown ellenőrzésre használjuk. A prémium itemekből
        egy tranzakcióban csak 1 db vásárolható, ezért a tranzakciók száma elég.
        """
        pattern = f"buy:{item_id}x%"
        query = "SELECT COUNT(*) FROM transactions WHERE guild_id=? AND reason LIKE ? AND created_at>=?"
        params: list[object] = [guild_id, pattern, since.isoformat()]
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(query, tuple(params))
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def buy_item(self, guild_id: int, user_id: int, item_id: str, quantity: int) -> tuple[str, str, int, int]:
        if quantity < 1:
            raise ValueError("A mennyiség legalább 1 legyen.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT name, emoji, price FROM shop_items WHERE item_id = ? AND active = 1", (item_id,))
            item = await cursor.fetchone()
            if item is None:
                await db.rollback(); raise LookupError("Nincs ilyen aktív tárgy a shopban.")
            name, emoji, price = str(item[0]), str(item[1]), int(item[2])
            total_price = price * quantity
            cursor = await db.execute("SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            user = await cursor.fetchone(); wallet = int(user[0]) if user else 0
            if wallet < total_price:
                await db.rollback(); raise ValueError("Nincs elég pénzed ehhez a vásárláshoz.")
            new_wallet = wallet - total_price
            await db.execute("UPDATE users SET wallet = ? WHERE guild_id = ? AND user_id = ?", (new_wallet, guild_id, user_id))
            await db.execute("""INSERT INTO inventory (guild_id, user_id, item_id, quantity) VALUES (?, ?, ?, ?)
                                ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity""", (guild_id, user_id, item_id, quantity))
            await db.execute("INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)", (guild_id, user_id, -total_price, f"buy:{item_id}x{quantity}", now))
            await db.commit()
        return name, emoji, total_price, new_wallet

    async def get_inventory(self, guild_id: int, user_id: int) -> list[tuple[str, str, str, int]]:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""SELECT s.item_id, s.name, s.emoji, i.quantity FROM inventory i
                                       JOIN shop_items s ON s.item_id = i.item_id
                                       WHERE i.guild_id = ? AND i.user_id = ? AND i.quantity > 0 ORDER BY s.price DESC""", (guild_id, user_id))
            rows = await cursor.fetchall()
        return [(str(r[0]), str(r[1]), str(r[2]), int(r[3])) for r in rows]

    async def get_inventory_detailed(self, guild_id: int, user_id: int) -> list[tuple[str, str, str, int, str, str]]:
        """Inventory rows enriched with rarity/category metadata for the shared UI."""
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT s.item_id, s.name, s.emoji, i.quantity,
                          COALESCE(s.rarity, 'common'), COALESCE(s.category, 'utility')
                   FROM inventory i
                   JOIN shop_items s ON s.item_id = i.item_id
                   WHERE i.guild_id = ? AND i.user_id = ? AND i.quantity > 0
                   ORDER BY
                     CASE COALESCE(s.rarity, 'common')
                       WHEN 'mythic' THEN 5 WHEN 'legendary' THEN 4 WHEN 'epic' THEN 3
                       WHEN 'rare' THEN 2 ELSE 1 END DESC,
                     s.price DESC, s.name ASC""",
                (guild_id, user_id),
            )
            rows = await cursor.fetchall()
        return [
            (str(r[0]), str(r[1]), str(r[2]), int(r[3]), str(r[4]), str(r[5]))
            for r in rows
        ]

    async def move_wallet_to_bank(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int]:
        return await self._move_money(guild_id, user_id, amount, wallet_to_bank=True)

    async def move_bank_to_wallet(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int]:
        return await self._move_money(guild_id, user_id, amount, wallet_to_bank=False)

    async def _move_money(self, guild_id: int, user_id: int, amount: int, wallet_to_bank: bool) -> tuple[int, int]:
        if amount <= 0: raise ValueError("Az összegnek pozitívnak kell lennie.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = await cursor.fetchone()
            if row is None: await db.rollback(); raise RuntimeError("A felhasználó nem található.")
            wallet, bank = int(row[0]), int(row[1])
            if wallet_to_bank:
                if wallet < amount: await db.rollback(); raise ValueError("Nincs ennyi pénz a tárcádban.")
                wallet -= amount; bank += amount; reason = f"deposit:{amount}"
            else:
                if bank < amount: await db.rollback(); raise ValueError("Nincs ennyi pénz a bankodban.")
                bank -= amount; wallet += amount; reason = f"withdraw:{amount}"
            await db.execute("UPDATE users SET wallet = ?, bank = ? WHERE guild_id = ? AND user_id = ?", (wallet, bank, guild_id, user_id))
            movement_stat = "economy.deposited" if wallet_to_bank else "economy.withdrawn"
            await db.execute(
                """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET value = value + excluded.value, updated_at = excluded.updated_at""",
                (guild_id, user_id, movement_stat, amount, now),
            )
            for stat_name, peak_value in (("economy.wallet_peak", wallet), ("economy.bank_peak", bank), ("economy.net_worth_peak", wallet + bank)):
                await db.execute(
                    """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at) VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET value = MAX(value, excluded.value), updated_at = excluded.updated_at""",
                    (guild_id, user_id, stat_name, peak_value, now),
                )
            await db.execute("INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, 0, ?, ?)", (guild_id, user_id, reason, now))
            await db.commit()
        return wallet, bank

    async def transfer_wallet(self, guild_id: int, sender_id: int, receiver_id: int, amount: int) -> tuple[int, int]:
        if amount <= 0: raise ValueError("Az összegnek pozitívnak kell lennie.")
        if sender_id == receiver_id: raise ValueError("Saját magadnak nem küldhetsz pénzt.")
        await self.ensure_user(guild_id, sender_id); await self.ensure_user(guild_id, receiver_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, sender_id))
            sender = await cursor.fetchone()
            if sender is None or int(sender[0]) < amount: await db.rollback(); raise ValueError("Nincs ennyi pénz a tárcádban.")
            sender_wallet = int(sender[0]) - amount
            await db.execute("UPDATE users SET wallet = ? WHERE guild_id = ? AND user_id = ?", (sender_wallet, guild_id, sender_id))
            await db.execute("UPDATE users SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?", (amount, guild_id, receiver_id))
            cursor = await db.execute("SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, receiver_id))
            receiver_wallet = int((await cursor.fetchone())[0])
            await db.executemany("INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)", [(guild_id, sender_id, -amount, f"pay_to:{receiver_id}", now), (guild_id, receiver_id, amount, f"pay_from:{sender_id}", now)])
            await db.executemany(
                """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET value = value + excluded.value, updated_at = excluded.updated_at""",
                [
                    (guild_id, sender_id, "economy.sent", amount, now),
                    (guild_id, receiver_id, "economy.received", amount, now),
                ],
            )
            await db.commit()
        return sender_wallet, receiver_wallet

    async def leaderboard(self, guild_id: int, category: str = "money", limit: int = 10) -> list[tuple[int, int, int, int]]:
        columns = {
            "money": ("wallet + bank", "wallet", "bank"),
            "rob": ("rob_profit", "rob_success", "rob_failed"),
            "gambling": ("gambling_profit", "game_wins", "0"),
            "wins": ("game_wins", "gambling_profit", "0"),
            "work": ("work_count", "wallet", "bank"),
            "wallet": ("wallet", "wallet", "bank"),
            "bank": ("bank", "wallet", "bank"),
            "crime": ("crime_success", "crime_failed", "wallet"),
            "daily": ("daily_streak", "best_daily_streak", "daily_count"),
            "earned": ("money_earned", "money_lost", "wallet"),
            "chicken": ("chicken_wins", "wallet", "bank"),
            "scratch": ("scratch_count", "wallet", "bank"),
            "weekly": ("weekly_count", "wallet", "bank"),
            "level": ("xp_points", "wallet", "bank"),
            "investment": ("investment_profit", "wallet", "bank"),
            "jackpot": ("jackpot_wins", "wallet", "bank"),
            "lottery": ("lottery_wins", "wallet", "bank"),
        }
        primary, secondary, tertiary = columns.get(category, columns["money"])
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(f"SELECT user_id, {secondary}, {tertiary}, {primary} AS score FROM users WHERE guild_id = ? ORDER BY score DESC LIMIT ?", (guild_id, limit))
            rows = await cursor.fetchall()
        return [(int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in rows]

    async def get_transactions(self, guild_id: int, user_id: int, limit: int = 10) -> list[tuple[int, str, str]]:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT amount, reason, created_at FROM transactions WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
                (guild_id, user_id, limit),
            )
            rows = await cursor.fetchall()
        return [(int(row[0]), str(row[1]), str(row[2])) for row in rows]

    async def set_wallet(self, guild_id: int, user_id: int, amount: int, reason: str) -> int:
        if amount < 0:
            raise ValueError("Az egyenleg nem lehet negatív.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = await cursor.fetchone()
            old = int(row[0]) if row else 0
            await db.execute("UPDATE users SET wallet = ? WHERE guild_id = ? AND user_id = ?", (amount, guild_id, user_id))
            await db.execute(
                "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, amount - old, reason, now),
            )
            await db.commit()
        return amount

    async def reserve_gamble(self, guild_id: int, user_id: int, bet: int, game: str) -> int:
        """Levonja és lefoglalja a tétet egy több lépéses játékhoz."""
        if bet <= 0:
            raise ValueError("A tétnek pozitívnak kell lennie.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
            wallet = int(row[0]) if row else 0
            if wallet < bet:
                await db.rollback()
                raise ValueError("Nincs elég pénz a tárcádban ehhez a téthez.")
            wallet -= bet
            await db.execute(
                "UPDATE users SET wallet = ? WHERE guild_id = ? AND user_id = ?",
                (wallet, guild_id, user_id),
            )
            await db.execute(
                "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, -bet, f"gamble_reserve:{game}", now),
            )
            await db.commit()
        return wallet

    async def resolve_reserved_gamble(
        self,
        guild_id: int,
        user_id: int,
        bet: int,
        payout: int,
        game: str,
    ) -> int:
        """Kifizet egy korábban lefoglalt tétet. A payout a teljes visszafizetés."""
        if bet <= 0 or payout < 0:
            raise ValueError("Érvénytelen játékelszámolás.")
        await self.ensure_user(guild_id, user_id)
        profit = payout - bet
        won = payout > bet
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                UPDATE users
                SET wallet = wallet + ?,
                    gambling_profit = gambling_profit + ?,
                    game_wins = game_wins + ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (payout, profit, 1 if won else 0, guild_id, user_id),
            )
            await self._record_gamble_stats_tx(db, guild_id, user_id, game, bet, profit, won, now)
            await db.execute(
                "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, payout, f"gamble_payout:{game}", now),
            )
            cursor = await db.execute(
                "SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
            await db.commit()
        return int(row[0]) if row else 0


    async def set_daily_streak(self, guild_id: int, user_id: int, streak: int) -> None:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET daily_streak = ?, best_daily_streak = MAX(best_daily_streak, ?), daily_count = daily_count + 1 WHERE guild_id = ? AND user_id = ?",
                (streak, streak, guild_id, user_id),
            )
            await db.commit()

    async def set_jail_until(self, guild_id: int, user_id: int, until: datetime | None) -> None:
        await self.ensure_user(guild_id, user_id)
        value = until.isoformat() if until else None
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET jail_until = ? WHERE guild_id = ? AND user_id = ?", (value, guild_id, user_id))
            await db.commit()

    async def get_jail_until(self, guild_id: int, user_id: int) -> datetime | None:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT jail_until FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = await cursor.fetchone()
        if not row or not row[0]:
            return None
        value = datetime.fromisoformat(str(row[0]))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    async def consume_item(self, guild_id: int, user_id: int, item_id: str, quantity: int = 1) -> bool:
        if quantity < 1:
            return False
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT quantity FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?", (guild_id, user_id, item_id))
            row = await cursor.fetchone()
            if row is None or int(row[0]) < quantity:
                await db.rollback()
                return False
            await db.execute("UPDATE inventory SET quantity = quantity - ? WHERE guild_id = ? AND user_id = ? AND item_id = ?", (quantity, guild_id, user_id, item_id))
            await db.commit()
        return True

    async def add_item(self, guild_id: int, user_id: int, item_id: str, quantity: int = 1) -> None:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO inventory (guild_id, user_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity",
                (guild_id, user_id, item_id, quantity),
            )
            await db.commit()


    async def add_bank(self, guild_id: int, user_id: int, amount: int, reason: str) -> int:
        if amount < 0:
            raise ValueError("A banki jóváírás nem lehet negatív.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE users SET bank = bank + ?, money_earned = money_earned + ? WHERE guild_id = ? AND user_id = ?",
                (amount, amount, guild_id, user_id),
            )
            await self._add_stat_tx(db, guild_id, user_id, "economy.earned", amount, now)
            cursor = await db.execute("SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            balance_row = await cursor.fetchone()
            if balance_row:
                wallet_now, bank_now = int(balance_row[0]), int(balance_row[1])
                await self._set_stat_max_tx(db, guild_id, user_id, "economy.bank_peak", bank_now, now)
                await self._set_stat_max_tx(db, guild_id, user_id, "economy.net_worth_peak", wallet_now + bank_now, now)
            await db.execute(
                "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, amount, reason, now),
            )
            cursor = await db.execute("SELECT bank FROM users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = await cursor.fetchone()
            await db.commit()
        return int(row[0]) if row else 0

    async def get_item_quantity(self, guild_id: int, user_id: int, item_id: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT quantity FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
                (guild_id, user_id, item_id),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def transfer_item(self, guild_id: int, sender_id: int, receiver_id: int, item_id: str, quantity: int) -> tuple[str, str, int]:
        if sender_id == receiver_id:
            raise ValueError("Saját magadnak nem küldhetsz tárgyat.")
        if quantity < 1:
            raise ValueError("A mennyiség legalább 1 legyen.")
        await self.ensure_user(guild_id, sender_id)
        await self.ensure_user(guild_id, receiver_id)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT name, emoji FROM shop_items WHERE item_id = ? AND active = 1", (item_id,))
            item = await cursor.fetchone()
            if item is None:
                await db.rollback()
                raise LookupError("Nincs ilyen tárgy.")
            cursor = await db.execute(
                "SELECT quantity FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
                (guild_id, sender_id, item_id),
            )
            row = await cursor.fetchone()
            if row is None or int(row[0]) < quantity:
                await db.rollback()
                raise ValueError("Nincs ennyi ebből a tárgyból az inventorydban.")
            await db.execute(
                "UPDATE inventory SET quantity = quantity - ? WHERE guild_id = ? AND user_id = ? AND item_id = ?",
                (quantity, guild_id, sender_id, item_id),
            )
            await db.execute(
                "INSERT INTO inventory (guild_id, user_id, item_id, quantity) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity",
                (guild_id, receiver_id, item_id, quantity),
            )
            await db.commit()
        return str(item[0]), str(item[1]), quantity

    async def sell_item(self, guild_id: int, user_id: int, item_id: str, quantity: int) -> tuple[str, str, int, int]:
        if quantity < 1:
            raise ValueError("A mennyiség legalább 1 legyen.")
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT name, emoji, price FROM shop_items WHERE item_id = ? AND active = 1", (item_id,))
            item = await cursor.fetchone()
        if item is None:
            raise LookupError("Nincs ilyen tárgy.")
        if not await self.consume_item(guild_id, user_id, item_id, quantity):
            raise ValueError("Nincs ennyi ebből a tárgyból az inventorydban.")
        value = int(int(item[2]) * eco.SHOP_SELL_RATIO) * quantity
        wallet = await self.add_wallet(guild_id, user_id, value, f"sell:{item_id}x{quantity}")
        return str(item[0]), str(item[1]), value, wallet


    async def list_shop_items_detailed(self) -> list[tuple[str, str, str, int, str, str, str]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT item_id, name, description, price, emoji, rarity, category FROM shop_items WHERE active = 1 ORDER BY category, price ASC")
            rows = await cursor.fetchall()
        return [(str(r[0]), str(r[1]), str(r[2]), int(r[3]), str(r[4]), str(r[5]), str(r[6])) for r in rows]

    async def get_market_state(self, guild_id: int, item_id: str, market_date: str) -> tuple[int, int, int] | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT price, stock, starting_stock FROM market_daily WHERE guild_id=? AND item_id=? AND market_date=?",
                (guild_id, item_id, market_date),
            )
            row = await cursor.fetchone()
        return (int(row[0]), int(row[1]), int(row[2])) if row else None

    async def create_market_state(self, guild_id: int, item_id: str, market_date: str, price: int, stock: int) -> tuple[int, int, int]:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO market_daily (guild_id,item_id,market_date,price,stock,starting_stock) VALUES (?,?,?,?,?,?)",
                (guild_id, item_id, market_date, price, stock, stock),
            )
            cursor = await db.execute(
                "SELECT price, stock, starting_stock FROM market_daily WHERE guild_id=? AND item_id=? AND market_date=?",
                (guild_id, item_id, market_date),
            )
            row = await cursor.fetchone()
            await db.commit()
        return int(row[0]), int(row[1]), int(row[2])

    async def buy_market_item(self, guild_id: int, user_id: int, item_id: str, quantity: int, market_date: str) -> tuple[str, str, int, int, int]:
        if quantity < 1:
            raise ValueError("A mennyiség legalább 1 legyen.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute("SELECT name,emoji FROM shop_items WHERE item_id=? AND active=1", (item_id,))
            item = await cur.fetchone()
            cur = await db.execute("SELECT price,stock FROM market_daily WHERE guild_id=? AND item_id=? AND market_date=?", (guild_id,item_id,market_date))
            state = await cur.fetchone()
            if item is None or state is None:
                await db.rollback(); raise LookupError("A piaci item jelenleg nem elérhető.")
            price, stock = int(state[0]), int(state[1])
            if stock < quantity:
                await db.rollback(); raise ValueError(f"Nincs ennyi készleten. Jelenlegi készlet: {stock} db.")
            total = price * quantity
            cur = await db.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id))
            row = await cur.fetchone(); wallet = int(row[0]) if row else 0
            if wallet < total:
                await db.rollback(); raise ValueError("Nincs elég pénzed ehhez a vásárláshoz.")
            wallet -= total
            await db.execute("UPDATE users SET wallet=? WHERE guild_id=? AND user_id=?", (wallet,guild_id,user_id))
            await db.execute("UPDATE market_daily SET stock=stock-? WHERE guild_id=? AND item_id=? AND market_date=?", (quantity,guild_id,item_id,market_date))
            await db.execute("INSERT INTO inventory (guild_id,user_id,item_id,quantity) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity", (guild_id,user_id,item_id,quantity))
            await db.execute("INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)", (guild_id,user_id,-total,f"market_buy:{item_id}x{quantity}",now))
            await db.commit()
        return str(item[0]), str(item[1]), total, wallet, stock-quantity

    async def sell_market_item(self, guild_id: int, user_id: int, item_id: str, quantity: int, market_date: str, sell_ratio: float = eco.MARKET_SELL_RATIO) -> tuple[str, str, int, int, int]:
        if quantity < 1:
            raise ValueError("A mennyiség legalább 1 legyen.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute("SELECT name,emoji FROM shop_items WHERE item_id=? AND active=1", (item_id,))
            item = await cur.fetchone()
            cur = await db.execute("SELECT price,stock FROM market_daily WHERE guild_id=? AND item_id=? AND market_date=?", (guild_id,item_id,market_date))
            state = await cur.fetchone()
            cur = await db.execute("SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_id=?", (guild_id,user_id,item_id))
            inv = await cur.fetchone()
            if item is None or state is None:
                await db.rollback(); raise LookupError("A piaci item jelenleg nem elérhető.")
            if inv is None or int(inv[0]) < quantity:
                await db.rollback(); raise ValueError("Nincs ennyi ebből a tárgyból az inventorydban.")
            price, stock = int(state[0]), int(state[1])
            value = int(price * sell_ratio) * quantity
            await db.execute("UPDATE inventory SET quantity=quantity-? WHERE guild_id=? AND user_id=? AND item_id=?", (quantity,guild_id,user_id,item_id))
            await db.execute("UPDATE market_daily SET stock=stock+? WHERE guild_id=? AND item_id=? AND market_date=?", (quantity,guild_id,item_id,market_date))
            await db.execute("UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?", (value,guild_id,user_id))
            await db.execute("INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)", (guild_id,user_id,value,f"market_sell:{item_id}x{quantity}",now))
            cur = await db.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id)); wallet=int((await cur.fetchone())[0])
            await db.commit()
        return str(item[0]), str(item[1]), value, wallet, stock+quantity

    async def get_active_booster(self, guild_id: int, user_id: int, booster_id: str) -> tuple[float, datetime] | None:
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT multiplier, expires_at FROM active_boosters WHERE guild_id=? AND user_id=? AND booster_id=?", (guild_id, user_id, booster_id))
            row = await cursor.fetchone()
            if not row:
                return None
            expires = datetime.fromisoformat(str(row[1]))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= now:
                await db.execute("DELETE FROM active_boosters WHERE guild_id=? AND user_id=? AND booster_id=?", (guild_id, user_id, booster_id))
                await db.commit()
                return None
            return float(row[0]), expires

    async def set_booster(self, guild_id: int, user_id: int, booster_id: str, multiplier: float, expires_at: datetime) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO active_boosters (guild_id,user_id,booster_id,multiplier,expires_at) VALUES (?,?,?,?,?) ON CONFLICT(guild_id,user_id,booster_id) DO UPDATE SET multiplier=excluded.multiplier, expires_at=excluded.expires_at", (guild_id,user_id,booster_id,multiplier,expires_at.isoformat()))
            await db.commit()

    async def list_boosters(self, guild_id: int, user_id: int) -> list[tuple[str, float, datetime]]:
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM active_boosters WHERE guild_id=? AND user_id=? AND expires_at <= ?", (guild_id,user_id,now.isoformat()))
            cursor = await db.execute("SELECT booster_id,multiplier,expires_at FROM active_boosters WHERE guild_id=? AND user_id=? ORDER BY expires_at", (guild_id,user_id))
            rows = await cursor.fetchall()
            await db.commit()
        result=[]
        for r in rows:
            dt=datetime.fromisoformat(str(r[2])); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            result.append((str(r[0]),float(r[1]),dt))
        return result

    async def get_quest_assignments(
        self, guild_id: int, user_id: int, period: str, period_key: str
    ) -> list[tuple[int, str, int, int, int, str | None, bool]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT slot, quest_id, start_value, target, reward_xp, reward_item, claimed
                   FROM quest_assignments
                   WHERE guild_id=? AND user_id=? AND period=? AND period_key=?
                   ORDER BY slot""",
                (guild_id, user_id, period, period_key),
            )
            rows = await cursor.fetchall()
        return [
            (int(r[0]), str(r[1]), int(r[2]), int(r[3]), int(r[4]), str(r[5]) if r[5] is not None else None, bool(r[6]))
            for r in rows
        ]

    async def create_quest_assignment(
        self,
        guild_id: int,
        user_id: int,
        period: str,
        period_key: str,
        slot: int,
        quest_id: str,
        start_value: int,
        target: int,
        reward_xp: int,
        reward_item: str | None,
    ) -> None:
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT OR IGNORE INTO quest_assignments
                   (guild_id,user_id,period,period_key,slot,quest_id,start_value,target,reward_xp,reward_item,claimed,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,0,?)""",
                (guild_id,user_id,period,period_key,slot,quest_id,start_value,target,reward_xp,reward_item,now),
            )
            await db.commit()

    async def claim_quest_assignment(
        self, guild_id: int, user_id: int, period: str, period_key: str, slot: int
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """UPDATE quest_assignments SET claimed=1, claimed_at=?
                   WHERE guild_id=? AND user_id=? AND period=? AND period_key=? AND slot=? AND claimed=0""",
                (now, guild_id, user_id, period, period_key, slot),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_prestige_data(self, guild_id: int, user_id: int) -> dict[str, int | str | None]:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT prestige_rank,total_wealth_sacrificed,first_prestige_at,last_prestige_at FROM user_prestige WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return {
                "prestige_rank": 0,
                "total_wealth_sacrificed": 0,
                "first_prestige_at": None,
                "last_prestige_at": None,
            }
        return {
            "prestige_rank": int(row[0]),
            "total_wealth_sacrificed": int(row[1]),
            "first_prestige_at": str(row[2]) if row[2] else None,
            "last_prestige_at": str(row[3]) if row[3] else None,
        }

    async def get_prestige_rank(self, guild_id: int, user_id: int) -> int:
        data = await self.get_prestige_data(guild_id, user_id)
        return int(data["prestige_rank"])

    async def perform_prestige(
        self,
        guild_id: int,
        user_id: int,
        *,
        required_xp: int,
        required_wealth: int,
    ) -> dict[str, int]:
        """Atomikus prestige reset. Prémium reward itemeket és lifetime adatokat megőrzi."""
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT wallet,bank,xp_points FROM users WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("A felhasználó nem található.")
                wallet, bank, xp_points = int(row[0]), int(row[1]), int(row[2])
                wealth = wallet + bank
                if xp_points < int(required_xp):
                    raise ValueError("A prestige level követelménye már nem teljesül. Nyisd meg újra a prestige panelt.")
                if wealth < int(required_wealth):
                    raise ValueError("A prestige vagyon követelménye már nem teljesül. Nyisd meg újra a prestige panelt.")

                cursor = await db.execute(
                    "SELECT prestige_rank,total_wealth_sacrificed,first_prestige_at FROM user_prestige WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                prestige_row = await cursor.fetchone()
                old_rank = int(prestige_row[0]) if prestige_row else 0
                old_total = int(prestige_row[1]) if prestige_row else 0
                first_at = str(prestige_row[2]) if prestige_row and prestige_row[2] else now
                new_rank = old_rank + 1

                # A valódi/premium reward itemek megmaradnak; minden gazdasági
                # item eltűnik, így nem lehet inventoryban vagy market assetben
                # vagyont átmenteni a prestige reseten.
                cursor = await db.execute(
                    """SELECT COALESCE(SUM(quantity), 0) FROM inventory
                       WHERE guild_id=? AND user_id=?
                         AND item_id NOT IN (SELECT item_id FROM shop_items WHERE category='reward')""",
                    (guild_id, user_id),
                )
                item_count_row = await cursor.fetchone()
                removed_items = int(item_count_row[0]) if item_count_row else 0
                await db.execute(
                    """DELETE FROM inventory
                       WHERE guild_id=? AND user_id=?
                         AND item_id NOT IN (SELECT item_id FROM shop_items WHERE category='reward')""",
                    (guild_id, user_id),
                )
                cursor = await db.execute(
                    "DELETE FROM active_boosters WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                removed_boosters = max(0, int(cursor.rowcount or 0))

                await db.execute(
                    "UPDATE users SET wallet=?, bank=0, xp_points=0 WHERE guild_id=? AND user_id=?",
                    (self.starting_balance, guild_id, user_id),
                )
                await db.execute(
                    """INSERT INTO user_prestige
                       (guild_id,user_id,prestige_rank,total_wealth_sacrificed,first_prestige_at,last_prestige_at)
                       VALUES (?,?,?,?,?,?)
                       ON CONFLICT(guild_id,user_id) DO UPDATE SET
                         prestige_rank=excluded.prestige_rank,
                         total_wealth_sacrificed=excluded.total_wealth_sacrificed,
                         first_prestige_at=COALESCE(user_prestige.first_prestige_at, excluded.first_prestige_at),
                         last_prestige_at=excluded.last_prestige_at""",
                    (guild_id, user_id, new_rank, old_total + wealth, first_at, now),
                )

                for stat_name, amount in (
                    ("prestige.count", 1),
                    ("prestige.wealth_sacrificed", wealth),
                ):
                    await db.execute(
                        """INSERT INTO user_statistics (guild_id,user_id,stat_name,value,updated_at)
                           VALUES (?,?,?,?,?)
                           ON CONFLICT(guild_id,user_id,stat_name) DO UPDATE SET
                             value=value+excluded.value, updated_at=excluded.updated_at""",
                        (guild_id, user_id, stat_name, amount, now),
                    )
                await db.execute(
                    """INSERT INTO user_statistics (guild_id,user_id,stat_name,value,updated_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(guild_id,user_id,stat_name) DO UPDATE SET
                         value=MAX(value, excluded.value), updated_at=excluded.updated_at""",
                    (guild_id, user_id, "prestige.highest", new_rank, now),
                )
                await db.execute(
                    "INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                    (guild_id, user_id, -wealth, f"prestige:{new_rank}", now),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        return {
            "old_rank": old_rank,
            "new_rank": new_rank,
            "wealth_sacrificed": wealth,
            "removed_items": removed_items,
            "removed_boosters": removed_boosters,
        }

    async def prestige_leaderboard(self, guild_id: int, limit: int = 10) -> list[tuple[int, int, int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT user_id,prestige_rank,total_wealth_sacrificed
                   FROM user_prestige WHERE guild_id=? AND prestige_rank>0
                   ORDER BY prestige_rank DESC,total_wealth_sacrificed DESC LIMIT ?""",
                (guild_id, max(1, int(limit))),
            )
            rows = await cursor.fetchall()
        return [(int(r[0]), int(r[1]), int(r[2])) for r in rows]

    @staticmethod
    def _crew_dict(row) -> dict[str, int | str]:
        return {
            "crew_id": int(row[0]),
            "guild_id": int(row[1]),
            "name": str(row[2]),
            "owner_id": int(row[3]),
            "bank": int(row[4]),
            "level": int(row[5]),
            "total_contributed": int(row[6]),
            "description": str(row[7] or ""),
            "created_at": str(row[8]),
            "member_count": int(row[9]),
        }

    async def get_crew(self, guild_id: int, crew_id: int) -> dict[str, int | str] | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT c.crew_id,c.guild_id,c.name,c.owner_id,c.bank,c.level,c.total_contributed,
                          c.description,c.created_at,
                          (SELECT COUNT(*) FROM crew_members m WHERE m.guild_id=c.guild_id AND m.crew_id=c.crew_id)
                   FROM crews c WHERE c.guild_id=? AND c.crew_id=?""",
                (guild_id, crew_id),
            )
            row = await cursor.fetchone()
        return self._crew_dict(row) if row else None

    async def get_crew_membership(
        self, guild_id: int, user_id: int
    ) -> tuple[dict[str, int | str], dict[str, int | str]] | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT c.crew_id,c.guild_id,c.name,c.owner_id,c.bank,c.level,c.total_contributed,
                          c.description,c.created_at,
                          (SELECT COUNT(*) FROM crew_members mm WHERE mm.guild_id=c.guild_id AND mm.crew_id=c.crew_id),
                          m.user_id,m.role,m.contributed,m.joined_at
                   FROM crew_members m
                   JOIN crews c ON c.crew_id=m.crew_id AND c.guild_id=m.guild_id
                   WHERE m.guild_id=? AND m.user_id=?""",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        crew = self._crew_dict(row[:10])
        member = {
            "user_id": int(row[10]),
            "role": str(row[11]),
            "contributed": int(row[12]),
            "joined_at": str(row[13]),
        }
        return crew, member

    async def get_crew_members(self, guild_id: int, crew_id: int) -> list[dict[str, int | str]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT user_id,role,contributed,joined_at
                   FROM crew_members WHERE guild_id=? AND crew_id=?
                   ORDER BY CASE role WHEN 'leader' THEN 2 WHEN 'officer' THEN 1 ELSE 0 END DESC,
                            contributed DESC, joined_at ASC""",
                (guild_id, crew_id),
            )
            rows = await cursor.fetchall()
        return [
            {"user_id": int(r[0]), "role": str(r[1]), "contributed": int(r[2]), "joined_at": str(r[3])}
            for r in rows
        ]

    async def create_crew(
        self,
        guild_id: int,
        user_id: int,
        name: str,
        normalized_name: str,
        cost: int,
    ) -> dict[str, int | str]:
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT crew_id FROM crew_members WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                if await cursor.fetchone():
                    raise ValueError("Már egy Crew tagja vagy.")
                cursor = await db.execute(
                    "SELECT 1 FROM crews WHERE guild_id=? AND normalized_name=?",
                    (guild_id, normalized_name),
                )
                if await cursor.fetchone():
                    raise ValueError("Ezen a szerveren már van ilyen nevű Crew.")
                cursor = await db.execute(
                    "SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                row = await cursor.fetchone()
                wallet = int(row[0]) if row else 0
                if wallet < int(cost):
                    raise ValueError(f"A Crew alapítása ${int(cost):,}, de nincs elég pénz a tárcádban.".replace(",", " "))

                await db.execute(
                    "UPDATE users SET wallet=wallet-?, money_lost=money_lost+? WHERE guild_id=? AND user_id=?",
                    (int(cost), int(cost), guild_id, user_id),
                )
                cursor = await db.execute(
                    """INSERT INTO crews (guild_id,name,normalized_name,owner_id,bank,level,total_contributed,description,created_at)
                       VALUES (?,?,?,?,0,1,0,'',?)""",
                    (guild_id, name, normalized_name, user_id, now),
                )
                crew_id = int(cursor.lastrowid or 0)
                await db.execute(
                    "INSERT INTO crew_members (guild_id,crew_id,user_id,role,contributed,joined_at) VALUES (?,?,?,'leader',0,?)",
                    (guild_id, crew_id, user_id, now),
                )
                await db.execute(
                    "INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                    (guild_id, user_id, -int(cost), f"crew_create:{crew_id}", now),
                )
                await self._add_stat_tx(db, guild_id, user_id, "economy.lost", int(cost), now)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        crew = await self.get_crew(guild_id, crew_id)
        if crew is None:
            raise RuntimeError("A Crew létrehozása sikertelen volt.")
        return crew

    async def set_crew_invite(
        self,
        guild_id: int,
        crew_id: int,
        user_id: int,
        invited_by: int,
        expires_at: datetime,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO crew_invites (guild_id,crew_id,user_id,invited_by,created_at,expires_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(guild_id,user_id) DO UPDATE SET
                     crew_id=excluded.crew_id, invited_by=excluded.invited_by,
                     created_at=excluded.created_at, expires_at=excluded.expires_at""",
                (guild_id, crew_id, user_id, invited_by, now, expires_at.isoformat()),
            )
            await db.commit()

    async def get_crew_invite(
        self, guild_id: int, user_id: int
    ) -> tuple[dict[str, int | str], str] | None:
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT i.crew_id,i.expires_at FROM crew_invites i
                   WHERE i.guild_id=? AND i.user_id=?""",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            expires = datetime.fromisoformat(str(row[1]))
            expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
            if expires <= now:
                await db.execute("DELETE FROM crew_invites WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                await db.commit()
                return None
            crew_id = int(row[0])
        crew = await self.get_crew(guild_id, crew_id)
        return (crew, expires.isoformat()) if crew else None

    async def accept_crew_invite(self, guild_id: int, user_id: int, member_cap: int) -> int:
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT crew_id FROM crew_members WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                if await cursor.fetchone():
                    raise ValueError("Már egy Crew tagja vagy.")
                cursor = await db.execute(
                    "SELECT crew_id,expires_at FROM crew_invites WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                invite = await cursor.fetchone()
                if invite is None:
                    raise ValueError("Nincs aktív Crew meghívód.")
                expires = datetime.fromisoformat(str(invite[1]))
                expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
                if expires <= now:
                    await db.execute("DELETE FROM crew_invites WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                    raise ValueError("A Crew meghívód lejárt.")
                crew_id = int(invite[0])
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM crew_members WHERE guild_id=? AND crew_id=?",
                    (guild_id, crew_id),
                )
                count = int((await cursor.fetchone())[0])
                if count >= int(member_cap):
                    raise ValueError("A Crew időközben megtelt.")
                await db.execute(
                    "INSERT INTO crew_members (guild_id,crew_id,user_id,role,contributed,joined_at) VALUES (?,?,?,'member',0,?)",
                    (guild_id, crew_id, user_id, now.isoformat()),
                )
                await db.execute("DELETE FROM crew_invites WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                await db.commit()
                return crew_id
            except Exception:
                await db.rollback()
                raise

    async def remove_crew_member(self, guild_id: int, crew_id: int, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=? AND role!='leader'",
                (guild_id, crew_id, user_id),
            )
            await db.execute("DELETE FROM crew_invites WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            await db.commit()
        if cursor.rowcount <= 0:
            raise ValueError("A Crew tag nem távolítható el.")

    async def set_crew_member_role(self, guild_id: int, crew_id: int, user_id: int, role: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "UPDATE crew_members SET role=? WHERE guild_id=? AND crew_id=? AND user_id=? AND role!='leader'",
                (role, guild_id, crew_id, user_id),
            )
            await db.commit()
        if cursor.rowcount <= 0:
            raise ValueError("A Crew rang nem módosítható.")

    async def transfer_crew_ownership(
        self, guild_id: int, crew_id: int, old_owner_id: int, new_owner_id: int
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT role FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=?",
                    (guild_id, crew_id, old_owner_id),
                )
                old = await cursor.fetchone()
                cursor = await db.execute(
                    "SELECT role FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=?",
                    (guild_id, crew_id, new_owner_id),
                )
                new = await cursor.fetchone()
                if not old or str(old[0]) != "leader" or not new:
                    raise ValueError("A vezetés átadása nem lehetséges.")
                await db.execute(
                    "UPDATE crew_members SET role='member' WHERE guild_id=? AND crew_id=? AND user_id=?",
                    (guild_id, crew_id, old_owner_id),
                )
                await db.execute(
                    "UPDATE crew_members SET role='leader' WHERE guild_id=? AND crew_id=? AND user_id=?",
                    (guild_id, crew_id, new_owner_id),
                )
                await db.execute(
                    "UPDATE crews SET owner_id=? WHERE guild_id=? AND crew_id=?",
                    (new_owner_id, guild_id, crew_id),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def deposit_to_crew(
        self, guild_id: int, crew_id: int, user_id: int, amount: int
    ) -> tuple[int, int]:
        if amount <= 0:
            raise ValueError("Az összegnek pozitívnak kell lennie.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT 1 FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=?",
                    (guild_id, crew_id, user_id),
                )
                if await cursor.fetchone() is None:
                    raise ValueError("Nem vagy ennek a Crew-nak a tagja.")
                cursor = await db.execute(
                    "SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                wallet = int((await cursor.fetchone())[0])
                if wallet < amount:
                    raise ValueError("Nincs ennyi pénz a tárcádban.")
                await db.execute("UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=?", (amount, guild_id, user_id))
                await db.execute(
                    "UPDATE crews SET bank=bank+?, total_contributed=total_contributed+? WHERE guild_id=? AND crew_id=?",
                    (amount, amount, guild_id, crew_id),
                )
                await db.execute(
                    "UPDATE crew_members SET contributed=contributed+? WHERE guild_id=? AND crew_id=? AND user_id=?",
                    (amount, guild_id, crew_id, user_id),
                )
                await db.execute(
                    "INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                    (guild_id, user_id, -amount, f"crew_deposit:{crew_id}", now),
                )
                cursor = await db.execute("SELECT bank FROM crews WHERE guild_id=? AND crew_id=?", (guild_id, crew_id))
                crew_bank = int((await cursor.fetchone())[0])
                await db.commit()
                return wallet - amount, crew_bank
            except Exception:
                await db.rollback()
                raise

    async def withdraw_from_crew(
        self, guild_id: int, crew_id: int, user_id: int, amount: int
    ) -> tuple[int, int]:
        if amount <= 0:
            raise ValueError("Az összegnek pozitívnak kell lennie.")
        await self.ensure_user(guild_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT role FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=?",
                    (guild_id, crew_id, user_id),
                )
                member = await cursor.fetchone()
                if member is None or str(member[0]) != "leader":
                    raise ValueError("Csak a Crew Leader vehet ki pénzt.")
                cursor = await db.execute("SELECT bank FROM crews WHERE guild_id=? AND crew_id=?", (guild_id, crew_id))
                row = await cursor.fetchone()
                crew_bank = int(row[0]) if row else 0
                if crew_bank < amount:
                    raise ValueError("Nincs ennyi pénz a Crew Bankban.")
                await db.execute("UPDATE crews SET bank=bank-? WHERE guild_id=? AND crew_id=?", (amount, guild_id, crew_id))
                await db.execute("UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?", (amount, guild_id, user_id))
                await db.execute(
                    "INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                    (guild_id, user_id, amount, f"crew_withdraw:{crew_id}", now),
                )
                cursor = await db.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                wallet = int((await cursor.fetchone())[0])
                await db.commit()
                return wallet, crew_bank - amount
            except Exception:
                await db.rollback()
                raise

    async def upgrade_crew(
        self, guild_id: int, crew_id: int, expected_level: int, cost: int
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT level,bank FROM crews WHERE guild_id=? AND crew_id=?",
                    (guild_id, crew_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError("A Crew nem található.")
                level, bank = int(row[0]), int(row[1])
                if level != int(expected_level):
                    raise ValueError("A Crew szintje időközben megváltozott. Nyisd meg újra a panelt.")
                if bank < int(cost):
                    raise ValueError(f"A fejlesztéshez ${int(cost):,} kell a Crew Bankban.".replace(",", " "))
                await db.execute(
                    "UPDATE crews SET bank=bank-?, level=level+1 WHERE guild_id=? AND crew_id=? AND level=?",
                    (int(cost), guild_id, crew_id, level),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def set_crew_description(self, guild_id: int, crew_id: int, description: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE crews SET description=? WHERE guild_id=? AND crew_id=?",
                (description, guild_id, crew_id),
            )
            await db.commit()

    async def disband_crew(self, guild_id: int, crew_id: int, owner_id: int) -> tuple[str, int]:
        await self.ensure_user(guild_id, owner_id)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT name,owner_id,bank FROM crews WHERE guild_id=? AND crew_id=?",
                    (guild_id, crew_id),
                )
                row = await cursor.fetchone()
                if row is None or int(row[1]) != owner_id:
                    raise ValueError("Csak a Crew Leader oszlathatja fel a Crew-t.")
                name, bank = str(row[0]), int(row[2])
                if bank:
                    await db.execute("UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?", (bank, guild_id, owner_id))
                    await db.execute(
                        "INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                        (guild_id, owner_id, bank, f"crew_disband_refund:{crew_id}", now),
                    )
                await db.execute("DELETE FROM crew_invites WHERE guild_id=? AND crew_id=?", (guild_id, crew_id))
                await db.execute("DELETE FROM crew_members WHERE guild_id=? AND crew_id=?", (guild_id, crew_id))
                await db.execute("DELETE FROM crews WHERE guild_id=? AND crew_id=?", (guild_id, crew_id))
                await db.commit()
                return name, bank
            except Exception:
                await db.rollback()
                raise

    async def crew_leaderboard(self, guild_id: int, limit: int = 10) -> list[dict[str, int | str]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT c.crew_id,c.guild_id,c.name,c.owner_id,c.bank,c.level,c.total_contributed,
                          c.description,c.created_at,
                          (SELECT COUNT(*) FROM crew_members m WHERE m.guild_id=c.guild_id AND m.crew_id=c.crew_id)
                   FROM crews c WHERE c.guild_id=?
                   ORDER BY c.level DESC,c.total_contributed DESC,c.bank DESC,c.created_at ASC LIMIT ?""",
                (guild_id, max(1, int(limit))),
            )
            rows = await cursor.fetchall()
        return [self._crew_dict(row) for row in rows]

    async def unlock_achievement(self, guild_id: int, user_id: int, achievement_id: str) -> bool:
        now=datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor=await db.execute("INSERT OR IGNORE INTO achievements (guild_id,user_id,achievement_id,unlocked_at) VALUES (?,?,?,?)",(guild_id,user_id,achievement_id,now))
            await db.commit()
            return cursor.rowcount > 0

    async def get_achievements(self, guild_id: int, user_id: int) -> list[str]:
        async with aiosqlite.connect(self.path) as db:
            cursor=await db.execute("SELECT achievement_id FROM achievements WHERE guild_id=? AND user_id=? ORDER BY unlocked_at",(guild_id,user_id))
            rows=await cursor.fetchall()
        return [str(r[0]) for r in rows]

    async def unlock_badge(self, guild_id: int, user_id: int, badge_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO user_badges (guild_id,user_id,badge_id,unlocked_at) VALUES (?,?,?,?)",
                (guild_id, user_id, badge_id, now),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_badges(self, guild_id: int, user_id: int) -> list[str]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT badge_id FROM user_badges WHERE guild_id=? AND user_id=? ORDER BY unlocked_at",
                (guild_id, user_id),
            )
            rows = await cursor.fetchall()
        return [str(r[0]) for r in rows]

    async def set_title(self, guild_id: int, user_id: int, title: str) -> None:
        await self.ensure_user(guild_id,user_id)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET selected_title=? WHERE guild_id=? AND user_id=?",(title,guild_id,user_id))
            await db.commit()

    async def add_lottery_tickets(self, guild_id: int, user_id: int, tickets: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO lottery_entries (guild_id,user_id,tickets) VALUES (?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET tickets=tickets+excluded.tickets",(guild_id,user_id,tickets))
            await db.commit()

    async def get_lottery_entries(self, guild_id: int) -> list[tuple[int,int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor=await db.execute("SELECT user_id,tickets FROM lottery_entries WHERE guild_id=? AND tickets>0",(guild_id,))
            rows=await cursor.fetchall()
        return [(int(r[0]),int(r[1])) for r in rows]

    async def clear_lottery(self, guild_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM lottery_entries WHERE guild_id=?",(guild_id,))
            await db.commit()

    async def set_guild_state(self, guild_id: int, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO guild_state (guild_id,key,value) VALUES (?,?,?) ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",(guild_id,key,value))
            await db.commit()

    async def get_guild_state(self, guild_id: int, key: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            cursor=await db.execute("SELECT value FROM guild_state WHERE guild_id=? AND key=?",(guild_id,key))
            row=await cursor.fetchone()
        return str(row[0]) if row else None

    async def get_shop_item(self, item_id: str) -> tuple[str, str, int, str, str] | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT name, emoji, price, rarity, category FROM shop_items WHERE item_id = ? AND active = 1",
                (item_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1]), int(row[2]), str(row[3]), str(row[4])


    async def set_guild_effect(self, guild_id: int, effect_id: str, multiplier: float, expires_at: datetime) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO guild_effects (guild_id,effect_id,multiplier,expires_at) VALUES (?,?,?,?) ON CONFLICT(guild_id,effect_id) DO UPDATE SET multiplier=excluded.multiplier, expires_at=excluded.expires_at", (guild_id,effect_id,multiplier,expires_at.isoformat()))
            await db.commit()

    async def get_guild_effect(self, guild_id: int, effect_id: str) -> tuple[float, datetime] | None:
        now=datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as db:
            cursor=await db.execute("SELECT multiplier,expires_at FROM guild_effects WHERE guild_id=? AND effect_id=?",(guild_id,effect_id))
            row=await cursor.fetchone()
            if not row:
                return None
            exp=datetime.fromisoformat(str(row[1])); exp=exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
            if exp<=now:
                await db.execute("DELETE FROM guild_effects WHERE guild_id=? AND effect_id=?",(guild_id,effect_id)); await db.commit(); return None
            return float(row[0]),exp

    async def list_guild_effects(self, guild_id: int) -> list[tuple[str,float,datetime]]:
        now=datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM guild_effects WHERE guild_id=? AND expires_at<=?",(guild_id,now.isoformat()))
            cursor=await db.execute("SELECT effect_id,multiplier,expires_at FROM guild_effects WHERE guild_id=?",(guild_id,))
            rows=await cursor.fetchall(); await db.commit()
        result=[]
        for eid,mult,expraw in rows:
            exp=datetime.fromisoformat(str(expraw)); exp=exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
            result.append((str(eid),float(mult),exp))
        return result

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT INTO moderation_warnings (guild_id,user_id,moderator_id,reason,created_at) VALUES (?,?,?,?,?)",
                (guild_id, user_id, moderator_id, reason, now),
            )
            await db.commit()
            return int(cursor.lastrowid or 0)

    async def warning_count(self, guild_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM moderation_warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def get_warnings(self, guild_id: int, user_id: int, limit: int = 15) -> list[tuple[int, int, str, str]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT id,moderator_id,reason,created_at FROM moderation_warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
                (guild_id, user_id, limit),
            )
            return [(int(r[0]), int(r[1]), str(r[2]), str(r[3])) for r in await cursor.fetchall()]

    async def clear_warnings(self, guild_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("DELETE FROM moderation_warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            await db.commit()
            return int(cursor.rowcount or 0)

    async def add_mod_case(self, guild_id: int, action: str, target_id: int, moderator_id: int, reason: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT INTO moderation_cases (guild_id,action,target_id,moderator_id,reason,created_at) VALUES (?,?,?,?,?,?)",
                (guild_id, action, target_id, moderator_id, reason, now),
            )
            await db.commit()
            return int(cursor.lastrowid or 0)

    async def get_mod_cases(self, guild_id: int, target_id: int | None = None, limit: int = 15) -> list[tuple[int, str, int, int, str, str]]:
        async with aiosqlite.connect(self.path) as db:
            if target_id is None:
                cursor = await db.execute(
                    "SELECT id,action,target_id,moderator_id,reason,created_at FROM moderation_cases WHERE guild_id=? ORDER BY id DESC LIMIT ?",
                    (guild_id, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT id,action,target_id,moderator_id,reason,created_at FROM moderation_cases WHERE guild_id=? AND target_id=? ORDER BY id DESC LIMIT ?",
                    (guild_id, target_id, limit),
                )
            return [(int(r[0]), str(r[1]), int(r[2]), int(r[3]), str(r[4]), str(r[5])) for r in await cursor.fetchall()]


    async def get_mod_case(self, guild_id: int, case_id: int) -> tuple[int, str, int, int, str, str] | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT id,action,target_id,moderator_id,reason,created_at FROM moderation_cases WHERE guild_id=? AND id=?",
                (guild_id, case_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return int(row[0]), str(row[1]), int(row[2]), int(row[3]), str(row[4]), str(row[5])

    async def get_automod_rule(self, guild_id: int, rule: str) -> tuple[bool, str, int, int] | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT enabled,action,threshold,timeout_seconds FROM automod_rules WHERE guild_id=? AND rule=?",
                (guild_id, rule),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return bool(row[0]), str(row[1]), int(row[2]), int(row[3])

    async def set_automod_rule(
        self, guild_id: int, rule: str, enabled: bool, action: str, threshold: int, timeout_seconds: int
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO automod_rules (guild_id,rule,enabled,action,threshold,timeout_seconds)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(guild_id,rule) DO UPDATE SET
                     enabled=excluded.enabled, action=excluded.action,
                     threshold=excluded.threshold, timeout_seconds=excluded.timeout_seconds""",
                (guild_id, rule, int(enabled), action, int(threshold), int(timeout_seconds)),
            )
            await db.commit()

    async def list_automod_rules(self, guild_id: int) -> dict[str, tuple[bool, str, int, int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT rule,enabled,action,threshold,timeout_seconds FROM automod_rules WHERE guild_id=?",
                (guild_id,),
            )
            rows = await cursor.fetchall()
        return {str(r[0]): (bool(r[1]), str(r[2]), int(r[3]), int(r[4])) for r in rows}

    async def add_automod_exemption(self, guild_id: int, rule: str, scope_type: str, scope_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO automod_exemptions (guild_id,rule,scope_type,scope_id) VALUES (?,?,?,?)",
                (guild_id, rule, scope_type, scope_id),
            )
            await db.commit()

    async def remove_automod_exemption(self, guild_id: int, rule: str, scope_type: str, scope_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM automod_exemptions WHERE guild_id=? AND rule=? AND scope_type=? AND scope_id=?",
                (guild_id, rule, scope_type, scope_id),
            )
            await db.commit()
            return bool(cursor.rowcount)

    async def list_automod_exemptions(self, guild_id: int, rule: str | None = None) -> list[tuple[str, str, int]]:
        async with aiosqlite.connect(self.path) as db:
            if rule is None:
                cursor = await db.execute(
                    "SELECT rule,scope_type,scope_id FROM automod_exemptions WHERE guild_id=? ORDER BY rule,scope_type,scope_id",
                    (guild_id,),
                )
            else:
                cursor = await db.execute(
                    "SELECT rule,scope_type,scope_id FROM automod_exemptions WHERE guild_id=? AND rule IN (?, 'all') ORDER BY rule,scope_type,scope_id",
                    (guild_id, rule),
                )
            rows = await cursor.fetchall()
        return [(str(r[0]), str(r[1]), int(r[2])) for r in rows]

    async def set_automod_domain(self, guild_id: int, mode: str, domain: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            # A domain cannot be both allowed and blocked.
            await db.execute("DELETE FROM automod_domains WHERE guild_id=? AND domain=?", (guild_id, domain))
            await db.execute(
                "INSERT OR REPLACE INTO automod_domains (guild_id,mode,domain) VALUES (?,?,?)",
                (guild_id, mode, domain),
            )
            await db.commit()

    async def remove_automod_domain(self, guild_id: int, domain: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("DELETE FROM automod_domains WHERE guild_id=? AND domain=?", (guild_id, domain))
            await db.commit()
            return bool(cursor.rowcount)

    async def list_automod_domains(self, guild_id: int, mode: str | None = None) -> list[tuple[str, str]]:
        async with aiosqlite.connect(self.path) as db:
            if mode is None:
                cursor = await db.execute("SELECT mode,domain FROM automod_domains WHERE guild_id=? ORDER BY mode,domain", (guild_id,))
            else:
                cursor = await db.execute("SELECT mode,domain FROM automod_domains WHERE guild_id=? AND mode=? ORDER BY domain", (guild_id, mode))
            rows = await cursor.fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]

    async def add_automod_word(self, guild_id: int, word: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR IGNORE INTO automod_words (guild_id,word) VALUES (?,?)", (guild_id, word))
            await db.commit()

    async def remove_automod_word(self, guild_id: int, word: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("DELETE FROM automod_words WHERE guild_id=? AND word=?", (guild_id, word))
            await db.commit()
            return bool(cursor.rowcount)

    async def list_automod_words(self, guild_id: int) -> list[str]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT word FROM automod_words WHERE guild_id=? ORDER BY word", (guild_id,))
            rows = await cursor.fetchall()
        return [str(r[0]) for r in rows]


    # -------------------- Yoru v3.7 persistent role / verification panels --------------------

    async def create_role_panel(
        self,
        guild_id: int,
        channel_id: int,
        title: str,
        description: str,
        mode: str,
        created_by: int,
        items: list[tuple[int, str, str | None, int]],
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            cursor = await db.execute(
                """INSERT INTO role_panels
                   (guild_id,channel_id,message_id,title,description,mode,active,created_by,created_at)
                   VALUES (?,?,NULL,?,?,?,1,?,?)""",
                (guild_id, channel_id, title, description, mode, created_by, now),
            )
            panel_id = int(cursor.lastrowid)
            await db.executemany(
                "INSERT INTO role_panel_items (panel_id,role_id,label,emoji,position) VALUES (?,?,?,?,?)",
                [(panel_id, role_id, label, emoji, position) for role_id, label, emoji, position in items],
            )
            await db.commit()
        return panel_id

    async def set_role_panel_message(self, panel_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE role_panels SET message_id=? WHERE panel_id=?", (message_id, panel_id))
            await db.commit()

    async def get_role_panel(self, panel_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT panel_id,guild_id,channel_id,message_id,title,description,mode,active,created_by,created_at FROM role_panels WHERE panel_id=?",
                (panel_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            cursor = await db.execute(
                "SELECT role_id,label,emoji,position FROM role_panel_items WHERE panel_id=? ORDER BY position,role_id",
                (panel_id,),
            )
            items = await cursor.fetchall()
        return {
            "panel_id": int(row[0]), "guild_id": int(row[1]), "channel_id": int(row[2]),
            "message_id": int(row[3]) if row[3] is not None else None, "title": str(row[4]),
            "description": str(row[5]), "mode": str(row[6]), "active": bool(row[7]),
            "created_by": int(row[8]), "created_at": str(row[9]),
            "items": [(int(i[0]), str(i[1]), str(i[2]) if i[2] else None, int(i[3])) for i in items],
        }

    async def list_role_panels(self, guild_id: int | None = None, *, active_only: bool = False) -> list[dict]:
        clauses, params = [], []
        if guild_id is not None:
            clauses.append("guild_id=?")
            params.append(guild_id)
        if active_only:
            clauses.append("active=1")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                f"SELECT panel_id FROM role_panels{where} ORDER BY panel_id", tuple(params)
            )
            ids = [int(r[0]) for r in await cursor.fetchall()]
        result = []
        for panel_id in ids:
            panel = await self.get_role_panel(panel_id)
            if panel is not None:
                result.append(panel)
        return result

    async def deactivate_role_panel(self, panel_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("UPDATE role_panels SET active=0 WHERE panel_id=? AND active=1", (panel_id,))
            await db.commit()
            return bool(cursor.rowcount)

    async def delete_role_panel(self, panel_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            cursor = await db.execute("DELETE FROM role_panels WHERE panel_id=?", (panel_id,))
            await db.commit()
            return bool(cursor.rowcount)

    async def upsert_verification_panel(
        self, guild_id: int, channel_id: int, role_id: int, remove_role_id: int | None,
        title: str, body: str, button_label: str, message_id: int | None = None, active: bool = True,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO verification_panels
                   (guild_id,channel_id,message_id,role_id,remove_role_id,title,body,button_label,active)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                     channel_id=excluded.channel_id,message_id=excluded.message_id,role_id=excluded.role_id,
                     remove_role_id=excluded.remove_role_id,title=excluded.title,body=excluded.body,
                     button_label=excluded.button_label,active=excluded.active""",
                (guild_id, channel_id, message_id, role_id, remove_role_id, title, body, button_label, int(active)),
            )
            await db.commit()

    async def set_verification_message(self, guild_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE verification_panels SET message_id=?, active=1 WHERE guild_id=?", (message_id, guild_id))
            await db.commit()

    async def get_verification_panel(self, guild_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT guild_id,channel_id,message_id,role_id,remove_role_id,title,body,button_label,active FROM verification_panels WHERE guild_id=?",
                (guild_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "guild_id": int(row[0]), "channel_id": int(row[1]),
            "message_id": int(row[2]) if row[2] is not None else None, "role_id": int(row[3]),
            "remove_role_id": int(row[4]) if row[4] is not None else None, "title": str(row[5]),
            "body": str(row[6]), "button_label": str(row[7]), "active": bool(row[8]),
        }

    async def list_verification_panels(self, *, active_only: bool = False) -> list[dict]:
        query = "SELECT guild_id FROM verification_panels" + (" WHERE active=1" if active_only else "") + " ORDER BY guild_id"
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(query)
            ids = [int(r[0]) for r in await cursor.fetchall()]
        result = []
        for guild_id in ids:
            panel = await self.get_verification_panel(guild_id)
            if panel is not None:
                result.append(panel)
        return result

    async def deactivate_verification_panel(self, guild_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("UPDATE verification_panels SET active=0 WHERE guild_id=? AND active=1", (guild_id,))
            await db.commit()
            return bool(cursor.rowcount)

    async def save_member_role_snapshot(self, guild_id: int, user_id: int, role_ids: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO member_role_snapshots (guild_id,user_id,role_ids,updated_at) VALUES (?,?,?,?)
                   ON CONFLICT(guild_id,user_id) DO UPDATE SET role_ids=excluded.role_ids,updated_at=excluded.updated_at""",
                (guild_id, user_id, role_ids, now),
            )
            await db.commit()

    async def pop_member_role_snapshot(self, guild_id: int, user_id: int) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT role_ids FROM member_role_snapshots WHERE guild_id=? AND user_id=?", (guild_id, user_id)
            )
            row = await cursor.fetchone()
            if row is not None:
                await db.execute("DELETE FROM member_role_snapshots WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                await db.commit()
        return str(row[0]) if row else None

    # -------------------- Yoru v3.8 Community Management --------------------

    async def create_community_suggestion(self, guild_id: int, channel_id: int, author_id: int, content: str, anonymous: bool = False) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """INSERT INTO community_suggestions
                   (guild_id,channel_id,message_id,author_id,anonymous,content,status,created_at,updated_at)
                   VALUES (?,?,NULL,?,?,?,'pending',?,?)""",
                (guild_id, channel_id, author_id, int(anonymous), content, now, now),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def set_community_suggestion_message(self, suggestion_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE community_suggestions SET message_id=?,updated_at=? WHERE suggestion_id=?",
                (message_id, datetime.now(timezone.utc).isoformat(), suggestion_id),
            )
            await db.commit()

    async def get_community_suggestion(self, suggestion_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT suggestion_id,guild_id,channel_id,message_id,author_id,anonymous,content,status,staff_id,staff_note,created_at,updated_at
                   FROM community_suggestions WHERE suggestion_id=?""",
                (suggestion_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            cursor = await db.execute(
                "SELECT vote,COUNT(*) FROM community_suggestion_votes WHERE suggestion_id=? GROUP BY vote",
                (suggestion_id,),
            )
            counts = {int(v): int(c) for v, c in await cursor.fetchall()}
        return {
            "suggestion_id": int(row[0]), "guild_id": int(row[1]), "channel_id": int(row[2]),
            "message_id": int(row[3]) if row[3] is not None else None, "author_id": int(row[4]),
            "anonymous": bool(row[5]), "content": str(row[6]), "status": str(row[7]),
            "staff_id": int(row[8]) if row[8] is not None else None,
            "staff_note": str(row[9]) if row[9] else None,
            "created_at": str(row[10]), "updated_at": str(row[11]),
            "upvotes": counts.get(1, 0), "downvotes": counts.get(-1, 0),
        }

    async def list_active_community_suggestions(self, limit: int = 500) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT suggestion_id FROM community_suggestions WHERE status='pending' AND message_id IS NOT NULL ORDER BY suggestion_id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
            ids = [int(r[0]) for r in await cursor.fetchall()]
        result = []
        for suggestion_id in ids:
            row = await self.get_community_suggestion(suggestion_id)
            if row:
                result.append(row)
        return result

    async def toggle_community_suggestion_vote(self, suggestion_id: int, user_id: int, vote: int) -> tuple[int, int, int]:
        vote = 1 if vote > 0 else -1
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            cursor = await db.execute(
                "SELECT vote FROM community_suggestion_votes WHERE suggestion_id=? AND user_id=?",
                (suggestion_id, user_id),
            )
            row = await cursor.fetchone()
            current = int(row[0]) if row else 0
            if current == vote:
                await db.execute(
                    "DELETE FROM community_suggestion_votes WHERE suggestion_id=? AND user_id=?",
                    (suggestion_id, user_id),
                )
                current = 0
            else:
                await db.execute(
                    """INSERT INTO community_suggestion_votes(suggestion_id,user_id,vote) VALUES (?,?,?)
                       ON CONFLICT(suggestion_id,user_id) DO UPDATE SET vote=excluded.vote""",
                    (suggestion_id, user_id, vote),
                )
                current = vote
            cursor = await db.execute(
                "SELECT vote,COUNT(*) FROM community_suggestion_votes WHERE suggestion_id=? GROUP BY vote",
                (suggestion_id,),
            )
            counts = {int(v): int(c) for v, c in await cursor.fetchall()}
            await db.commit()
        return counts.get(1, 0), counts.get(-1, 0), current

    async def set_community_suggestion_status(self, suggestion_id: int, status: str, staff_id: int, note: str | None = None) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "UPDATE community_suggestions SET status=?,staff_id=?,staff_note=?,updated_at=? WHERE suggestion_id=?",
                (status, staff_id, note, datetime.now(timezone.utc).isoformat(), suggestion_id),
            )
            await db.commit()
            return bool(cursor.rowcount)

    async def create_community_poll(self, guild_id: int, channel_id: int, author_id: int, question: str, options: list[str], closes_at: datetime) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """INSERT INTO community_polls
                   (guild_id,channel_id,message_id,author_id,question,options_json,closes_at,closed,created_at)
                   VALUES (?,?,NULL,?,?,?,?,0,?)""",
                (guild_id, channel_id, author_id, question, json.dumps(options, ensure_ascii=False), closes_at.isoformat(), now),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def set_community_poll_message(self, poll_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE community_polls SET message_id=? WHERE poll_id=?", (message_id, poll_id))
            await db.commit()

    async def get_community_poll(self, poll_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT poll_id,guild_id,channel_id,message_id,author_id,question,options_json,closes_at,closed,created_at FROM community_polls WHERE poll_id=?",
                (poll_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            options = json.loads(str(row[6]))
            cursor = await db.execute(
                "SELECT option_index,COUNT(*) FROM community_poll_votes WHERE poll_id=? GROUP BY option_index",
                (poll_id,),
            )
            counts = {int(i): int(c) for i, c in await cursor.fetchall()}
        return {
            "poll_id": int(row[0]), "guild_id": int(row[1]), "channel_id": int(row[2]),
            "message_id": int(row[3]) if row[3] is not None else None, "author_id": int(row[4]),
            "question": str(row[5]), "options": [str(x) for x in options], "closes_at": str(row[7]),
            "closed": bool(row[8]), "created_at": str(row[9]), "counts": counts,
        }

    async def list_active_community_polls(self, limit: int = 250) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT poll_id FROM community_polls WHERE closed=0 AND message_id IS NOT NULL ORDER BY poll_id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
            ids = [int(r[0]) for r in await cursor.fetchall()]
        result = []
        for poll_id in ids:
            row = await self.get_community_poll(poll_id)
            if row:
                result.append(row)
        return result

    async def toggle_community_poll_vote(self, poll_id: int, user_id: int, option_index: int) -> tuple[int, dict[int, int]]:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            cursor = await db.execute(
                "SELECT option_index FROM community_poll_votes WHERE poll_id=? AND user_id=?",
                (poll_id, user_id),
            )
            row = await cursor.fetchone()
            current = int(row[0]) if row else -1
            if current == option_index:
                await db.execute(
                    "DELETE FROM community_poll_votes WHERE poll_id=? AND user_id=?",
                    (poll_id, user_id),
                )
                current = -1
            else:
                await db.execute(
                    """INSERT INTO community_poll_votes(poll_id,user_id,option_index) VALUES (?,?,?)
                       ON CONFLICT(poll_id,user_id) DO UPDATE SET option_index=excluded.option_index""",
                    (poll_id, user_id, option_index),
                )
                current = option_index
            cursor = await db.execute(
                "SELECT option_index,COUNT(*) FROM community_poll_votes WHERE poll_id=? GROUP BY option_index",
                (poll_id,),
            )
            counts = {int(i): int(c) for i, c in await cursor.fetchall()}
            await db.commit()
        return current, counts

    async def close_community_poll(self, poll_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("UPDATE community_polls SET closed=1 WHERE poll_id=? AND closed=0", (poll_id,))
            await db.commit()
            return bool(cursor.rowcount)

    async def create_community_giveaway(self, guild_id: int, channel_id: int, host_id: int, prize: str, winner_count: int, ends_at: datetime) -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """INSERT INTO community_giveaways
                   (guild_id,channel_id,message_id,host_id,prize,winner_count,ends_at,ended,created_at)
                   VALUES (?,?,NULL,?,?,?,?,0,?)""",
                (guild_id, channel_id, host_id, prize, winner_count, ends_at.isoformat(), now),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def set_community_giveaway_message(self, giveaway_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE community_giveaways SET message_id=? WHERE giveaway_id=?", (message_id, giveaway_id))
            await db.commit()

    async def get_community_giveaway(self, giveaway_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT giveaway_id,guild_id,channel_id,message_id,host_id,prize,winner_count,ends_at,ended,created_at FROM community_giveaways WHERE giveaway_id=?",
                (giveaway_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            cursor = await db.execute(
                "SELECT user_id FROM community_giveaway_entries WHERE giveaway_id=? ORDER BY user_id",
                (giveaway_id,),
            )
            entries = [int(r[0]) for r in await cursor.fetchall()]
        return {
            "giveaway_id": int(row[0]), "guild_id": int(row[1]), "channel_id": int(row[2]),
            "message_id": int(row[3]) if row[3] is not None else None, "host_id": int(row[4]),
            "prize": str(row[5]), "winner_count": int(row[6]), "ends_at": str(row[7]),
            "ended": bool(row[8]), "created_at": str(row[9]), "entries": entries,
        }

    async def list_active_community_giveaways(self, limit: int = 250) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT giveaway_id FROM community_giveaways WHERE ended=0 AND message_id IS NOT NULL ORDER BY giveaway_id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
            ids = [int(r[0]) for r in await cursor.fetchall()]
        result = []
        for giveaway_id in ids:
            row = await self.get_community_giveaway(giveaway_id)
            if row:
                result.append(row)
        return result

    async def toggle_community_giveaway_entry(self, giveaway_id: int, user_id: int) -> tuple[bool, int]:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            cursor = await db.execute(
                "SELECT 1 FROM community_giveaway_entries WHERE giveaway_id=? AND user_id=?",
                (giveaway_id, user_id),
            )
            exists = await cursor.fetchone() is not None
            if exists:
                await db.execute(
                    "DELETE FROM community_giveaway_entries WHERE giveaway_id=? AND user_id=?",
                    (giveaway_id, user_id),
                )
                joined = False
            else:
                await db.execute(
                    "INSERT INTO community_giveaway_entries(giveaway_id,user_id) VALUES (?,?)",
                    (giveaway_id, user_id),
                )
                joined = True
            cursor = await db.execute(
                "SELECT COUNT(*) FROM community_giveaway_entries WHERE giveaway_id=?",
                (giveaway_id,),
            )
            count = int((await cursor.fetchone())[0])
            await db.commit()
        return joined, count

    async def end_community_giveaway(self, giveaway_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "UPDATE community_giveaways SET ended=1 WHERE giveaway_id=? AND ended=0",
                (giveaway_id,),
            )
            await db.commit()
            return bool(cursor.rowcount)

    async def set_community_afk(self, guild_id: int, user_id: int, reason: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO community_afk(guild_id,user_id,reason,since) VALUES (?,?,?,?)
                   ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=excluded.reason,since=excluded.since""",
                (guild_id, user_id, reason, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def get_community_afk(self, guild_id: int, user_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT reason,since FROM community_afk WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
        return {"reason": str(row[0]), "since": str(row[1])} if row else None

    async def clear_community_afk(self, guild_id: int, user_id: int) -> dict | None:
        current = await self.get_community_afk(guild_id, user_id)
        if current is None:
            return None
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM community_afk WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            await db.commit()
        return current

    async def get_community_starboard_post(self, guild_id: int, source_message_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT source_channel_id,starboard_message_id,star_count FROM community_starboard_posts WHERE guild_id=? AND source_message_id=?",
                (guild_id, source_message_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "source_channel_id": int(row[0]),
            "starboard_message_id": int(row[1]),
            "star_count": int(row[2]),
        }

    async def upsert_community_starboard_post(self, guild_id: int, source_message_id: int, source_channel_id: int, starboard_message_id: int, star_count: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO community_starboard_posts(guild_id,source_message_id,source_channel_id,starboard_message_id,star_count)
                   VALUES (?,?,?,?,?) ON CONFLICT(guild_id,source_message_id) DO UPDATE SET
                   source_channel_id=excluded.source_channel_id,
                   starboard_message_id=excluded.starboard_message_id,
                   star_count=excluded.star_count""",
                (guild_id, source_message_id, source_channel_id, starboard_message_id, star_count),
            )
            await db.commit()

    async def delete_community_starboard_post(self, guild_id: int, source_message_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM community_starboard_posts WHERE guild_id=? AND source_message_id=?",
                (guild_id, source_message_id),
            )
            await db.commit()
            return bool(cursor.rowcount)

    async def set_community_sticky(self, guild_id: int, channel_id: int, content: str, created_by: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO community_stickies(guild_id,channel_id,content,active,last_message_id,message_counter,last_posted_at,created_by)
                   VALUES (?,?,?,1,NULL,0,NULL,?) ON CONFLICT(guild_id,channel_id) DO UPDATE SET
                   content=excluded.content,active=1,message_counter=0,created_by=excluded.created_by""",
                (guild_id, channel_id, content, created_by),
            )
            await db.commit()

    async def get_community_sticky(self, guild_id: int, channel_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT content,active,last_message_id,message_counter,last_posted_at,created_by FROM community_stickies WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "content": str(row[0]), "active": bool(row[1]),
            "last_message_id": int(row[2]) if row[2] is not None else None,
            "message_counter": int(row[3]), "last_posted_at": str(row[4]) if row[4] else None,
            "created_by": int(row[5]),
        }

    async def list_community_stickies(self, guild_id: int | None = None, *, active_only: bool = True) -> list[dict]:
        clauses, params = [], []
        if guild_id is not None:
            clauses.append("guild_id=?")
            params.append(guild_id)
        if active_only:
            clauses.append("active=1")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                f"SELECT guild_id,channel_id FROM community_stickies{where} ORDER BY guild_id,channel_id",
                tuple(params),
            )
            keys = [(int(a), int(b)) for a, b in await cursor.fetchall()]
        result = []
        for gid, cid in keys:
            row = await self.get_community_sticky(gid, cid)
            if row:
                row.update({"guild_id": gid, "channel_id": cid})
                result.append(row)
        return result

    async def update_community_sticky_runtime(
        self,
        guild_id: int,
        channel_id: int,
        *,
        last_message_id: int | None = None,
        message_counter: int | None = None,
        last_posted_at: str | None = None,
    ) -> None:
        fields, params = [], []
        if last_message_id is not None:
            fields.append("last_message_id=?")
            params.append(last_message_id)
        if message_counter is not None:
            fields.append("message_counter=?")
            params.append(message_counter)
        if last_posted_at is not None:
            fields.append("last_posted_at=?")
            params.append(last_posted_at)
        if not fields:
            return
        params.extend([guild_id, channel_id])
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                f"UPDATE community_stickies SET {','.join(fields)} WHERE guild_id=? AND channel_id=?",
                tuple(params),
            )
            await db.commit()

    async def remove_community_sticky(self, guild_id: int, channel_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM community_stickies WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id),
            )
            await db.commit()
            return bool(cursor.rowcount)


    async def rebase_guild_economy(self, guild_id: int) -> dict[str, int]:
        """v3.5 one-time economy rebase while preserving identity/lifetime activity.

        Preserved: user created_at, moderation, Crew membership/names, lifetime count stats,
        and premium reward purchase transactions/items. Reset: money, level XP, normal inventory,
        boosters, market, quests, prestige, Crew bank/levels/contributions and economy-value stats.
        """
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("BEGIN IMMEDIATE")
            deleted: dict[str, int] = {}
            try:
                # Player economy state; keep account creation date and identity row.
                await db.execute(
                    """UPDATE users SET
                       wallet=?, bank=0,
                       last_daily=NULL,last_work=NULL,last_beg=NULL,last_search=NULL,last_slut=NULL,
                       last_crime=NULL,last_rob=NULL,last_role_income=NULL,last_weekly=NULL,last_monthly=NULL,
                       last_interest=NULL,last_invest=NULL,jail_until=NULL,
                       daily_streak=0,best_daily_streak=0,
                       money_earned=0,money_lost=0,xp_points=0,selected_title='Kezdő',
                       investment_profit=0,rob_profit=0,gambling_profit=0
                       WHERE guild_id=?""",
                    (self.starting_balance, guild_id),
                )

                # Normal inventory disappears, but already purchased real rewards stay.
                cur = await db.execute(
                    """DELETE FROM inventory WHERE guild_id=?
                       AND item_id NOT IN (SELECT item_id FROM shop_items WHERE category='reward')""",
                    (guild_id,),
                )
                deleted["inventory"] = max(0, int(cur.rowcount or 0))

                for table in ("active_boosters", "lottery_entries", "guild_effects", "market_daily", "quest_assignments", "user_prestige", "crew_invites"):
                    cur = await db.execute(f"DELETE FROM {table} WHERE guild_id=?", (guild_id,))
                    deleted[table] = max(0, int(cur.rowcount or 0))

                # Activity achievements will re-unlock from preserved lifetime count stats;
                # wealth/old-economy achievements must be earned again on the new scale.
                for table in ("achievements", "user_badges"):
                    cur = await db.execute(f"DELETE FROM {table} WHERE guild_id=?", (guild_id,))
                    deleted[table] = max(0, int(cur.rowcount or 0))

                # Crew identity/membership survives, economy power resets.
                cur = await db.execute(
                    "UPDATE crews SET bank=0, level=1, total_contributed=0 WHERE guild_id=?",
                    (guild_id,),
                )
                deleted["crews_rebased"] = max(0, int(cur.rowcount or 0))
                await db.execute("UPDATE crew_members SET contributed=0 WHERE guild_id=?", (guild_id,))

                # Old role income settings were created for the inflated economy; require reconfiguration.
                cur = await db.execute("DELETE FROM role_income WHERE guild_id=?", (guild_id,))
                deleted["role_income"] = max(0, int(cur.rowcount or 0))

                # Preserve premium purchase history for cooldown/monthly-stock enforcement.
                cur = await db.execute(
                    """DELETE FROM transactions WHERE guild_id=?
                       AND reason NOT LIKE 'buy:nitro_basic_1mx%'
                       AND reason NOT LIKE 'buy:discord_nitro_1mx%'""",
                    (guild_id,),
                )
                deleted["transactions"] = max(0, int(cur.rowcount or 0))

                # Preserve lifetime COUNTS, remove values tied to the old inflated money scale and old XP.
                money_stat_patterns = (
                    "economy.%", "progression.%", "work.earned", "work.biggest_reward",
                    "search.earned", "search.biggest_reward", "beg.earned", "beg.biggest_reward",
                    "crime.earned", "crime.lost", "crime.biggest_%", "slut.earned", "slut.lost", "slut.biggest_%",
                    "rob.profit", "rob.lost", "rob.lost_as_victim", "rob.biggest_%",
                    "gambling.profit", "gambling.wagered", "gambling.biggest_%", "gambling.%.profit", "gambling.%.wagered", "gambling.%.biggest_%",
                    "community.%.earned", "community.%.spent", "community.%.biggest_%",
                    "market.spent", "market.earned", "shop.spent", "shop.earned",
                    "investment.profit", "investment.wagered", "investment.biggest_%",
                    "interest.earned", "role_income.earned", "crew.contributed", "prestige.%",
                    "quests.daily.earned", "quests.weekly.earned", "quests.%.progression_xp",
                )
                clauses = " OR ".join("stat_name LIKE ?" for _ in money_stat_patterns)
                cur = await db.execute(
                    f"DELETE FROM user_statistics WHERE guild_id=? AND ({clauses})",
                    (guild_id, *money_stat_patterns),
                )
                deleted["money_statistics"] = max(0, int(cur.rowcount or 0))

                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return deleted

    async def reset_guild_economy(self, guild_id: int) -> dict[str, int]:
        """Teljesen törli egy szerver játékos-economy állapotát.

        A shop katalógus, role income konfiguráció és moderációs adatok megmaradnak.
        A felhasználók a következő economy parancsnál új játékosként jönnek létre
        a konfigurált STARTING_BALANCE értékkel.
        """
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("BEGIN IMMEDIATE")

            tables = (
                "transactions",
                "inventory",
                "achievements",
                "user_badges",
                "active_boosters",
                "lottery_entries",
                "guild_effects",
                "market_daily",
                "user_statistics",
                "quest_assignments",
                "user_prestige",
                "crew_invites",
                "crew_members",
                "crews",
                "users",
            )
            deleted: dict[str, int] = {}
            try:
                for table in tables:
                    cursor = await db.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
                    deleted[table] = max(0, int(cursor.rowcount or 0))
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        return deleted

    async def economy_summary(self, guild_id: int) -> tuple[int, int, int, int]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*), COALESCE(SUM(wallet),0), COALESCE(SUM(bank),0), COALESCE(MAX(wallet+bank),0) FROM users WHERE guild_id=?",
                (guild_id,),
            )
            row = await cursor.fetchone()
        return int(row[0]), int(row[1]), int(row[2]), int(row[3])
