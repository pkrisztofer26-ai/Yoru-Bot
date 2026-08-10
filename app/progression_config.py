from __future__ import annotations

from dataclasses import dataclass

from app import economy_config as eco


@dataclass(frozen=True)
class AchievementDefinition:
    name: str
    description: str
    stat: str | None = None
    target: int = 1
    category: str = "general"
    wealth_target: int | None = None


@dataclass(frozen=True)
class BadgeDefinition:
    emoji: str
    name: str
    description: str
    requirement: str


@dataclass(frozen=True)
class QuestDefinition:
    quest_id: str
    title: str
    description: str
    emoji: str
    stat: str
    target: int
    reward_xp: int
    reward_item: str | None = None


def _series(
    prefix: str,
    label: str,
    emoji: str,
    stat: str,
    targets: list[int],
    category: str,
) -> dict[str, AchievementDefinition]:
    result: dict[str, AchievementDefinition] = {}
    tiers = ["I", "II", "III", "IV", "V", "VI"]
    for idx, target in enumerate(targets):
        tier = tiers[idx] if idx < len(tiers) else str(idx + 1)
        result[f"{prefix}_{target}"] = AchievementDefinition(
            name=f"{emoji} {label} {tier}",
            description=f"Érd el a(z) {target:,} értéket: {label.lower()}.",
            stat=stat,
            target=target,
            category=category,
        )
    return result


ACHIEVEMENT_DEFINITIONS: dict[str, AchievementDefinition] = {
    "first_daily": AchievementDefinition("🌅 Első nap", "Vedd át az első daily jutalmad.", "daily.count", 1, "activity"),
    "streak_7": AchievementDefinition("🔥 Hetes sorozat", "Érj el 7 napos daily streaket.", "daily.streak.best", 7, "activity"),
    "streak_30": AchievementDefinition("🌋 Megállíthatatlan", "Érj el 30 napos daily streaket.", "daily.streak.best", 30, "activity"),
    "jackpot_win": AchievementDefinition("🎟️ Jackpot", "Nyerj közösségi jackpotot.", "community.jackpot.wins", 1, "community"),
    "lottery_win": AchievementDefinition("🍀 Lottókirály", "Nyerj a Yoru lottón.", "community.lottery.wins", 1, "community"),
    "sudden_death_win": AchievementDefinition("☠️ Utolsó túlélő", "Nyerj Hirtelen Halált.", "community.sudden_death.wins", 1, "community"),
    "treasure_10": AchievementDefinition("🎁 Kincsvadász", "Vegyél részt 10 Kincses Ládában.", "community.treasure_chest.participations", 10, "community"),
    "crate_10": AchievementDefinition("📦 Ládabontó", "Nyiss ki 10 ládát.", "inventory.crates_opened", 10, "inventory"),
    "crate_50": AchievementDefinition("🧰 Raktárromboló", "Nyiss ki 50 ládát.", "inventory.crates_opened", 50, "inventory"),
    "booster_25": AchievementDefinition("⚡ Túlhajtás", "Használj el 25 boostert.", "inventory.boosters_used", 25, "inventory"),
    "shop_25": AchievementDefinition("🛒 Vásárló", "Vásárolj 25 tárgyat a shopból.", "shop.purchases", 25, "inventory"),
    "market_25": AchievementDefinition("📈 Kereskedő", "Köss 25 piaci vásárlást.", "market.purchases", 25, "market"),
    "invest_10": AchievementDefinition("📊 Befektető", "Fektess be 10 alkalommal.", "investment.count", 10, "market"),
    "invest_win_25": AchievementDefinition("💹 Tőzsdecápa", "Nyerj 25 befektetésen.", "investment.wins", 25, "market"),
    "prestige_1": AchievementDefinition("🌌 Újjászületett", "Hajts végre 1 prestige-et.", "prestige.count", 1, "prestige"),
    "prestige_3": AchievementDefinition("🌀 Visszatérő", "Hajts végre 3 prestige-et.", "prestige.count", 3, "prestige"),
    "prestige_5": AchievementDefinition("🌠 Ascended", "Hajts végre 5 prestige-et.", "prestige.count", 5, "prestige"),
    "prestige_10": AchievementDefinition("🪐 Örökös", "Hajts végre 10 prestige-et.", "prestige.count", 10, "prestige"),
    "crew_join": AchievementDefinition("🤝 Csapatjátékos", "Csatlakozz egy Crew-hoz.", "crew.joined", 1, "social"),
    "crew_contrib_25m": AchievementDefinition("💸 Támogató", "Fizess be összesen $2 milliót Crew Bankba.", "crew.contributed", 2_000_000, "social"),
    "crew_contrib_250m": AchievementDefinition("🏦 Mecénás", "Fizess be összesen $10 milliót Crew Bankba.", "crew.contributed", 10_000_000, "social"),
    "crew_contrib_1b": AchievementDefinition("🐋 Crew Whale", "Fizess be összesen $50 milliót Crew Bankba.", "crew.contributed", 50_000_000, "social"),
    "crew_upgrade": AchievementDefinition("🏗️ Crew Architect", "Fejlessz egy Crew-t legalább egyszer.", "crew.upgrades", 1, "social"),
}

ACHIEVEMENT_DEFINITIONS.update(_series("worker", "Munkás", "🛠️", "work.count", [10, 50, 100, 500, 1000], "activity"))
ACHIEVEMENT_DEFINITIONS.update(_series("searcher", "Kutató", "🔎", "search.count", [10, 50, 200, 500], "activity"))
ACHIEVEMENT_DEFINITIONS.update(_series("beggar", "Koldus", "🙏", "beg.count", [10, 50, 200], "activity"))
ACHIEVEMENT_DEFINITIONS.update(_series("slut", "Éjszakai műszak", "💋", "slut.count", [10, 50, 200], "activity"))
ACHIEVEMENT_DEFINITIONS.update(_series("crime", "Bűnöző", "🕵️", "crime.success", [10, 50, 100, 500], "crime"))
ACHIEVEMENT_DEFINITIONS.update(_series("robber", "Rabló", "🥷", "rob.success", [1, 10, 50, 100], "crime"))
ACHIEVEMENT_DEFINITIONS.update(_series("gambler", "Szerencsejátékos", "🎰", "gambling.wins", [10, 50, 100, 500, 1000], "gambling"))
ACHIEVEMENT_DEFINITIONS.update(_series("gambles", "High Roller", "🎲", "gambling.plays", [100, 500, 1000, 5000], "gambling"))
ACHIEVEMENT_DEFINITIONS.update(_series("blackjack", "Blackjack játékos", "🃏", "gambling.blackjack.wins", [25, 100, 500], "gambling"))
ACHIEVEMENT_DEFINITIONS.update(_series("coinflip", "Pénzfeldobó", "🪙", "gambling.coinflip.wins", [25, 100, 500], "gambling"))
ACHIEVEMENT_DEFINITIONS.update(_series("roulette", "Rulettjátékos", "🎡", "gambling.roulette.wins", [25, 100, 500], "gambling"))
ACHIEVEMENT_DEFINITIONS.update(_series("slots", "Slotgép", "🎰", "gambling.slots.wins", [25, 100, 500], "gambling"))

for achievement_id, name in [
    ("millionaire", "💰 Milliomos"),
    ("ten_million", "💎 Nagymenő"),
    ("wealth_1b", "👑 Vagyonos"),
    ("wealth_5b", "🐉 Elit"),
]:
    target = eco.WEALTH_ACHIEVEMENT_TARGETS[achievement_id]
    ACHIEVEMENT_DEFINITIONS[achievement_id] = AchievementDefinition(
        name=name,
        description=f"Érj el ${target:,} teljes vagyont.",
        category="wealth",
        wealth_target=target,
    )


BADGE_DEFINITIONS: dict[str, BadgeDefinition] = {
    "worker": BadgeDefinition("🛠️", "Munkagép", "100 munka teljesítve.", "worker_100"),
    "criminal": BadgeDefinition("🕵️", "Bűnöző", "100 sikeres crime.", "crime_100"),
    "robber": BadgeDefinition("🥷", "Tolvaj", "50 sikeres rablás.", "robber_50"),
    "gambler": BadgeDefinition("🎰", "Szerencsejátékos", "100 gambling győzelem.", "gambler_100"),
    "high_roller": BadgeDefinition("🎲", "High Roller", "1000 gambling játék.", "gambles_1000"),
    "wealthy": BadgeDefinition("💎", "Nagymenő", "$5 millió vagyon.", "ten_million"),
    "billionaire": BadgeDefinition("👑", "Vagyonos", "$25 millió vagyon.", "wealth_1b"),
    "streak": BadgeDefinition("🔥", "Kitartó", "30 napos daily streak.", "streak_30"),
    "jackpot": BadgeDefinition("🏆", "Jackpot Vadász", "Közösségi jackpot megnyerve.", "jackpot_win"),
    "lottery": BadgeDefinition("🍀", "Lottókirály", "Yoru lottery megnyerve.", "lottery_win"),
    "survivor": BadgeDefinition("☠️", "Túlélő", "Hirtelen Halál győzelem.", "sudden_death_win"),
    "collector": BadgeDefinition("📦", "Gyűjtő", "50 láda kinyitva.", "crate_50"),
    "investor": BadgeDefinition("📈", "Befektető", "25 nyertes befektetés.", "invest_win_25"),
    "blackjack": BadgeDefinition("🃏", "Blackjack Veteran", "100 blackjack győzelem.", "blackjack_100"),
    "prestige": BadgeDefinition("🌌", "Újjászületett", "Első prestige teljesítve.", "prestige_1"),
    "ascended": BadgeDefinition("🌠", "Ascended", "5 prestige teljesítve.", "prestige_5"),
    "eternal": BadgeDefinition("🪐", "Örökös", "10 prestige teljesítve.", "prestige_10"),
    "team_player": BadgeDefinition("🤝", "Csapatjátékos", "$2 millió Crew befizetés.", "crew_contrib_25m"),
    "patron": BadgeDefinition("🏦", "Mecénás", "$10 millió Crew befizetés.", "crew_contrib_250m"),
    "crew_architect": BadgeDefinition("🏗️", "Crew Architect", "Legalább egy Crew fejlesztés.", "crew_upgrade"),
}


TITLE_REQUIREMENTS: dict[str, str | None] = {
    "Kezdő": None,
    "Dolgos": "worker_10",
    "Munkagép": "worker_100",
    "Bűnöző": "crime_50",
    "Keresztapa": "crime_500",
    "Tolvaj": "robber_10",
    "Bankrabló": "robber_100",
    "Szerencsejátékos": "gambler_50",
    "High Roller": "gambles_1000",
    "Milliomos": "millionaire",
    "Nagymenő": "ten_million",
    "Vagyonos": "wealth_1b",
    "Kitartó": "streak_7",
    "Megállíthatatlan": "streak_30",
    "Jackpot Vadász": "jackpot_win",
    "Lottókirály": "lottery_win",
    "Utolsó túlélő": "sudden_death_win",
    "Gyűjtő": "crate_50",
    "Befektető": "invest_win_25",
    "Blackjack Veteran": "blackjack_100",
    "Újjászületett": "prestige_1",
    "Visszatérő": "prestige_3",
    "Ascended": "prestige_5",
    "Örökös": "prestige_10",
    "Csapatjátékos": "crew_join",
    "Támogató": "crew_contrib_25m",
    "Mecénás": "crew_contrib_250m",
    "Crew Architect": "crew_upgrade",
}


DAILY_QUESTS: tuple[QuestDefinition, ...] = (
    QuestDefinition("daily_work_3", "Műszakkezdés", "Dolgozz 3 alkalommal.", "🛠️", "work.count", 3, eco.QUEST_MONEY_REWARDS["daily_small"]),
    QuestDefinition("daily_work_5", "Túlóra", "Dolgozz 5 alkalommal.", "🏗️", "work.count", 5, eco.QUEST_MONEY_REWARDS["daily_large"]),
    QuestDefinition("daily_crime_2", "Kis balhé", "Próbálj meg 2 crime-ot.", "🕵️", "crime.attempts", 2, eco.QUEST_MONEY_REWARDS["daily_medium"]),
    QuestDefinition("daily_search_2", "Kincsvadászat", "Használd a search-öt 2 alkalommal.", "🔎", "search.count", 2, eco.QUEST_MONEY_REWARDS["daily_small"]),
    QuestDefinition("daily_beg_3", "Aprópénz", "Koldulj 3 alkalommal.", "🙏", "beg.count", 3, eco.QUEST_MONEY_REWARDS["daily_small"]),
    QuestDefinition("daily_slut_2", "Éjszakai műszak", "Használd a slut parancsot 2 alkalommal.", "💋", "slut.count", 2, eco.QUEST_MONEY_REWARDS["daily_medium"]),
    QuestDefinition("daily_gamble_5", "Kaszinótúra", "Játssz 5 gambling játékot.", "🎰", "gambling.plays", 5, eco.QUEST_MONEY_REWARDS["daily_medium"]),
    QuestDefinition("daily_gamble_win_2", "Nyertes széria", "Nyerj 2 gambling játékot.", "🏆", "gambling.wins", 2, eco.QUEST_MONEY_REWARDS["daily_large"]),
    QuestDefinition("daily_shop_1", "Bevásárlás", "Vásárolj 1 itemet a shopból.", "🛒", "shop.purchases", 1, eco.QUEST_MONEY_REWARDS["daily_small"]),
    QuestDefinition("daily_invest_1", "Mini befektető", "Fektess be 1 alkalommal.", "📈", "investment.count", 1, eco.QUEST_MONEY_REWARDS["daily_medium"]),
    QuestDefinition("daily_crate_1", "Dobozbontás", "Nyiss ki 1 ládát.", "📦", "inventory.crates_opened", 1, eco.QUEST_MONEY_REWARDS["daily_small"], "lottery_ticket"),
)


WEEKLY_QUESTS: tuple[QuestDefinition, ...] = (
    QuestDefinition("weekly_work_25", "Munkahét", "Dolgozz 25 alkalommal.", "🛠️", "work.count", 25, eco.QUEST_MONEY_REWARDS["weekly_medium"]),
    QuestDefinition("weekly_crime_10", "Bűnöző hét", "Próbálj meg 10 crime-ot.", "🕵️", "crime.attempts", 10, eco.QUEST_MONEY_REWARDS["weekly_medium"]),
    QuestDefinition("weekly_search_8", "Felfedező", "Keress 8 alkalommal.", "🔎", "search.count", 8, eco.QUEST_MONEY_REWARDS["weekly_small"]),
    QuestDefinition("weekly_gamble_35", "Kaszinómaraton", "Játssz 35 gambling játékot.", "🎰", "gambling.plays", 35, eco.QUEST_MONEY_REWARDS["weekly_medium"]),
    QuestDefinition("weekly_gamble_win_15", "Győztes hét", "Nyerj 15 gambling játékot.", "🏆", "gambling.wins", 15, eco.QUEST_MONEY_REWARDS["weekly_large"]),
    QuestDefinition("weekly_rob_3", "Rablóturné", "Próbálj meg 3 rablást.", "🥷", "rob.attempts", 3, eco.QUEST_MONEY_REWARDS["weekly_large"]),
    QuestDefinition("weekly_shop_8", "Shopping spree", "Vásárolj 8 itemet.", "🛒", "shop.purchases", 8, eco.QUEST_MONEY_REWARDS["weekly_medium"], "common_crate"),
    QuestDefinition("weekly_crate_5", "Ládavadász", "Nyiss ki 5 ládát.", "📦", "inventory.crates_opened", 5, eco.QUEST_MONEY_REWARDS["weekly_medium"], "common_crate"),
    QuestDefinition("weekly_invest_5", "Portfólió", "Fektess be 5 alkalommal.", "📊", "investment.count", 5, eco.QUEST_MONEY_REWARDS["weekly_large"]),
    QuestDefinition("weekly_beg_15", "Utcai legenda", "Koldulj 15 alkalommal.", "🙏", "beg.count", 15, eco.QUEST_MONEY_REWARDS["weekly_small"]),
    QuestDefinition("weekly_slut_8", "Éjszakás hét", "Használd a slut parancsot 8 alkalommal.", "💋", "slut.count", 8, eco.QUEST_MONEY_REWARDS["weekly_medium"]),
)


QUESTS_BY_PERIOD = {
    "daily": DAILY_QUESTS,
    "weekly": WEEKLY_QUESTS,
}

QUEST_COUNT_PER_PERIOD = 3
