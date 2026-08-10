from __future__ import annotations

import itertools
import unittest

from app import economy_config as eco
from app.progression_math import level_from_xp, minimum_xp_for_level
from app.prestige_config import PRESTIGE_INCOME_BONUS_CAP, PRESTIGE_WEALTH_BASE
from app.crew_config import CREW_CREATE_COST, CREW_UPGRADE_COSTS


class BalanceConfigTests(unittest.TestCase):
    def test_rebase_scale(self) -> None:
        self.assertEqual(eco.STARTING_BALANCE, 25_000)
        self.assertEqual(eco.WORK_REWARD, (6_000, 25_000))
        self.assertLessEqual(max(row[2] for row in eco.SEARCH_PLACES), 15_000)
        self.assertEqual(eco.CRIME_REWARD[1], 95_000)
        self.assertEqual(eco.SLUT_REWARD[1], 85_000)
        self.assertEqual(eco.MONTHLY_REWARD, (1_000_000, 1_500_000))
        self.assertEqual(eco.ROB_SUCCESS_SHARE, 0.60)

    def test_no_premium_search_drop(self) -> None:
        drop_ids = {item_id for item_id, _chance in eco.SEARCH_ITEM_DROPS}
        self.assertNotIn("nitro_basic_1m", drop_ids)
        self.assertNotIn("discord_nitro_1m", drop_ids)

    def test_premium_rewards(self) -> None:
        basic = eco.PREMIUM_REWARD_RULES["nitro_basic_1m"]
        full = eco.PREMIUM_REWARD_RULES["discord_nitro_1m"]
        self.assertEqual(basic["price"], 500_000_000)
        self.assertEqual(full["price"], 750_000_000)
        self.assertGreaterEqual(basic["min_account_age_days"], 30)
        self.assertGreaterEqual(full["min_account_age_days"], 45)
        self.assertGreaterEqual(basic["min_level"], 35)
        self.assertGreaterEqual(full["min_level"], 45)

    def test_gambling_house_edge_without_max_bet(self) -> None:
        rtps = {
            "coinflip": 0.5 * eco.COINFLIP_TOTAL_PAYOUT,
            "dice": (1 / 6) * eco.DICE_TOTAL_PAYOUT,
            "roulette_even": (18 / 37) * eco.ROULETTE_EVEN_TOTAL_PAYOUT,
            "roulette_single": (1 / 37) * eco.ROULETTE_SINGLE_TOTAL_PAYOUT,
            "chicken": eco.CHICKEN_WIN_CHANCE * eco.CHICKEN_TOTAL_PAYOUT,
            "highlow": (6 / 13) * eco.HIGHLOW_TOTAL_PAYOUT + (1 / 13),
            "rps": (1 / 3) * eco.RPS_TOTAL_PAYOUT + (1 / 3),
        }
        for game, rtp in rtps.items():
            with self.subTest(game=game):
                self.assertGreaterEqual(rtp, 0.90)
                self.assertLessEqual(rtp, 0.96)
        self.assertFalse(hasattr(eco, "GAMBLING_MAX_BET"))

    def test_slots_rtp(self) -> None:
        probs = [w / sum(eco.SLOTS_WEIGHTS) for w in eco.SLOTS_WEIGHTS]
        rtp = 0.0
        for i, j, k in itertools.product(range(len(probs)), repeat=3):
            probability = probs[i] * probs[j] * probs[k]
            if i == j == k:
                payout = eco.SLOTS_TRIPLE_TOTAL_PAYOUT[eco.SLOTS_SYMBOLS[i]]
            elif len({i, j, k}) == 2:
                payout = eco.SLOTS_PAIR_TOTAL_PAYOUT
            else:
                payout = 0.0
            rtp += probability * payout
        self.assertGreaterEqual(rtp, 0.92)
        self.assertLess(rtp, 0.96)

    @staticmethod
    def _crate_ev(minimum: int, maximum: int) -> float:
        low1, high1 = minimum, max(minimum, int(maximum * eco.CRATE_TIER_1_MAX_RATIO))
        low2, high2 = max(minimum, int(maximum * eco.CRATE_TIER_2_MIN_RATIO)), max(minimum, int(maximum * eco.CRATE_TIER_2_MAX_RATIO))
        low3, high3 = max(minimum, int(maximum * eco.CRATE_TIER_3_MIN_RATIO)), maximum
        p1 = eco.CRATE_TIER_1_THRESHOLD
        p2 = eco.CRATE_TIER_2_THRESHOLD - eco.CRATE_TIER_1_THRESHOLD
        p3 = 1.0 - eco.CRATE_TIER_2_THRESHOLD
        return p1 * (low1 + high1) / 2 + p2 * (low2 + high2) / 2 + p3 * (low3 + high3) / 2

    def test_crates_are_money_sinks(self) -> None:
        for item_id, (minimum, maximum, _label) in eco.CRATE_DEFINITIONS.items():
            price = eco.SHOP_PRICES[item_id]
            ratio = self._crate_ev(minimum, maximum) / price
            with self.subTest(item_id=item_id):
                self.assertGreaterEqual(ratio, 0.82)
                self.assertLess(ratio, 0.91)

    def test_level_curve_is_activity_based_scale(self) -> None:
        self.assertEqual(level_from_xp(0), 1)
        self.assertEqual(minimum_xp_for_level(35), 5_780)
        self.assertEqual(minimum_xp_for_level(45), 9_680)
        self.assertEqual(minimum_xp_for_level(50), 12_005)
        self.assertEqual(level_from_xp(minimum_xp_for_level(50)), 50)

    def test_active_income_stays_below_million_per_hour(self) -> None:
        avg_work = sum((low + high) / 2 for _label, low, high in eco.WORK_JOBS) / len(eco.WORK_JOBS)
        work_per_hour = 3600 / eco.WORK_COOLDOWN.total_seconds()
        self.assertLess(avg_work * work_per_hour, 250_000)
        self.assertEqual(eco.CRIME_REWARD[1], 95_000)
        self.assertEqual(eco.SLUT_REWARD[1], 85_000)
        crime_p = sum(chance for _name, chance in eco.CRIME_SCENARIOS) / len(eco.CRIME_SCENARIOS)
        crime_ev = crime_p * (sum(eco.CRIME_REWARD) / 2) - (1 - crime_p) * (sum(eco.CRIME_FINE) / 2)
        slut_ev = eco.SLUT_SUCCESS_CHANCE * (sum(eco.SLUT_REWARD) / 2) - (1 - eco.SLUT_SUCCESS_CHANCE) * (sum(eco.SLUT_FINE) / 2)
        self.assertGreater(crime_ev, -5_000)
        self.assertLess(crime_ev, 5_000)
        self.assertGreater(slut_ev, -5_000)
        self.assertLess(slut_ev, 5_000)

    def test_centralized_shop_and_event_tunables(self) -> None:
        self.assertEqual(eco.SHOP_SELL_RATIO, 0.50)
        self.assertEqual(eco.BLACK_MARKET_PRICE_MULTIPLIER, (0.70, 0.85))
        self.assertEqual(eco.GUILD_EVENT_WORK_MULTIPLIER, 1.50)
        self.assertEqual(eco.GUILD_EVENT_CRIME_MULTIPLIER, 1.25)

    def test_long_term_sinks(self) -> None:
        self.assertEqual(CREW_CREATE_COST, 2_000_000)
        self.assertEqual(CREW_UPGRADE_COSTS[4], 100_000_000)
        self.assertEqual(PRESTIGE_WEALTH_BASE, 35_000_000)
        self.assertLessEqual(PRESTIGE_INCOME_BONUS_CAP, 0.40)

    def test_event_scale(self) -> None:
        self.assertEqual(eco.AUTO_SAFE_MIN_REWARD, 100_000)
        self.assertEqual(eco.AUTO_SAFE_MAX_REWARD, 500_000)
        self.assertEqual(eco.AUTO_BOMB_MIN_ENTRY, 25_000)
        self.assertEqual(eco.AUTO_BOMB_MAX_ENTRY, 150_000)


if __name__ == "__main__":
    unittest.main()
