from __future__ import annotations

import re

import discord
from discord.ext import commands

from app.amounts import parse_amount
from app.database import Database
from app.services.economy_events_settings import (
    COOLDOWN_DEFAULTS,
    ECONOMY_FEATURE_LABELS,
    REWARD_DEFAULTS,
    EconomyEventsSettingsService,
)
from app.cogs.settings import PagedGuildChannelSelect
from app.ui import BRAND, DANGER, SUCCESS, base_embed, money

TEXT_CHANNEL_TYPES = (discord.ChannelType.text, discord.ChannelType.news)

FEATURES = ["daily", "weekly", "monthly", "work", "crime", "search", "beg", "rob", "slut", "gambling"]
COOLDOWN_LABELS = {
    "daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "work": "Work",
    "crime": "Crime", "search": "Search", "beg": "Beg", "rob": "Rob", "slut": "Slut",
    "interest": "Interest", "role_income": "Role Income",
}
REWARD_LABELS = {
    "daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "work": "Work",
    "crime_reward": "Crime nyeremény", "crime_fine": "Crime büntetés",
    "slut_reward": "Slut nyeremény", "slut_fine": "Slut büntetés",
}


def _fmt_duration(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400} nap"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} óra"
    if seconds % 60 == 0:
        return f"{seconds // 60} perc"
    return f"{seconds} mp"


def _parse_duration(raw: str) -> int:
    value = raw.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)(s|sec|mp|m|min|h|ora|óra|d|nap)?", value)
    if not match:
        raise ValueError("Használj ilyet: `30s`, `5m`, `2h`, `1d`.")
    number = float(match.group(1).replace(",", "."))
    suffix = match.group(2) or "s"
    mult = 1
    if suffix in {"m", "min"}: mult = 60
    elif suffix in {"h", "ora", "óra"}: mult = 3600
    elif suffix in {"d", "nap"}: mult = 86400
    seconds = int(number * mult)
    if not 1 <= seconds <= 365 * 86400:
        raise ValueError("A cooldown 1 másodperc és 365 nap között lehet.")
    return seconds


def _parse_amount_range(raw: str) -> tuple[int, int]:
    parts = re.split(r"\s*[-–—:]\s*", raw.strip(), maxsplit=1)
    if len(parts) != 2:
        raise ValueError("Range formátum: `15k-80k`.")
    minimum, maximum = parse_amount(parts[0]), parse_amount(parts[1])
    if minimum < 0 or maximum < minimum:
        raise ValueError("A range minimuma nem lehet negatív és nem lehet nagyobb a maximumnál.")
    return minimum, maximum


def _parse_percent_range(raw: str) -> tuple[float, float]:
    parts = re.split(r"\s*[-–—:]\s*", raw.strip().replace("%", ""), maxsplit=1)
    if len(parts) != 2:
        raise ValueError("Százalék range formátum: `15-25`.")
    minimum = float(parts[0].replace(",", ".")) / 100.0
    maximum = float(parts[1].replace(",", ".")) / 100.0
    if not 0 <= minimum <= maximum <= 1:
        raise ValueError("A százalék range 0–100% között legyen, min ≤ max.")
    return minimum, maximum


def _parse_pair_percent(raw: str) -> tuple[float, float]:
    parts = re.split(r"\s*[/|:]\s*", raw.strip().replace("%", ""), maxsplit=1)
    if len(parts) != 2:
        raise ValueError("Használd ezt: `100/100` (rate%/cap%).")
    first = float(parts[0].replace(",", ".")) / 100.0
    second = float(parts[1].replace(",", ".")) / 100.0
    if not 0 <= first <= 10 or not 0 <= second <= 10:
        raise ValueError("Interest rate/cap: 0–1000%.")
    return first, second


class OwnedSettingsView(discord.ui.View):
    def __init__(self, cog: "EconomyEventsSettingsCog", owner_id: int, *, timeout: float = 600) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a beállítópanelt nem te nyitottad meg.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Ehhez **Szerver kezelése** jogosultság kell.", ephemeral=True)
            return False
        return True

    async def back_home(self, interaction: discord.Interaction) -> None:
        settings = self.cog.bot.get_cog("SettingsCog")
        if settings is None:
            return await interaction.response.send_message("❌ A Settings modul nem érhető el.", ephemeral=True)
        await settings.show_home(interaction, self.owner_id)


class EconomyView(OwnedSettingsView):
    def __init__(self, cog, owner_id, guild: discord.Guild, states: dict[str, bool], page: int = 0):
        super().__init__(cog, owner_id)
        self.guild = guild
        self.channel_page = page
        self._style(self.economy, states["economy"]); self._style(self.gambling, states["gambling"])
        self._style(self.bank, states["bank"]); self._style(self.interest, states["interest"]); self._style(self.role_income, states["role_income"])

    @staticmethod
    def _style(button: discord.ui.Button, enabled: bool):
        button.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
        button.label = (button.label.split(":", 1)[0] + (": ON" if enabled else ": OFF"))

    async def refresh(self, interaction): await self.cog.show_economy(interaction, self.owner_id, self)
    async def handle_channel_selection(self, interaction, _key, channels):
        return None
    async def toggle(self, interaction, key):
        current = await self.cog.service.get_feature_enabled(interaction.guild_id, key)
        await self.cog.service.set_feature_enabled(interaction.guild_id, key, not current)
        await self.refresh(interaction)

    @discord.ui.button(label="Economy", emoji="💰", row=0)
    async def economy(self, i, _): await self.toggle(i, "economy")
    @discord.ui.button(label="Gambling", emoji="🎰", row=0)
    async def gambling(self, i, _): await self.toggle(i, "gambling")
    @discord.ui.button(label="Bank", emoji="🏦", row=0)
    async def bank(self, i, _): await self.toggle(i, "bank")
    @discord.ui.button(label="Interest", emoji="📈", row=0)
    async def interest(self, i, _): await self.toggle(i, "interest")
    @discord.ui.button(label="Role Income", emoji="🎭", row=0)
    async def role_income(self, i, _): await self.toggle(i, "role_income")

    @discord.ui.button(label="Parancsok", emoji="🎛️", style=discord.ButtonStyle.secondary, row=1)
    async def commands(self, i, _): await self.cog.show_economy_commands(i, self.owner_id)
    @discord.ui.button(label="Cooldownok", emoji="⏳", style=discord.ButtonStyle.secondary, row=1)
    async def cooldowns(self, i, _): await self.cog.show_cooldowns(i, self.owner_id)
    @discord.ui.button(label="Rewardok", emoji="💵", style=discord.ButtonStyle.secondary, row=1)
    async def rewards(self, i, _): await self.cog.show_rewards(i, self.owner_id)
    @discord.ui.button(label="Advanced", emoji="⚙️", style=discord.ButtonStyle.secondary, row=1)
    async def advanced(self, i, _): await self.cog.show_advanced(i, self.owner_id)
    @discord.ui.button(label="Helyek", emoji="📍", style=discord.ButtonStyle.secondary, row=1)
    async def locations(self, i, _): await self.cog.show_economy_locations(i, self.owner_id)
    @discord.ui.button(label="Alapértékek", emoji="♻️", style=discord.ButtonStyle.danger, row=3)
    async def reset(self, i, _):
        await self.cog.service.reset_economy_all(i.guild_id); await self.refresh(i)
    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, i, _): await self.back_home(i)


class EconomyLocationsView(OwnedSettingsView):
    """Toggle-based multi channel/category allowlist editor."""

    def __init__(self, cog, owner_id, guild: discord.Guild, channel_page: int = 0, category_page: int = 0):
        super().__init__(cog, owner_id)
        self.guild = guild
        self.channel_page = channel_page
        self.category_page = category_page
        self.add_item(PagedGuildChannelSelect(
            self, guild, page_attr="channel_page", selection_key="economy_channels_toggle",
            placeholder="Csatorna hozzáadás / eltávolítás…", channel_types=TEXT_CHANNEL_TYPES, row=0, max_values=5,
        ))
        self.add_item(PagedGuildChannelSelect(
            self, guild, page_attr="category_page", selection_key="economy_categories_toggle",
            placeholder="Kategória hozzáadás / eltávolítás…", channel_types=(discord.ChannelType.category,), row=1, max_values=5,
        ))

    async def refresh(self, interaction):
        await self.cog.show_economy_locations(
            interaction, self.owner_id, channel_page=self.channel_page, category_page=self.category_page
        )

    async def handle_channel_selection(self, interaction, key, channels):
        if key == "economy_channels_toggle":
            current = set(await self.cog.service.get_economy_channel_ids(interaction.guild_id))
            for channel in channels:
                if channel.id in current:
                    current.remove(channel.id)
                else:
                    current.add(channel.id)
            await self.cog.service.set_economy_channel_ids(interaction.guild_id, sorted(current))
        elif key == "economy_categories_toggle":
            current = set(await self.cog.service.get_economy_category_ids(interaction.guild_id))
            for category in channels:
                if category.id in current:
                    current.remove(category.id)
                else:
                    current.add(category.id)
            await self.cog.service.set_economy_category_ids(interaction.guild_id, sorted(current))
        await self.refresh(interaction)

    @discord.ui.button(label="Összes törlése", emoji="🧹", style=discord.ButtonStyle.danger, row=2)
    async def clear_all(self, interaction, _button):
        await self.cog.service.clear_economy_locations(interaction.guild_id)
        await self.refresh(interaction)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, _button):
        await self.cog.show_economy(interaction, self.owner_id)


class EconomyCommandsView(OwnedSettingsView):
    def __init__(self, cog, owner_id, states):
        super().__init__(cog, owner_id)
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith("eco_feature:"):
                key = child.custom_id.split(":", 1)[1]
                enabled = states[key]
                child.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
                child.label = ECONOMY_FEATURE_LABELS[key] + (" ✓" if enabled else " ✕")

    async def _toggle(self, i, key):
        current = await self.cog.service.get_feature_enabled(i.guild_id, key)
        await self.cog.service.set_feature_enabled(i.guild_id, key, not current)
        await self.cog.show_economy_commands(i, self.owner_id)

    @discord.ui.button(label="Daily", custom_id="eco_feature:daily", row=0)
    async def daily(self,i,_): await self._toggle(i,"daily")
    @discord.ui.button(label="Weekly", custom_id="eco_feature:weekly", row=0)
    async def weekly(self,i,_): await self._toggle(i,"weekly")
    @discord.ui.button(label="Monthly", custom_id="eco_feature:monthly", row=0)
    async def monthly(self,i,_): await self._toggle(i,"monthly")
    @discord.ui.button(label="Work", custom_id="eco_feature:work", row=0)
    async def work(self,i,_): await self._toggle(i,"work")
    @discord.ui.button(label="Crime", custom_id="eco_feature:crime", row=0)
    async def crime(self,i,_): await self._toggle(i,"crime")
    @discord.ui.button(label="Search", custom_id="eco_feature:search", row=1)
    async def search(self,i,_): await self._toggle(i,"search")
    @discord.ui.button(label="Beg", custom_id="eco_feature:beg", row=1)
    async def beg(self,i,_): await self._toggle(i,"beg")
    @discord.ui.button(label="Rob", custom_id="eco_feature:rob", row=1)
    async def rob(self,i,_): await self._toggle(i,"rob")
    @discord.ui.button(label="Slut", custom_id="eco_feature:slut", row=1)
    async def slut(self,i,_): await self._toggle(i,"slut")
    @discord.ui.button(label="Gambling", custom_id="eco_feature:gambling", row=1)
    async def gambling(self,i,_): await self._toggle(i,"gambling")
    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self,i,_): await self.cog.show_economy(i,self.owner_id)


class KeySelect(discord.ui.Select):
    def __init__(self, view, mode: str):
        self.parent_view = view; self.mode = mode
        source = COOLDOWN_LABELS if mode == "cooldown" else REWARD_LABELS
        super().__init__(placeholder="Válassz beállítást…", options=[discord.SelectOption(label=v, value=k) for k,v in source.items()], row=0)
    async def callback(self, interaction):
        self.parent_view.selected = self.values[0]
        await self.parent_view.refresh(interaction)


class CooldownView(OwnedSettingsView):
    def __init__(self,cog,owner_id,selected="work"):
        super().__init__(cog,owner_id); self.selected=selected; self.add_item(KeySelect(self,"cooldown"))
    async def refresh(self,i): await self.cog.show_cooldowns(i,self.owner_id,self.selected)
    @discord.ui.button(label="Beállítás",emoji="✏️",style=discord.ButtonStyle.primary,row=1)
    async def set_value(self,i,_): await i.response.send_modal(CooldownModal(self.cog,self.owner_id,self.selected))
    @discord.ui.button(label="Kijelölt reset",emoji="♻️",style=discord.ButtonStyle.secondary,row=1)
    async def reset_one(self,i,_): await self.cog.service.set_cooldown_seconds(i.guild_id,self.selected,None); await self.refresh(i)
    @discord.ui.button(label="Mind reset",emoji="🧹",style=discord.ButtonStyle.danger,row=1)
    async def reset_all(self,i,_): await self.cog.service.reset_all_cooldowns(i.guild_id); await self.refresh(i)
    @discord.ui.button(label="Vissza",emoji="⬅️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,_): await self.cog.show_economy(i,self.owner_id)


class CooldownModal(discord.ui.Modal, title="Cooldown beállítása"):
    value = discord.ui.TextInput(label="Idő", placeholder="pl. 30s, 5m, 2h, 1d", max_length=20)
    def __init__(self,cog,owner_id,key): super().__init__(); self.cog=cog; self.owner_id=owner_id; self.key=key
    async def on_submit(self,i):
        try: seconds=_parse_duration(str(self.value.value)); await self.cog.service.set_cooldown_seconds(i.guild_id,self.key,seconds)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.cooldown_embed(i.guild,self.key),view=CooldownView(self.cog,self.owner_id,self.key))


class RewardView(OwnedSettingsView):
    def __init__(self,cog,owner_id,selected="work"):
        super().__init__(cog,owner_id); self.selected=selected; self.add_item(KeySelect(self,"reward"))
    async def refresh(self,i): await self.cog.show_rewards(i,self.owner_id,self.selected)
    @discord.ui.button(label="Range beállítás",emoji="✏️",style=discord.ButtonStyle.primary,row=1)
    async def set_value(self,i,_): await i.response.send_modal(RewardModal(self.cog,self.owner_id,self.selected))
    @discord.ui.button(label="Kijelölt reset",emoji="♻️",style=discord.ButtonStyle.secondary,row=1)
    async def reset_one(self,i,_): await self.cog.service.set_reward_range(i.guild_id,self.selected,None,None); await self.refresh(i)
    @discord.ui.button(label="Mind reset",emoji="🧹",style=discord.ButtonStyle.danger,row=1)
    async def reset_all(self,i,_): await self.cog.service.reset_all_reward_ranges(i.guild_id); await self.refresh(i)
    @discord.ui.button(label="Vissza",emoji="⬅️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,_): await self.cog.show_economy(i,self.owner_id)


class RewardModal(discord.ui.Modal, title="Reward range"):
    minimum = discord.ui.TextInput(label="Minimum",placeholder="pl. 60k",max_length=24)
    maximum = discord.ui.TextInput(label="Maximum",placeholder="pl. 280k",max_length=24)
    def __init__(self,cog,owner_id,key): super().__init__(); self.cog=cog; self.owner_id=owner_id; self.key=key
    async def on_submit(self,i):
        try:
            lo=parse_amount(str(self.minimum.value)); hi=parse_amount(str(self.maximum.value)); await self.cog.service.set_reward_range(i.guild_id,self.key,lo,hi)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.reward_embed(i.guild,self.key),view=RewardView(self.cog,self.owner_id,self.key))


class AdvancedView(OwnedSettingsView):
    @discord.ui.button(label="Rob %",emoji="🥷",style=discord.ButtonStyle.primary,row=0)
    async def rob(self,i,_): await i.response.send_modal(RobModal(self.cog,self.owner_id))
    @discord.ui.button(label="Gambling profit ×",emoji="🎰",style=discord.ButtonStyle.primary,row=0)
    async def payout(self,i,_): await i.response.send_modal(PayoutModal(self.cog,self.owner_id))
    @discord.ui.button(label="Pénznem",emoji="💱",style=discord.ButtonStyle.primary,row=0)
    async def currency(self,i,_): await i.response.send_modal(CurrencyModal(self.cog,self.owner_id))
    @discord.ui.button(label="Kezdő egyenleg",emoji="💵",style=discord.ButtonStyle.primary,row=0)
    async def starting_balance(self,i,_): await i.response.send_modal(StartingBalanceModal(self.cog,self.owner_id,await self.cog.service.get_starting_balance(i.guild_id)))
    @discord.ui.button(label="Rob szabályok",emoji="🛡️",style=discord.ButtonStyle.secondary,row=1)
    async def rob_rules(self,i,_): await i.response.send_modal(RobRulesModal(self.cog,self.owner_id,await self.cog.rob_rules_values(i.guild_id)))
    @discord.ui.button(label="Védelem / kor",emoji="🔐",style=discord.ButtonStyle.secondary,row=1)
    async def access_rules(self,i,_): await i.response.send_modal(AccessRulesModal(self.cog,self.owner_id,await self.cog.access_rules_values(i.guild_id)))
    @discord.ui.button(label="Role Income",emoji="🎭",style=discord.ButtonStyle.secondary,row=1)
    async def role_rules(self,i,_): await i.response.send_modal(RoleIncomeRulesModal(self.cog,self.owner_id,await self.cog.role_income_values(i.guild_id)))
    @discord.ui.button(label="Daily / Crime",emoji="🗓️",style=discord.ButtonStyle.secondary,row=2)
    async def daily_crime(self,i,_): await i.response.send_modal(DailyCrimeRulesModal(self.cog,self.owner_id,await self.cog.daily_crime_values(i.guild_id)))
    @discord.ui.button(label="Risk / Interest",emoji="🎲",style=discord.ButtonStyle.secondary,row=2)
    async def risk_interest(self,i,_): await i.response.send_modal(RiskInterestRulesModal(self.cog,self.owner_id,await self.cog.risk_interest_values(i.guild_id)))
    @discord.ui.button(label="Advanced reset",emoji="♻️",style=discord.ButtonStyle.danger,row=3)
    async def reset(self,i,_): await self.cog.service.reset_economy_advanced(i.guild_id); await self.cog.show_advanced(i,self.owner_id)
    @discord.ui.button(label="Vissza",emoji="⬅️",style=discord.ButtonStyle.secondary,row=3)
    async def back(self,i,_): await self.cog.show_economy(i,self.owner_id)



class StartingBalanceModal(discord.ui.Modal,title="Economy • Kezdő egyenleg"):
    amount=discord.ui.TextInput(label="Új játékos kezdő wallet",placeholder="25k",max_length=24)
    def __init__(self,cog,owner,current):
        super().__init__(); self.cog=cog; self.owner=owner; self.amount.default=str(current)
    async def on_submit(self,i):
        try: await self.cog.service.set_starting_balance(i.guild_id,parse_amount(str(self.amount.value)))
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.advanced_embed(i.guild),view=AdvancedView(self.cog,self.owner))


class RobRulesModal(discord.ui.Modal,title="Rob szabályok"):
    success=discord.ui.TextInput(label="Alap siker %",placeholder="25",max_length=8)
    boosted=discord.ui.TextInput(label="Booster max siker %",placeholder="35",max_length=8)
    victim=discord.ui.TextInput(label="Minimum célpont wallet",placeholder="50k",max_length=24)
    own=discord.ui.TextInput(label="Minimum saját wallet",placeholder="25k",max_length=24)
    coverage=discord.ui.TextInput(label="Kockázati fedezet %",placeholder="5",max_length=8)
    def __init__(self,cog,owner,values):
        super().__init__(); self.cog=cog; self.owner=owner
        self.success.default=f"{values[0]*100:g}"; self.boosted.default=f"{values[1]*100:g}"
        self.victim.default=str(values[2]); self.own.default=str(values[3]); self.coverage.default=f"{values[4]*100:g}"
    async def on_submit(self,i):
        try:
            success=float(str(self.success.value).replace(",","."))/100; boosted=float(str(self.boosted.value).replace(",","."))/100
            victim=parse_amount(str(self.victim.value)); own=parse_amount(str(self.own.value)); coverage=float(str(self.coverage.value).replace(",","."))/100
            await self.cog.service.set_rob_rules(i.guild_id,success_chance=success,boosted_max_chance=boosted,min_victim_wallet=victim,min_attempt_wallet=own,coverage_share=coverage)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.advanced_embed(i.guild),view=AdvancedView(self.cog,self.owner))


class AccessRulesModal(discord.ui.Modal,title="Economy védelem / account age"):
    protection=discord.ui.TextInput(label="Withdraw Rob-védelem",placeholder="5m",max_length=20)
    interest=discord.ui.TextInput(label="Interest minimum bank",placeholder="100k",max_length=24)
    weekly=discord.ui.TextInput(label="Weekly min account age (nap)",placeholder="7",max_length=8)
    monthly=discord.ui.TextInput(label="Monthly min account age (nap)",placeholder="30",max_length=8)
    def __init__(self,cog,owner,values):
        super().__init__(); self.cog=cog; self.owner=owner
        self.protection.default=_fmt_duration(values[0]); self.interest.default=str(values[1]); self.weekly.default=str(values[2]); self.monthly.default=str(values[3])
    async def on_submit(self,i):
        try:
            seconds=_parse_duration(str(self.protection.value)) if str(self.protection.value).strip() not in {"0","0s","0m"} else 0
            interest=parse_amount(str(self.interest.value)); weekly=int(str(self.weekly.value)); monthly=int(str(self.monthly.value))
            await self.cog.service.set_withdraw_rob_protection_seconds(i.guild_id,seconds)
            await self.cog.service.set_access_rules(i.guild_id,interest_min_bank=interest,weekly_age_days=weekly,monthly_age_days=monthly)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.advanced_embed(i.guild),view=AdvancedView(self.cog,self.owner))


class RoleIncomeRulesModal(discord.ui.Modal,title="Role Income szabályok"):
    first=discord.ui.TextInput(label="Első claim jóváírás (óra)",placeholder="4",max_length=8)
    accumulation=discord.ui.TextInput(label="Max felhalmozás (óra)",placeholder="24",max_length=8)
    stacking=discord.ui.TextInput(label="Rangok stackelnek? igen/nem",placeholder="nem",max_length=8)
    def __init__(self,cog,owner,values):
        super().__init__(); self.cog=cog; self.owner=owner
        self.first.default=str(values[0]); self.accumulation.default=str(values[1]); self.stacking.default="igen" if values[2] else "nem"
    async def on_submit(self,i):
        try:
            first=int(str(self.first.value)); accumulation=int(str(self.accumulation.value)); raw=str(self.stacking.value).strip().lower()
            if raw not in {"igen","nem","yes","no","true","false","1","0","on","off"}: raise ValueError("Stacking: igen vagy nem.")
            stacking=raw in {"igen","yes","true","1","on"}
            await self.cog.service.set_role_income_rules(i.guild_id,first_claim_hours=first,max_accumulation_hours=accumulation,stacking=stacking)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.advanced_embed(i.guild),view=AdvancedView(self.cog,self.owner))

class DailyCrimeRulesModal(discord.ui.Modal,title="Daily / Crime balance"):
    daily_bonus=discord.ui.TextInput(label="Daily streak bónusz / nap",placeholder="2500",max_length=24)
    daily_days=discord.ui.TextInput(label="Daily bonus max nap",placeholder="20",max_length=8)
    daily_grace=discord.ui.TextInput(label="Daily streak grace (óra)",placeholder="48",max_length=8)
    jail_chance=discord.ui.TextInput(label="Crime bukásnál jail esély %",placeholder="45",max_length=8)
    jail_range=discord.ui.TextInput(label="Crime jail perc (min-max)",placeholder="5-15",max_length=20)
    def __init__(self,cog,owner,values):
        super().__init__(); self.cog=cog; self.owner=owner
        self.daily_bonus.default=str(values[0]); self.daily_days.default=str(values[1]); self.daily_grace.default=str(values[2])
        self.jail_chance.default=f"{values[3]*100:g}"; self.jail_range.default=f"{values[4]}-{values[5]}"
    async def on_submit(self,i):
        try:
            bonus=parse_amount(str(self.daily_bonus.value)); days=int(str(self.daily_days.value)); grace=int(str(self.daily_grace.value))
            chance=float(str(self.jail_chance.value).replace(",",".").replace("%",""))/100
            jail_min,jail_max=_parse_amount_range(str(self.jail_range.value))
            await self.cog.service.set_daily_crime_rules(i.guild_id,daily_bonus=bonus,daily_max_days=days,daily_grace_hours=grace,crime_jail_chance=chance,crime_jail_min_minutes=jail_min,crime_jail_max_minutes=jail_max)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.advanced_embed(i.guild),view=AdvancedView(self.cog,self.owner))


class RiskInterestRulesModal(discord.ui.Modal,title="Risk / Interest balance"):
    slut_chance=discord.ui.TextInput(label="Slut siker %",placeholder="56",max_length=8)
    rob_flat=discord.ui.TextInput(label="Rob fail flat fine (min-max)",placeholder="15k-80k",max_length=40)
    rob_share=discord.ui.TextInput(label="Rob fail célpont % (min-max)",placeholder="15-25",max_length=20)
    interest_min=discord.ui.TextInput(label="Interest minimum reward",placeholder="250",max_length=24)
    interest_mult=discord.ui.TextInput(label="Interest rate/cap %",placeholder="100/100",max_length=24)
    def __init__(self,cog,owner,values):
        super().__init__(); self.cog=cog; self.owner=owner
        self.slut_chance.default=f"{values[0]*100:g}"; self.rob_flat.default=f"{values[1]}-{values[2]}"
        self.rob_share.default=f"{values[3]*100:g}-{values[4]*100:g}"; self.interest_min.default=str(values[5])
        self.interest_mult.default=f"{values[6]*100:g}/{values[7]*100:g}"
    async def on_submit(self,i):
        try:
            slut=float(str(self.slut_chance.value).replace(",",".").replace("%",""))/100
            flat_min,flat_max=_parse_amount_range(str(self.rob_flat.value)); share_min,share_max=_parse_percent_range(str(self.rob_share.value))
            minimum=parse_amount(str(self.interest_min.value)); rate_mult,cap_mult=_parse_pair_percent(str(self.interest_mult.value))
            await self.cog.service.set_risk_interest_rules(i.guild_id,slut_success_chance=slut,rob_flat_min=flat_min,rob_flat_max=flat_max,rob_share_min=share_min,rob_share_max=share_max,interest_min_reward=minimum,interest_rate_multiplier=rate_mult,interest_cap_multiplier=cap_mult)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.advanced_embed(i.guild),view=AdvancedView(self.cog,self.owner))


class RobModal(discord.ui.Modal,title="Rob zsákmány"):
    value=discord.ui.TextInput(label="Wallet százalék",placeholder="70",max_length=6)
    def __init__(self,cog,owner): super().__init__(); self.cog=cog; self.owner=owner
    async def on_submit(self,i):
        try: value=float(str(self.value.value).replace(",",".")); await self.cog.service.set_rob_share(i.guild_id,value/100)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.advanced_embed(i.guild),view=AdvancedView(self.cog,self.owner))


class PayoutModal(discord.ui.Modal,title="Gambling win-profit szorzó"):
    value=discord.ui.TextInput(label="Szorzó",placeholder="1.0",max_length=6)
    def __init__(self,cog,owner): super().__init__(); self.cog=cog; self.owner=owner
    async def on_submit(self,i):
        try: value=float(str(self.value.value).replace(",",".")); await self.cog.service.set_gambling_payout_multiplier(i.guild_id,value)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.advanced_embed(i.guild),view=AdvancedView(self.cog,self.owner))


class CurrencyModal(discord.ui.Modal,title="Pénznem"):
    name=discord.ui.TextInput(label="Név",placeholder="Yoru Dollar",max_length=32)
    symbol=discord.ui.TextInput(label="Jel / emoji",placeholder="$",max_length=12)
    def __init__(self,cog,owner): super().__init__(); self.cog=cog; self.owner=owner
    async def on_submit(self,i):
        try: await self.cog.service.set_currency_name(i.guild_id,str(self.name.value)); await self.cog.service.set_currency_symbol(i.guild_id,str(self.symbol.value)); await self.cog.service.prepare_currency(i.guild_id)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        await i.response.edit_message(embed=await self.cog.advanced_embed(i.guild),view=AdvancedView(self.cog,self.owner))


class EventsView(OwnedSettingsView):
    def __init__(self,cog,owner,guild,config,page=0):
        super().__init__(cog,owner); self.guild=guild; self.channel_page=page
        for button,key in [(self.auto,"auto_enabled"),(self.safe,"safe_enabled"),(self.bomb,"bomb_enabled"),(self.manual,"manual_enabled")]:
            enabled=getattr(config,key); button.style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger; button.label=button.label.split(":",1)[0]+(": ON" if enabled else ": OFF")
        self.add_item(PagedGuildChannelSelect(self,guild,page_attr="channel_page",selection_key="event_channel",placeholder="Auto event csatorna kiválasztása…",channel_types=TEXT_CHANNEL_TYPES,row=2))
    async def refresh(self,i): await self.cog.show_events(i,self.owner_id,self)
    async def handle_channel_selection(self,i,_key,channels): await self.cog.service.set_event_channel_id(i.guild_id,channels[0].id); self.cog.reschedule(i.guild_id); await self.refresh(i)
    async def _toggle(self,i,key):
        cfg=await self.cog.service.get_event_config(i.guild_id,self.cog.bot.settings); current=getattr(cfg,key+"_enabled"); await self.cog.service.set_event_toggle(i.guild_id,key,not current); self.cog.reschedule(i.guild_id); await self.refresh(i)
    @discord.ui.button(label="Auto",emoji="🤖",row=0)
    async def auto(self,i,_): await self._toggle(i,"auto")
    @discord.ui.button(label="Kincses Láda",emoji="🎁",row=0)
    async def safe(self,i,_): await self._toggle(i,"safe")
    @discord.ui.button(label="Hirtelen Halál",emoji="☠️",row=0)
    async def bomb(self,i,_): await self._toggle(i,"bomb")
    @discord.ui.button(label="Manuális",emoji="🛠️",row=0)
    async def manual(self,i,_): await self._toggle(i,"manual")
    @discord.ui.button(label="Időzítés",emoji="⏱️",style=discord.ButtonStyle.secondary,row=1)
    async def timing(self,i,_): await i.response.send_modal(EventTimingModal(self.cog,self.owner_id))
    @discord.ui.button(label="Aktivitás",emoji="💬",style=discord.ButtonStyle.secondary,row=1)
    async def activity(self,i,_): await i.response.send_modal(EventActivityModal(self.cog,self.owner_id))
    @discord.ui.button(label="Rewardok",emoji="💎",style=discord.ButtonStyle.secondary,row=1)
    async def rewards(self,i,_): await i.response.send_modal(EventRewardsModal(self.cog,self.owner_id))
    @discord.ui.button(label="Alapértékek",emoji="♻️",style=discord.ButtonStyle.danger,row=1)
    async def reset(self,i,_): await self.cog.service.reset_events_all(i.guild_id); self.cog.reschedule(i.guild_id); await self.refresh(i)
    @discord.ui.button(label="Csatorna törlése",emoji="🧹",style=discord.ButtonStyle.secondary,row=3)
    async def clear(self,i,_): await self.cog.service.set_event_channel_id(i.guild_id,None); self.cog.reschedule(i.guild_id); await self.refresh(i)
    @discord.ui.button(label="Vissza",emoji="⬅️",style=discord.ButtonStyle.secondary,row=3)
    async def back(self,i,_): await self.back_home(i)


class EventTimingModal(discord.ui.Modal,title="Event időzítés"):
    minimum=discord.ui.TextInput(label="Minimum idő (óra)",placeholder="0.42 = kb. 25 perc",max_length=12)
    maximum=discord.ui.TextInput(label="Maximum idő (óra)",placeholder="2",max_length=12)
    join=discord.ui.TextInput(label="Jelentkezési idő (mp)",placeholder="60",max_length=6)
    rounds=discord.ui.TextInput(label="HH köridő (mp)",placeholder="15",max_length=6)
    def __init__(self,cog,owner): super().__init__(); self.cog=cog; self.owner=owner
    async def on_submit(self,i):
        try: await self.cog.service.set_event_timing(i.guild_id,min_hours=float(str(self.minimum.value).replace(",",".")),max_hours=float(str(self.maximum.value).replace(",",".")),join_seconds=int(str(self.join.value)),bomb_round_seconds=int(str(self.rounds.value)))
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        self.cog.reschedule(i.guild_id); await i.response.edit_message(embed=await self.cog.events_embed(i.guild),view=EventsView(self.cog,self.owner,i.guild,await self.cog.service.get_event_config(i.guild_id,self.cog.bot.settings)))


class EventActivityModal(discord.ui.Modal,title="Event activity gate"):
    messages=discord.ui.TextInput(label="Szükséges üzenet",placeholder="25",max_length=8)
    users=discord.ui.TextInput(label="Minimum külön user",placeholder="3",max_length=6)
    window=discord.ui.TextInput(label="Ablak (perc)",placeholder="15",max_length=6)
    cooldown=discord.ui.TextInput(label="User cooldown (mp)",placeholder="10",max_length=6)
    def __init__(self,cog,owner): super().__init__(); self.cog=cog; self.owner=owner
    async def on_submit(self,i):
        try: await self.cog.service.set_event_activity(i.guild_id,messages=int(str(self.messages.value)),min_users=int(str(self.users.value)),window_minutes=int(str(self.window.value)),user_cooldown_seconds=int(str(self.cooldown.value)))
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        self.cog.reschedule(i.guild_id); await i.response.edit_message(embed=await self.cog.events_embed(i.guild),view=EventsView(self.cog,self.owner,i.guild,await self.cog.service.get_event_config(i.guild_id,self.cog.bot.settings)))


class EventRewardsModal(discord.ui.Modal,title="Event rewardok"):
    safe_min=discord.ui.TextInput(label="Láda minimum",placeholder="500k",max_length=24)
    safe_max=discord.ui.TextInput(label="Láda maximum",placeholder="5m",max_length=24)
    bomb_min=discord.ui.TextInput(label="HH belépő minimum",placeholder="100k",max_length=24)
    bomb_max=discord.ui.TextInput(label="HH belépő maximum",placeholder="1m",max_length=24)
    chance=discord.ui.TextInput(label="Láda esély %",placeholder="65",max_length=6)
    def __init__(self,cog,owner): super().__init__(); self.cog=cog; self.owner=owner
    async def on_submit(self,i):
        try: await self.cog.service.set_event_rewards(i.guild_id,safe_min=parse_amount(str(self.safe_min.value)),safe_max=parse_amount(str(self.safe_max.value)),bomb_min=parse_amount(str(self.bomb_min.value)),bomb_max=parse_amount(str(self.bomb_max.value)),safe_chance=float(str(self.chance.value).replace(",","."))/100)
        except ValueError as e: return await i.response.send_message(f"❌ {e}",ephemeral=True)
        self.cog.reschedule(i.guild_id); await i.response.edit_message(embed=await self.cog.events_embed(i.guild),view=EventsView(self.cog,self.owner,i.guild,await self.cog.service.get_event_config(i.guild_id,self.cog.bot.settings)))


class EconomyEventsSettingsCog(commands.Cog):
    def __init__(self,bot:commands.Bot,db:Database): self.bot=bot; self.db=db; self.service=EconomyEventsSettingsService(db)

    def reschedule(self,guild_id:int):
        cog=self.bot.get_cog("EventCog")
        if cog is not None and hasattr(cog,"reschedule_auto_event"):
            cog.reschedule_auto_event(guild_id)
        community=self.bot.get_cog("CommunityCog")
        if community is not None and hasattr(community,"reschedule_event_config"):
            community.reschedule_event_config(guild_id)

    async def economy_home_status(self,guild:discord.Guild)->str:
        enabled=await self.service.get_economy_enabled(guild.id)
        channels=await self.service.get_economy_channel_ids(guild.id); categories=await self.service.get_economy_category_ids(guild.id)
        location_count=len(channels)+len(categories)
        return ("🟢 Aktív" if enabled else "🔴 Kikapcsolva") + (f" • {location_count} engedélyezett hely" if location_count else " • minden csatorna")

    async def events_home_status(self,guild:discord.Guild)->str:
        cfg=await self.service.get_event_config(guild.id,self.bot.settings)
        return ("🟢 Auto" if cfg.auto_enabled else "⚪ Auto OFF") + (f" • <#{cfg.channel_id}>" if cfg.channel_id else " • nincs csatorna")

    async def economy_embed(self,guild):
        await self.service.prepare_currency(guild.id)
        states={k:await self.service.get_feature_enabled(guild.id,k) for k in ["economy","gambling","bank","interest","role_income"]}
        channels=await self.service.get_economy_channel_ids(guild.id); categories=await self.service.get_economy_category_ids(guild.id); name=await self.service.get_currency_name(guild.id); symbol=await self.service.get_currency_symbol(guild.id)
        embed=base_embed("💰 Economy • Beállítások","Szerverenkénti economy kapcsolók, több engedélyezett csatorna/kategória, balance és cooldown konfiguráció.",BRAND)
        embed.add_field(name="Állapot",value="🟢 Bekapcsolva" if states["economy"] else "🔴 Kikapcsolva",inline=True)
        location_text = "Minden csatorna" if not channels and not categories else f"{len(channels)} csatorna • {len(categories)} kategória"
        embed.add_field(name="📍 Engedélyezett helyek",value=location_text,inline=True)
        embed.add_field(name="Pénznem",value=f"{symbol} • **{name}**",inline=True)
        embed.add_field(name="Fő modulok",value=" • ".join(f"{'🟢' if states[k] else '🔴'} {ECONOMY_FEATURE_LABELS[k]}" for k in ["gambling","bank","interest","role_income"]),inline=False)
        return embed,states

    async def show_economy(self,i,owner,existing=None):
        embed,states=await self.economy_embed(i.guild); await i.response.edit_message(embed=embed,view=EconomyView(self,owner,i.guild,states,existing.channel_page if existing else 0))

    async def economy_locations_embed(self, guild: discord.Guild) -> discord.Embed:
        channels = await self.service.get_economy_channel_ids(guild.id)
        categories = await self.service.get_economy_category_ids(guild.id)
        embed = base_embed(
            "📍 Economy • Engedélyezett helyek",
            "Válassz csatornát vagy kategóriát a listából. A kiválasztás **toggle**: ami már engedélyezett, azt eltávolítja. Ha egyik lista is üres, az economy bárhol használható.",
            BRAND,
        )
        channel_lines = [f"<#{cid}>" for cid in channels if guild.get_channel(cid) is not None]
        category_lines = [f"📁 <#{cid}>" for cid in categories if guild.get_channel(cid) is not None]
        embed.add_field(name=f"💬 Csatornák ({len(channels)})", value="\n".join(channel_lines[:20]) or "—", inline=True)
        embed.add_field(name=f"📁 Kategóriák ({len(categories)})", value="\n".join(category_lines[:20]) or "—", inline=True)
        if len(channels) > 20 or len(categories) > 20:
            embed.set_footer(text="Yoru • Economy • A listából maximum 20-20 elem látszik, a szabályokban minden mentett elem aktív.")
        return embed

    async def show_economy_locations(self, i, owner, *, channel_page: int = 0, category_page: int = 0):
        await i.response.edit_message(
            embed=await self.economy_locations_embed(i.guild),
            view=EconomyLocationsView(self, owner, i.guild, channel_page=channel_page, category_page=category_page),
        )

    async def show_economy_commands(self,i,owner):
        states={k:await self.service.get_feature_enabled(i.guild_id,k) for k in FEATURES}; embed=base_embed("🎛️ Economy • Parancsok","Kapcsold külön a reward/munka/gambling funkciókat.")
        embed.add_field(name="Állapot",value="\n".join(f"{'🟢' if states[k] else '🔴'} **{ECONOMY_FEATURE_LABELS[k]}**" for k in FEATURES),inline=False)
        await i.response.edit_message(embed=embed,view=EconomyCommandsView(self,owner,states))

    async def cooldown_embed(self,guild,selected):
        embed=base_embed("⏳ Economy • Cooldownok",f"Kijelölt: **{COOLDOWN_LABELS[selected]}**")
        lines=[]
        for k in COOLDOWN_DEFAULTS:
            seconds=int((await self.service.get_cooldown(guild.id,k)).total_seconds()); lines.append(f"**{COOLDOWN_LABELS[k]}:** {_fmt_duration(seconds)}")
        embed.add_field(name="Aktuális értékek",value="\n".join(lines),inline=False); return embed
    async def show_cooldowns(self,i,owner,selected="work"): await i.response.edit_message(embed=await self.cooldown_embed(i.guild,selected),view=CooldownView(self,owner,selected))

    async def reward_embed(self,guild,selected):
        await self.service.prepare_currency(guild.id); embed=base_embed("💵 Economy • Reward range-ek",f"Kijelölt: **{REWARD_LABELS[selected]}**")
        lines=[]
        for k in REWARD_DEFAULTS:
            lo,hi=await self.service.get_reward_range(guild.id,k); lines.append(f"**{REWARD_LABELS[k]}:** {money(lo)} – {money(hi)}")
        embed.add_field(name="Aktuális értékek",value="\n".join(lines),inline=False); return embed
    async def show_rewards(self,i,owner,selected="work"): await i.response.edit_message(embed=await self.reward_embed(i.guild,selected),view=RewardView(self,owner,selected))

    async def rob_rules_values(self,guild_id):
        return (await self.service.get_rob_success_chance(guild_id),await self.service.get_rob_boosted_max_chance(guild_id),await self.service.get_rob_min_victim_wallet(guild_id),await self.service.get_rob_min_attempt_wallet(guild_id),await self.service.get_rob_min_coverage_share(guild_id))
    async def access_rules_values(self,guild_id):
        return (await self.service.get_withdraw_rob_protection_seconds(guild_id),await self.service.get_interest_min_bank(guild_id),await self.service.get_weekly_min_account_age_days(guild_id),await self.service.get_monthly_min_account_age_days(guild_id))
    async def role_income_values(self,guild_id):
        return (await self.service.get_role_income_first_claim_hours(guild_id),await self.service.get_role_income_max_accumulation_hours(guild_id),await self.service.get_role_income_stacking(guild_id))
    async def daily_crime_values(self,guild_id):
        jail_min,jail_max=await self.service.get_crime_jail_minutes(guild_id)
        return (await self.service.get_daily_streak_bonus(guild_id),await self.service.get_daily_streak_bonus_max_days(guild_id),await self.service.get_daily_streak_grace_hours(guild_id),await self.service.get_crime_jail_chance(guild_id),jail_min,jail_max)
    async def risk_interest_values(self,guild_id):
        flat_min,flat_max=await self.service.get_rob_fail_flat_range(guild_id); share_min,share_max=await self.service.get_rob_fail_share_range(guild_id)
        return (await self.service.get_slut_success_chance(guild_id),flat_min,flat_max,share_min,share_max,await self.service.get_interest_min_reward(guild_id),await self.service.get_interest_rate_multiplier(guild_id),await self.service.get_interest_cap_multiplier(guild_id))

    async def advanced_embed(self,guild):
        await self.service.prepare_currency(guild.id); share=await self.service.get_rob_share(guild.id); mult=await self.service.get_gambling_payout_multiplier(guild.id); name=await self.service.get_currency_name(guild.id); symbol=await self.service.get_currency_symbol(guild.id)
        rob=await self.rob_rules_values(guild.id); access=await self.access_rules_values(guild.id); role=await self.role_income_values(guild.id)
        daily=await self.daily_crime_values(guild.id); risk=await self.risk_interest_values(guild.id); starting=await self.service.get_starting_balance(guild.id)
        embed=base_embed("⚙️ Economy • Advanced","A DB-ben tárolt Yoru Settings az elsődleges; a kódbeli értékek csak fallback defaultok.")
        embed.add_field(name="💵 Kezdő egyenleg",value=f"Új játékos wallet: **{money(starting)}**",inline=False)
        embed.add_field(name="🥷 Rob",value=f"Loot **{share*100:.1f}%** • siker **{rob[0]*100:.1f}%** (boost max {rob[1]*100:.1f}%)\nCél min **{money(rob[2])}** • saját min **{money(rob[3])}** • fedezet **{rob[4]*100:.1f}%**",inline=False)
        embed.add_field(name="🗓️ Daily / Crime",value=f"Streak +**{money(daily[0])}/nap** • max **{daily[1]} nap** • grace **{daily[2]}h**\nCrime jail **{daily[3]*100:.1f}%** • **{daily[4]}–{daily[5]} perc**",inline=False)
        embed.add_field(name="🎲 Risk / Interest",value=f"Slut siker **{risk[0]*100:.1f}%** • Rob fail flat **{money(risk[1])}–{money(risk[2])}** • cél **{risk[3]*100:.1f}–{risk[4]*100:.1f}%**\nInterest min reward **{money(risk[5])}** • rate **{risk[6]:.2f}×** • cap **{risk[7]:.2f}×**",inline=False)
        embed.add_field(name="🔐 Védelem",value=f"Withdraw: **{_fmt_duration(access[0])}** • Interest min **{money(access[1])}**\nWeekly age **{access[2]} nap** • Monthly age **{access[3]} nap**",inline=False)
        embed.add_field(name="🎭 Role Income",value=f"Első claim **{role[0]}h** • max felhalmozás **{role[1]}h** • stacking **{'ON' if role[2] else 'OFF'}**",inline=False)
        embed.add_field(name="🎰 Win-profit szorzó",value=f"**{mult:.2f}×**",inline=True); embed.add_field(name="💱 Pénznem",value=f"{symbol} • **{name}**",inline=True); return embed
    async def show_advanced(self,i,owner): await i.response.edit_message(embed=await self.advanced_embed(i.guild),view=AdvancedView(self,owner))

    async def events_embed(self,guild):
        cfg=await self.service.get_event_config(guild.id,self.bot.settings)
        event_cog=self.bot.get_cog("EventCog")
        if event_cog and hasattr(event_cog, "get_runtime_config"):
            await event_cog.get_runtime_config(guild.id)
        status=event_cog.get_activity_status(guild.id) if event_cog and hasattr(event_cog,"get_activity_status") else None
        embed=base_embed("🎁 Events • Beállítások","Kincses Láda és Hirtelen Halál automatikus/manuális vezérlése.")
        embed.add_field(name="Kapcsolók",value=f"{'🟢' if cfg.auto_enabled else '🔴'} Auto • {'🟢' if cfg.safe_enabled else '🔴'} Láda • {'🟢' if cfg.bomb_enabled else '🔴'} HH • {'🟢' if cfg.manual_enabled else '🔴'} Manuális",inline=False)
        embed.add_field(name="📍 Auto csatorna",value=f"<#{cfg.channel_id}>" if cfg.channel_id else "Nincs beállítva",inline=True); embed.add_field(name="⏱️ Intervallum",value=f"**{cfg.min_hours:.2f}–{cfg.max_hours:.2f} óra**",inline=True); embed.add_field(name="📝 Jelentkezés",value=f"**{cfg.join_seconds} mp**",inline=True)
        embed.add_field(name="🎁 Láda",value=f"{money(cfg.safe_min_reward)} – {money(cfg.safe_max_reward)} • {cfg.safe_chance*100:.0f}% esély",inline=True); embed.add_field(name="☠️ HH",value=f"{money(cfg.bomb_min_entry)} – {money(cfg.bomb_max_entry)} / fő • {cfg.bomb_round_seconds} mp/kör",inline=True)
        if status: embed.add_field(name="💬 Activity gate",value=f"{'🟢 ARMED' if status['armed'] else '⚪ Vár'} • {status['messages']}/{status['required_messages']} msg • {status['users']}/{status['required_users']} user • {status['window_minutes']} perc",inline=False)
        return embed
    async def show_events(self,i,owner,existing=None):
        cfg=await self.service.get_event_config(i.guild_id,self.bot.settings); event_cog=self.bot.get_cog("EventCog");
        if event_cog and hasattr(event_cog,"get_runtime_config"): await event_cog.get_runtime_config(i.guild_id)
        await i.response.edit_message(embed=await self.events_embed(i.guild),view=EventsView(self,owner,i.guild,cfg,existing.channel_page if existing else 0))
