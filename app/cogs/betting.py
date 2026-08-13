from __future__ import annotations

import asyncio
import contextlib
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from app import betting_config as cfg
from app.amounts import parse_amount
from app.cogs.settings import OwnedView, PagedGuildChannelSelect
from app.services.betting import BettingService, HorseSettlement, TicketSettlement, parse_dt
from app.ui import BRAND, DANGER, GOLD, SUCCESS, base_embed, error_embed, money


def _ts(value: str, style: str = "R") -> str:
    try:
        return f"<t:{int(parse_dt(value).timestamp())}:{style}>"
    except Exception:
        return "—"


def _market_label(key: str) -> str:
    return cfg.MARKET_GROUP_LABELS.get(key, key)


def _signed_money(value: int) -> str:
    return f"+{money(value)}" if value > 0 else f"-{money(abs(value))}" if value < 0 else money(0)


def _results_now() -> datetime:
    """Hungarian day boundary for daily result forum posts, UTC fallback if tzdata is unavailable."""
    try:
        return datetime.now(ZoneInfo("Europe/Budapest"))
    except ZoneInfoNotFoundError:
        return datetime.now(timezone.utc)


class PlayerView(discord.ui.View):
    def __init__(self, cog: "BettingCog", owner_id: int, *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout); self.cog=cog; self.owner_id=owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ez nem a te fogadási felületed.", ephemeral=True); return False
        return True


class BettingPanelView(discord.ui.View):
    def __init__(self, cog: "BettingCog") -> None:
        super().__init__(timeout=None); self.cog=cog

    @discord.ui.button(label="Napi Tippmix", emoji="⚽", style=discord.ButtonStyle.primary, custom_id="yoru:betting:tippmix")
    async def tippmix(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_daily(interaction, edit=False)

    @discord.ui.button(label="Szelvényem", emoji="🎟️", style=discord.ButtonStyle.success, custom_id="yoru:betting:slip")
    async def slip(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_slip(interaction, edit=False)

    @discord.ui.button(label="Fogadásaim", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="yoru:betting:history")
    async def history(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_history(interaction, edit=False)

    @discord.ui.button(label="Kincsem", emoji="🐎", style=discord.ButtonStyle.primary, custom_id="yoru:betting:horse")
    async def horse(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_horse(interaction, edit=False)

    @discord.ui.button(label="Eredmények", emoji="🏆", style=discord.ButtonStyle.secondary, custom_id="yoru:betting:results")
    async def results(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_results(interaction, edit=False)

    @discord.ui.button(label="Statisztikák", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="yoru:betting:stats")
    async def stats(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_stats(interaction, edit=False)


class BettingHomeView(PlayerView):
    @discord.ui.button(label="Tippmix", emoji="⚽", style=discord.ButtonStyle.primary, row=0)
    async def tippmix(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_daily(interaction, edit=True)
    @discord.ui.button(label="Szelvény", emoji="🎟️", style=discord.ButtonStyle.success, row=0)
    async def slip(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_slip(interaction, edit=True)
    @discord.ui.button(label="Kincsem", emoji="🐎", style=discord.ButtonStyle.primary, row=0)
    async def horse(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_horse(interaction, edit=True)
    @discord.ui.button(label="History", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def history(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_history(interaction, edit=True)
    @discord.ui.button(label="Eredmények", emoji="🏆", style=discord.ButtonStyle.secondary, row=1)
    async def results(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_results(interaction, edit=True)
    @discord.ui.button(label="Statisztika", emoji="📊", style=discord.ButtonStyle.secondary, row=1)
    async def stats(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_stats(interaction, edit=True)


class LeagueSelect(discord.ui.Select):
    def __init__(self, view: "LeagueView", leagues: list[tuple[str,int]]) -> None:
        self.parent_view=view
        opts=[discord.SelectOption(label=name[:100],value=name,description=f"{count} mai meccs") for name,count in leagues[:25]]
        super().__init__(placeholder="Válassz ligát…",options=opts,min_values=1,max_values=1,row=0)
    async def callback(self, interaction: discord.Interaction) -> None: await self.parent_view.cog.show_matches(interaction,self.values[0])


class LeagueView(PlayerView):
    def __init__(self,cog:"BettingCog",owner_id:int,leagues:list[tuple[str,int]])->None:
        super().__init__(cog,owner_id); self.add_item(LeagueSelect(self,leagues))
    @discord.ui.button(label="Szelvényem",emoji="🎟️",style=discord.ButtonStyle.success,row=1)
    async def slip(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_slip(interaction,edit=True)
    @discord.ui.button(label="Központ",emoji="⬅️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_home(interaction,edit=True)


class MatchSelect(discord.ui.Select):
    def __init__(self,view:"MatchListView",matches:list[dict[str,Any]])->None:
        self.parent_view=view
        opts=[]
        for m in matches[:25]:
            status="🔴 VÉGE" if m["status"]=="settled" else "🟢"
            desc=f"{status} • {_ts(m['kickoff_at'])}"
            opts.append(discord.SelectOption(label=f"{m['home']} – {m['away']}"[:100],value=str(m["match_id"]),description=desc[:100]))
        super().__init__(placeholder="Válassz meccset…",options=opts,min_values=1,max_values=1,row=0)
    async def callback(self,interaction:discord.Interaction)->None:
        await self.parent_view.cog.show_match(interaction,int(self.values[0]),self.parent_view.league)


class MatchListView(PlayerView):
    def __init__(self,cog:"BettingCog",owner_id:int,league:str,matches:list[dict[str,Any]])->None:
        super().__init__(cog,owner_id); self.league=league; self.add_item(MatchSelect(self,matches))
    @discord.ui.button(label="Ligák",emoji="⬅️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_daily(interaction,edit=True)
    @discord.ui.button(label="Szelvény",emoji="🎟️",style=discord.ButtonStyle.success,row=1)
    async def slip(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_slip(interaction,edit=True)


class MarketGroupSelect(discord.ui.Select):
    def __init__(self,view:"MarketView",groups:list[str])->None:
        self.parent_view=view
        opts=[discord.SelectOption(label=_market_label(g)[:100],value=g,emoji={"1x2":"⚽","double":"🛡️","goals":"🥅","btts":"🔥","dnb":"↔️","half":"⏱️","handicap":"📐","score":"🎯"}.get(g)) for g in groups]
        super().__init__(placeholder="Fogadási piac…",options=opts,min_values=1,max_values=1,row=0)
    async def callback(self,interaction:discord.Interaction)->None: await self.parent_view.cog.show_market_options(interaction,self.parent_view.match_id,self.values[0],self.parent_view.league)


class MarketView(PlayerView):
    def __init__(self,cog:"BettingCog",owner_id:int,match_id:int,league:str,groups:list[str])->None:
        super().__init__(cog,owner_id); self.match_id=match_id; self.league=league; self.add_item(MarketGroupSelect(self,groups))
    @discord.ui.button(label="Meccsek",emoji="⬅️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_matches(interaction,self.league)
    @discord.ui.button(label="Szelvény",emoji="🎟️",style=discord.ButtonStyle.success,row=1)
    async def slip(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_slip(interaction,edit=True)


class MarketOptionSelect(discord.ui.Select):
    def __init__(self,view:"MarketOptionView",options:list[dict[str,Any]])->None:
        self.parent_view=view
        opts=[discord.SelectOption(label=str(x["label"])[:100],value=str(x["selection_key"]),description=f"Odds: {float(x['odds']):.2f}x") for x in options[:25]]
        super().__init__(placeholder="Tipp hozzáadása a szelvényhez…",options=opts,min_values=1,max_values=1,row=0)
    async def callback(self,interaction:discord.Interaction)->None:
        await self.parent_view.cog.add_leg(interaction,self.parent_view.match_id,self.parent_view.market_key,self.values[0],self.parent_view.league)


class MarketOptionView(PlayerView):
    def __init__(self,cog:"BettingCog",owner_id:int,match_id:int,market_key:str,league:str,options:list[dict[str,Any]])->None:
        super().__init__(cog,owner_id); self.match_id=match_id; self.market_key=market_key; self.league=league; self.add_item(MarketOptionSelect(self,options))
    @discord.ui.button(label="Piacok",emoji="⬅️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_match(interaction,self.match_id,self.league)
    @discord.ui.button(label="Szelvény",emoji="🎟️",style=discord.ButtonStyle.success,row=1)
    async def slip(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_slip(interaction,edit=True)


class RemoveLegSelect(discord.ui.Select):
    def __init__(self,view:"SlipView",legs:list[dict[str,Any]])->None:
        self.parent_view=view
        opts=[discord.SelectOption(label=f"{x['home']} – {x['away']}"[:100],value=str(x["match_id"]),description=f"{x['label']} @{float(x['odds']):.2f}"[:100]) for x in legs[:25]]
        super().__init__(placeholder="Tipp törlése…",options=opts,min_values=1,max_values=1,row=0)
    async def callback(self,interaction:discord.Interaction)->None:
        await self.parent_view.cog.service.remove_draft_leg(interaction.guild_id,interaction.user.id,int(self.values[0])); await self.parent_view.cog.show_slip(interaction,edit=True)


class TicketStakeModal(discord.ui.Modal):
    def __init__(self,cog:"BettingCog",mode:str,nlegs:int)->None:
        super().__init__(title={"single":"Single fogadás","combo":"Kötés / Kombi","system":"Rendszerfogadás"}[mode],timeout=180)
        self.cog=cog; self.mode=mode; self.nlegs=nlegs
        self.stake=discord.ui.TextInput(label="Tét" if mode=="combo" else "Tét / egység",placeholder="pl. 100k, 5m, 1b vagy all",max_length=30)
        self.add_item(self.stake)
        self.system_k=None
        if mode=="system":
            self.system_k=discord.ui.TextInput(label=f"Kötés mérete (2–{max(2,nlegs-1)})",placeholder=str(max(2,nlegs-1)),max_length=2)
            self.add_item(self.system_k)
    async def on_submit(self,interaction:discord.Interaction)->None:
        if interaction.guild_id is None:return
        wallet,_bank=await self.cog.service.db.get_balance(interaction.guild_id,interaction.user.id)
        try:
            available=max(0,wallet)
            k=int(str(self.system_k.value)) if self.system_k else None
            raw=str(self.stake.value).strip().lower()
            # "all" mindig a TELJES fogadásra értendő: Single esetén szétosztjuk
            # a tippek között, rendszer esetén a kombinációk között.
            if raw in {"all","max","minden","összes","osszes"}:
                units = self.nlegs if self.mode=="single" else (math.comb(self.nlegs,k) if self.mode=="system" and k is not None and 0 <= k <= self.nlegs else 1)
                stake=max(0,available//max(1,units))
            else:
                stake=parse_amount(raw,available)
            result=await self.cog.service.place_ticket(interaction.guild_id,interaction.user.id,stake_unit=stake,bet_type=self.mode,system_k=k)
        except ValueError as exc:return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        embed=base_embed("✅ Szelvény feladva",f"Szelvény **#{result['ticket_id']}** rögzítve.",SUCCESS)
        embed.add_field(name="Típus",value={"single":"Single","combo":"Kötés","system":f"Rendszer {result['system_k']}/{len(result['legs'])}"}[result['bet_type']],inline=True)
        embed.add_field(name="Összes tét",value=money(result["total_stake"]),inline=True); embed.add_field(name="Max. nyeremény",value=money(result["potential_payout"]),inline=True)
        embed.set_footer(text="Yoru privát üzenetet küld a lezáráskor, ha a szerveren engedélyezve van.")
        await interaction.response.send_message(embed=embed,ephemeral=True)


class SlipView(PlayerView):
    def __init__(self,cog:"BettingCog",owner_id:int,legs:list[dict[str,Any]])->None:
        super().__init__(cog,owner_id); self.legs=legs
        if legs:self.add_item(RemoveLegSelect(self,legs))
    @discord.ui.button(label="Single",emoji="1️⃣",style=discord.ButtonStyle.secondary,row=1)
    async def single(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:
        if not self.legs:return await interaction.response.send_message("❌ Üres a szelvény.",ephemeral=True)
        await interaction.response.send_modal(TicketStakeModal(self.cog,"single",len(self.legs)))
    @discord.ui.button(label="Kötés",emoji="🔗",style=discord.ButtonStyle.success,row=1)
    async def combo(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:
        if not self.legs:return await interaction.response.send_message("❌ Üres a szelvény.",ephemeral=True)
        await interaction.response.send_modal(TicketStakeModal(self.cog,"combo",len(self.legs)))
    @discord.ui.button(label="Rendszer",emoji="🧩",style=discord.ButtonStyle.primary,row=1)
    async def system(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:
        if len(self.legs)<3:return await interaction.response.send_message("❌ Rendszerfogadáshoz legalább 3 tipp kell.",ephemeral=True)
        await interaction.response.send_modal(TicketStakeModal(self.cog,"system",len(self.legs)))
    @discord.ui.button(label="Ürítés",emoji="🗑️",style=discord.ButtonStyle.danger,row=2)
    async def clear(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:
        await self.cog.service.clear_draft(interaction.guild_id,interaction.user.id); await self.cog.show_slip(interaction,edit=True)
    @discord.ui.button(label="Meccsek",emoji="⚽",style=discord.ButtonStyle.secondary,row=2)
    async def games(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_daily(interaction,edit=True)
    @discord.ui.button(label="Központ",emoji="⬅️",style=discord.ButtonStyle.secondary,row=2)
    async def back(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_home(interaction,edit=True)


class HorsePickSelect(discord.ui.Select):
    def __init__(self,view:"HorseView",horses:list[dict[str,Any]])->None:
        self.parent_view=view; opts=[]
        labels={"win":"Győztes","top2":"Top 2","top3":"Top 3"}
        for h in horses:
            for market in ("win","top2","top3"):
                opts.append(discord.SelectOption(label=f"{h['name']} • {labels[market]}"[:100],value=f"{h['index']}:{market}",description=f"{float(h[market]):.2f}x"))
        super().__init__(placeholder="Ló + piac kiválasztása…",options=opts[:25],min_values=1,max_values=1,row=0)
    async def callback(self,interaction:discord.Interaction)->None:
        idx,market=self.values[0].split(":",1); await interaction.response.send_modal(HorseStakeModal(self.parent_view.cog,self.parent_view.race,int(idx),market))


class HorseStakeModal(discord.ui.Modal,title="🐎 Kincsem fogadás"):
    stake=discord.ui.TextInput(label="Tét",placeholder="pl. 100k, 5m, 1b vagy all",max_length=30)
    def __init__(self,cog:"BettingCog",race:dict[str,Any],horse_index:int,market:str)->None:
        super().__init__(); self.cog=cog; self.race=race; self.horse_index=horse_index; self.market=market
    async def on_submit(self,interaction:discord.Interaction)->None:
        wallet,_bank=await self.cog.service.db.get_balance(interaction.guild_id,interaction.user.id)
        try:
            amount=parse_amount(str(self.stake.value),max(0,wallet)); result=await self.cog.service.place_horse_bet(interaction.guild_id,interaction.user.id,int(self.race["race_id"]),self.horse_index,self.market,amount)
        except ValueError as exc:return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        labels={"win":"Győztes","top2":"Top 2","top3":"Top 3"}; embed=base_embed("✅ Kincsem fogadás rögzítve",f"**{result['horse']['name']}** • {labels[self.market]}",SUCCESS)
        embed.add_field(name="Odds",value=f"{result['odds']:.2f}x",inline=True); embed.add_field(name="Tét",value=money(result["stake"]),inline=True); embed.add_field(name="Lehetséges",value=money(round(result["stake"]*result["odds"])),inline=True)
        await interaction.response.send_message(embed=embed,ephemeral=True)


class HorseView(PlayerView):
    def __init__(self,cog:"BettingCog",owner_id:int,race:dict[str,Any])->None:
        super().__init__(cog,owner_id); self.race=race; self.add_item(HorsePickSelect(self,race["horses"]))
    @discord.ui.button(label="Fogadásaim",emoji="📋",style=discord.ButtonStyle.secondary,row=1)
    async def history(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_history(interaction,edit=True)
    @discord.ui.button(label="Központ",emoji="⬅️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self.cog.show_home(interaction,edit=True)


class BettingSettingsModal(discord.ui.Modal,title="Fogadás • Balance"):
    min_stake=discord.ui.TextInput(label="Minimum tét",placeholder="50k",max_length=30)
    max_legs=discord.ui.TextInput(label="Max tippek / szelvény",placeholder="12",max_length=3)
    max_payout=discord.ui.TextInput(label="Max payout",placeholder="50b",max_length=30)
    daily_matches=discord.ui.TextInput(label="Napi virtuális meccsek",placeholder="32",max_length=3)
    def __init__(self,view:"BettingSettingsView")->None: super().__init__(); self.parent_view=view
    async def on_submit(self,interaction:discord.Interaction)->None:
        try:
            await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.BETTING_MIN_STAKE_KEY,parse_amount(str(self.min_stake.value)))
            await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.BETTING_MAX_LEGS_KEY,max(1,min(20,int(str(self.max_legs.value)))))
            await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.BETTING_MAX_PAYOUT_KEY,parse_amount(str(self.max_payout.value)))
            await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.BETTING_DAILY_MATCHES_KEY,max(cfg.MIN_DAILY_MATCHES,min(cfg.MAX_DAILY_MATCHES,int(str(self.daily_matches.value)))))
        except ValueError as exc:return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        await self.parent_view.cog.show_settings(interaction,self.parent_view.owner_id,existing=self.parent_view)


class HorseTimingModal(discord.ui.Modal,title="Kincsem • Időzítés"):
    interval=discord.ui.TextInput(label="Futam intervallum (óra)",placeholder="4",max_length=2)
    close=discord.ui.TextInput(label="Fogadás zárása futam előtt (perc)",placeholder="2",max_length=2)
    def __init__(self,view:"BettingSettingsView")->None: super().__init__(); self.parent_view=view
    async def on_submit(self,interaction:discord.Interaction)->None:
        try:
            hours=max(1,min(24,int(str(self.interval.value)))); close=max(1,min(30,int(str(self.close.value))))
        except ValueError:return await interaction.response.send_message("❌ Egész számokat adj meg.",ephemeral=True)
        await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.BETTING_HORSE_INTERVAL_KEY,hours); await self.parent_view.cog.service.settings.set_int(interaction.guild_id,cfg.BETTING_HORSE_CLOSE_MINUTES_KEY,close)
        await self.parent_view.cog.show_settings(interaction,self.parent_view.owner_id,existing=self.parent_view)


class BettingSettingsView(OwnedView):
    def __init__(self,cog:"BettingCog",owner_id:int,guild:discord.Guild,states:dict[str,bool],*,channel_page:int=0,forum_page:int=0,log_page:int=0)->None:
        super().__init__(cog,owner_id); self.guild=guild; self.states=states; self.channel_page=channel_page; self.forum_page=forum_page; self.log_page=log_page; self._sync()
        self.add_item(PagedGuildChannelSelect(self,guild,page_attr="channel_page",selection_key="channel",placeholder="Fogadási panel csatorna…",channel_types=(discord.ChannelType.text,discord.ChannelType.news),row=2))
        self.add_item(PagedGuildChannelSelect(self,guild,page_attr="forum_page",selection_key="forum",placeholder="Napi eredmény Forum…",channel_types=(discord.ChannelType.forum,),row=3))
        self.add_item(PagedGuildChannelSelect(self,guild,page_attr="log_page",selection_key="log",placeholder="Fogadási log csatorna…",channel_types=(discord.ChannelType.text,discord.ChannelType.news),row=4))
    def _sync(self)->None:
        for button,key,label in ((self.enabled,"enabled","Fogadás"),(self.tippmix,"tippmix","Tippmix"),(self.horse,"horse","Kincsem"),(self.dm,"dm","DM")):
            button.label=f"{label}: {'ON' if self.states[key] else 'OFF'}"; button.style=discord.ButtonStyle.success if self.states[key] else discord.ButtonStyle.secondary
    async def handle_channel_selection(self,interaction:discord.Interaction,selection_key:str,channels:list[discord.abc.GuildChannel])->None:
        if channels:
            key = {
                "channel": cfg.BETTING_CHANNEL_KEY,
                "forum": cfg.BETTING_RESULTS_FORUM_KEY,
                "log": cfg.BETTING_LOG_CHANNEL_KEY,
            }.get(selection_key)
            if key is not None:
                await self.cog.service.settings.set_int(interaction.guild_id,key,channels[0].id)
        await self.cog.show_settings(interaction,self.owner_id,existing=self)
    async def refresh(self,interaction:discord.Interaction)->None: await self.cog.show_settings(interaction,self.owner_id,existing=self)
    async def _toggle(self,interaction:discord.Interaction,key:str,setting:str)->None:
        await self.cog.service.settings.set_bool(interaction.guild_id,setting,not self.states[key]); await self.refresh(interaction)
    @discord.ui.button(label="Fogadás",emoji="🏟️",style=discord.ButtonStyle.success,row=0)
    async def enabled(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self._toggle(interaction,"enabled",cfg.BETTING_ENABLED_KEY)
    @discord.ui.button(label="Tippmix",emoji="⚽",style=discord.ButtonStyle.secondary,row=0)
    async def tippmix(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self._toggle(interaction,"tippmix",cfg.BETTING_TIPPMIX_ENABLED_KEY)
    @discord.ui.button(label="Kincsem",emoji="🐎",style=discord.ButtonStyle.secondary,row=0)
    async def horse(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self._toggle(interaction,"horse",cfg.BETTING_HORSE_ENABLED_KEY)
    @discord.ui.button(label="DM",emoji="📨",style=discord.ButtonStyle.secondary,row=0)
    async def dm(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await self._toggle(interaction,"dm",cfg.BETTING_DM_ENABLED_KEY)
    @discord.ui.button(label="Balance",emoji="🎚️",style=discord.ButtonStyle.primary,row=1)
    async def balance(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await interaction.response.send_modal(BettingSettingsModal(self))
    @discord.ui.button(label="Kincsem timing",emoji="⏱️",style=discord.ButtonStyle.primary,row=1)
    async def timing(self,interaction:discord.Interaction,_button:discord.ui.Button)->None: await interaction.response.send_modal(HorseTimingModal(self))
    @discord.ui.button(label="Vissza",emoji="⬅️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,interaction:discord.Interaction,_button:discord.ui.Button)->None:
        settings=self.cog.bot.get_cog("SettingsCog"); await settings.show_home(interaction,self.owner_id) if settings else interaction.response.send_message("❌ Settings nem elérhető.",ephemeral=True)


class BettingCog(commands.GroupCog,group_name="betting",group_description="Yoru Fogadási Központ • Tippmix és Kincsem."):
    def __init__(self,bot:commands.Bot,service:BettingService)->None:
        self.bot=bot; self.service=service; self.worker:asyncio.Task|None=None; super().__init__()

    async def cog_load(self)->None:
        self.bot.add_view(BettingPanelView(self)); self.worker=asyncio.create_task(self._worker_loop())

    async def cog_unload(self)->None:
        if self.worker:self.worker.cancel()

    async def _allowed(self,interaction:discord.Interaction)->bool:
        if interaction.guild_id is None:return False
        if not await self.service.enabled(interaction.guild_id):
            await interaction.response.send_message("❌ A Fogadási Központ ezen a szerveren ki van kapcsolva.",ephemeral=True); return False
        return True

    def panel_embed(self)->discord.Embed:
        embed=base_embed("🏟️ YORU FOGADÁSI KÖZPONT","Virtuális napi focimeccsek, interaktív szelvényépítés és 4 órás Kincsem futamok. A személyes kezelőfelület privát/ephemeral.",BRAND)
        embed.add_field(name="⚽ Napi Tippmix",value="Ligák → meccs → piac → szelvény. 24 óránként új virtuális kínálat.",inline=False)
        embed.add_field(name="🐎 Kincsem",value="Alapból 4 óránként egy új futam. Győztes / Top 2 / Top 3 piacok.",inline=False)
        embed.add_field(name="📨 Settlement",value="Az eredmény Historyban mindig megmarad; DM értesítés szerverenként kapcsolható.",inline=False)
        embed.set_footer(text="Yoru • A panel állandó és mindenki használhatja")
        return embed

    async def show_home(self,interaction:discord.Interaction,*,edit:bool)->None:
        embed=base_embed("🏟️ Fogadási Központ","Válassz a napi Tippmix, Kincsem és saját fogadásaid között.",BRAND); view=BettingHomeView(self,interaction.user.id)
        await (interaction.response.edit_message(embed=embed,view=view) if edit else interaction.response.send_message(embed=embed,view=view,ephemeral=True))

    async def show_daily(self,interaction:discord.Interaction,*,edit:bool)->None:
        if not await self._allowed(interaction):return
        if not await self.service.tippmix_enabled(interaction.guild_id):return await interaction.response.send_message("❌ A Tippmix ki van kapcsolva.",ephemeral=True)
        cycle=await self.service.ensure_daily_matches(interaction.guild_id); leagues=await self.service.leagues_for_cycle(interaction.guild_id,cycle); legs=await self.service.draft(interaction.guild_id,interaction.user.id)
        embed=base_embed("⚽ Napi Tippmix",f"**{sum(x[1] for x in leagues)}** virtuális meccs • **{len(legs)}** tipp a szelvényeden. Válassz ligát.",BRAND)
        embed.set_footer(text="A kínálat 24 órás napi ciklusban frissül • odds a szelvény feladásakor rögzül")
        view=LeagueView(self,interaction.user.id,leagues); await (interaction.response.edit_message(embed=embed,view=view) if edit else interaction.response.send_message(embed=embed,view=view,ephemeral=True))

    async def show_matches(self,interaction:discord.Interaction,league:str)->None:
        cycle=await self.service.ensure_daily_matches(interaction.guild_id); matches=await self.service.matches(interaction.guild_id,cycle,league=league)
        lines=[]
        for m in matches[:12]:
            marker="✅" if m["status"]=="settled" else "🟢"; result=f" **{m['home_score']}–{m['away_score']}**" if m["status"]=="settled" else f" {_ts(m['kickoff_at'])}"
            odds=m["odds"].get("1x2",[]); oddtxt=" • ".join(f"{x['selection_key']} {float(x['odds']):.2f}" for x in odds)
            lines.append(f"{marker} **{m['home']} – {m['away']}**{result}\n`{oddtxt}`")
        embed=base_embed(f"⚽ {league}","\n\n".join(lines) if lines else "Nincs mai meccs.",BRAND); await interaction.response.edit_message(embed=embed,view=MatchListView(self,interaction.user.id,league,matches))

    async def show_match(self,interaction:discord.Interaction,match_id:int,league:str)->None:
        match=await self.service.get_match(interaction.guild_id,match_id); status="LEZÁRVA" if match["status"]=="settled" else f"Kezdés {_ts(match['kickoff_at'])}"
        embed=base_embed(f"⚽ {match['home']} – {match['away']}",f"**{match['league']}** • {status}\nVálassz piacot az alábbi listából.",BRAND)
        if match["status"]=="settled":embed.add_field(name="Végeredmény",value=f"**{match['home_score']} – {match['away_score']}** • HT {match['ht_home']}–{match['ht_away']}",inline=False)
        groups=list(match["odds"].keys()); await interaction.response.edit_message(embed=embed,view=MarketView(self,interaction.user.id,match_id,league,groups))

    async def show_market_options(self,interaction:discord.Interaction,match_id:int,market_key:str,league:str)->None:
        match=await self.service.get_match(interaction.guild_id,match_id); options=match["odds"].get(market_key,[])
        lines="\n".join(f"**{x['label']}** — `{float(x['odds']):.2f}x`" for x in options[:15])
        if len(options)>15:lines+=f"\n… +{len(options)-15} opció a dropdownban"
        embed=base_embed(f"{_market_label(market_key)} • {match['home']} – {match['away']}",lines,BRAND); await interaction.response.edit_message(embed=embed,view=MarketOptionView(self,interaction.user.id,match_id,market_key,league,options))

    async def add_leg(self,interaction:discord.Interaction,match_id:int,market_key:str,selection_key:str,league:str)->None:
        try:leg=await self.service.add_draft_leg(interaction.guild_id,interaction.user.id,match_id,market_key,selection_key)
        except ValueError as exc:return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        match=leg["match"]; embed=base_embed("✅ Tipp a szelvényen",f"**{match['home']} – {match['away']}**\n{leg['label']} • **{leg['odds']:.2f}x**",SUCCESS); await interaction.response.edit_message(embed=embed,view=MarketView(self,interaction.user.id,match_id,league,list(match["odds"].keys())))

    async def show_slip(self,interaction:discord.Interaction,*,edit:bool)->None:
        if not await self._allowed(interaction):return
        legs=await self.service.draft(interaction.guild_id,interaction.user.id)
        lines=[]; product=1.0
        for x in legs:
            product*=float(x["odds"]); lines.append(f"**{x['home']} – {x['away']}**\n{x['label']} • `{float(x['odds']):.2f}x`")
        embed=base_embed("🎟️ Szelvényem","\n\n".join(lines) if lines else "A szelvényed üres. A napi meccseknél adj hozzá tippeket.",GOLD)
        if legs:embed.add_field(name="Kombi összodds",value=f"**{product:.2f}x**",inline=True); embed.add_field(name="Tippek",value=f"**{len(legs)}/{await self.service.max_legs(interaction.guild_id)}**",inline=True)
        embed.set_footer(text="Single: tét/tipp • Kötés: egy közös tét • Rendszer: tét/kombináció")
        view=SlipView(self,interaction.user.id,legs); await (interaction.response.edit_message(embed=embed,view=view) if edit else interaction.response.send_message(embed=embed,view=view,ephemeral=True))

    async def show_horse(self,interaction:discord.Interaction,*,edit:bool)->None:
        if not await self._allowed(interaction):return
        if not await self.service.horse_enabled(interaction.guild_id):return await interaction.response.send_message("❌ A Kincsem ki van kapcsolva.",ephemeral=True)
        race=await self.service.current_or_next_race(interaction.guild_id); lines=[]
        for i,h in enumerate(race["horses"],1):lines.append(f"**{i}. {h['name']}** • Győztes `{h['win']:.2f}x` • Top2 `{h['top2']:.2f}x` • Top3 `{h['top3']:.2f}x`")
        embed=base_embed("🐎 Kincsem • Következő futam",f"Futam: **{_ts(race['starts_at'],'F')}** ({_ts(race['starts_at'])})\nFogadás zár: **{_ts(race['closes_at'])}**\n\n"+"\n".join(lines),GOLD)
        view=HorseView(self,interaction.user.id,race); await (interaction.response.edit_message(embed=embed,view=view) if edit else interaction.response.send_message(embed=embed,view=view,ephemeral=True))

    async def show_history(self,interaction:discord.Interaction,*,edit:bool)->None:
        if not await self._allowed(interaction):return
        tickets=await self.service.ticket_history(interaction.guild_id,interaction.user.id,8); horses=await self.service.horse_history(interaction.guild_id,interaction.user.id,8); lines=[]
        icons={"won":"✅","lost":"❌","open":"⏳","partial":"🟡","push":"↩️"}
        for t in tickets[:6]: lines.append(f"{icons.get(t['status'],'•')} Tippmix **#{t['ticket_id']}** • {t['bet_type']} • tét {money(t['total_stake'])} • payout **{money(t['payout'])}**")
        for h in horses[:6]: lines.append(f"{icons.get(h['status'],'•')} Kincsem **#{h['bet_id']}** • {h['horse_name']} {h['market']} @{h['odds']:.2f} • {money(h['stake'])} → **{money(h['payout'])}**")
        embed=base_embed("📋 Fogadásaim","\n".join(lines) if lines else "Még nincs fogadásod.",BRAND); view=BettingHomeView(self,interaction.user.id); await (interaction.response.edit_message(embed=embed,view=view) if edit else interaction.response.send_message(embed=embed,view=view,ephemeral=True))

    async def show_results(self,interaction:discord.Interaction,*,edit:bool)->None:
        if not await self._allowed(interaction):return
        rows=await self.service.recent_results(interaction.guild_id,18); lines=[f"⚽ **{r['home']} {r['home_score']}–{r['away_score']} {r['away']}** • {r['league']}" for r in rows]
        embed=base_embed("🏆 Legutóbbi eredmények","\n".join(lines) if lines else "Még nincs lezárt virtuális meccs.",BRAND); view=BettingHomeView(self,interaction.user.id); await (interaction.response.edit_message(embed=embed,view=view) if edit else interaction.response.send_message(embed=embed,view=view,ephemeral=True))

    async def show_stats(self,interaction:discord.Interaction,*,edit:bool)->None:
        if not await self._allowed(interaction):return
        s=await self.service.user_stats(interaction.guild_id,interaction.user.id); embed=base_embed("📊 Fogadási statisztikád",f"Fogadások: **{s['bets']}**\nÖsszes tét: **{money(s['staked'])}**\nÖsszes payout: **{money(s['payout'])}**\nProfit/Loss: **{_signed_money(s['profit'])}**\nLegnagyobb payout: **{money(s['biggest'])}**",BRAND); view=BettingHomeView(self,interaction.user.id); await (interaction.response.edit_message(embed=embed,view=view) if edit else interaction.response.send_message(embed=embed,view=view,ephemeral=True))

    async def _dm_ticket(self,t:TicketSettlement)->None:
        if not await self.service.dm_enabled(t.guild_id):return
        with contextlib.suppress(discord.HTTPException,discord.Forbidden,discord.NotFound):
            user=self.bot.get_user(t.user_id) or await self.bot.fetch_user(t.user_id); color=SUCCESS if t.payout>t.total_stake else DANGER
            embed=base_embed(f"{'✅' if t.payout>t.total_stake else '❌'} Tippmix #{t.ticket_id} lezárva",f"Tét: **{money(t.total_stake)}**\nPayout: **{money(t.payout)}**\nEredmény: **{t.status.upper()}**",color); await user.send(embed=embed)

    async def _dm_horse(self,b:HorseSettlement)->None:
        if not await self.service.dm_enabled(b.guild_id):return
        with contextlib.suppress(discord.HTTPException,discord.Forbidden,discord.NotFound):
            user=self.bot.get_user(b.user_id) or await self.bot.fetch_user(b.user_id); embed=base_embed(f"{'✅' if b.payout else '❌'} Kincsem fogadás lezárva",f"**{b.horse_name}** • {b.market}\nTét: **{money(b.stake)}**\nPayout: **{money(b.payout)}**",SUCCESS if b.payout else DANGER); await user.send(embed=embed)

    async def _daily_results_thread(self,guild:discord.Guild)->discord.Thread|None:
        """Return today's result post inside the configured Forum, creating it once if needed."""
        forum_id=await self.service.settings.get_int(guild.id,cfg.BETTING_RESULTS_FORUM_KEY)
        forum=guild.get_channel(forum_id) if forum_id else None
        if not isinstance(forum,discord.ForumChannel):
            return None

        now=_results_now()
        day_key=now.strftime("%Y-%m-%d")
        stored_day=await self.service.settings.get_text(guild.id,cfg.BETTING_RESULTS_THREAD_DAY_KEY,"")
        stored_id=await self.service.settings.get_int(guild.id,cfg.BETTING_RESULTS_THREAD_ID_KEY)
        if stored_day==day_key and stored_id:
            thread=guild.get_thread(stored_id) or forum.get_thread(stored_id)
            if thread is None:
                with contextlib.suppress(discord.HTTPException,discord.Forbidden,discord.NotFound):
                    fetched=await self.bot.fetch_channel(stored_id)
                    if isinstance(fetched,discord.Thread) and fetched.parent_id==forum.id:
                        thread=fetched
            if thread is not None:
                if thread.archived:
                    try:
                        await thread.edit(archived=False,reason="Yoru napi fogadási eredmények folytatása")
                    except (discord.HTTPException,discord.Forbidden):
                        thread=None
                if thread is not None:
                    return thread

        title=f"📅 {now.strftime('%Y.%m.%d')} • Sportfogadás eredmények"
        for thread in forum.threads:
            if thread.name==title:
                await self.service.settings.set_text(guild.id,cfg.BETTING_RESULTS_THREAD_DAY_KEY,day_key)
                await self.service.settings.set_int(guild.id,cfg.BETTING_RESULTS_THREAD_ID_KEY,thread.id)
                return thread

        starter=base_embed(
            title,
            "Az aznapi **Tippmix** és **Kincsem** lezárt eredmények automatikus naplója.\nA személyes szelvényed eredménye továbbra is DM-ben és a Fogadásaim/History panelen érhető el.",
            BRAND,
        )
        created=await forum.create_thread(
            name=title[:100],
            embed=starter,
            auto_archive_duration=1440,
            reason="Yoru napi sportfogadási eredmények",
        )
        thread=getattr(created,"thread",created)
        if not isinstance(thread,discord.Thread):
            return None
        await self.service.settings.set_text(guild.id,cfg.BETTING_RESULTS_THREAD_DAY_KEY,day_key)
        await self.service.settings.set_int(guild.id,cfg.BETTING_RESULTS_THREAD_ID_KEY,thread.id)
        return thread

    async def _announce(self,guild:discord.Guild,result:dict[str,Any])->None:
        thread=await self._daily_results_thread(guild)
        if thread is None:
            # Szándékosan NINCS fallback a Fogadási Központ panel csatornájára:
            # eredmények csak a külön Forum napi posztjába kerülhetnek.
            return
        if result["matches"]:
            lines=[f"⚽ **{m['home']} {m['home_score']}–{m['away_score']} {m['away']}** • {m['league']}" for m in result["matches"][:10]]
            await thread.send(embed=base_embed("🏆 Tippmix • Eredmények","\n".join(lines),BRAND))
        for race in result["races"]:
            order=race["order"]; horses=race["horses"]
            podium="\n".join(f"**{i}. {horses[idx]['name']}**" for i,idx in enumerate(order[:3],1))
            await thread.send(embed=base_embed("🐎 Kincsem • Végeredmény",podium,GOLD))

    async def _worker_loop(self)->None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            for guild in list(self.bot.guilds):
                try:
                    if not await self.service.enabled(guild.id):continue
                    result=await self.service.process_due(guild.id)
                    if result["matches"] or result["races"]:
                        try:
                            await self._announce(guild,result)
                        except Exception:
                            import logging
                            logging.getLogger("vaultbot.betting").exception("Betting Forum announce hiba guild=%s",guild.id)
                    # A publikus Forum output soha nem blokkolhatja a személyes settlement DM-eket.
                    for t in result["tickets"]: await self._dm_ticket(t)
                    for b in result["horse_bets"]: await self._dm_horse(b)
                except Exception:
                    import logging; logging.getLogger("vaultbot.betting").exception("Betting worker hiba guild=%s",guild.id)
            await asyncio.sleep(60)

    async def home_status(self,guild:discord.Guild)->str:
        enabled=await self.service.enabled(guild.id); tip=await self.service.tippmix_enabled(guild.id); horse=await self.service.horse_enabled(guild.id); return f"{'🟢' if enabled else '⚪'} Tippmix {'ON' if tip else 'OFF'} • Kincsem {'ON' if horse else 'OFF'}"

    async def show_settings(self,interaction:discord.Interaction,owner_id:int,existing:BettingSettingsView|None=None)->None:
        if interaction.guild is None:return
        if not interaction.response.is_done():await interaction.response.defer()
        states={"enabled":await self.service.enabled(interaction.guild_id),"tippmix":await self.service.tippmix_enabled(interaction.guild_id),"horse":await self.service.horse_enabled(interaction.guild_id),"dm":await self.service.dm_enabled(interaction.guild_id)}
        channel_id=await self.service.settings.get_int(interaction.guild_id,cfg.BETTING_CHANNEL_KEY)
        forum_id=await self.service.settings.get_int(interaction.guild_id,cfg.BETTING_RESULTS_FORUM_KEY)
        log_id=await self.service.settings.get_int(interaction.guild_id,cfg.BETTING_LOG_CHANNEL_KEY)
        channel=interaction.guild.get_channel(channel_id) if channel_id else None
        forum=interaction.guild.get_channel(forum_id) if forum_id else None
        log=interaction.guild.get_channel(log_id) if log_id else None
        embed=base_embed("🏟️ Fogadás • Settings","Yoru DB settings az elsődleges source of truth.",BRAND)
        embed.add_field(name="Modulok",value=f"Fogadás **{'ON' if states['enabled'] else 'OFF'}** • Tippmix **{'ON' if states['tippmix'] else 'OFF'}** • Kincsem **{'ON' if states['horse'] else 'OFF'}** • DM **{'ON' if states['dm'] else 'OFF'}**",inline=False)
        embed.add_field(name="Balance",value=f"Min tét **{money(await self.service.min_stake(interaction.guild_id))}** • max legs **{await self.service.max_legs(interaction.guild_id)}** • max payout **{money(await self.service.max_payout(interaction.guild_id))}**\nNapi meccs **{await self.service.daily_match_count(interaction.guild_id)}** • Kincsem **{await self.service.horse_interval_hours(interaction.guild_id)}h**",inline=False)
        embed.add_field(name="Csatornák",value=f"Panel: {channel.mention if channel else 'Nincs'}\nNapi eredmény Forum: {forum.mention if isinstance(forum,discord.ForumChannel) else 'Nincs'}\nLog: {log.mention if log else 'Nincs'}",inline=False)
        view=BettingSettingsView(self,owner_id,interaction.guild,states,channel_page=existing.channel_page if existing else 0,forum_page=existing.forum_page if existing else 0,log_page=existing.log_page if existing else 0); await interaction.edit_original_response(embed=embed,view=view,attachments=[])

    @app_commands.command(name="panel",description="Admin: állandó Fogadási Központ panel kirakása ebbe a csatornába.")
    @app_commands.default_permissions(manage_guild=True)
    async def panel(self,interaction:discord.Interaction)->None:
        if interaction.guild is None or interaction.channel is None:return
        if not isinstance(interaction.user,discord.Member) or not interaction.user.guild_permissions.manage_guild:return await interaction.response.send_message("❌ Manage Server szükséges.",ephemeral=True)
        await self.service.settings.set_int(interaction.guild_id,cfg.BETTING_CHANNEL_KEY,interaction.channel_id); await interaction.response.defer(ephemeral=True); msg=await interaction.channel.send(embed=self.panel_embed(),view=BettingPanelView(self)); await interaction.followup.send(f"✅ Fogadási panel kirakva: {msg.jump_url}",ephemeral=True)

    @app_commands.command(name="open",description="Megnyitja a saját Fogadási Központodat.")
    async def open_panel(self,interaction:discord.Interaction)->None: await self.show_home(interaction,edit=False)

    @app_commands.command(name="settings",description="Fogadási szerverbeállítások.")
    @app_commands.default_permissions(manage_guild=True)
    async def settings_command(self,interaction:discord.Interaction)->None:
        if interaction.guild is None:return
        if not isinstance(interaction.user,discord.Member) or not interaction.user.guild_permissions.manage_guild:return await interaction.response.send_message("❌ Manage Server szükséges.",ephemeral=True)
        await interaction.response.send_message("⚙️ Betöltés…",ephemeral=True); await self.show_settings(interaction,interaction.user.id)

    @commands.command(name="betting",aliases=["fogadas","fogadás","tippmix"])
    @commands.guild_only()
    async def betting_prefix(self,ctx:commands.Context)->None:
        if not await self.service.enabled(ctx.guild.id):return await ctx.send("❌ A Fogadási Központ ki van kapcsolva.")
        # A tartós publikus panelt csak admin rakhatja ki !bettingpanel-lel.
        # Ez a prefix csak egy ideiglenes belépő, hogy ne lehessen telepanelozni a csatornát.
        await ctx.send(embed=self.panel_embed(),view=BettingPanelView(self),delete_after=120)

    @commands.command(name="bettingpanel",aliases=["betpanel","fogadaspanel","fogadáspanel"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def betting_panel_prefix(self,ctx:commands.Context)->None:
        await self.service.settings.set_int(ctx.guild.id,cfg.BETTING_CHANNEL_KEY,ctx.channel.id); await ctx.send(embed=self.panel_embed(),view=BettingPanelView(self))
