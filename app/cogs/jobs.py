from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from app import jobs_config as cfg
from app.activity_visuals import (
    render_borsod,
    render_borsod_reveal_animation,
    render_job_final,
    render_job_lobby,
    render_route_animation,
    render_scenario_state,
    render_transport_state,
    render_warehouse,
    render_warehouse_transition,
)
from app.cogs.access_utils import handle_wrong_economy_channel
from app.cogs.settings import OwnedView, PagedGuildChannelSelect
from app.services.jobs import JobBusyError, JobCooldownError, JobsService
from app.ui import BRAND, GOLD, SUCCESS, base_embed, error_embed, money, progress_bar


RENDER_SEMAPHORE = asyncio.Semaphore(3)


def _job_title(job: str) -> str:
    j = cfg.JOB_BY_KEY[job]
    return f"{j.emoji} {j.name}"


def _accent(job: str):
    return cfg.JOB_BY_KEY[job].accent


def _board_tokens(session: dict) -> list[str]:
    data = session["data"]
    revealed = {int(i) for i in data.get("revealed", [])}
    cells = data.get("cells", [])
    return [str(cells[i]["emoji"]) if i in revealed else "?" for i in range(min(25, len(cells)))]


def _session_timing(session: dict, key: str, default: float) -> float:
    try:
        return float(session.get("data", {}).get("timing", {}).get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _cooldown_text(seconds: float) -> str:
    total = max(0, int(seconds))
    if total <= 0:
        return "✅ Kész"
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    if hours:
        return f"⏳ {hours}ó {minutes:02d}p"
    return f"⏳ {max(1, minutes)}p"


# v3.24.3: the two single-player robberies live in the Jobs launcher, but
# retain their own Live World cooldown/balance model. They intentionally do
# not pretend to have Jobs Mastery/history until that progression is designed.
RISKY_JOB_OPTIONS = {
    "shoprob": ("Boltrablás", "🏪", "Interaktív rablás • 2ó alap cooldown • nincs tét."),
    "bankrob": ("Bankrablás", "🏦", "Interaktív rablás • 4ó alap cooldown • magasabb kockázat."),
}
JOB_LAUNCH_KEYS = set(cfg.JOB_BY_KEY) | set(RISKY_JOB_OPTIONS)


class JobOwnedView(discord.ui.View):
    def __init__(self, cog: "JobsCog", owner_id: int, *, session_id: str | None = None, timeout: float = cfg.SESSION_TIMEOUT_SECONDS) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id
        self.session_id = session_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ez nem a te műszakod.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.session_id:
            try:
                await self.cog.service.abandon(self.session_id)
            except Exception:
                pass
        if self.message:
            try:
                for child in self.children:
                    if hasattr(child, "disabled"):
                        child.disabled = True
                await self.message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass


class JobsSelect(discord.ui.Select):
    def __init__(self, view: "JobsLobbyView") -> None:
        self.parent_view = view
        options = [
            discord.SelectOption(label=j.name, value=j.key, emoji=j.emoji, description=j.description[:100], default=j.key == view.selected)
            for j in cfg.JOBS
        ]
        options.extend(
            discord.SelectOption(label=name,value=key,emoji=emoji,description=description[:100],default=key==view.selected)
            for key,(name,emoji,description) in RISKY_JOB_OPTIONS.items()
        )
        super().__init__(placeholder="Válassz interaktív munkát…", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected = self.values[0]
        await self.parent_view.cog.refresh_lobby(interaction, self.parent_view)


class JobsLobbyView(JobOwnedView):
    def __init__(
        self,
        cog: "JobsCog",
        owner_id: int,
        *,
        selected: str = "warehouse",
        cooldown_remaining: float = 0.0,
        abandoned: bool = False,
    ) -> None:
        super().__init__(cog, owner_id, timeout=600)
        self.selected = selected if selected in JOB_LAUNCH_KEYS else "warehouse"
        self.cooldown_remaining = max(0.0, float(cooldown_remaining))
        self.abandoned = bool(abandoned)
        self.add_item(JobsSelect(self))
        if self.selected in RISKY_JOB_OPTIONS:
            self.start.label = "Rablás indítása"
            self.start.emoji = "🎭"
            self.start.style = discord.ButtonStyle.danger
        elif self.cooldown_remaining > 0:
            self.start.disabled = True
            self.start.style = discord.ButtonStyle.secondary
            short = _cooldown_text(self.cooldown_remaining).replace("⏳ ", "")
            self.start.label = f"Cooldown • {short}"
            self.start.emoji = "⏳"

    @discord.ui.button(label="Műszak indítása", emoji="▶️", style=discord.ButtonStyle.success, row=1)
    async def start(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.start_job_interaction(interaction, self.selected)

    @discord.ui.button(label="Mastery", emoji="🏅", style=discord.ButtonStyle.primary, row=1)
    async def mastery(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await self.cog.mastery_embed(interaction.guild_id, interaction.user), view=self)

    @discord.ui.button(label="History", emoji="🧾", style=discord.ButtonStyle.secondary, row=1)
    async def history(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await self.cog.history_embed(interaction.guild_id, interaction.user), view=self)

    @discord.ui.button(label="Főoldal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.refresh_lobby(interaction, self)


class WarehouseChoiceButton(discord.ui.Button):
    def __init__(self, parent: "WarehouseView", index: int, text: str) -> None:
        super().__init__(label=text[:80], style=discord.ButtonStyle.primary, row=index // 2)
        self.parent_view = parent
        self.choice = index

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.stop()
        await self.parent_view.cog.warehouse_answer(interaction, self.parent_view.session_id, self.choice)


class WarehouseView(JobOwnedView):
    def __init__(self, cog: "JobsCog", owner_id: int, session: dict) -> None:
        super().__init__(cog, owner_id, session_id=session["session_id"], timeout=_session_timing(session, "warehouse_decision_timeout_seconds", cfg.WAREHOUSE_DECISION_TIMEOUT_SECONDS))
        for idx, sequence in enumerate(session["data"]["candidates"]):
            self.add_item(WarehouseChoiceButton(self, idx, " → ".join(sequence)))


class BorsodCellButton(discord.ui.Button):
    def __init__(self, parent: "BorsodView", index: int, token: str) -> None:
        revealed = token != "?"
        super().__init__(emoji=(token if revealed else "⬛"), style=discord.ButtonStyle.secondary if not revealed else discord.ButtonStyle.primary, row=index // 5, disabled=revealed)
        self.parent_view = parent
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.stop()
        await self.parent_view.cog.borsod_pick(interaction, self.parent_view.session_id, self.index)


class BorsodView(JobOwnedView):
    def __init__(self, cog: "JobsCog", owner_id: int, session: dict) -> None:
        super().__init__(cog, owner_id, session_id=session["session_id"], timeout=_session_timing(session, "session_timeout_seconds", cfg.SESSION_TIMEOUT_SECONDS))
        for idx, token in enumerate(_board_tokens(session)):
            self.add_item(BorsodCellButton(self, idx, token))


class TransportView(JobOwnedView):
    def __init__(self, cog: "JobsCog", owner_id: int, session: dict) -> None:
        super().__init__(cog, owner_id, session_id=session["session_id"], timeout=_session_timing(session, "scenario_decision_timeout_seconds", cfg.TRANSPORT_DECISION_TIMEOUT_SECONDS))
        self.job = str(session["job"])

    @discord.ui.button(label="Rövid / biztos", emoji="🟢", style=discord.ButtonStyle.success, row=0)
    async def safe(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        await self.cog.transport_choose(interaction, self.session_id, "safe")

    @discord.ui.button(label="Hosszabb / jobb", emoji="🟡", style=discord.ButtonStyle.primary, row=0)
    async def long(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        await self.cog.transport_choose(interaction, self.session_id, "long")

    @discord.ui.button(label="Problémás / magas reward", emoji="🔴", style=discord.ButtonStyle.danger, row=0)
    async def risky(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        await self.cog.transport_choose(interaction, self.session_id, "risky")


class ScenarioChoiceButton(discord.ui.Button):
    def __init__(self, parent: "JobScenarioView", index: int, choice: dict) -> None:
        style = discord.ButtonStyle.success if choice.get("default") else (discord.ButtonStyle.danger if index >= 2 else discord.ButtonStyle.primary)
        super().__init__(
            label=str(choice.get("label", "Döntés"))[:80],
            emoji=str(choice.get("emoji") or "🎯"),
            style=style,
            row=index // 3,
        )
        self.parent_view = parent
        self.choice_key = str(choice.get("key", ""))

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.resolved = True
        self.parent_view.stop()
        if self.parent_view.kind == "borsod":
            await self.parent_view.cog.borsod_scenario_choose(interaction, self.parent_view.session_id, self.choice_key)
        else:
            await self.parent_view.cog.transport_scenario_choose(interaction, self.parent_view.session_id, self.choice_key)


class JobScenarioView(JobOwnedView):
    def __init__(self, cog: "JobsCog", owner_id: int, session: dict, scenario: dict, *, kind: str) -> None:
        timeout = _session_timing(session, "scenario_decision_timeout_seconds", cfg.DECISION_TIMEOUT_SECONDS)
        super().__init__(cog, owner_id, session_id=session["session_id"], timeout=timeout)
        self.kind = kind
        self.scenario = scenario
        self.resolved = False
        for idx, choice in enumerate(scenario.get("choices", [])):
            self.add_item(ScenarioChoiceButton(self, idx, choice))

    async def on_timeout(self) -> None:
        if self.resolved or not self.message or not self.session_id:
            return
        self.resolved = True
        try:
            await self.cog.resolve_scenario_timeout(self.message, self.owner_id, self.session_id, self.kind)
        except Exception:
            try:
                await self.cog.service.cancel(self.session_id)
            except Exception:
                pass


class JobsRewardModal(discord.ui.Modal, title="Interactive Jobs • Reward tuning"):
    multiplier = discord.ui.TextInput(label="Reward multiplier %", placeholder="100", min_length=2, max_length=3)

    def __init__(self, view: "JobsSettingsView", current_bp: int) -> None:
        super().__init__()
        self.parent_view = view
        self.multiplier.default = str(round(current_bp / 100))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            percent = int(str(self.multiplier.value).strip())
        except ValueError:
            return await interaction.response.send_message("❌ 50 és 200 közötti százalékot adj meg.", ephemeral=True)
        if not 50 <= percent <= 200:
            return await interaction.response.send_message("❌ 50 és 200 közötti százalékot adj meg.", ephemeral=True)
        await self.parent_view.cog.service.settings.set_int(interaction.guild_id, cfg.JOB_REWARD_MULTIPLIER_KEY, percent * 100)
        await self.parent_view.refresh(interaction)


class JobsCooldownModal(discord.ui.Modal, title="Jobs • Cooldown / timeout"):
    cooldown_minutes = discord.ui.TextInput(label="Közös cooldown (perc)", max_length=10)
    abandon_minutes = discord.ui.TextInput(label="Félbehagyás cooldown (perc)", max_length=10)
    session_minutes = discord.ui.TextInput(label="Általános idle timeout (perc)", max_length=10)

    def __init__(self, view: "JobsSettingsView", runtime) -> None:
        super().__init__(timeout=300); self.parent_view=view
        self.cooldown_minutes.default=f"{runtime.cooldown_seconds/60:g}"
        self.abandon_minutes.default=f"{runtime.abandon_cooldown_seconds/60:g}"
        self.session_minutes.default=f"{runtime.session_timeout_seconds/60:g}"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.cog.service.gameplay.set_jobs(
                interaction.guild_id,
                cooldown_seconds=round(float(str(self.cooldown_minutes.value).replace(",","."))*60),
                abandon_cooldown_seconds=round(float(str(self.abandon_minutes.value).replace(",","."))*60),
                session_timeout_seconds=round(float(str(self.session_minutes.value).replace(",","."))*60),
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction)


class JobsDecisionModal(discord.ui.Modal, title="Jobs • Döntési idők"):
    memorize = discord.ui.TextInput(label="Raktáros memóriaidő (mp)", max_length=10)
    warehouse_choice = discord.ui.TextInput(label="Raktáros választási idő (mp)", max_length=10)
    scenario_choice = discord.ui.TextInput(label="Scenario választási idő (mp)", max_length=10)

    def __init__(self, view: "JobsSettingsView", runtime) -> None:
        super().__init__(timeout=300); self.parent_view=view
        self.memorize.default=f"{runtime.warehouse_memorize_seconds:g}"
        self.warehouse_choice.default=f"{runtime.warehouse_decision_timeout_seconds:g}"
        self.scenario_choice.default=f"{runtime.scenario_decision_timeout_seconds:g}"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.cog.service.gameplay.set_jobs(
                interaction.guild_id,
                warehouse_memorize_seconds=float(str(self.memorize.value).replace(",",".")),
                warehouse_decision_timeout_seconds=float(str(self.warehouse_choice.value).replace(",",".")),
                scenario_decision_timeout_seconds=float(str(self.scenario_choice.value).replace(",",".")),
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction)


class JobsSettingsView(OwnedView):
    def __init__(self, cog: "JobsCog", owner_id: int, guild: discord.Guild, states: dict[str, bool], *, channel_page: int = 0) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.states = states
        self.channel_page = channel_page
        self._sync_labels()
        self.add_item(PagedGuildChannelSelect(
            self, guild, page_attr="channel_page", selection_key="log", placeholder="Jobs log csatorna…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news), row=2,
        ))

    def _sync_labels(self) -> None:
        mapping = ((self.master, "warehouse", "Raktáros"), (self.borsod, "borsod", "Lopkodás"), (self.courier, "courier", "Futár"), (self.taxi, "taxi", "Taxi"))
        self.enabled.label = f"Jobs: {'ON' if self.states['enabled'] else 'OFF'}"
        self.enabled.style = discord.ButtonStyle.success if self.states["enabled"] else discord.ButtonStyle.danger
        for button, key, label in mapping:
            button.label = f"{label}: {'ON' if self.states[key] else 'OFF'}"
            button.style = discord.ButtonStyle.success if self.states[key] else discord.ButtonStyle.secondary

    async def handle_channel_selection(self, interaction: discord.Interaction, selection_key: str, channels: list[discord.abc.GuildChannel]) -> None:
        if selection_key == "log" and channels:
            await self.cog.service.settings.set_int(interaction.guild_id, cfg.JOBS_LOG_CHANNEL_KEY, channels[0].id)
        await self.refresh(interaction)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_settings(interaction, self.owner_id, existing=self)

    async def _toggle_job(self, interaction: discord.Interaction, key: str) -> None:
        new = not self.states[key]
        await self.cog.service.settings.set_bool(interaction.guild_id, f"{cfg.JOB_ENABLED_PREFIX}{key}", new)
        await self.refresh(interaction)

    @discord.ui.button(label="Jobs", emoji="🧰", style=discord.ButtonStyle.success, row=0)
    async def enabled(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.service.settings.set_bool(interaction.guild_id, cfg.JOBS_ENABLED_KEY, not self.states["enabled"])
        await self.refresh(interaction)

    @discord.ui.button(label="Raktáros", emoji="📦", style=discord.ButtonStyle.secondary, row=0)
    async def master(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle_job(interaction, "warehouse")

    @discord.ui.button(label="Lopkodás", emoji="🔌", style=discord.ButtonStyle.secondary, row=0)
    async def borsod(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle_job(interaction, "borsod")

    @discord.ui.button(label="Futár", emoji="🚚", style=discord.ButtonStyle.secondary, row=1)
    async def courier(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle_job(interaction, "courier")

    @discord.ui.button(label="Taxi", emoji="🚕", style=discord.ButtonStyle.secondary, row=1)
    async def taxi(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle_job(interaction, "taxi")

    @discord.ui.button(label="Reward", emoji="🎚️", style=discord.ButtonStyle.primary, row=1)
    async def reward(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.service.settings.get_int(interaction.guild_id, cfg.JOB_REWARD_MULTIPLIER_KEY)
        await interaction.response.send_modal(JobsRewardModal(self, current or cfg.DEFAULT_REWARD_MULTIPLIER_BP))

    @discord.ui.button(label="Cooldown / timeout", emoji="⏱️", style=discord.ButtonStyle.primary, row=3)
    async def cooldown_tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        runtime=await self.cog.service.gameplay.jobs(interaction.guild_id)
        await interaction.response.send_modal(JobsCooldownModal(self,runtime))

    @discord.ui.button(label="Döntési idők", emoji="🎯", style=discord.ButtonStyle.primary, row=3)
    async def decision_tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        runtime=await self.cog.service.gameplay.jobs(interaction.guild_id)
        await interaction.response.send_modal(JobsDecisionModal(self,runtime))

    @discord.ui.button(label="Timing default", emoji="♻️", style=discord.ButtonStyle.secondary, row=3)
    async def timing_reset(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.service.gameplay.reset_jobs(interaction.guild_id)
        await self.refresh(interaction)

    @discord.ui.button(label="Log kikapcsolása", emoji="🧹", style=discord.ButtonStyle.secondary, row=1)
    async def clear_log(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.service.settings.set_int(interaction.guild_id, cfg.JOBS_LOG_CHANNEL_KEY, None)
        await self.refresh(interaction)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        settings_cog = self.cog.bot.get_cog("SettingsCog")
        if settings_cog is None:
            return await interaction.response.send_message("❌ A Settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, self.owner_id)


class JobsCog(commands.GroupCog, group_name="jobs", group_description="Yoru Interactive Jobs • aktív early-game pénzkeresés."):
    def __init__(self, bot: commands.Bot, service: JobsService) -> None:
        self.bot = bot
        self.service = service
        super().__init__()

    async def _render(self, fn, *args, **kwargs):
        async with RENDER_SEMAPHORE:
            return await asyncio.to_thread(fn, *args, **kwargs)

    async def _guard_interaction(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            return False
        try:
            await self.bot.economy.require_access(interaction.guild_id, "economy", interaction.channel_id, getattr(interaction.channel, "category_id", None))
            if not await self.service.is_enabled(interaction.guild_id):
                raise ValueError("Az Interactive Jobs rendszer ezen a szerveren ki van kapcsolva.")
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
            return False
        return True

    async def _guard_prefix(self, ctx: commands.Context) -> bool:
        try:
            await self.bot.economy.require_access(ctx.guild.id, "economy", ctx.channel.id, getattr(ctx.channel, "category_id", None))
            if not await self.service.is_enabled(ctx.guild.id):
                raise ValueError("Az Interactive Jobs rendszer ezen a szerveren ki van kapcsolva.")
        except ValueError as exc:
            text = str(exc).lower()
            if "csatorn" in text or "kateg" in text or "hely" in text:
                await handle_wrong_economy_channel(ctx, self.bot.economy, kind="economy")
            else:
                await ctx.send(embed=error_embed(ctx.author, str(exc)))
            return False
        return True

    async def lobby_embed(self, guild_id: int, user: discord.abc.User) -> tuple[discord.Embed, discord.File, dict]:
        rows = await self.service.mastery_summary(guild_id, user.id)
        cooldown = await self.service.cooldown_state(guild_id, user.id)
        runtime = await self.service.gameplay.jobs(guild_id)
        remaining = float(cooldown["remaining"])
        lines=[]
        for job, mastery in zip(cfg.JOBS, rows):
            lv, current, need = cfg.mastery_progress(int(mastery["xp"]))
            lines.append((
                job.name,
                f"{int(mastery['shifts'])} műszak • rekord {mastery['best_rating']}",
                f"Mastery Lv.{lv} • {current}/{need} XP",
            ))
        if remaining > 0:
            if bool(cooldown["abandoned"]):
                status=f"FÉLBEMARADT MŰSZAK • {_cooldown_text(remaining)}"
                cooldown_text=f"**{_cooldown_text(remaining)}** • {_cooldown_text(runtime.abandon_cooldown_seconds).replace('⏳ ','')} anti-reroll cooldown egy félbehagyott műszak után."
            else:
                status=f"KÖZÖS COOLDOWN • {_cooldown_text(remaining)}"
                cooldown_text=f"**{_cooldown_text(remaining)}** • bármelyik befejezett job után az összes munka {_cooldown_text(runtime.cooldown_seconds).replace('⏳ ','')} időre lezár."
        else:
            status="MŰSZAK ELÉRHETŐ • VÁLASSZ MUNKÁT"
            cooldown_text=f"✅ **Műszak elérhető.** Válassz egy munkát; teljesítés után az egész Jobs rendszer {_cooldown_text(runtime.cooldown_seconds).replace('⏳ ','')} cooldownra kerül."
        fp=await self._render(render_job_lobby,user.display_name,lines,status=status)
        embed=base_embed("🧰 YORU INTERACTIVE JOBS", "Aktív, tét nélküli pénzkeresés. **Egy műszakot választasz**, majd a teljes Jobs pool közös cooldownra kerül.", BRAND)
        embed.set_author(name=user.display_name,icon_url=getattr(user.display_avatar,"url",None))
        embed.set_image(url="attachment://jobs_lobby.png")
        embed.add_field(name="⏱️ Közös Jobs cooldown", value=cooldown_text, inline=False)
        embed.add_field(
            name="🎭 Kockázatos melók",
            value="🏪 **Boltrablás** és 🏦 **Bankrablás** is a választóban van. Interaktívak, de a saját Live cooldownjukat használják; nincs közös Jobs Mastery-bónuszuk.",
            inline=False,
        )
        embed.add_field(name="💡 Loop",value=f"Válassz munkát → reagálj a scenario-kra → építs Masteryt → {_cooldown_text(runtime.cooldown_seconds).replace('⏳ ','')} múlva választhatsz új műszakot.",inline=False)
        embed.set_footer(text="Yoru • Jobs • kényelmes döntési ablakok • egy aktív műszak / játékos / szerver")
        return embed,discord.File(fp=fp,filename="jobs_lobby.png"),cooldown

    def _lobby_view(self, owner_id: int, cooldown: dict, *, selected: str = "warehouse") -> JobsLobbyView:
        return JobsLobbyView(
            self,owner_id,selected=selected,
            cooldown_remaining=float(cooldown.get("remaining",0.0)),
            abandoned=bool(cooldown.get("abandoned",False)),
        )

    async def mastery_embed(self, guild_id: int, user: discord.abc.User) -> discord.Embed:
        rows=await self.service.mastery_summary(guild_id,user.id)
        embed=base_embed("🏅 Job Mastery", "Minden munkának külön progressionje van. Az income bonus **max +10%**, hogy ne törje szét az economy-t.", GOLD)
        embed.set_author(name=user.display_name,icon_url=getattr(user.display_avatar,"url",None))
        for job,row in zip(cfg.JOBS,rows):
            lv,current,need=cfg.mastery_progress(int(row["xp"])); bonus=cfg.mastery_bonus(lv)*100
            embed.add_field(name=f"{job.emoji} {job.name} • Lv.{lv}",value=f"`{progress_bar(current,need,12)}` **{current}/{need} XP**\nMűszak: **{row['shifts']}** • rekord: **{row['best_rating']}** • income: **+{bonus:g}%**\nÖsszes kereset: **{money(int(row['total_earned']))}**",inline=False)
        return embed

    async def history_embed(self, guild_id: int, user: discord.abc.User) -> discord.Embed:
        rows=await self.service.history(guild_id,user.id,10)
        desc=[]
        for r in rows:
            job=cfg.JOB_BY_KEY.get(str(r["job"])); label=f"{job.emoji} {job.name}" if job else str(r["job"])
            try: ts=int(datetime.fromisoformat(str(r["created_at"])).timestamp()); when=f"<t:{ts}:R>"
            except ValueError: when="—"
            desc.append(f"{label} • **{r['rating']}** ({r['score']}/100) • **+{money(int(r['reward']))}** • {when}")
        return base_embed("🧾 Jobs History", "\n".join(desc) if desc else "Még nincs lezárt Interactive Job műszakod.", BRAND)

    async def refresh_lobby(self, interaction: discord.Interaction, view: JobsLobbyView) -> None:
        embed,file,cooldown=await self.lobby_embed(interaction.guild_id,interaction.user)
        new=self._lobby_view(view.owner_id,cooldown,selected=view.selected)
        await interaction.response.edit_message(embed=embed,attachments=[file],view=new)
        new.message=interaction.message

    async def _edit_after_defer(self, interaction: discord.Interaction, *, embed: discord.Embed, file: discord.File, view: discord.ui.View | None):
        if interaction.message is not None:
            await interaction.message.edit(embed=embed,attachments=[file],view=view)
            if isinstance(view,JobOwnedView): view.message=interaction.message
            return interaction.message
        msg=await interaction.edit_original_response(embed=embed,attachments=[file],view=view)
        if isinstance(view,JobOwnedView): view.message=msg
        return msg

    async def _log_result(self, guild_id: int, user_id: int, result) -> None:
        channel_id=await self.service.settings.get_int(guild_id,cfg.JOBS_LOG_CHANNEL_KEY)
        if not channel_id: return
        channel=self.bot.get_channel(channel_id)
        if channel is None or not hasattr(channel,"send"): return
        embed=base_embed("🧾 Yoru Jobs Log",f"**{_job_title(result.job)}** lezárva",BRAND)
        embed.add_field(name="Játékos",value=f"<@{user_id}>\n`{user_id}`",inline=True)
        embed.add_field(name="Rating",value=f"**{result.rating}** • {result.score}/100",inline=True)
        embed.add_field(name="Payout",value=f"**{money(result.reward)}**",inline=True)
        embed.add_field(name="Mastery",value=f"Lv.{result.mastery_level} • +{result.mastery_xp} XP",inline=True)
        embed.add_field(name="Session",value=f"`{result.session_id}`",inline=True)
        embed.set_footer(text="Yoru • belső Jobs audit")
        await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())

    async def _final_embed_file(self,user:discord.abc.User,result,guild_id:int):
        job=cfg.JOB_BY_KEY[result.job]
        fp=await self._render(render_job_final,user.display_name,job.name,accent=job.accent,rating=result.rating,score=result.score,reward=result.reward,mastery_level=result.mastery_level,mastery_xp=result.mastery_xp)
        embed=base_embed(f"{job.emoji} {job.name} • {result.rating} rating",f"Műszak kész. **+{money(result.reward)}** került a walletedbe.",SUCCESS)
        embed.set_author(name=user.display_name,icon_url=getattr(user.display_avatar,"url",None)); embed.set_image(url="attachment://job_final.png")
        embed.add_field(name="Performance",value=f"**{result.score}/100**",inline=True); embed.add_field(name="Mastery",value=f"**Lv.{result.mastery_level}** • +{result.mastery_xp} XP",inline=True); embed.add_field(name="Wallet",value=f"**{money(result.wallet)}**",inline=True)
        runtime=await self.service.gameplay.jobs(guild_id)
        embed.add_field(name="⏱️ Következő Jobs műszak",value=f"**{_cooldown_text(runtime.cooldown_seconds).replace('⏳ ','')} múlva** • addig mind a négy munka cooldownon van.",inline=False)
        return embed,discord.File(fp=fp,filename="job_final.png")

    async def start_job_interaction(self, interaction: discord.Interaction, job: str) -> None:
        if not await self._guard_interaction(interaction): return
        if job in RISKY_JOB_OPTIONS:
            live=self.bot.get_cog("LiveWorldCog")
            if live is None or not hasattr(live,"start_robbery_ui"):
                return await interaction.response.send_message(embed=error_embed(interaction.user,"A Live World modul jelenleg nem elérhető."),ephemeral=True)
            return await live.start_robbery_ui(interaction,job)
        if job not in cfg.JOB_BY_KEY:
            return await interaction.response.send_message(embed=error_embed(interaction.user,"Ismeretlen munka."),ephemeral=True)
        await interaction.response.defer()
        try:
            if job=="warehouse": session=await self.service.start_warehouse(interaction.guild_id,interaction.user.id); await self._start_warehouse_ui(interaction,session)
            elif job=="borsod": session=await self.service.start_borsod(interaction.guild_id,interaction.user.id); await self._start_borsod_ui(interaction,session)
            else: session=await self.service.start_transport(interaction.guild_id,interaction.user.id,job); await self._start_transport_ui(interaction,session)
        except (JobBusyError,ValueError) as exc:
            embed=error_embed(interaction.user,str(exc))
            if interaction.message is not None: await interaction.followup.send(embed=embed,ephemeral=True)
            else: await interaction.edit_original_response(embed=embed,attachments=[],view=None)

    async def _finish_job_message(self, message: discord.Message, user: discord.abc.User, guild_id: int, result) -> None:
        embed,file=await self._final_embed_file(user,result,guild_id)
        await message.edit(embed=embed,attachments=[file],view=None)
        await self._log_result(guild_id,user.id,result)

    async def _show_warehouse_memory(self, message: discord.Message, user: discord.abc.User, session: dict, *, intro: str) -> None:
        data=session["data"]
        anim=await self._render(render_warehouse_transition,user.display_name,data["sequence"],int(data["round"]))
        embed=base_embed("📦 Raktáros",intro,BRAND)
        embed.set_image(url="attachment://warehouse_shift.gif")
        await message.edit(embed=embed,attachments=[discord.File(fp=anim,filename="warehouse_shift.gif")],view=None)
        await asyncio.sleep(cfg.WAREHOUSE_ANIMATION_SECONDS)
        latest=await self.service.get_session(session["session_id"])
        if latest["status"]!="active":
            return
        data=latest["data"]
        memorize=await self._render(
            render_warehouse,user.display_name,data["sequence"],phase="memorize",
            round_no=int(data["round"]),correct=int(data["correct"]),combo=int(data["combo"]),
        )
        memorize_seconds=_session_timing(session,"warehouse_memorize_seconds",cfg.WAREHOUSE_MEMORIZE_SECONDS)
        embed=base_embed("📦 Raktáros",f"Jegyezd meg. **{memorize_seconds:g} másodperced van**, ez nem reflexjáték.",BRAND)
        embed.set_image(url="attachment://warehouse_memory.png")
        await message.edit(embed=embed,attachments=[discord.File(fp=memorize,filename="warehouse_memory.png")],view=None)
        await asyncio.sleep(memorize_seconds)
        latest=await self.service.get_session(session["session_id"])
        if latest["status"]!="active":
            return
        data=latest["data"]
        fp=await self._render(
            render_warehouse,user.display_name,data["sequence"],phase="choose",
            round_no=int(data["round"]),correct=int(data["correct"]),combo=int(data["combo"]),
        )
        view=WarehouseView(self,user.id,latest)
        decision_seconds=_session_timing(latest,"warehouse_decision_timeout_seconds",cfg.WAREHOUSE_DECISION_TIMEOUT_SECONDS)
        embed=base_embed("📦 Raktáros",f"Válaszd ki a helyes sorrendet. **{int(decision_seconds)} mp** áll rendelkezésedre.",BRAND)
        embed.set_image(url="attachment://warehouse_state.png")
        await message.edit(embed=embed,attachments=[discord.File(fp=fp,filename="warehouse_state.png")],view=view)
        view.message=message

    async def _start_warehouse_ui(self, interaction: discord.Interaction, session: dict) -> None:
        data=session["data"]
        anim=await self._render(render_warehouse_transition,interaction.user.display_name,data["sequence"],int(data["round"]))
        embed=base_embed("📦 Raktáros","A polcsor mozog, utána külön időt kapsz a megjegyzésre.",BRAND)
        embed.set_image(url="attachment://warehouse_shift.gif")
        msg=await self._edit_after_defer(interaction,embed=embed,file=discord.File(fp=anim,filename="warehouse_shift.gif"),view=None)
        await asyncio.sleep(cfg.WAREHOUSE_ANIMATION_SECONDS)
        latest=await self.service.get_session(session["session_id"])
        if latest["status"]!="active":
            return
        data=latest["data"]
        memorize=await self._render(render_warehouse,interaction.user.display_name,data["sequence"],phase="memorize",round_no=int(data["round"]),correct=int(data["correct"]),combo=int(data["combo"]))
        memorize_seconds=_session_timing(latest,"warehouse_memorize_seconds",cfg.WAREHOUSE_MEMORIZE_SECONDS)
        embed=base_embed("📦 Raktáros",f"Jegyezd meg. **{memorize_seconds:g} másodperced van**.",BRAND)
        embed.set_image(url="attachment://warehouse_memory.png")
        await msg.edit(embed=embed,attachments=[discord.File(fp=memorize,filename="warehouse_memory.png")],view=None)
        await asyncio.sleep(memorize_seconds)
        latest=await self.service.get_session(session["session_id"])
        if latest["status"]!="active":
            return
        data=latest["data"]
        fp=await self._render(render_warehouse,interaction.user.display_name,data["sequence"],phase="choose",round_no=int(data["round"]),correct=int(data["correct"]),combo=int(data["combo"]))
        view=WarehouseView(self,interaction.user.id,latest)
        decision_seconds=_session_timing(latest,"warehouse_decision_timeout_seconds",cfg.WAREHOUSE_DECISION_TIMEOUT_SECONDS)
        embed=base_embed("📦 Raktáros",f"Válaszd ki a helyes sorrendet. **{int(decision_seconds)} mp** áll rendelkezésedre.",BRAND)
        embed.set_image(url="attachment://warehouse_state.png")
        await msg.edit(embed=embed,attachments=[discord.File(fp=fp,filename="warehouse_state.png")],view=view)
        view.message=msg

    async def warehouse_answer(self, interaction: discord.Interaction, session_id: str, choice: int) -> None:
        await interaction.response.defer()
        try:
            session,correct,done=await self.service.warehouse_answer(session_id,choice)
        except ValueError as exc:
            return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        if done:
            result=await self.service.finish(session_id)
            await self._finish_job_message(interaction.message,interaction.user,interaction.guild_id,result)
            return
        await self._show_warehouse_memory(
            interaction.message,interaction.user,session,
            intro=f"{'✅ Helyes' if correct else '❌ Hibás'} • következő kör. Nézd végig, aztán kapsz külön memóriaidőt.",
        )

    async def _show_borsod_board(self, message: discord.Message, user: discord.abc.User, session: dict, *, description: str | None=None) -> None:
        data=session["data"]
        board=_board_tokens(session)
        fp=await self._render(render_borsod,user.display_name,board,int(data["attempts_left"]),int(session["reward"]),event=str(data["event"]))
        view=BorsodView(self,user.id,session)
        embed=base_embed("🔌 Borsodi Lopkodás",description or str(data["event"]),BRAND)
        embed.set_image(url="attachment://borsod_state.png")
        await message.edit(embed=embed,attachments=[discord.File(fp=fp,filename="borsod_state.png")],view=view)
        view.message=message

    async def _show_scenario(self, message: discord.Message, user: discord.abc.User, session: dict, scenario: dict, *, kind: str) -> None:
        job=str(session["job"])
        definition=cfg.JOB_BY_KEY[job]
        data=session["data"]
        seconds=int(_session_timing(session,"scenario_decision_timeout_seconds",cfg.DECISION_TIMEOUT_SECONDS))
        if kind=="borsod":
            stage=max(1,7-int(data.get("attempts_left",7)))
            total=7
        else:
            stage=int(session["stage"])
            total=int(data["total"])
        fp=await self._render(
            render_scenario_state,user.display_name,definition.name,accent=definition.accent,
            stage=stage,total=total,score=int(session["score"]),reward=int(session["reward"]),
            scenario_title=str(scenario["title"]),prompt=str(scenario["prompt"]),choices=list(scenario.get("choices",[])),seconds=seconds,
        )
        view=JobScenarioView(self,user.id,session,scenario,kind=kind)
        embed=base_embed(
            f"{definition.emoji} {definition.name} • {scenario['title']}",
            f"{scenario['prompt']}\n\n**{seconds} másodperced van dönteni.** Ha kifut az idő, Yoru a biztonságos alapválasztást használja.",
            GOLD,
        )
        embed.set_image(url="attachment://job_scenario.png")
        await message.edit(embed=embed,attachments=[discord.File(fp=fp,filename="job_scenario.png")],view=view)
        view.message=message

    async def _start_borsod_ui(self, interaction: discord.Interaction, session: dict) -> None:
        data=session["data"]
        board=_board_tokens(session)
        fp=await self._render(render_borsod,interaction.user.display_name,board,int(data["attempts_left"]),int(session["reward"]),event=str(data["event"]))
        embed=base_embed("🔌 Borsodi Lopkodás","5×5 grid • **7 keresés** • nincs tét. A 🚓 most **döntési scenario-t** nyit, nem automatikusan zárja le a műszakot.",GOLD)
        embed.set_image(url="attachment://borsod_state.png")
        view=BorsodView(self,interaction.user.id,session)
        await self._edit_after_defer(interaction,embed=embed,file=discord.File(fp=fp,filename="borsod_state.png"),view=view)

    async def borsod_pick(self, interaction: discord.Interaction, session_id: str, index: int) -> None:
        await interaction.response.defer()
        before=await self.service.get_session(session_id)
        board_before=_board_tokens(before)
        try:
            session,cell,done=await self.service.borsod_pick(session_id,index)
        except ValueError as exc:
            return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        data=session["data"]
        anim=await self._render(render_borsod_reveal_animation,interaction.user.display_name,board_before,index,str(cell["emoji"]),int(data["attempts_left"]),int(session["reward"]))
        embed=base_embed("🔌 Borsodi Lopkodás",str(data["event"]),GOLD if not cell["hazard"] else discord.Color.red())
        embed.set_image(url="attachment://borsod_reveal.gif")
        await interaction.message.edit(embed=embed,attachments=[discord.File(fp=anim,filename="borsod_reveal.gif")],view=None)
        await asyncio.sleep(cfg.BORSOD_REVEAL_HOLD_SECONDS)
        scenario=cell.get("scenario")
        if scenario:
            await self._show_scenario(interaction.message,interaction.user,session,scenario,kind="borsod")
            return
        if done:
            result=await self.service.finish(session_id)
            await self._finish_job_message(interaction.message,interaction.user,interaction.guild_id,result)
            return
        await self._show_borsod_board(interaction.message,interaction.user,session)

    async def borsod_scenario_choose(self, interaction: discord.Interaction, session_id: str, choice_key: str) -> None:
        await interaction.response.defer()
        try:
            session,outcome,done=await self.service.resolve_borsod_scenario(session_id,choice_key)
        except ValueError as exc:
            return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        if done:
            result=await self.service.finish(session_id)
            await self._finish_job_message(interaction.message,interaction.user,interaction.guild_id,result)
            return
        await self._show_borsod_board(interaction.message,interaction.user,session,description=str(outcome["event"]))

    async def _show_transport_next(self, message: discord.Message, user: discord.abc.User, session: dict, *, previous: str | None=None) -> None:
        job=str(session["job"])
        definition=cfg.JOB_BY_KEY[job]
        data=session["data"]
        fp=await self._render(
            render_transport_state,user.display_name,definition.name,accent=definition.accent,
            stage=int(session["stage"]),total=int(data["total"]),score=int(session["score"]),reward=int(session["reward"]),event=str(data["current"]),
        )
        view=TransportView(self,user.id,session)
        description="Válassz útvonalat. Ez csak az első döntés: menet közben külön scenario is jön."
        if previous:
            description=f"{previous}\n\nKövetkező fuvar: válassz útvonalat, utána reagálnod kell az eseményre."
        embed=base_embed(f"{definition.emoji} {definition.name}",description,BRAND)
        embed.set_image(url="attachment://transport_state.png")
        await message.edit(embed=embed,attachments=[discord.File(fp=fp,filename="transport_state.png")],view=view)
        view.message=message

    async def _start_transport_ui(self, interaction: discord.Interaction, session: dict) -> None:
        job=str(session["job"])
        definition=cfg.JOB_BY_KEY[job]
        data=session["data"]
        fp=await self._render(render_transport_state,interaction.user.display_name,definition.name,accent=definition.accent,stage=int(session["stage"]),total=int(data["total"]),score=int(session["score"]),reward=int(session["reward"]),event=str(data["current"]))
        embed=base_embed(f"{definition.emoji} {definition.name}","Válassz útvonalat. **Nem fut le automatikusan:** az út közben scenario jelenik meg, ahol külön döntened kell.",BRAND)
        embed.set_image(url="attachment://transport_state.png")
        view=TransportView(self,interaction.user.id,session)
        await self._edit_after_defer(interaction,embed=embed,file=discord.File(fp=fp,filename="transport_state.png"),view=view)

    async def transport_choose(self, interaction: discord.Interaction, session_id: str, route: str) -> None:
        await interaction.response.defer()
        try:
            session,scenario=await self.service.prepare_transport_scenario(session_id,route)
        except ValueError as exc:
            return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        job=str(session["job"])
        definition=cfg.JOB_BY_KEY[job]
        vehicle="FUTÁR" if job=="courier" else "TAXI"
        anim=await self._render(
            render_route_animation,interaction.user.display_name,definition.name,vehicle,
            accent=definition.accent,event=str(scenario["title"]),success=True,
        )
        embed=base_embed(f"{definition.emoji} {definition.name}",f"**{scenario['route_label']}** • úton vagy… figyeld, mi történik.",BRAND)
        embed.set_image(url="attachment://route.gif")
        await interaction.message.edit(embed=embed,attachments=[discord.File(fp=anim,filename="route.gif")],view=None)
        await asyncio.sleep(cfg.ROUTE_ANIMATION_HOLD_SECONDS)
        latest=await self.service.get_session(session_id)
        if latest["status"]!="active":
            return
        await self._show_scenario(interaction.message,interaction.user,latest,scenario,kind="transport")

    async def _after_transport_scenario(self, message: discord.Message, user: discord.abc.User, guild_id: int, session: dict, outcome: dict, done: bool) -> None:
        job=str(session["job"])
        definition=cfg.JOB_BY_KEY[job]
        vehicle="FUTÁR" if job=="courier" else "TAXI"
        anim=await self._render(
            render_route_animation,user.display_name,definition.name,vehicle,
            accent=definition.accent,event=str(outcome["event"]),success=bool(outcome["success"]),
        )
        result_line=f"{'✅' if outcome['success'] else '❌'} {outcome['choice']} • +{money(int(outcome['reward']))}"
        embed=base_embed(f"{definition.emoji} {definition.name}",result_line,SUCCESS if outcome["success"] else GOLD)
        embed.set_image(url="attachment://route.gif")
        await message.edit(embed=embed,attachments=[discord.File(fp=anim,filename="route.gif")],view=None)
        await asyncio.sleep(cfg.ROUTE_ANIMATION_HOLD_SECONDS)
        if done:
            result=await self.service.finish(session["session_id"])
            await self._finish_job_message(message,user,guild_id,result)
            return
        latest=await self.service.get_session(session["session_id"])
        await self._show_transport_next(message,user,latest,previous=str(outcome["event"]))

    async def transport_scenario_choose(self, interaction: discord.Interaction, session_id: str, choice_key: str) -> None:
        await interaction.response.defer()
        try:
            session,outcome,done=await self.service.resolve_transport_scenario(session_id,choice_key)
        except ValueError as exc:
            return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await self._after_transport_scenario(interaction.message,interaction.user,interaction.guild_id,session,outcome,done)

    async def resolve_scenario_timeout(self, message: discord.Message, owner_id: int, session_id: str, kind: str) -> None:
        guild=message.guild
        if guild is None:
            await self.service.cancel(session_id)
            return
        user=guild.get_member(owner_id) or self.bot.get_user(owner_id)
        if user is None:
            await self.service.cancel(session_id)
            return
        if kind=="borsod":
            session,outcome,done=await self.service.resolve_borsod_scenario(session_id,timeout=True)
            if done:
                result=await self.service.finish(session_id)
                await self._finish_job_message(message,user,guild.id,result)
            else:
                await self._show_borsod_board(message,user,session,description=str(outcome["event"]))
            return
        session,outcome,done=await self.service.resolve_transport_scenario(session_id,timeout=True)
        await self._after_transport_scenario(message,user,guild.id,session,outcome,done)

    async def show_settings(self, interaction: discord.Interaction, owner_id: int, existing: JobsSettingsView | None=None) -> None:
        if interaction.guild is None: return
        if not interaction.response.is_done(): await interaction.response.defer()
        states={"enabled":await self.service.is_enabled(interaction.guild_id)}
        for job in cfg.JOBS: states[job.key]=await self.service.job_enabled(interaction.guild_id,job.key)
        bp=await self.service.settings.get_int(interaction.guild_id,cfg.JOB_REWARD_MULTIPLIER_KEY) or cfg.DEFAULT_REWARD_MULTIPLIER_BP; channel_id=await self.service.settings.get_int(interaction.guild_id,cfg.JOBS_LOG_CHANNEL_KEY); channel=interaction.guild.get_channel(channel_id) if channel_id else None
        runtime=await self.service.gameplay.jobs(interaction.guild_id)
        embed=base_embed("🧰 Interactive Jobs beállítások","A Yoru DB settings az elsődleges source of truth; a kódbeli Jobs értékek fallback defaultok.",BRAND)
        embed.add_field(name="Állapot",value="🟢 Aktív" if states["enabled"] else "🔴 Kikapcsolva",inline=True)
        embed.add_field(name="Reward",value=f"**{bp/100:.0f}%**",inline=True)
        embed.add_field(name="Log",value=channel.mention if isinstance(channel,discord.abc.GuildChannel) else "Nincs",inline=True)
        embed.add_field(name="⏱️ Cooldown / timeout",value=f"Közös cooldown **{runtime.cooldown_seconds/60:g}p** • abandon **{runtime.abandon_cooldown_seconds/60:g}p** • idle **{runtime.session_timeout_seconds/60:g}p**",inline=False)
        embed.add_field(name="🎯 Döntési idők",value=f"Raktáros memória **{runtime.warehouse_memorize_seconds:g}s** • választás **{runtime.warehouse_decision_timeout_seconds:g}s** • scenario **{runtime.scenario_decision_timeout_seconds:g}s**",inline=False)
        embed.add_field(name="Munkák",value="\n".join(f"{'🟢' if states[j.key] else '⚪'} {j.emoji} {j.name}" for j in cfg.JOBS),inline=False)
        embed.set_footer(text="Yoru • Settings • Jobs")
        view=JobsSettingsView(self,owner_id,interaction.guild,states,channel_page=(existing.channel_page if existing else 0))
        await interaction.edit_original_response(embed=embed,view=view,attachments=[])

    async def home_status(self, guild: discord.Guild) -> str:
        enabled = await self.service.is_enabled(guild.id)
        active = 0
        for job in cfg.JOBS:
            if await self.service.job_enabled(guild.id, job.key):
                active += 1
        return f"{'🟢' if enabled else '⚪'} {active}/{len(cfg.JOBS)} job aktív"

    @app_commands.command(name="panel",description="Megnyitja az Interactive Jobs lobby-t.")
    async def panel(self, interaction: discord.Interaction) -> None:
        if not await self._guard_interaction(interaction): return
        embed,file,cooldown=await self.lobby_embed(interaction.guild_id,interaction.user); view=self._lobby_view(interaction.user.id,cooldown); await interaction.response.send_message(embed=embed,file=file,view=view); view.message=await interaction.original_response()

    @app_commands.command(name="warehouse",description="Raktáros memória/sequence műszak indítása.")
    async def warehouse(self, interaction: discord.Interaction) -> None: await self.start_job_interaction(interaction,"warehouse")

    @app_commands.command(name="borsod",description="Borsodi Lopkodás 5×5 loot-grid műszak.")
    async def borsod_job(self, interaction: discord.Interaction) -> None: await self.start_job_interaction(interaction,"borsod")

    @app_commands.command(name="courier",description="Futár interaktív műszak indítása.")
    async def courier(self, interaction: discord.Interaction) -> None: await self.start_job_interaction(interaction,"courier")

    @app_commands.command(name="shoprob",description="Boltrablás indítása a Jobs rendszerből.")
    async def shoprob_job(self, interaction: discord.Interaction) -> None: await self.start_job_interaction(interaction,"shoprob")

    @app_commands.command(name="bankrob",description="Bankrablás indítása a Jobs rendszerből.")
    async def bankrob_job(self, interaction: discord.Interaction) -> None: await self.start_job_interaction(interaction,"bankrob")

    @app_commands.command(name="taxi",description="Taxi interaktív műszak indítása.")
    async def taxi_job(self, interaction: discord.Interaction) -> None: await self.start_job_interaction(interaction,"taxi")

    @app_commands.command(name="mastery",description="Megmutatja a Job Mastery szintjeidet.")
    async def mastery(self, interaction: discord.Interaction) -> None:
        if not await self._guard_interaction(interaction): return
        await interaction.response.send_message(embed=await self.mastery_embed(interaction.guild_id,interaction.user),ephemeral=True)

    @app_commands.command(name="history",description="Megmutatja a legutóbbi Interactive Jobs műszakokat.")
    async def history(self, interaction: discord.Interaction) -> None:
        if not await self._guard_interaction(interaction): return
        await interaction.response.send_message(embed=await self.history_embed(interaction.guild_id,interaction.user),ephemeral=True)

    @app_commands.command(name="settings",description="Interactive Jobs szerverbeállítások.")
    @app_commands.default_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None: return
        if not isinstance(interaction.user,discord.Member) or not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Ehhez **Szerver kezelése** jogosultság kell.",ephemeral=True)
        embed=base_embed("🧰 Interactive Jobs","Beállítások betöltése…"); await interaction.response.send_message(embed=embed,ephemeral=True); await self.show_settings(interaction,interaction.user.id)

    @commands.command(name="jobs",aliases=["job","munka","munkak","munkák"])
    @commands.guild_only()
    async def jobs_prefix(self, ctx: commands.Context) -> None:
        if not await self._guard_prefix(ctx): return
        embed,file,cooldown=await self.lobby_embed(ctx.guild.id,ctx.author); view=self._lobby_view(ctx.author.id,cooldown); msg=await ctx.send(embed=embed,file=file,view=view); view.message=msg

    async def _prefix_start(self, ctx: commands.Context, job: str) -> None:
        if not await self._guard_prefix(ctx):
            return
        try:
            if job=="warehouse":
                session=await self.service.start_warehouse(ctx.guild.id,ctx.author.id)
                msg=await ctx.send(embed=base_embed("📦 Raktáros","Műszak indul…"))
                await self._show_warehouse_memory(msg,ctx.author,session,intro="A polcsor mozog, utána külön időt kapsz a megjegyzésre.")
            elif job=="borsod":
                session=await self.service.start_borsod(ctx.guild.id,ctx.author.id)
                data=session["data"]
                fp=await self._render(render_borsod,ctx.author.display_name,_board_tokens(session),int(data["attempts_left"]),0,event=str(data["event"]))
                view=BorsodView(self,ctx.author.id,session)
                embed=base_embed("🔌 Borsodi Lopkodás","5×5 grid • 7 keresés • a járőr külön döntési scenario-t nyit.",GOLD)
                embed.set_image(url="attachment://borsod_state.png")
                msg=await ctx.send(embed=embed,file=discord.File(fp=fp,filename="borsod_state.png"),view=view)
                view.message=msg
            else:
                session=await self.service.start_transport(ctx.guild.id,ctx.author.id,job)
                definition=cfg.JOB_BY_KEY[job]
                data=session["data"]
                fp=await self._render(render_transport_state,ctx.author.display_name,definition.name,accent=definition.accent,stage=1,total=int(data["total"]),score=50,reward=0,event=str(data["current"]))
                view=TransportView(self,ctx.author.id,session)
                embed=base_embed(f"{definition.emoji} {definition.name}","Válassz útvonalat. Utána menet közben külön scenario-döntés jön.")
                embed.set_image(url="attachment://transport_state.png")
                msg=await ctx.send(embed=embed,file=discord.File(fp=fp,filename="transport_state.png"),view=view)
                view.message=msg
        except (JobBusyError,JobCooldownError,ValueError) as exc:
            await ctx.send(embed=error_embed(ctx.author,str(exc)))

    @commands.command(name="raktaros",aliases=["raktáros"])
    @commands.guild_only()
    async def warehouse_prefix(self,ctx:commands.Context)->None: await self._prefix_start(ctx,"warehouse")

    @commands.command(name="lopkodas",aliases=["lopkodás","borsod"])
    @commands.guild_only()
    async def borsod_prefix(self,ctx:commands.Context)->None: await self._prefix_start(ctx,"borsod")

    @commands.command(name="futar",aliases=["futár"])
    @commands.guild_only()
    async def courier_prefix(self,ctx:commands.Context)->None: await self._prefix_start(ctx,"courier")

    @commands.command(name="taxi")
    @commands.guild_only()
    async def taxi_prefix(self,ctx:commands.Context)->None: await self._prefix_start(ctx,"taxi")
