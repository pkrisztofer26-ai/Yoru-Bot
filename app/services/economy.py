from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random

from app.database import Database
from app import economy_config as eco
from app.services.statistics import StatisticsService
from app.services.prestige import PrestigeService
from app.services.crew import CrewService
from app.services.economy_events_settings import EconomyEventsSettingsService
from app.ui import money


class EconomyService:
    DAILY_COOLDOWN = eco.DAILY_COOLDOWN
    BEG_COOLDOWN = eco.BEG_COOLDOWN
    SEARCH_COOLDOWN = eco.SEARCH_COOLDOWN
    WORK_COOLDOWN = eco.WORK_COOLDOWN
    CRIME_COOLDOWN = eco.CRIME_COOLDOWN
    ROB_COOLDOWN = eco.ROB_COOLDOWN
    SLUT_COOLDOWN = eco.SLUT_COOLDOWN
    CLAIM_INCOME_COOLDOWN = eco.CLAIM_INCOME_COOLDOWN
    ROLE_INCOME_MAX_ACCUMULATION = eco.ROLE_INCOME_MAX_ACCUMULATION
    ROLE_INCOME_FIRST_CLAIM_HOURS = eco.ROLE_INCOME_FIRST_CLAIM_HOURS

    def __init__(
        self,
        database: Database,
        statistics: StatisticsService,
        prestige: PrestigeService | None = None,
        crew: CrewService | None = None,
    ) -> None:
        self.db = database
        self.stats = statistics
        self.prestige = prestige
        self.crew = crew
        self.guild_settings = EconomyEventsSettingsService(database)

    async def prepare_context(self, guild_id: int) -> None:
        await self.guild_settings.prepare_currency(guild_id)

    async def require_access(
        self,
        guild_id: int,
        feature: str,
        channel_id: int | None = None,
        category_id: int | None = None,
    ) -> None:
        await self.prepare_context(guild_id)
        await self.guild_settings.require_feature(guild_id, feature)
        await self.guild_settings.require_channel(guild_id, channel_id, category_id)

    async def apply_prestige_bonus(self, guild_id: int, user_id: int, amount: int, source: str) -> int:
        """Apply permanent progression bonuses in a stable order.

        The method keeps its historical name for backwards compatibility with
        ExtrasService, but now applies both Prestige and Crew bonuses.
        """
        boosted = int(amount)
        if boosted <= 0:
            return boosted
        if self.prestige is not None:
            boosted, _bonus = await self.prestige.boost_reward(guild_id, user_id, boosted, source)
        if self.crew is not None:
            boosted, _bonus = await self.crew.boost_reward(guild_id, user_id, boosted, source)
        return boosted

    async def balance(self, guild_id: int, user_id: int) -> tuple[int, int]:
        await self.prepare_context(guild_id)
        return await self.db.get_balance(guild_id, user_id)
    async def profile(self, guild_id: int, user_id: int) -> dict[str, object]:
        await self.prepare_context(guild_id)
        data: dict[str, object] = dict(await self.db.get_profile(guild_id, user_id))
        data["statistics"] = await self.stats.get_many(guild_id, user_id)
        return data
    async def deposit(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int]:
        await self.guild_settings.require_feature(guild_id, "bank")
        return await self.db.move_wallet_to_bank(guild_id, user_id, amount)

    async def withdraw(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int]:
        await self.guild_settings.require_feature(guild_id, "bank")
        return await self.db.move_bank_to_wallet(guild_id, user_id, amount)

    async def pay(self, guild_id: int, sender_id: int, receiver_id: int, amount: int) -> tuple[int, int]:
        await self.guild_settings.require_feature(guild_id, "economy")
        return await self.db.transfer_wallet(guild_id, sender_id, receiver_id, amount)
    async def leaderboard(self, guild_id: int, category: str = "money", limit: int = 10):
        await self.prepare_context(guild_id)
        return await self.db.leaderboard(guild_id, category, limit)
    async def history(self, guild_id: int, user_id: int, limit: int = 10):
        await self.prepare_context(guild_id)
        return await self.db.get_transactions(guild_id, user_id, limit)

    async def admin_add(self, guild_id: int, user_id: int, amount: int, admin_id: int) -> int:
        return await self.db.add_wallet(guild_id, user_id, amount, f"admin_adjust:{admin_id}")

    async def admin_set(self, guild_id: int, user_id: int, amount: int, admin_id: int) -> int:
        return await self.db.set_wallet(guild_id, user_id, amount, f"admin_set:{admin_id}")

    async def jail_status(self, guild_id: int, user_id: int) -> datetime | None:
        until = await self.db.get_jail_until(guild_id, user_id)
        now = datetime.now(timezone.utc)
        if until and until > now:
            return until
        if until:
            await self.db.set_jail_until(guild_id, user_id, None)
        return None

    async def require_not_jailed(self, guild_id: int, user_id: int) -> None:
        until = await self.jail_status(guild_id, user_id)
        if until:
            raise JailError(until)

    async def _check_cooldown(self, guild_id: int, user_id: int, column: str, cooldown: timedelta) -> datetime:
        now = datetime.now(timezone.utc)
        last = await self.db.get_timestamp(guild_id, user_id, column)
        if last and now < last + cooldown:
            raise CooldownError(last + cooldown)
        return now

    async def _award_activity_xp(self, guild_id: int, user_id: int, source: str) -> int:
        amount = int(eco.PROGRESSION_XP_REWARDS.get(source, 0))
        if amount <= 0:
            return 0
        await self.db.add_progression_xp(guild_id, user_id, amount, source)
        return amount

    async def claim_daily(self, guild_id: int, user_id: int) -> tuple[int, int, datetime]:
        await self.guild_settings.require_feature(guild_id, "daily")
        cooldown = await self.guild_settings.get_cooldown(guild_id, "daily")
        now = await self._check_cooldown(guild_id, user_id, "last_daily", cooldown)
        profile = await self.db.get_profile(guild_id, user_id)
        previous = await self.db.get_timestamp(guild_id, user_id, "last_daily")
        current_streak = int(profile.get("daily_streak", 0))
        if previous and now <= previous + timedelta(hours=eco.DAILY_STREAK_GRACE_HOURS):
            streak = current_streak + 1
        else:
            streak = 1
        base = random.randint(*(await self.guild_settings.get_reward_range(guild_id, "daily")))
        bonus = min(streak - 1, eco.DAILY_STREAK_BONUS_MAX_DAYS) * eco.DAILY_STREAK_BONUS
        reward = base + bonus
        reward = await self.apply_prestige_bonus(guild_id, user_id, reward, "daily")
        await self.db.add_wallet(guild_id, user_id, reward, f"daily:streak_{streak}")
        await self.db.set_daily_streak(guild_id, user_id, streak)
        await self.stats.increment(guild_id, user_id, "daily.count")
        await self.stats.set(guild_id, user_id, "daily.streak.current", streak)
        await self.stats.set_max(guild_id, user_id, "daily.streak.best", streak)
        await self.stats.set_max(guild_id, user_id, "daily.biggest_reward", reward)
        await self._award_activity_xp(guild_id, user_id, "daily")
        await self.db.set_timestamp(guild_id, user_id, "last_daily", now)
        return reward, streak, now + cooldown

    async def beg(self, guild_id: int, user_id: int) -> tuple[int, str, datetime]:
        await self.guild_settings.require_feature(guild_id, "beg")
        cooldown = await self.guild_settings.get_cooldown(guild_id, "beg")
        now = await self._check_cooldown(guild_id, user_id, "last_beg", cooldown)
        outcomes = eco.BEG_OUTCOMES
        text, minimum, maximum = random.choice(outcomes)
        reward = random.randint(minimum, maximum) if maximum > 0 else 0
        if reward:
            reward = await self.apply_prestige_bonus(guild_id, user_id, reward, "beg")
            await self.db.add_wallet(guild_id, user_id, reward, f"beg:{text}")
        await self.db.increment_stat(guild_id, user_id, "beg_count")
        await self.stats.increment(guild_id, user_id, "beg.count")
        if reward > 0:
            await self.stats.add(guild_id, user_id, "beg.earned", reward)
            await self.stats.set_max(guild_id, user_id, "beg.biggest_reward", reward)
        else:
            await self.stats.increment(guild_id, user_id, "beg.empty")
        await self._award_activity_xp(guild_id, user_id, "beg")
        await self.db.set_timestamp(guild_id, user_id, "last_beg", now)
        return reward, text, now + cooldown


    async def search(self, guild_id: int, user_id: int) -> tuple[int, str, datetime, tuple[str, str, str] | None]:
        await self.guild_settings.require_feature(guild_id, "search")
        cooldown = await self.guild_settings.get_cooldown(guild_id, "search")
        now = await self._check_cooldown(guild_id, user_id, "last_search", cooldown)
        places = eco.SEARCH_PLACES
        place, minimum, maximum = random.choice(places)
        reward = random.randint(minimum, maximum)
        reward = await self.apply_prestige_bonus(guild_id, user_id, reward, "search")
        await self.db.add_wallet(guild_id, user_id, reward, f"search:{place}")

        dropped: tuple[str, str, str] | None = None
        roll = random.random()
        cursor = 0.0
        for item_id, chance in eco.SEARCH_ITEM_DROPS:
            cursor += chance
            if roll < cursor:
                info = await self.db.get_shop_item(item_id)
                if info:
                    name, emoji, _price, _rarity, _category = info
                    await self.db.add_item(guild_id, user_id, item_id, 1)
                    await self.stats.increment(guild_id, user_id, "search.items_found")
                    await self.stats.increment(guild_id, user_id, f"search.item.{item_id}")
                    dropped = (item_id, name, emoji)
                break

        await self.db.increment_stat(guild_id, user_id, "search_count")
        await self.stats.increment(guild_id, user_id, "search.count")
        await self.stats.add(guild_id, user_id, "search.earned", reward)
        await self.stats.set_max(guild_id, user_id, "search.biggest_reward", reward)
        await self._award_activity_xp(guild_id, user_id, "search")
        await self.db.set_timestamp(guild_id, user_id, "last_search", now)
        return reward, place, now + cooldown, dropped

    async def cooldowns(self, guild_id: int, user_id: int) -> dict[str, datetime | None]:
        await self.prepare_context(guild_id)
        now = datetime.now(timezone.utc)
        definitions = {
            "daily": ("last_daily", await self.guild_settings.get_cooldown(guild_id, "daily")),
            "beg": ("last_beg", await self.guild_settings.get_cooldown(guild_id, "beg")),
            "search": ("last_search", await self.guild_settings.get_cooldown(guild_id, "search")),
            "work": ("last_work", await self.guild_settings.get_cooldown(guild_id, "work")),
            "crime": ("last_crime", await self.guild_settings.get_cooldown(guild_id, "crime")),
            "rob": ("last_rob", await self.guild_settings.get_cooldown(guild_id, "rob")),
            "weekly": ("last_weekly", await self.guild_settings.get_cooldown(guild_id, "weekly")),
            "monthly": ("last_monthly", await self.guild_settings.get_cooldown(guild_id, "monthly")),
            "interest": ("last_interest", await self.guild_settings.get_cooldown(guild_id, "interest")),
            "slut": ("last_slut", await self.guild_settings.get_cooldown(guild_id, "slut")),
            "claimincome": ("last_role_income", await self.guild_settings.get_cooldown(guild_id, "role_income")),
        }
        result: dict[str, datetime | None] = {}
        for name, (column, duration) in definitions.items():
            last = await self.db.get_timestamp(guild_id, user_id, column)
            ready = last + duration if last else None
            result[name] = ready if ready and ready > now else None
        return result

    async def work(self, guild_id: int, user_id: int) -> tuple[int, str, datetime]:
        await self.guild_settings.require_feature(guild_id, "work")
        await self.require_not_jailed(guild_id, user_id)
        cooldown = await self.guild_settings.get_cooldown(guild_id, "work")
        now = await self._check_cooldown(guild_id, user_id, "last_work", cooldown)
        jobs = eco.WORK_JOBS
        job, minimum, maximum = random.choice(jobs)
        # A munkák íze eltérő marad, de a teljes economy tartomány központilag szabályozható.
        work_range = await self.guild_settings.get_reward_range(guild_id, "work")
        low = max(work_range[0], minimum)
        high = min(work_range[1], maximum)
        if high < low:
            low, high = work_range
        reward = random.randint(low, high)
        booster = await self.db.get_active_booster(guild_id, user_id, "work_booster")
        if booster:
            reward = int(reward * booster[0])
        guild_effect = await self.db.get_guild_effect(guild_id, "work_multiplier")
        if guild_effect:
            reward = int(reward * guild_effect[0])
        reward = await self.apply_prestige_bonus(guild_id, user_id, reward, "work")
        await self.db.add_wallet(guild_id, user_id, reward, f"work:{job}")
        await self.db.increment_stat(guild_id, user_id, "work_count")
        await self.stats.increment(guild_id, user_id, "work.count")
        await self.stats.add(guild_id, user_id, "work.earned", reward)
        await self.stats.set_max(guild_id, user_id, "work.biggest_reward", reward)
        await self._award_activity_xp(guild_id, user_id, "work")
        await self.db.set_timestamp(guild_id, user_id, "last_work", now)
        return reward, job, now + cooldown

    async def crime(self, guild_id: int, user_id: int) -> tuple[bool, int, str, datetime, datetime | None]:
        await self.guild_settings.require_feature(guild_id, "crime")
        await self.require_not_jailed(guild_id, user_id)
        cooldown = await self.guild_settings.get_cooldown(guild_id, "crime")
        now = await self._check_cooldown(guild_id, user_id, "last_crime", cooldown)
        crimes = eco.CRIME_SCENARIOS
        scenario, chance = random.choice(crimes)
        success = random.random() < chance
        if success:
            amount = random.randint(*(await self.guild_settings.get_reward_range(guild_id, "crime_reward")))
            booster = await self.db.get_active_booster(guild_id, user_id, "crime_booster")
            if booster:
                amount = int(amount * booster[0])
            guild_effect = await self.db.get_guild_effect(guild_id, "crime_multiplier")
            if guild_effect:
                amount = int(amount * guild_effect[0])
            amount = await self.apply_prestige_bonus(guild_id, user_id, amount, "crime")
            await self.db.add_wallet(guild_id, user_id, amount, f"crime:{scenario}")
            await self.db.increment_stat(guild_id, user_id, "crime_success")
            await self.stats.increment(guild_id, user_id, "crime.success")
            await self.stats.add(guild_id, user_id, "crime.earned", amount)
            await self.stats.set_max(guild_id, user_id, "crime.biggest_reward", amount)
        else:
            amount = random.randint(*(await self.guild_settings.get_reward_range(guild_id, "crime_fine")))
            await self.db.add_wallet(
                guild_id, user_id, -amount, f"crime_fine:{scenario}", allow_negative=True
            )
            await self.db.increment_stat(guild_id, user_id, "crime_failed")
            await self.stats.increment(guild_id, user_id, "crime.fail")
            await self.stats.add(guild_id, user_id, "crime.lost", amount)
            await self.stats.set_max(guild_id, user_id, "crime.biggest_loss", amount)
        await self.stats.increment(guild_id, user_id, "crime.attempts")
        jail_until = None
        if not success and random.random() < eco.CRIME_JAIL_CHANCE:
            jail_until = now + timedelta(minutes=random.randint(eco.CRIME_JAIL_MIN_MINUTES, eco.CRIME_JAIL_MAX_MINUTES))
            await self.db.set_jail_until(guild_id, user_id, jail_until)
            await self.stats.increment(guild_id, user_id, "crime.jailed")
        await self._award_activity_xp(guild_id, user_id, "crime")
        await self.db.set_timestamp(guild_id, user_id, "last_crime", now)
        return success, amount, scenario, now + cooldown, jail_until

    async def rob(self, guild_id: int, robber_id: int, victim_id: int) -> tuple[bool, int, datetime]:
        await self.guild_settings.require_feature(guild_id, "rob")
        await self.require_not_jailed(guild_id, robber_id)
        if robber_id == victim_id: raise ValueError("Saját magadat nem rabolhatod ki.")
        cooldown = await self.guild_settings.get_cooldown(guild_id, "rob")
        now = await self._check_cooldown(guild_id, robber_id, "last_rob", cooldown)
        victim_wallet, _ = await self.db.get_balance(guild_id, victim_id)
        robber_wallet, _ = await self.db.get_balance(guild_id, robber_id)
        if victim_wallet < eco.ROB_MIN_VICTIM_WALLET:
            raise ValueError(f"A célpont tárcájában nincs legalább {money(eco.ROB_MIN_VICTIM_WALLET)}.")
        required_cover = max(eco.ROB_MIN_ATTEMPT_WALLET, int(victim_wallet * eco.ROB_MIN_COVERAGE_SHARE))
        if robber_wallet < required_cover:
            raise ValueError(
                f"Ehhez a rabláshoz legalább {money(required_cover)} kell a saját tárcádban kockázati fedezetként."
            )
        rob_chance = eco.ROB_SUCCESS_CHANCE
        rob_booster = await self.db.get_active_booster(guild_id, robber_id, "rob_booster")
        if rob_booster:
            rob_chance = min(eco.ROB_BOOSTED_MAX_CHANCE, rob_chance * rob_booster[0])
        success = random.random() < rob_chance
        if success and await self.db.consume_item(guild_id, victim_id, "rob_shield", 1):
            success = False
            await self.db.set_timestamp(guild_id, robber_id, "last_rob", now)
            await self.db.increment_stat(guild_id, robber_id, "rob_failed")
            await self.stats.increment(guild_id, robber_id, "rob.attempts")
            await self.stats.increment(guild_id, robber_id, "rob.fail")
            await self.stats.increment(guild_id, robber_id, "rob.blocked_by_shield")
            await self._award_activity_xp(guild_id, robber_id, "rob")
            return False, 0, now + cooldown
        if success:
            rob_share = await self.guild_settings.get_rob_share(guild_id)
            amount = max(1, int(victim_wallet * rob_share))
            stolen, _ = await self.db.rob_wallet(guild_id, robber_id, victim_id, amount)
            await self.db.increment_stat(guild_id, robber_id, "rob_success")
            await self.db.increment_stat(guild_id, robber_id, "rob_profit", stolen)
            await self.stats.increment(guild_id, robber_id, "rob.attempts")
            await self.stats.increment(guild_id, robber_id, "rob.success")
            await self.stats.add(guild_id, robber_id, "rob.profit", stolen)
            await self.stats.set_max(guild_id, robber_id, "rob.biggest_steal", stolen)
            await self.stats.add(guild_id, victim_id, "rob.lost_as_victim", stolen)
            amount = stolen
        else:
            flat_fine = random.randint(*eco.ROB_FAIL_FINE)
            proportional_fine = int(victim_wallet * random.uniform(*eco.ROB_FAIL_FINE_SHARE))
            amount = max(flat_fine, proportional_fine)
            amount = await self.db.pay_rob_fine(guild_id, robber_id, victim_id, amount)
            await self.db.increment_stat(guild_id, robber_id, "rob_failed")
            await self.stats.increment(guild_id, robber_id, "rob.attempts")
            await self.stats.increment(guild_id, robber_id, "rob.fail")
            await self.stats.add(guild_id, robber_id, "rob.lost", amount)
        await self._award_activity_xp(guild_id, robber_id, "rob")
        await self.db.set_timestamp(guild_id, robber_id, "last_rob", now)
        return success, amount, now + cooldown

    async def slut(self, guild_id: int, user_id: int) -> tuple[bool, int, str, datetime]:
        await self.guild_settings.require_feature(guild_id, "slut")
        await self.require_not_jailed(guild_id, user_id)
        cooldown = await self.guild_settings.get_cooldown(guild_id, "slut")
        now = await self._check_cooldown(guild_id, user_id, "last_slut", cooldown)
        success = random.random() < eco.SLUT_SUCCESS_CHANCE
        if success:
            amount = random.randint(*(await self.guild_settings.get_reward_range(guild_id, "slut_reward")))
            amount = await self.apply_prestige_bonus(guild_id, user_id, amount, "slut")
            text = random.choice(eco.SLUT_SUCCESS_MESSAGES)
            await self.db.add_wallet(guild_id, user_id, amount, "slut_success")
            await self.stats.increment(guild_id, user_id, "slut.success")
            await self.stats.add(guild_id, user_id, "slut.earned", amount)
            await self.stats.set_max(guild_id, user_id, "slut.biggest_reward", amount)
        else:
            amount = random.randint(*(await self.guild_settings.get_reward_range(guild_id, "slut_fine")))
            text = random.choice(eco.SLUT_FAIL_MESSAGES)
            await self.db.add_wallet(
                guild_id, user_id, -amount, "slut_fail", allow_negative=True
            )
            await self.stats.increment(guild_id, user_id, "slut.fail")
            await self.stats.add(guild_id, user_id, "slut.lost", amount)
            await self.stats.set_max(guild_id, user_id, "slut.biggest_loss", amount)
        await self.stats.increment(guild_id, user_id, "slut.count")
        await self._award_activity_xp(guild_id, user_id, "slut")
        await self.db.set_timestamp(guild_id, user_id, "last_slut", now)
        return success, amount, text, now + cooldown

    async def set_role_income(self, guild_id: int, role_id: int, hourly_amount: int) -> None:
        await self.db.set_role_income(guild_id, role_id, hourly_amount)

    async def role_income_list(self, guild_id: int) -> list[tuple[int, int]]:
        return await self.db.get_role_incomes(guild_id)

    async def claim_role_income(self, guild_id: int, user_id: int, role_ids: set[int]) -> tuple[int, int, datetime]:
        await self.guild_settings.require_feature(guild_id, "role_income")
        cooldown = await self.guild_settings.get_cooldown(guild_id, "role_income")
        now = datetime.now(timezone.utc)
        rates = await self.db.get_role_incomes(guild_id)
        eligible_rates = [amount for role_id, amount in rates if role_id in role_ids]
        if not eligible_rates:
            raise ValueError("Nincs olyan rangod, amely Role Income-ot ad.")
        # Discordon a hierarchikus rangok gyakran együtt vannak egy játékoson.
        # Alapból ezért nem stackeljük az összes Role Income-ot, mert az könnyen
        # többszörözné a passzív bevételt. Configból visszakapcsolható, ha kell.
        hourly = sum(eligible_rates) if eco.ROLE_INCOME_STACKING else max(eligible_rates)
        last = await self.db.get_timestamp(guild_id, user_id, "last_role_income")
        if last is None:
            # Első használatkor azonnal jár egy teljes claim-ciklusnyi income.
            # Így egy új játékost nem büntetünk egy 4 órás várakozással.
            last = now - timedelta(hours=self.ROLE_INCOME_FIRST_CLAIM_HOURS)
        elapsed = min(now - last, self.ROLE_INCOME_MAX_ACCUMULATION)
        full_hours = int(elapsed.total_seconds() // 3600)
        if elapsed < cooldown:
            raise CooldownError(last + cooldown)
        reward = hourly * full_hours
        reward = await self.apply_prestige_bonus(guild_id, user_id, reward, "role_income")
        await self.db.add_wallet(guild_id, user_id, reward, f"role_income:{full_hours}h")
        await self.stats.increment(guild_id, user_id, "role_income.claims")
        await self.stats.add(guild_id, user_id, "role_income.earned", reward)
        await self.stats.add(guild_id, user_id, "role_income.hours", full_hours)
        await self._award_activity_xp(guild_id, user_id, "role_income")
        await self.db.set_timestamp(guild_id, user_id, "last_role_income", last + timedelta(hours=full_hours))
        return reward, full_hours, now


class CooldownError(Exception):
    def __init__(self, ready_at: datetime) -> None:
        super().__init__("A parancs még cooldownon van.")
        self.ready_at = ready_at


class JailError(Exception):
    def __init__(self, ready_at: datetime) -> None:
        super().__init__("A felhasználó börtönben van.")
        self.ready_at = ready_at
