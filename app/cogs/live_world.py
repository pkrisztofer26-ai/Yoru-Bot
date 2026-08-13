from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from app import live_world_config as cfg
from app.amounts import parse_amount
from app.cogs.settings import OwnedView
from app.poker_engine import PokerPlayer, PokerTableState, best_hand, hand_name
from app.services.live_world import MAV_UI_REFRESH_SECONDS, LiveResult, LiveWorldService, mav_crash_deadline
from app.ui import BRAND, DANGER, GOLD, SUCCESS, base_embed, error_embed, money


logger = logging.getLogger(__name__)


def _bar(value: int, maximum: int = 100, size: int = 12) -> str:
    value=max(0,min(maximum,int(value))); fill=round(size*value/maximum); return "█"*fill+"░"*(size-fill)


class OwnerView(discord.ui.View):
    def __init__(self,cog:"LiveWorldCog",owner_id:int,*,timeout:float|None=300)->None:
        super().__init__(timeout=timeout); self.cog=cog; self.owner_id=owner_id
    async def interaction_check(self,interaction:discord.Interaction)->bool:
        if interaction.user.id!=self.owner_id:
            await interaction.response.send_message("❌ Ez nem a te játékod.",ephemeral=True); return False
        return True


class RobberyView(OwnerView):
    def __init__(self,cog:"LiveWorldCog",owner_id:int,session:dict[str,Any])->None:
        super().__init__(cog,owner_id,timeout=600)
        self.session_id=str(session["session_id"])
        self.expected_stage=int(session.get("stage",1))
    async def on_timeout(self)->None:
        # A timed-out robbery has no reserved stake, but it must not remain an
        # eternal active Live session that blocks every other game.
        with contextlib.suppress(Exception):
            await self.cog.service.cancel_active_robbery(self.session_id,"ui_timeout")
        self.cog.robbery_locks.pop(self.session_id,None)
    @discord.ui.button(label="Óvatos",emoji="🟢",style=discord.ButtonStyle.success,row=0)
    async def safe(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.robbery_action(interaction,self.session_id,"safe",self.expected_stage)
    @discord.ui.button(label="Gyors",emoji="🟡",style=discord.ButtonStyle.primary,row=0)
    async def fast(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.robbery_action(interaction,self.session_id,"fast",self.expected_stage)
    @discord.ui.button(label="Kapzsi",emoji="🔴",style=discord.ButtonStyle.danger,row=0)
    async def greedy(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.robbery_action(interaction,self.session_id,"greedy",self.expected_stage)
    @discord.ui.button(label="Menekülés / Cashout",emoji="💰",style=discord.ButtonStyle.secondary,row=1)
    async def cashout(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.robbery_cashout(interaction,self.session_id)


class MavCrashView(OwnerView):
    def __init__(self,cog:"LiveWorldCog",owner_id:int,session_id:str)->None:
        # A MÁV kör 180 másodpercnél tovább is futhat. A cashout gomb ezért
        # a teljes session alatt él, és ugyanaz a View marad a message-en.
        super().__init__(cog,owner_id,timeout=None); self.session_id=session_id
        self.cashout.custom_id=f"live:mav:cashout:{session_id}"
    @discord.ui.button(label="CASHOUT",emoji="💸",style=discord.ButtonStyle.success)
    async def cashout(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.mav_cashout(interaction,self.session_id)


class LiveSettingsModal(discord.ui.Modal,title="Live World • Balance"):
    shop_cd=discord.ui.TextInput(label="Boltrablás cooldown (perc)",placeholder="120",max_length=5)
    bank_cd=discord.ui.TextInput(label="Bankrablás cooldown (perc)",placeholder="240",max_length=5)
    mav_min=discord.ui.TextInput(label="MÁV minimum tét",placeholder="50k",max_length=30)
    poker_min=discord.ui.TextInput(label="Poker minimum buy-in",placeholder="250k",max_length=30)
    max_payout=discord.ui.TextInput(label="Rablás max payout",placeholder="100b",max_length=30)
    def __init__(self,view:"LiveSettingsView")->None:super().__init__();self.parent_view=view
    async def on_submit(self,interaction:discord.Interaction)->None:
        try:
            await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.SHOPROB_COOLDOWN_KEY,max(1,min(1440,int(str(self.shop_cd.value)))))
            await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.BANKROB_COOLDOWN_KEY,max(1,min(1440,int(str(self.bank_cd.value)))))
            await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.MAV_MIN_BET_KEY,parse_amount(str(self.mav_min.value)))
            await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.POKER_MIN_BUYIN_KEY,parse_amount(str(self.poker_min.value)))
            await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.LIVE_MAX_PAYOUT_KEY,parse_amount(str(self.max_payout.value)))
        except ValueError as exc:return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        await self.parent_view.cog.show_settings(interaction,self.parent_view.owner_id)


class LiveSettingsView(OwnedView):
    def __init__(self,cog:"LiveWorldCog",owner_id:int,states:dict[str,bool])->None:
        super().__init__(cog,owner_id);self.states=states;self._sync()
    def _sync(self)->None:
        for b,k,label in ((self.enabled,"enabled","Live"),(self.shop,"shoprob","Bolt"),(self.bank,"bankrob","Bank"),(self.mav,"mav","MÁV"),(self.poker,"poker","Poker")):
            b.label=f"{label}: {'ON' if self.states[k] else 'OFF'}"; b.style=discord.ButtonStyle.success if self.states[k] else discord.ButtonStyle.secondary
    async def _toggle(self,interaction:discord.Interaction,key:str,setting:str)->None:
        await self.cog.service.settings.set_bool(interaction.guild_id,setting,not self.states[key]); await self.cog.show_settings(interaction,self.owner_id)
    @discord.ui.button(label="Live",emoji="🌆",style=discord.ButtonStyle.success,row=0)
    async def enabled(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self._toggle(interaction,"enabled",cfg.LIVE_ENABLED_KEY)
    @discord.ui.button(label="Bolt",emoji="🏪",style=discord.ButtonStyle.secondary,row=0)
    async def shop(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self._toggle(interaction,"shoprob",cfg.SHOPROB_ENABLED_KEY)
    @discord.ui.button(label="Bank",emoji="🏦",style=discord.ButtonStyle.secondary,row=0)
    async def bank(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self._toggle(interaction,"bankrob",cfg.BANKROB_ENABLED_KEY)
    @discord.ui.button(label="MÁV",emoji="🚂",style=discord.ButtonStyle.secondary,row=0)
    async def mav(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self._toggle(interaction,"mav",cfg.MAV_ENABLED_KEY)
    @discord.ui.button(label="Poker",emoji="♠️",style=discord.ButtonStyle.secondary,row=0)
    async def poker(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self._toggle(interaction,"poker",cfg.POKER_ENABLED_KEY)
    @discord.ui.button(label="Balance",emoji="🎚️",style=discord.ButtonStyle.primary,row=1)
    async def balance(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await interaction.response.send_modal(LiveSettingsModal(self))
    @discord.ui.button(label="Vissza",emoji="⬅️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:
        settings=self.cog.bot.get_cog("SettingsCog")
        if settings:await settings.show_home(interaction,self.owner_id)


@dataclass
class PokerRuntime:
    state: PokerTableState
    message: discord.Message
    timeout_task: asyncio.Task|None=None


class PokerLobbyView(discord.ui.View):
    def __init__(self,cog:"LiveWorldCog",table_id:str)->None:
        super().__init__(timeout=600);self.cog=cog;self.table_id=table_id
    @discord.ui.button(label="Csatlakozás",emoji="➕",style=discord.ButtonStyle.success)
    async def join(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self.cog.poker_join(interaction,self.table_id)
    @discord.ui.button(label="Kilépés",emoji="➖",style=discord.ButtonStyle.secondary)
    async def leave(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self.cog.poker_leave(interaction,self.table_id)
    @discord.ui.button(label="START",emoji="▶️",style=discord.ButtonStyle.primary)
    async def start(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self.cog.poker_start(interaction,self.table_id)
    @discord.ui.button(label="Törlés",emoji="🗑️",style=discord.ButtonStyle.danger)
    async def cancel(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self.cog.poker_cancel_lobby(interaction,self.table_id)


class PokerActionView(discord.ui.View):
    def __init__(self,cog:"LiveWorldCog",table_id:str)->None:
        super().__init__(timeout=None);self.cog=cog;self.table_id=table_id
    @discord.ui.button(label="Fold",emoji="🟥",style=discord.ButtonStyle.danger,row=0)
    async def fold(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self.cog.poker_action(interaction,self.table_id,"fold")
    @discord.ui.button(label="Check / Call",emoji="✅",style=discord.ButtonStyle.success,row=0)
    async def call(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self.cog.poker_action(interaction,self.table_id,"call")
    @discord.ui.button(label="Raise 2×",emoji="⬆️",style=discord.ButtonStyle.primary,row=0)
    async def raise2(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self.cog.poker_action(interaction,self.table_id,"raise")
    @discord.ui.button(label="ALL-IN",emoji="🔥",style=discord.ButtonStyle.danger,row=0)
    async def allin(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self.cog.poker_action(interaction,self.table_id,"allin")
    @discord.ui.button(label="Lapjaim",emoji="🃏",style=discord.ButtonStyle.secondary,row=1)
    async def hand(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:await self.cog.poker_hand(interaction,self.table_id)


class LiveWorldCog(commands.GroupCog,group_name="live",group_description="Yoru Live World • single-player rablások, MÁV Crash és Poker."):
    def __init__(self,bot:commands.Bot,service:LiveWorldService)->None:
        self.bot=bot;self.service=service
        self.mav_tasks:dict[str,asyncio.Task]={}
        self.mav_views:dict[str,MavCrashView]={}
        self.mav_edit_tasks:dict[str,asyncio.Task]={}
        self.mav_final_tasks:dict[str,asyncio.Task]={}
        self.mav_locks:dict[str,asyncio.Lock]={}
        self.robbery_locks:dict[str,asyncio.Lock]={}
        self.poker_tables:dict[str,PokerRuntime]={};super().__init__()

    async def cog_unload(self)->None:
        # Never abandon a reserved MÁV stake during cog reload/unload. Runner
        # cancellation contains an exactly-once DB refund, so wait for those
        # cancellation handlers to finish before the cog disappears.
        mav_tasks=list(self.mav_tasks.values())
        edit_tasks=list(self.mav_edit_tasks.values())
        final_tasks=list(self.mav_final_tasks.values())
        for task in mav_tasks+edit_tasks+final_tasks:
            if not task.done():task.cancel()
        if mav_tasks:
            await asyncio.gather(*mav_tasks,return_exceptions=True)
        if edit_tasks:
            await asyncio.gather(*edit_tasks,return_exceptions=True)
        if final_tasks:
            await asyncio.gather(*final_tasks,return_exceptions=True)
        for rt in list(self.poker_tables.values()):
            if rt.timeout_task:rt.timeout_task.cancel()

    async def home_status(self,guild:discord.Guild)->str:
        enabled=await self.service.enabled(guild.id); active=0
        for game in ("shoprob","bankrob","mav","poker"):
            if await self.service.game_enabled(guild.id,game):active+=1
        return f"{'🟢' if enabled else '⚪'} {active}/4 mód aktív"

    async def show_settings(self,interaction:discord.Interaction,owner_id:int)->None:
        if interaction.guild is None:return
        if not interaction.response.is_done():await interaction.response.defer()
        states={"enabled":await self.service.enabled(interaction.guild_id)}
        for game in ("shoprob","bankrob","mav","poker"):states[game]=await self.service.game_enabled(interaction.guild_id,game)
        embed=base_embed("🌆 Live World • Settings","Single-player rablások, MÁV Crash és multiplayer Texas Hold'em.",BRAND)
        embed.add_field(name="Modulok",value=" • ".join(f"{'🟢' if states[g] else '⚪'} {g}" for g in ("shoprob","bankrob","mav","poker")),inline=False)
        embed.add_field(name="Cooldown",value=f"Bolt **{int((await self.service.robbery_cooldown(interaction.guild_id,'shoprob')).total_seconds()/60)}p** • Bank **{int((await self.service.robbery_cooldown(interaction.guild_id,'bankrob')).total_seconds()/60)}p**",inline=True)
        embed.add_field(name="Minimum",value=f"MÁV **{money(await self.service.mav_min_bet(interaction.guild_id))}** • Poker **{money(await self.service.poker_min_buyin(interaction.guild_id))}**",inline=True)
        await interaction.edit_original_response(embed=embed,view=LiveSettingsView(self,owner_id,states),attachments=[])

    def robbery_embed(self,user:discord.abc.User,session:dict[str,Any])->discord.Embed:
        game=str(session["game"]); d=cfg.ROBBERY_DEFS[game]; data=session["data"]; embed=base_embed(f"{d['emoji']} {d['name']}",str(data.get("event","Válassz döntést.")),GOLD if game=="bankrob" else BRAND)
        embed.set_author(name=user.display_name,icon_url=getattr(user.display_avatar,"url",None)); embed.add_field(name="Szakasz",value=f"**{session['stage']}/{d['stages']}**",inline=True); embed.add_field(name="Loot",value=f"**{money(int(data['loot']))}**",inline=True); embed.add_field(name="Heat",value=f"`{_bar(int(data['heat']))}` **{data['heat']}%**",inline=False); embed.set_footer(text="Óvatos = kisebb risk • Kapzsi = nagyobb loot és heat • bármikor cashout")
        return embed

    async def start_robbery_ui(self,interaction:discord.Interaction,game:str)->None:
        if interaction.guild_id is None:return
        await interaction.response.defer()
        try:session=await self.service.start_robbery(interaction.guild_id,interaction.user.id,game)
        except ValueError as exc:return await interaction.edit_original_response(embed=error_embed(interaction.user,str(exc)),view=None)
        self.robbery_locks[str(session["session_id"])]=asyncio.Lock()
        await interaction.edit_original_response(embed=self.robbery_embed(interaction.user,session),view=RobberyView(self,interaction.user.id,session))

    async def robbery_action(self,interaction:discord.Interaction,session_id:str,choice:str,expected_stage:int)->None:
        await interaction.response.defer()
        lock=self.robbery_locks.setdefault(session_id,asyncio.Lock())
        final_embed=None; next_session=None
        async with lock:
            try:
                session,done=await self.service.robbery_step(session_id,choice,expected_stage=expected_stage)
                if done:
                    result=await self.service.finish_robbery(session_id,"failed" if session["data"].get("failed") else "complete")
                    title="🚨 Lebuktál" if session["data"].get("failed") else "✅ Sikeres meló"
                    final_embed=base_embed(title,f"Kifizetés: **{money(result.reward)}**\nWallet: **{money(result.wallet)}**",DANGER if session["data"].get("failed") else SUCCESS)
                else:
                    next_session=session
            except ValueError as exc:
                return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        if final_embed is not None:
            self.robbery_locks.pop(session_id,None)
            return await interaction.message.edit(embed=final_embed,view=None)
        await interaction.message.edit(embed=self.robbery_embed(interaction.user,next_session),view=RobberyView(self,interaction.user.id,next_session))

    async def robbery_cashout(self,interaction:discord.Interaction,session_id:str)->None:
        await interaction.response.defer()
        lock=self.robbery_locks.setdefault(session_id,asyncio.Lock())
        async with lock:
            try:result=await self.service.robbery_cashout(session_id)
            except ValueError as exc:return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        self.robbery_locks.pop(session_id,None)
        await interaction.message.edit(embed=base_embed("💰 Megléptél a loottal",f"Kifizetés: **{money(result.reward)}**\nWallet: **{money(result.wallet)}**",SUCCESS),view=None)

    def mav_embed(self,user:discord.abc.User,stake:int,mult:float,*,crashed:bool=False,cashout:float|None=None,payout:int|None=None)->discord.Embed:
        if crashed:return base_embed("🚂💥 MÁV CRASH",f"A vonat **{mult:.2f}x**-nél kisiklott.\nElvesztett tét: **{money(stake)}**",DANGER)
        if cashout is not None:
            paid=round(stake*cashout) if payout is None else int(payout)
            return base_embed("🚂✅ Kiszálltál",f"Cashout: **{cashout:.2f}x**\nPayout: **{money(paid)}**",SUCCESS)
        progress=min(100,int((mult-1)*18)); embed=base_embed("🚂 MÁV CRASH",f"`{_bar(progress)}`\n\n# **{mult:.2f}x**\n\nCashoutolj, mielőtt kisiklik.",GOLD); embed.add_field(name="Tét",value=money(stake),inline=True); embed.add_field(name="Aktuális érték",value=money(round(stake*mult)),inline=True); return embed

    def _queue_mav_edit(self,session_id:str,message:discord.Message,embed:discord.Embed)->None:
        """Best-effort live refresh. Never let Discord rate limits stop game time."""
        old=self.mav_edit_tasks.get(session_id)
        if old is not None and not old.done():return
        async def worker()->None:
            try:
                # Omit view: the original stable MavCrashView + custom_id stay intact.
                await message.edit(embed=embed)
            except (discord.HTTPException,discord.NotFound):
                pass
            finally:
                if self.mav_edit_tasks.get(session_id) is asyncio.current_task():self.mav_edit_tasks.pop(session_id,None)
        self.mav_edit_tasks[session_id]=asyncio.create_task(worker())

    async def _cancel_mav_live_edit(self,session_id:str)->None:
        task=self.mav_edit_tasks.pop(session_id,None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await task

    async def _final_mav_edit(self,message:discord.Message,embed:discord.Embed)->bool:
        """Final state is important enough to retry instead of silently suppressing it."""
        for attempt in range(3):
            try:
                await message.edit(embed=embed,view=None);return True
            except discord.NotFound:
                return False
            except discord.HTTPException:
                if attempt<2:await asyncio.sleep(0.45*(attempt+1))
        return False

    def _queue_mav_final_edit(self,session_id:str,message:discord.Message,embed:discord.Embed)->None:
        """Publish a terminal UI state without ever blocking DB settlement."""
        old=self.mav_final_tasks.get(session_id)
        if old is not None and not old.done():old.cancel()
        async def worker()->None:
            try:
                await self._final_mav_edit(message,embed)
            except asyncio.CancelledError:
                raise
            finally:
                if self.mav_final_tasks.get(session_id) is asyncio.current_task():self.mav_final_tasks.pop(session_id,None)
        self.mav_final_tasks[session_id]=asyncio.create_task(worker())

    async def _cancel_mav_final_edit(self,session_id:str)->None:
        task=self.mav_final_tasks.pop(session_id,None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await task

    def _cleanup_mav_runtime(self,session_id:str)->None:
        self.mav_views.pop(session_id,None)
        self.mav_edit_tasks.pop(session_id,None)
        self.mav_locks.pop(session_id,None)

    async def _register_mav(self,message:discord.Message,user:discord.abc.User,session:dict[str,Any],stake:int,view:MavCrashView)->None:
        session_id=str(session["session_id"]); data=session["data"]
        self.mav_views[session_id]=view
        self.mav_locks[session_id]=asyncio.Lock()
        task=asyncio.create_task(self._run_mav(message,user,session_id,stake,float(data["crash_at"]),str(data.get("started_at") or "")))
        self.mav_tasks[session_id]=task

    async def start_mav_ui(self,interaction:discord.Interaction,stake:int)->None:
        await interaction.response.defer()
        try:session=await self.service.start_mav(interaction.guild_id,interaction.user.id,stake)
        except ValueError as exc:return await interaction.edit_original_response(embed=error_embed(interaction.user,str(exc)),view=None)
        sid=str(session["session_id"]);view=MavCrashView(self,interaction.user.id,sid)
        msg=await interaction.edit_original_response(embed=self.mav_embed(interaction.user,stake,1.0),view=view)
        await self._register_mav(msg,interaction.user,session,stake,view)

    async def _run_mav(self,message:discord.Message,user:discord.abc.User,session_id:str,stake:int,crash_at:float,started_at:str)->None:
        data={"started_at":started_at,"crash_at":crash_at,"current":1.0}; natural_terminal=False
        try:
            crash_deadline=mav_crash_deadline(data)
            while True:
                now=discord.utils.utcnow()
                remaining=(crash_deadline-now).total_seconds()
                if remaining<=0:
                    break
                mult=self.service.mav_current_from_data(data,at=now)
                self._queue_mav_edit(session_id,message,self.mav_embed(user,stake,mult))
                # The sleep is deadline-aware. Discord message.edit runs in a
                # separate best-effort task and can never extend game time.
                await asyncio.sleep(max(0.01,min(MAV_UI_REFRESH_SECONDS,remaining)))

            # BACKEND FIRST: commit the crash immediately at the authoritative
            # deadline. No Discord call and no artificial grace sleep may sit
            # in front of this transaction.
            lock=self.mav_locks.setdefault(session_id,asyncio.Lock())
            async with lock:
                try:
                    result=await self.service.settle_mav(session_id)
                except ValueError:
                    return
            natural_terminal=True

            # Money state is already final. UI publication is only best-effort.
            await self._cancel_mav_live_edit(session_id)
            if result.outcome=="crash":
                self._queue_mav_final_edit(session_id,message,self.mav_embed(user,stake,crash_at,crashed=True))
        except asyncio.CancelledError:
            # Cashout cancellation reaches here after DB settlement, therefore
            # refund_active_mav is a no-op. Any unrelated cancellation safely
            # returns a still-active stake exactly once.
            with contextlib.suppress(Exception):
                await asyncio.shield(self.service.refund_active_mav(session_id,"runner_cancelled"))
            raise
        except Exception:
            logger.exception("MÁV runner crashed unexpectedly: %s",session_id)
            refund=None
            with contextlib.suppress(Exception):
                refund=await self.service.refund_active_mav(session_id,"runner_exception")
            if refund is not None:
                embed=base_embed(
                    "🚂⚠️ MÁV • Technikai hiba",
                    f"A kör biztonságosan lezárult, a teljes tét visszakerült.\nVisszatérítés: **{money(refund.reward)}**",
                    GOLD,
                )
                self._queue_mav_final_edit(session_id,message,embed)
        finally:
            if self.mav_tasks.get(session_id) is asyncio.current_task():self.mav_tasks.pop(session_id,None)
            if natural_terminal:self._cleanup_mav_runtime(session_id)

    async def mav_cashout(self,interaction:discord.Interaction,session_id:str)->None:
        # Capture the immutable Discord snowflake timestamp before any await.
        # Even if acknowledging the interaction is delayed/expired, the money
        # decision must still be processed from the original click time.
        clicked_at=interaction.created_at
        with contextlib.suppress(discord.HTTPException,discord.InteractionResponded):
            await interaction.response.defer()

        edit_task=self.mav_edit_tasks.pop(session_id,None)
        if edit_task is not None and not edit_task.done():edit_task.cancel()

        lock=self.mav_locks.setdefault(session_id,asyncio.Lock())
        result=None; stake=0; crash_at=1.0; clicked_mult=1.0
        async with lock:
            try:
                row=await self.service.mav_snapshot(session_id)
                stake=int(row["stake"]); crash_at=float(row["data"].get("crash_at",1.0))
                clicked_mult=self.service.mav_current_from_data(row["data"],at=clicked_at)
                # settle_mav also supports an already-committed crash: if this
                # callback was created before the deadline it atomically corrects
                # that zero-payout crash exactly once.
                result=await self.service.settle_mav(session_id,cashout_at=clicked_at)
            except ValueError as exc:
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
                return

        # Critical DB state is committed at this point. Cancel only this
        # session's runner/display tasks; other players are untouched.
        runner=self.mav_tasks.get(session_id)
        if runner is not None and runner is not asyncio.current_task() and not runner.done():runner.cancel()
        await self._cancel_mav_live_edit(session_id)
        await self._cancel_mav_final_edit(session_id)

        if result.outcome=="crash":
            final_embed=self.mav_embed(interaction.user,stake,crash_at,crashed=True)
        else:
            try:cashout=float(result.outcome.removeprefix("cashout_").removesuffix("x"))
            except ValueError:cashout=clicked_mult
            final_embed=self.mav_embed(interaction.user,stake,cashout,cashout=cashout,payout=result.reward)

        ok=await self._final_mav_edit(interaction.message,final_embed)
        if not ok:
            with contextlib.suppress(discord.HTTPException):
                await interaction.followup.send(embed=final_embed,ephemeral=True)
        self._cleanup_mav_runtime(session_id)

    async def _poker_lobby_embed(self,table_id:str)->discord.Embed:
        table,users=await self.service.poker_lobby(table_id); names=[]
        guild=self.bot.get_guild(int(table["guild_id"]))
        for uid in users:
            member=guild.get_member(uid) if guild else None; names.append(f"• **{member.display_name if member else uid}**")
        embed=base_embed(f"♠️ Texas Hold'em • {table_id}",f"Buy-in: **{money(int(table['buy_in']))}**\nJátékosok **{len(users)}/6**\n\n"+"\n".join(names),BRAND); embed.set_footer(text="2–6 játékos • owner indít • egy teljes Hold'em hand")
        return embed

    async def poker_create(self,interaction:discord.Interaction,buy_in:int)->None:
        if interaction.guild_id is None or interaction.channel is None:return
        try:table_id=await self.service.create_poker_table(interaction.guild_id,interaction.channel_id,interaction.user.id,buy_in)
        except ValueError as exc:return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await interaction.response.send_message(embed=await self._poker_lobby_embed(table_id),view=PokerLobbyView(self,table_id)); msg=await interaction.original_response(); await self.service.set_poker_message(table_id,msg.id)

    async def poker_join(self,interaction:discord.Interaction,table_id:str)->None:
        try:await self.service.add_poker_player(table_id,interaction.user.id)
        except ValueError as exc:return await interaction.response.send_message(str(exc),ephemeral=True)
        await interaction.response.edit_message(embed=await self._poker_lobby_embed(table_id),view=PokerLobbyView(self,table_id))

    async def poker_leave(self,interaction:discord.Interaction,table_id:str)->None:
        table,users=await self.service.poker_lobby(table_id)
        if interaction.user.id==int(table["owner_id"]):return await interaction.response.send_message("❌ Az owner nem léphet ki; törölje a lobby-t.",ephemeral=True)
        await self.service.remove_poker_player(table_id,interaction.user.id); await interaction.response.edit_message(embed=await self._poker_lobby_embed(table_id),view=PokerLobbyView(self,table_id))

    async def poker_cancel_lobby(self,interaction:discord.Interaction,table_id:str)->None:
        table,_=await self.service.poker_lobby(table_id)
        if interaction.user.id!=int(table["owner_id"]):return await interaction.response.send_message("❌ Csak az owner törölheti.",ephemeral=True)
        import aiosqlite
        async with aiosqlite.connect(self.service.db.path) as conn:await conn.execute("UPDATE poker_tables SET status='cancelled',finished_at=?,updated_at=? WHERE table_id=? AND status='lobby'",(datetime_now(),datetime_now(),table_id));await conn.commit()
        await interaction.response.edit_message(embed=base_embed("♠️ Poker lobby törölve","Nem történt pénzlevonás.",DANGER),view=None)

    async def poker_start(self,interaction:discord.Interaction,table_id:str)->None:
        table,users=await self.service.poker_lobby(table_id)
        if interaction.user.id!=int(table["owner_id"]):return await interaction.response.send_message("❌ Csak az owner indíthatja.",ephemeral=True)
        await interaction.response.defer()
        try:table,users=await self.service.reserve_poker_buyins(table_id)
        except ValueError as exc:return await interaction.followup.send(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        players=[]
        for uid in users:
            member=interaction.guild.get_member(uid); players.append(PokerPlayer(uid,member.display_name if member else str(uid),int(table["buy_in"])))
        state=PokerTableState(table_id,interaction.guild_id,int(table["owner_id"]),int(table["buy_in"]),players); state.start_hand(); runtime=PokerRuntime(state,interaction.message);self.poker_tables[table_id]=runtime
        await self._send_hole_cards(interaction.guild,state); await interaction.message.edit(embed=self._poker_game_embed(state),view=PokerActionView(self,table_id)); self._schedule_poker_timeout(table_id)

    def _poker_game_embed(self,state:PokerTableState)->discord.Embed:
        board=" ".join(state.board) if state.board else "— — — — —"; current=state.players[state.current_index] if not state.finished else None
        lines=[]
        for i,p in enumerate(state.players):
            flag="❌ FOLD" if p.folded else "🔥 ALL-IN" if p.all_in else "▶️" if current is p else "•"
            lines.append(f"{flag} **{p.name}** • stack {money(p.stack)} • bent {money(p.total_bet)}")
        embed=base_embed(f"♠️ Texas Hold'em • {state.street.upper()}",f"Board: **{board}**\nPot: **{money(state.pot())}**\nAktuális tét: **{money(state.current_bet)}**\n\n"+"\n".join(lines),BRAND)
        if state.last_action:embed.add_field(name="Legutóbbi akció",value=state.last_action,inline=False)
        if current:embed.set_footer(text=f"Következik: {current.name} • {cfg.POKER_TURN_SECONDS}s döntési idő")
        return embed

    async def _send_hole_cards(self,guild:discord.Guild,state:PokerTableState)->None:
        for p in state.players:
            member=guild.get_member(p.user_id)
            if member:
                with contextlib.suppress(discord.Forbidden,discord.HTTPException):await member.send(embed=base_embed(f"♠️ Poker • {state.table_id}",f"A lapjaid: **{' '.join(p.cards)}**",GOLD))

    async def poker_hand(self,interaction:discord.Interaction,table_id:str)->None:
        rt=self.poker_tables.get(table_id)
        if not rt:return await interaction.response.send_message("❌ Ez az asztal már nem aktív.",ephemeral=True)
        p=next((x for x in rt.state.players if x.user_id==interaction.user.id),None)
        if not p:return await interaction.response.send_message("❌ Nem vagy ennél az asztalnál.",ephemeral=True)
        await interaction.response.send_message(f"🃏 Lapjaid: **{' '.join(p.cards)}**",ephemeral=True)

    async def poker_action(self,interaction:discord.Interaction,table_id:str,action:str)->None:
        rt=self.poker_tables.get(table_id)
        if not rt:return await interaction.response.send_message("❌ Az asztal már lezárult.",ephemeral=True)
        state=rt.state; current=state.players[state.current_index]
        if current.user_id!=interaction.user.id:return await interaction.response.send_message(f"⏳ Most **{current.name}** következik.",ephemeral=True)
        await interaction.response.defer()
        try:
            idx=state.current_index
            if action=="fold":state.fold(idx)
            elif action=="call":state.check_call(idx)
            elif action=="raise":state.raise_to(idx,max(state.current_bet*2,state.current_bet+state.bb))
            else:state.all_in(idx)
            await self._after_poker_action(table_id)
        except Exception as exc:return await interaction.followup.send(f"❌ Poker hiba: {exc}",ephemeral=True)

    async def _after_poker_action(self,table_id:str)->None:
        rt=self.poker_tables.get(table_id)
        if not rt:return
        state=rt.state
        if state.finished:
            await self._finish_poker(table_id);return
        await rt.message.edit(embed=self._poker_game_embed(state),view=PokerActionView(self,table_id)); self._schedule_poker_timeout(table_id)

    def _schedule_poker_timeout(self,table_id:str)->None:
        rt=self.poker_tables.get(table_id)
        if not rt:return
        if rt.timeout_task:rt.timeout_task.cancel()
        nonce=rt.state.action_nonce;rt.timeout_task=asyncio.create_task(self._poker_timeout(table_id,nonce))

    async def _poker_timeout(self,table_id:str,nonce:int)->None:
        try:
            await asyncio.sleep(cfg.POKER_TURN_SECONDS);rt=self.poker_tables.get(table_id)
            if not rt or rt.state.finished or rt.state.action_nonce!=nonce:return
            idx=rt.state.current_index
            if rt.state.can_check(idx):rt.state.check_call(idx);rt.state.last_action=f"{rt.state.players[idx].name}: timeout → check"
            else:rt.state.fold(idx);rt.state.last_action=f"{rt.state.players[idx].name}: timeout → fold"
            await self._after_poker_action(table_id)
        except asyncio.CancelledError:pass

    async def _finish_poker(self,table_id:str)->None:
        rt=self.poker_tables.get(table_id)
        if not rt:return
        state=rt.state
        if rt.timeout_task:rt.timeout_task.cancel()
        pot_wins=state.showdown_payouts(); payouts={}
        for i,p in enumerate(state.players):payouts[p.user_id]=p.stack+pot_wins.get(i,0)
        await self.service.settle_poker(table_id,payouts)
        live=[i for i,p in enumerate(state.players) if not p.folded]
        lines=[]
        for i,p in enumerate(state.players):
            hand="Fold" if p.folded else hand_name(best_hand(p.cards+state.board)) if len(state.board)>=5 else "Nyertes fold miatt"
            lines.append(f"**{p.name}** • {' '.join(p.cards)} • {hand} • payout **{money(payouts[p.user_id])}**")
        embed=base_embed("♠️ Texas Hold'em • Showdown",f"Board: **{' '.join(state.board) or '—'}**\n\n"+"\n".join(lines),GOLD);await rt.message.edit(embed=embed,view=None);self.poker_tables.pop(table_id,None)

    @app_commands.command(name="shoprob",description="Single-player interaktív Boltrablás.")
    async def shoprob(self,interaction:discord.Interaction)->None:await self.start_robbery_ui(interaction,"shoprob")
    @app_commands.command(name="bankrob",description="Single-player interaktív Bankrablás.")
    async def bankrob(self,interaction:discord.Interaction)->None:await self.start_robbery_ui(interaction,"bankrob")
    @app_commands.command(name="mav",description="Single-player MÁV Crash.")
    async def mav(self,interaction:discord.Interaction,tet:str)->None:
        wallet,_bank=await self.service.db.get_balance(interaction.guild_id,interaction.user.id)
        try:stake=parse_amount(tet,max(0,wallet))
        except ValueError as exc:return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await self.start_mav_ui(interaction,stake)
    @app_commands.command(name="poker",description="2–6 fős Texas Hold'em lobby létrehozása.")
    async def poker(self,interaction:discord.Interaction,buyin:str)->None:
        wallet,_bank=await self.service.db.get_balance(interaction.guild_id,interaction.user.id)
        try:amount=parse_amount(buyin,max(0,wallet))
        except ValueError as exc:return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await self.poker_create(interaction,amount)
    @app_commands.command(name="pokerhand",description="Megmutatja privátban az aktív poker lapjaidat.")
    async def pokerhand(self,interaction:discord.Interaction)->None:
        for table_id,rt in self.poker_tables.items():
            if any(p.user_id==interaction.user.id for p in rt.state.players):return await self.poker_hand(interaction,table_id)
        await interaction.response.send_message("❌ Nincs aktív poker asztalod.",ephemeral=True)
    @app_commands.command(name="settings",description="Live World szerverbeállítások.")
    @app_commands.default_permissions(manage_guild=True)
    async def settings_cmd(self,interaction:discord.Interaction)->None:
        if not isinstance(interaction.user,discord.Member) or not interaction.user.guild_permissions.manage_guild:return await interaction.response.send_message("❌ Manage Server szükséges.",ephemeral=True)
        await interaction.response.send_message("⚙️ Betöltés…",ephemeral=True);await self.show_settings(interaction,interaction.user.id)

    @commands.command(name="boltrablas",aliases=["boltrablás","shoprob"])
    @commands.guild_only()
    async def shoprob_prefix(self,ctx:commands.Context)->None:
        class Fake:pass
        # Prefix UI uses a tiny interaction adapter only for the shared start logic would be brittle;
        # keep prefix straightforward instead.
        try:session=await self.service.start_robbery(ctx.guild.id,ctx.author.id,"shoprob")
        except ValueError as exc:return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        self.robbery_locks[str(session["session_id"])]=asyncio.Lock()
        await ctx.send(embed=self.robbery_embed(ctx.author,session),view=RobberyView(self,ctx.author.id,session))
    @commands.command(name="bankrablas",aliases=["bankrablás","bankrob"])
    @commands.guild_only()
    async def bankrob_prefix(self,ctx:commands.Context)->None:
        try:session=await self.service.start_robbery(ctx.guild.id,ctx.author.id,"bankrob")
        except ValueError as exc:return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        self.robbery_locks[str(session["session_id"])]=asyncio.Lock()
        await ctx.send(embed=self.robbery_embed(ctx.author,session),view=RobberyView(self,ctx.author.id,session))
    @commands.command(name="mav",aliases=["máv","crash"])
    @commands.guild_only()
    async def mav_prefix(self,ctx:commands.Context,tet:str)->None:
        wallet,_bank=await self.service.db.get_balance(ctx.guild.id,ctx.author.id)
        try:stake=parse_amount(tet,max(0,wallet));session=await self.service.start_mav(ctx.guild.id,ctx.author.id,stake)
        except ValueError as exc:return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        sid=str(session["session_id"]);view=MavCrashView(self,ctx.author.id,sid)
        msg=await ctx.send(embed=self.mav_embed(ctx.author,stake,1.0),view=view)
        await self._register_mav(msg,ctx.author,session,stake,view)

    @commands.command(name="poker")
    @commands.guild_only()
    async def poker_prefix(self,ctx:commands.Context,buyin:str)->None:
        wallet,_bank=await self.service.db.get_balance(ctx.guild.id,ctx.author.id)
        try:
            amount=parse_amount(buyin,max(0,wallet))
            table_id=await self.service.create_poker_table(ctx.guild.id,ctx.channel.id,ctx.author.id,amount)
        except ValueError as exc:
            return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        msg=await ctx.send(embed=await self._poker_lobby_embed(table_id),view=PokerLobbyView(self,table_id))
        await self.service.set_poker_message(table_id,msg.id)

    @commands.command(name="pokerhand",aliases=["lapjaim","kezem"])
    @commands.guild_only()
    async def pokerhand_prefix(self,ctx:commands.Context)->None:
        for _table_id,rt in self.poker_tables.items():
            player=next((p for p in rt.state.players if p.user_id==ctx.author.id),None)
            if player is not None:
                try:
                    await ctx.author.send(embed=base_embed("♠️ Privát lapjaid",f"**{' '.join(player.cards)}**",BRAND))
                    with contextlib.suppress(discord.HTTPException):
                        await ctx.message.add_reaction("✅")
                except discord.Forbidden:
                    await ctx.send("❌ Nem tudok DM-et küldeni neked.",delete_after=8)
                return
        await ctx.send("❌ Nincs aktív poker asztalod.",delete_after=8)

def datetime_now()->str:
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).isoformat()
