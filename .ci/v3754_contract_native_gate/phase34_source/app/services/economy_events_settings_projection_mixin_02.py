from __future__ import annotations
from .economy_events_settings_projection_support import *

class EconomyEventsSettingsServiceProjectionMixin02:

    async def set_reward_range(self, guild_id: int, key: str, minimum: int | None, maximum: int | None) -> None:
        if key not in REWARD_DEFAULTS:
            raise ValueError(f'Ismeretlen jutalomtartomány: {key}')
        if minimum is None or maximum is None:
            await self.state.set_int(guild_id, f'economy_reward_{key}_min', None)
            await self.state.set_int(guild_id, f'economy_reward_{key}_max', None)
            return
        if minimum < 0 or maximum < minimum:
            raise ValueError('A minimum nem lehet negatív, a maximum pedig nem lehet kisebb a minimumnál.')
        if maximum > 10 ** 15:
            raise ValueError('A jutalom felső határa túl nagy. Legfeljebb 1 kvadrillió állítható be.')
        await self.state.set_int(guild_id, f'economy_reward_{key}_min', int(minimum))
        await self.state.set_int(guild_id, f'economy_reward_{key}_max', int(maximum))

    async def reset_all_reward_ranges(self, guild_id: int) -> None:
        for key in REWARD_DEFAULTS:
            await self.set_reward_range(guild_id, key, None, None)

    async def get_rob_share(self, guild_id: int) -> float:
        raw = await self._get_float_default(guild_id, 'economy_rob_success_share', eco.ROB_SUCCESS_SHARE)
        return max(0.01, min(1.0, raw))

    async def set_rob_share(self, guild_id: int, share: float | None) -> None:
        if share is None:
            await self.guild_state_repository.set(guild_id, 'economy_rob_success_share', '')
            return
        if share < 0.01 or share > 1.0:
            raise ValueError('A Rob zsákmány százaléka 1% és 100% között lehet.')
        await self._set_float(guild_id, 'economy_rob_success_share', share)

    async def get_gambling_payout_multiplier(self, guild_id: int) -> float:
        raw = await self._get_float_default(guild_id, 'economy_gambling_payout_multiplier', 1.0)
        return max(0.25, min(3.0, raw))

    async def set_gambling_payout_multiplier(self, guild_id: int, value: float | None) -> None:
        if value is None:
            await self.guild_state_repository.set(guild_id, 'economy_gambling_payout_multiplier', '')
            return
        if value < 0.25 or value > 3.0:
            raise ValueError('A kaszinókifizetési szorzó 0,25× és 3,00× között lehet.')
        await self._set_float(guild_id, 'economy_gambling_payout_multiplier', value)

    async def get_rob_success_chance(self, guild_id: int) -> float:
        return max(0.0, min(1.0, await self._get_float_default(guild_id, 'economy_rob_success_chance', eco.ROB_SUCCESS_CHANCE)))

    async def get_rob_min_victim_wallet(self, guild_id: int) -> int:
        return max(0, await self._get_int_default(guild_id, 'economy_rob_min_victim_wallet', eco.ROB_MIN_VICTIM_WALLET))

    async def get_rob_min_attempt_wallet(self, guild_id: int) -> int:
        return max(0, await self._get_int_default(guild_id, 'economy_rob_min_attempt_wallet', eco.ROB_MIN_ATTEMPT_WALLET))

    async def get_rob_min_coverage_share(self, guild_id: int) -> float:
        return max(0.0, min(1.0, await self._get_float_default(guild_id, 'economy_rob_min_coverage_share', eco.ROB_MIN_COVERAGE_SHARE)))

    async def get_withdraw_rob_protection_seconds(self, guild_id: int) -> int:
        default = int(eco.WITHDRAW_ROB_PROTECTION.total_seconds())
        return max(0, min(7 * 86400, await self._get_int_default(guild_id, 'economy_withdraw_rob_protection_seconds', default)))

    async def get_interest_min_bank(self, guild_id: int) -> int:
        return max(0, await self._get_int_default(guild_id, 'economy_interest_min_bank', eco.INTEREST_MIN_BANK))

    async def get_starting_balance(self, guild_id: int) -> int:
        return await self.db.get_starting_balance(guild_id)

    async def get_crime_jail_chance(self, guild_id: int) -> float:
        return max(0.0, min(1.0, await self._get_float_default(guild_id, 'economy_crime_jail_chance', eco.CRIME_JAIL_CHANCE)))

    async def get_crime_jail_minutes(self, guild_id: int) -> tuple[int, int]:
        minimum = max(0, min(1440, await self._get_int_default(guild_id, 'economy_crime_jail_min_minutes', eco.CRIME_JAIL_MIN_MINUTES)))
        maximum = max(minimum, min(1440, await self._get_int_default(guild_id, 'economy_crime_jail_max_minutes', eco.CRIME_JAIL_MAX_MINUTES)))
        return (minimum, maximum)

    async def get_slut_success_chance(self, guild_id: int) -> float:
        return max(0.0, min(1.0, await self._get_float_default(guild_id, 'economy_slut_success_chance', eco.SLUT_SUCCESS_CHANCE)))

    async def get_rob_fail_flat_range(self, guild_id: int) -> tuple[int, int]:
        minimum = max(0, await self._get_int_default(guild_id, 'economy_rob_fail_fine_min', eco.ROB_FAIL_FINE[0]))
        maximum = max(minimum, await self._get_int_default(guild_id, 'economy_rob_fail_fine_max', eco.ROB_FAIL_FINE[1]))
        return (min(minimum, 10 ** 15), min(maximum, 10 ** 15))

    async def get_rob_fail_share_range(self, guild_id: int) -> tuple[float, float]:
        minimum = max(0.0, min(1.0, await self._get_float_default(guild_id, 'economy_rob_fail_share_min', eco.ROB_FAIL_FINE_SHARE[0])))
        maximum = max(minimum, min(1.0, await self._get_float_default(guild_id, 'economy_rob_fail_share_max', eco.ROB_FAIL_FINE_SHARE[1])))
        return (minimum, maximum)

    async def get_interest_min_reward(self, guild_id: int) -> int:
        return max(0, min(10 ** 15, await self._get_int_default(guild_id, 'economy_interest_min_reward', eco.INTEREST_MIN_REWARD)))

    async def get_interest_rate_multiplier(self, guild_id: int) -> float:
        percent = await self._get_int_default(guild_id, 'economy_interest_rate_multiplier_percent', 100)
        return max(0.0, min(10.0, percent / 100.0))

    async def get_interest_cap_multiplier(self, guild_id: int) -> float:
        percent = await self._get_int_default(guild_id, 'economy_interest_cap_multiplier_percent', 100)
        return max(0.0, min(10.0, percent / 100.0))

    async def reset_economy_advanced(self, guild_id: int) -> None:
        await self.set_rob_share(guild_id, None)
        await self.set_gambling_payout_multiplier(guild_id, None)
        for key in ('economy_rob_success_chance', 'economy_rob_min_victim_wallet', 'economy_rob_min_attempt_wallet', 'economy_rob_min_coverage_share', 'economy_withdraw_rob_protection_seconds', 'economy_interest_min_bank', 'economy_starting_balance', 'economy_weekly_min_account_age_days', 'economy_monthly_min_account_age_days', 'economy_crime_jail_chance', 'economy_crime_jail_min_minutes', 'economy_crime_jail_max_minutes', 'economy_slut_success_chance', 'economy_rob_fail_fine_min', 'economy_rob_fail_fine_max', 'economy_rob_fail_share_min', 'economy_rob_fail_share_max', 'economy_interest_min_reward', 'economy_interest_rate_multiplier_percent', 'economy_interest_cap_multiplier_percent'):
            await self.guild_state_repository.set(guild_id, key, '')
        await self.guild_state_repository.set(guild_id, 'economy_currency_name', '')
        await self.guild_state_repository.set(guild_id, 'economy_currency_symbol', '')
