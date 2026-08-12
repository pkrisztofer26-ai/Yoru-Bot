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
    render_transport_state,
    render_warehouse,
    render_warehouse_transition,
)
from app.cogs.access_utils import handle_wrong_economy_channel
from app.cogs.settings import OwnedView, PagedGuildChannelSelect
from app.services.jobs import JobBusyError, JobsService
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
                await self.cog.service.cancel(self.session_id)
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
        super().__init__(placeholder="Válassz interaktív munkát…", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected = self.values[0]
        await self.parent_view.cog.refresh_lobby(interaction, self.parent_view)


class JobsLobbyView(JobOwnedView):
    def __init__(self, cog: "JobsCog", owner_id: int, *, selected: str = "warehouse") -> None:
        super().__init__(cog, owner_id, timeout=600)
        self.selected = selected if selected in cfg.JOB_BY_KEY else "warehouse"
        self.add_item(JobsSelect(self))

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
        await self.parent_view.cog.warehouse_answer(interaction, self.parent_view.session_id, self.choice)


class WarehouseView(JobOwnedView):
    def __init__(self, cog: "JobsCog", owner_id: int, session: dict) -> None:
        super().__init__(cog, owner_id, session_id=session["session_id"])
        for idx, sequence in enumerate(session["data"]["candidates"]):
            self.add_item(WarehouseChoiceButton(self, idx, " → ".join(sequence)))


class BorsodCellButton(discord.ui.Button):
    def __init__(self, parent: "BorsodView", index: int, token: str) -> None:
        revealed = token != "?"
        super().__init__(emoji=(token if revealed else "⬛"), style=discord.ButtonStyle.secondary if not revealed else discord.ButtonStyle.primary, row=index // 5, disabled=revealed)
        self.parent_view = parent
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.cog.borsod_pick(interaction, self.parent_view.session_id, self.index)


class BorsodView(JobOwnedView):
    def __init__(self, cog: "JobsCog", owner_id: int, session: dict) -> None:
        super().__init__(cog, owner_id, session_id=session["session_id"])
        for idx, token in enumerate(_board_tokens(session)):
            self.add_item(BorsodCellButton(self, idx, token))


class TransportView(JobOwnedView):
    def __init__(self, cog: "JobsCog", owner_id: int, session: dict) -> None:
        super().__init__(cog, owner_id, session_id=session["session_id"])
        self.job = str(session["job"])

    @discord.ui.button(label="Rövid / biztos", emoji="🟢", style=discord.ButtonStyle.success, row=0)
    async def safe(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.transport_choose(interaction, self.session_id, "safe")

    @discord.ui.button(label="Hosszabb / jobb", emoji="🟡", style=discord.ButtonStyle.primary, row=0)
    async def long(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.transport_choose(interaction, self.session_id, "long")

    @discord.ui.button(label="Problémás / magas reward", emoji="🔴", style=discord.ButtonStyle.danger, row=0)
    async def risky(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.transport_choose(interaction, self.session_id, "risky")


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

    @discord.ui.button(label="Log kikapcsolása", emoji="🧹", style=discord.ButtonStyle.secondary, row=1)
    async def clear_log(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.service.settings.set_int(interaction.guild_id, cfg.JOBS_LOG_CHANNEL_KEY, None)
        await self.refresh(interaction)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
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

    async def lobby_embed(self, guild_id: int, user: discord.abc.User) -> tuple[discord.Embed, discord.File]:
        rows = await self.service.mastery_summary(guild_id, user.id)
        lines=[]
        for job, mastery in zip(cfg.JOBS, rows):
            lv, current, need = cfg.mastery_progress(int(mastery["xp"]))
            lines.append((job.name, f"{int(mastery['shifts'])} műszak • rekord {mastery['best_rating']}", f"Mastery Lv.{lv} • {current}/{need} XP"))
        fp=await self._render(render_job_lobby,user.display_name,lines)
        embed=base_embed("🧰 YORU INTERACTIVE JOBS", "Aktív, tét nélküli pénzkeresés. **Nincs AFK payout:** a műszakhoz dönteni/kattintani kell.", BRAND)
        embed.set_author(name=user.display_name,icon_url=getattr(user.display_avatar,"url",None))
        embed.set_image(url="attachment://jobs_lobby.png")
        embed.add_field(name="💡 Loop",value="Játssz → teljesíts jobot → építs Masteryt → növeld a rekordod + kapj kis, plafonozott income bónuszt.",inline=False)
        embed.set_footer(text="Yoru • Jobs • egy aktív Interactive Job / játékos / szerver")
        return embed,discord.File(fp=fp,filename="jobs_lobby.png")

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
        embed,file=await self.lobby_embed(interaction.guild_id,interaction.user)
        new=JobsLobbyView(self,view.owner_id,selected=view.selected)
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

    async def _final_embed_file(self,user:discord.abc.User,result):
        job=cfg.JOB_BY_KEY[result.job]
        fp=await self._render(render_job_final,user.display_name,job.name,accent=job.accent,rating=result.rating,score=result.score,reward=result.reward,mastery_level=result.mastery_level,mastery_xp=result.mastery_xp)
        embed=base_embed(f"{job.emoji} {job.name} • {result.rating} rating",f"Műszak kész. **+{money(result.reward)}** került a walletedbe.",SUCCESS)
        embed.set_author(name=user.display_name,icon_url=getattr(user.display_avatar,"url",None)); embed.set_image(url="attachment://job_final.png")
        embed.add_field(name="Performance",value=f"**{result.score}/100**",inline=True); embed.add_field(name="Mastery",value=f"**Lv.{result.mastery_level}** • +{result.mastery_xp} XP",inline=True); embed.add_field(name="Wallet",value=f"**{money(result.wallet)}**",inline=True)
        return embed,discord.File(fp=fp,filename="job_final.png")

    async def start_job_interaction(self, interaction: discord.Interaction, job: str) -> None:
        if not await self._guard_interaction(interaction): return
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

    async def _start_warehouse_ui(self, interaction: discord.Interaction, session: dict) -> None:
        data=session["data"]
        anim=await self._render(render_warehouse_transition,interaction.user.display_name,data["sequence"],int(data["round"])); embed=base_embed("📦 Raktáros", "Jegyezd meg a sorrendet. A kép rövidesen eltűnik.", BRAND); embed.set_image(url="attachment://warehouse_shift.gif")
        msg=await self._edit_after_defer(interaction,embed=embed,file=discord.File(fp=anim,filename="warehouse_shift.gif"),view=None)
        await asyncio.sleep(2.4)
        try:
            latest=await self.service.get_session(session["session_id"])
            if latest["status"]!="active": return
            fp=await self._render(render_warehouse,interaction.user.display_name,latest["data"]["sequence"],phase="choose",round_no=int(latest["data"]["round"]),correct=int(latest["data"]["correct"]),combo=int(latest["data"]["combo"])); view=WarehouseView(self,interaction.user.id,latest)
            embed=base_embed("📦 Raktáros", "Válaszd ki a helyes sorrendet.", BRAND); embed.set_image(url="attachment://warehouse_state.png")
            await msg.edit(embed=embed,attachments=[discord.File(fp=fp,filename="warehouse_state.png")],view=view); view.message=msg
        except (discord.NotFound,discord.Forbidden,discord.HTTPException): pass

    async def warehouse_answer(self, interaction: discord.Interaction, session_id: str, choice: int) -> None:
        await interaction.response.defer()
        try: session,correct,done=await self.service.warehouse_answer(session_id,choice)
        except ValueError as exc: return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        if done:
            result=await self.service.finish(session_id); embed,file=await self._final_embed_file(interaction.user,result); await interaction.message.edit(embed=embed,attachments=[file],view=None); await self._log_result(interaction.guild_id,interaction.user.id,result); return
        data=session["data"]
        anim=await self._render(render_warehouse_transition,interaction.user.display_name,data["sequence"],int(data["round"])); embed=base_embed("📦 Raktáros",f"{'✅ Helyes' if correct else '❌ Hibás'} • következő kör: jegyezd meg a sorrendet.",SUCCESS if correct else GOLD); embed.set_image(url="attachment://warehouse_shift.gif")
        await interaction.message.edit(embed=embed,attachments=[discord.File(fp=anim,filename="warehouse_shift.gif")],view=None)
        await asyncio.sleep(2.4)
        latest=await self.service.get_session(session_id); fp=await self._render(render_warehouse,interaction.user.display_name,latest["data"]["sequence"],phase="choose",round_no=int(latest["data"]["round"]),correct=int(latest["data"]["correct"]),combo=int(latest["data"]["combo"])); view=WarehouseView(self,interaction.user.id,latest); embed=base_embed("📦 Raktáros","Válaszd ki a helyes sorrendet.",BRAND); embed.set_image(url="attachment://warehouse_state.png"); await interaction.message.edit(embed=embed,attachments=[discord.File(fp=fp,filename="warehouse_state.png")],view=view); view.message=interaction.message

    async def _start_borsod_ui(self, interaction: discord.Interaction, session: dict) -> None:
        data=session["data"]; board=_board_tokens(session); fp=await self._render(render_borsod,interaction.user.display_name,board,int(data["attempts_left"]),int(session["reward"]),event=str(data["event"])); embed=base_embed("🔌 Borsodi Lopkodás","5×5 grid • **7 keresés** • nincs tét. A 🚓 járőr korán lezárhatja a runt, de a meglévő loot 70%-át megtartod.",GOLD); embed.set_image(url="attachment://borsod_state.png"); view=BorsodView(self,interaction.user.id,session); await self._edit_after_defer(interaction,embed=embed,file=discord.File(fp=fp,filename="borsod_state.png"),view=view)

    async def borsod_pick(self, interaction: discord.Interaction, session_id: str, index: int) -> None:
        await interaction.response.defer(); before=await self.service.get_session(session_id); board_before=_board_tokens(before)
        try: session,cell,done=await self.service.borsod_pick(session_id,index)
        except ValueError as exc: return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        data=session["data"]; anim=await self._render(render_borsod_reveal_animation,interaction.user.display_name,board_before,index,str(cell["emoji"]),int(data["attempts_left"]),int(session["reward"])); embed=base_embed("🔌 Borsodi Lopkodás",str(data["event"]),GOLD if not cell["hazard"] else discord.Color.red()); embed.set_image(url="attachment://borsod_reveal.gif"); await interaction.message.edit(embed=embed,attachments=[discord.File(fp=anim,filename="borsod_reveal.gif")],view=None); await asyncio.sleep(1.35)
        if done:
            result=await self.service.finish(session_id); embed,file=await self._final_embed_file(interaction.user,result); await interaction.message.edit(embed=embed,attachments=[file],view=None); await self._log_result(interaction.guild_id,interaction.user.id,result); return
        board=_board_tokens(session); fp=await self._render(render_borsod,interaction.user.display_name,board,int(data["attempts_left"]),int(session["reward"]),event=str(data["event"])); view=BorsodView(self,interaction.user.id,session); embed=base_embed("🔌 Borsodi Lopkodás",str(data["event"]),BRAND); embed.set_image(url="attachment://borsod_state.png"); await interaction.message.edit(embed=embed,attachments=[discord.File(fp=fp,filename="borsod_state.png")],view=view); view.message=interaction.message

    async def _start_transport_ui(self, interaction: discord.Interaction, session: dict) -> None:
        job=str(session["job"]); definition=cfg.JOB_BY_KEY[job]; data=session["data"]; fp=await self._render(render_transport_state,interaction.user.display_name,definition.name,accent=definition.accent,stage=int(session["stage"]),total=int(data["total"]),score=int(session["score"]),reward=int(session["reward"]),event=str(data["current"])); embed=base_embed(f"{definition.emoji} {definition.name}","Válassz útvonalat. A biztosabb opció kevesebbet fizet, a problémás út magasabb potenciált és több event-risket ad.",BRAND); embed.set_image(url="attachment://transport_state.png"); view=TransportView(self,interaction.user.id,session); await self._edit_after_defer(interaction,embed=embed,file=discord.File(fp=fp,filename="transport_state.png"),view=view)

    async def transport_choose(self, interaction: discord.Interaction, session_id: str, route: str) -> None:
        await interaction.response.defer()
        try: session,event,done=await self.service.transport_choose(session_id,route)
        except ValueError as exc: return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        job=str(session["job"]); definition=cfg.JOB_BY_KEY[job]; vehicle="FUTÁR" if job=="courier" else "TAXI"; anim=await self._render(render_route_animation,interaction.user.display_name,definition.name,vehicle,accent=definition.accent,event=str(event["event"]),success=not bool(event["bad"])); embed=base_embed(f"{definition.emoji} {definition.name}",f"**{event['event']}** • run +{money(int(event['reward']))}",SUCCESS if not event["bad"] else GOLD); embed.set_image(url="attachment://route.gif"); await interaction.message.edit(embed=embed,attachments=[discord.File(fp=anim,filename="route.gif")],view=None); await asyncio.sleep(2.45)
        if done:
            result=await self.service.finish(session_id); embed,file=await self._final_embed_file(interaction.user,result); await interaction.message.edit(embed=embed,attachments=[file],view=None); await self._log_result(interaction.guild_id,interaction.user.id,result); return
        data=session["data"]; fp=await self._render(render_transport_state,interaction.user.display_name,definition.name,accent=definition.accent,stage=int(session["stage"]),total=int(data["total"]),score=int(session["score"]),reward=int(session["reward"]),event=str(data["current"])); view=TransportView(self,interaction.user.id,session); embed=base_embed(f"{definition.emoji} {definition.name}",f"Előző esemény: **{event['event']}**. Következő fuvarhoz válassz útvonalat.",BRAND); embed.set_image(url="attachment://transport_state.png"); await interaction.message.edit(embed=embed,attachments=[discord.File(fp=fp,filename="transport_state.png")],view=view); view.message=interaction.message

    async def show_settings(self, interaction: discord.Interaction, owner_id: int, existing: JobsSettingsView | None=None) -> None:
        if interaction.guild is None: return
        states={"enabled":await self.service.is_enabled(interaction.guild_id)}
        for job in cfg.JOBS: states[job.key]=await self.service.job_enabled(interaction.guild_id,job.key)
        bp=await self.service.settings.get_int(interaction.guild_id,cfg.JOB_REWARD_MULTIPLIER_KEY) or cfg.DEFAULT_REWARD_MULTIPLIER_BP; channel_id=await self.service.settings.get_int(interaction.guild_id,cfg.JOBS_LOG_CHANNEL_KEY); channel=interaction.guild.get_channel(channel_id) if channel_id else None
        embed=base_embed("🧰 Interactive Jobs beállítások","Minden Jobs beállítás DB-ben marad, release ZIP nem írja felül.",BRAND); embed.add_field(name="Állapot",value="🟢 Aktív" if states["enabled"] else "🔴 Kikapcsolva",inline=True); embed.add_field(name="Reward",value=f"**{bp/100:.0f}%**",inline=True); embed.add_field(name="Log",value=channel.mention if isinstance(channel,discord.abc.GuildChannel) else "Nincs",inline=True); embed.add_field(name="Munkák",value="\n".join(f"{'🟢' if states[j.key] else '⚪'} {j.emoji} {j.name}" for j in cfg.JOBS),inline=False); embed.set_footer(text="Yoru • Settings • Jobs")
        view=JobsSettingsView(self,owner_id,interaction.guild,states,channel_page=(existing.channel_page if existing else 0))
        if interaction.response.is_done(): await interaction.edit_original_response(embed=embed,view=view,attachments=[])
        else: await interaction.response.edit_message(embed=embed,view=view,attachments=[])

    async def home_status(self, guild: discord.Guild) -> str:
        enabled=await self.service.is_enabled(guild.id); active=sum(1 for j in cfg.JOBS if await self.service.job_enabled(guild.id,j.key)); return f"{'🟢' if enabled else '⚪'} {active}/{len(cfg.JOBS)} job aktív"

    @app_commands.command(name="panel",description="Megnyitja az Interactive Jobs lobby-t.")
    async def panel(self, interaction: discord.Interaction) -> None:
        if not await self._guard_interaction(interaction): return
        embed,file=await self.lobby_embed(interaction.guild_id,interaction.user); view=JobsLobbyView(self,interaction.user.id); await interaction.response.send_message(embed=embed,file=file,view=view); view.message=await interaction.original_response()

    @app_commands.command(name="warehouse",description="Raktáros memória/sequence műszak indítása.")
    async def warehouse(self, interaction: discord.Interaction) -> None: await self.start_job_interaction(interaction,"warehouse")

    @app_commands.command(name="borsod",description="Borsodi Lopkodás 5×5 loot-grid műszak.")
    async def borsod_job(self, interaction: discord.Interaction) -> None: await self.start_job_interaction(interaction,"borsod")

    @app_commands.command(name="courier",description="Futár interaktív műszak indítása.")
    async def courier(self, interaction: discord.Interaction) -> None: await self.start_job_interaction(interaction,"courier")

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
        embed,file=await self.lobby_embed(ctx.guild.id,ctx.author); view=JobsLobbyView(self,ctx.author.id); msg=await ctx.send(embed=embed,file=file,view=view); view.message=msg

    async def _prefix_start(self, ctx: commands.Context, job: str) -> None:
        if not await self._guard_prefix(ctx): return
        try:
            if job=="warehouse": session=await self.service.start_warehouse(ctx.guild.id,ctx.author.id); data=session["data"]; anim=await self._render(render_warehouse_transition,ctx.author.display_name,data["sequence"],int(data["round"])); embed=base_embed("📦 Raktáros","Jegyezd meg a sorrendet. A kép rövidesen eltűnik."); embed.set_image(url="attachment://warehouse_shift.gif"); msg=await ctx.send(embed=embed,file=discord.File(fp=anim,filename="warehouse_shift.gif")); await asyncio.sleep(2.4); latest=await self.service.get_session(session["session_id"]); fp=await self._render(render_warehouse,ctx.author.display_name,latest["data"]["sequence"],phase="choose",round_no=int(latest["data"]["round"]),correct=0,combo=0); view=WarehouseView(self,ctx.author.id,latest); embed=base_embed("📦 Raktáros","Válaszd ki a helyes sorrendet."); embed.set_image(url="attachment://warehouse_state.png"); await msg.edit(embed=embed,attachments=[discord.File(fp=fp,filename="warehouse_state.png")],view=view); view.message=msg
            elif job=="borsod": session=await self.service.start_borsod(ctx.guild.id,ctx.author.id); data=session["data"]; fp=await self._render(render_borsod,ctx.author.display_name,_board_tokens(session),int(data["attempts_left"]),0,event=str(data["event"])); view=BorsodView(self,ctx.author.id,session); embed=base_embed("🔌 Borsodi Lopkodás","5×5 grid • 7 keresés • nincs tét.",GOLD); embed.set_image(url="attachment://borsod_state.png"); msg=await ctx.send(embed=embed,file=discord.File(fp=fp,filename="borsod_state.png"),view=view); view.message=msg
            else: session=await self.service.start_transport(ctx.guild.id,ctx.author.id,job); definition=cfg.JOB_BY_KEY[job]; data=session["data"]; fp=await self._render(render_transport_state,ctx.author.display_name,definition.name,accent=definition.accent,stage=1,total=int(data["total"]),score=50,reward=0,event=str(data["current"])); view=TransportView(self,ctx.author.id,session); embed=base_embed(f"{definition.emoji} {definition.name}","Válassz útvonalat."); embed.set_image(url="attachment://transport_state.png"); msg=await ctx.send(embed=embed,file=discord.File(fp=fp,filename="transport_state.png"),view=view); view.message=msg
        except (JobBusyError,ValueError) as exc: await ctx.send(embed=error_embed(ctx.author,str(exc)))

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
