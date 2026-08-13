from __future__ import annotations

import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands

from app import casino_config as casino_cfg
from app.services.economy import CooldownError, JailError
from app.services.extras import ExtrasCasinoResult, ExtrasService
from app.amounts import parse_amount
from app.gamble_rooms import is_gamble_room
from app.casino_quick_visuals import (
    render_chicken,
    render_chicken_animation,
    render_highlow,
    render_highlow_animation,
    render_rps,
    render_rps_animation,
)
from app.ui import BRAND, DANGER, GOLD, SUCCESS, action_embed, cooldown_embed, error_embed, money, player_embed


class HighLowView(discord.ui.View):
    def __init__(self, cog: "ExtrasCog", owner: discord.abc.User, session, current_rank: int) -> None:
        super().__init__(timeout=casino_cfg.HIGHLOW_V2_TIMEOUT_SECONDS)
        self.cog = cog
        self.owner = owner
        self.owner_id = owner.id
        self.session = session
        self.current_rank = int(current_rank)
        self.multiplier = 1.0
        self.streak = 0
        self.message: discord.Message | None = None
        self.finished = False
        self._lock = asyncio.Lock()
        self._sync_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ez nem a te játékod.", ephemeral=True)
            return False
        return True

    def _sync_buttons(self) -> None:
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            if self.finished:
                child.disabled = True
            elif child.custom_id == "hl:higher":
                child.disabled = self.current_rank >= 14
            elif child.custom_id == "hl:lower":
                child.disabled = self.current_rank <= 2
            elif child.custom_id == "hl:cashout":
                child.disabled = self.streak <= 0 or self.multiplier <= 1.0

    def embed(self, *, image_filename: str = "highlow.png", phase: str = "Válassz: Higher vagy Lower", result: str | None = None) -> discord.Embed:
        color = BRAND
        if result == "win": color = SUCCESS
        elif result == "lose": color = DANGER
        elif result in {"cashout", "tie"}: color = GOLD
        embed = player_embed("🃏 HIGH / LOW", self.owner, color=color)
        embed.description = phase
        embed.set_image(url=f"attachment://{image_filename}")
        embed.add_field(name="🎟️ Tét", value=f"**{money(self.session.bet)}**", inline=True)
        embed.add_field(name="🔥 Streak", value=f"**{self.streak}**", inline=True)
        embed.add_field(name="💸 Cashout", value=f"**x{self.multiplier:.2f}**", inline=True)
        embed.set_footer(text="Yoru • High / Low")
        return embed

    @staticmethod
    def _step_factor(current: int, direction: str) -> float:
        favorable = (14 - current) if direction == "higher" else (current - 2)
        if favorable <= 0:
            return 1.0
        effective_probability = favorable / 12.0  # tie repeats; 12 decisive ranks remain
        return max(casino_cfg.HIGHLOW_V2_MIN_STEP_MULTIPLIER, casino_cfg.HIGHLOW_V2_HOUSE_FACTOR / effective_probability)

    async def _render(self, func, *args, **kwargs):
        return await self.cog._render_visual(func, *args, **kwargs)

    async def _show_static(self, *, phase: str, result: str | None = None) -> None:
        if self.message is None:
            return
        fp = await self._render(
            render_highlow,
            self.current_rank,
            None,
            player_name=self.owner.display_name,
            phase="RESULT" if self.finished else "CHOOSE",
            multiplier=self.multiplier,
            streak=self.streak,
            reveal=False,
        )
        await self.message.edit(embed=self.embed(image_filename="highlow.png", phase=phase, result=result), attachments=[discord.File(fp=fp, filename="highlow.png")], view=self)

    async def _settle_loss(self, next_rank: int, direction: str) -> None:
        settlement = await self.cog.extras.casino.settle(
            self.session,
            0,
            result=f"lose:{direction}:{self.current_rank}->{next_rank}:streak={self.streak}",
            multiplier=0.0,
        )
        self.finished = True
        self._sync_buttons()
        if self.message is not None:
            fp = await self._render(
                render_highlow,
                self.current_rank,
                next_rank,
                player_name=self.owner.display_name,
                phase="LOSE",
                multiplier=self.multiplier,
                streak=self.streak,
                reveal=True,
            )
            embed = self.embed(image_filename="highlow.png", phase=f"❌ Rossz tipp • **-{money(self.session.bet)}** • Egyenleg: **{money(settlement.wallet)}**", result="lose")
            await self.message.edit(embed=embed, attachments=[discord.File(fp=fp, filename="highlow.png")], view=self)
        await self.cog.extras.casino.release_player_game(self.session.game_id)
        self.stop()

    async def _guess(self, interaction: discord.Interaction, direction: str) -> None:
        async with self._lock:
            if self.finished:
                return
            if (direction == "higher" and self.current_rank >= 14) or (direction == "lower" and self.current_rank <= 2):
                return await interaction.response.send_message("❌ Erre az irányra ebből a lapból nem lehet tippelni.", ephemeral=True)
            await interaction.response.defer()
            old_rank = self.current_rank
            next_rank = random.randint(2, 14)
            animation = await self._render(
                render_highlow_animation,
                old_rank,
                next_rank,
                player_name=self.owner.display_name,
                multiplier=self.multiplier,
                streak=self.streak,
            )
            if self.message is not None:
                await self.message.edit(embed=self.embed(image_filename="highlow.gif", phase="🃏 Lap húzása…"), attachments=[discord.File(fp=animation, filename="highlow.gif")], view=self)
            await asyncio.sleep(1.75)
            if next_rank == old_rank:
                if self.message is not None:
                    fp = await self._render(render_highlow, old_rank, next_rank, player_name=self.owner.display_name, phase="TIE", multiplier=self.multiplier, streak=self.streak, reveal=True)
                    await self.message.edit(embed=self.embed(image_filename="highlow.png", phase="🤝 Tie — a kör ugyanonnan folytatódik.", result="tie"), attachments=[discord.File(fp=fp, filename="highlow.png")], view=self)
                return
            won = next_rank > old_rank if direction == "higher" else next_rank < old_rank
            if not won:
                await self._settle_loss(next_rank, direction)
                return
            self.multiplier *= self._step_factor(old_rank, direction)
            self.multiplier = round(self.multiplier, 4)
            self.streak += 1
            self.current_rank = next_rank
            self._sync_buttons()
            if self.message is not None:
                fp = await self._render(render_highlow, self.current_rank, None, player_name=self.owner.display_name, phase="CHOOSE", multiplier=self.multiplier, streak=self.streak, reveal=False)
                await self.message.edit(
                    embed=self.embed(image_filename="highlow.png", phase=f"✅ Talált! Cashout most: **{money(int(self.session.bet * self.multiplier))}**", result="win"),
                    attachments=[discord.File(fp=fp, filename="highlow.png")],
                    view=self,
                )

    async def _cashout(self, interaction: discord.Interaction | None = None, *, timeout: bool = False) -> None:
        async with self._lock:
            if self.finished:
                return
            if (self.streak <= 0 or self.multiplier <= 1.0) and not timeout:
                if interaction is not None and not interaction.response.is_done():
                    await interaction.response.send_message("❌ Cash Out csak akkor érhető el, ha már van tényleges profitod.", ephemeral=True)
                return
            if interaction is not None and not interaction.response.is_done():
                await interaction.response.defer()
            payout = max(self.session.bet, int(round(self.session.bet * self.multiplier)))
            settlement = await self.cog.extras.casino.settle(
                self.session,
                payout,
                result=f"cashout:streak={self.streak}:x{self.multiplier:.4f}",
                multiplier=(payout / self.session.bet) if self.session.bet else 0.0,
            )
            self.finished = True
            self._sync_buttons()
            phase = f"💰 {'Timeout cashout' if timeout else 'Cashout'} • **+{money(max(0, settlement.profit))}** • Egyenleg: **{money(settlement.wallet)}**"
            await self._show_static(phase=phase, result="cashout")
            await self.cog.extras.casino.release_player_game(self.session.game_id)
            self.stop()

    @discord.ui.button(label="Higher", emoji="⬆️", style=discord.ButtonStyle.primary, custom_id="hl:higher", row=0)
    async def higher(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._guess(interaction, "higher")

    @discord.ui.button(label="Lower", emoji="⬇️", style=discord.ButtonStyle.primary, custom_id="hl:lower", row=0)
    async def lower(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._guess(interaction, "lower")

    @discord.ui.button(label="Cash Out", emoji="💰", style=discord.ButtonStyle.success, custom_id="hl:cashout", row=0)
    async def cashout(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._cashout(interaction)

    async def on_timeout(self) -> None:
        if self.finished:
            return
        try:
            if self.streak > 0:
                await self._cashout(timeout=True)
            else:
                await self.cog.extras.casino.refund(self.session, "highlow_timeout")
                self.finished = True
                self._sync_buttons()
                await self._show_static(phase="⌛ Timeout — az induló tét visszajárt.", result="tie")
        except Exception:
            try:
                await self.cog.extras.casino.release_player_game(self.session.game_id)
            except Exception:
                pass
        self.stop()


class ExtrasCog(commands.Cog):
    def __init__(self, bot: commands.Bot, extras: ExtrasService) -> None:
        self.bot = bot
        self.extras = extras
        self._render_semaphore = asyncio.Semaphore(max(1, int(casino_cfg.QUICK_GAME_RENDER_CONCURRENCY)))

    async def _render_visual(self, func, *args, **kwargs):
        gambling = self.bot.get_cog("GamblingCog")
        if gambling is not None and hasattr(gambling, "_render_visual"):
            return await gambling._render_visual(func, *args, **kwargs)
        async with self._render_semaphore:
            return await asyncio.to_thread(func, *args, **kwargs)

    async def _guard(self, interaction: discord.Interaction, feature: str) -> bool:
        if interaction.guild_id is None:
            return False
        try:
            if feature == "gambling" and is_gamble_room(interaction.channel):
                await self.extras.economy.prepare_context(interaction.guild_id)
                await self.extras.economy.guild_settings.require_feature(interaction.guild_id, "gambling")
            else:
                await self.extras.economy.require_access(
                    interaction.guild_id, feature, interaction.channel_id, getattr(interaction.channel, "category_id", None)
                )
        except ValueError as e:
            await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
            return False
        return True

    @app_commands.command(name="weekly", description="Átveszed a heti economy jutalmadat.")
    async def weekly(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "weekly"): return
        try: reward, ready = await self.extras.weekly(interaction.guild_id, interaction.user.id)
        except CooldownError as e: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Weekly", e.ready_at), ephemeral=True)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        embed = action_embed("📅 Weekly", interaction.user, color=SUCCESS)
        embed.add_field(name="💰 Jutalom", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="monthly", description="Átveszed a havi economy jutalmadat.")
    async def monthly(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "monthly"): return
        try: reward, ready = await self.extras.monthly(interaction.guild_id, interaction.user.id)
        except CooldownError as e: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Monthly", e.ready_at), ephemeral=True)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        embed = action_embed("🗓️ Monthly", interaction.user, color=SUCCESS)
        embed.add_field(name="💰 Jutalom", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="interest", description="Banki kamatot veszel fel 6 óránként.")
    async def interest(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "interest"): return
        try: reward, bank, ready = await self.extras.interest(interaction.guild_id, interaction.user.id)
        except CooldownError as e: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Interest", e.ready_at), ephemeral=True)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        embed = action_embed("🏦 Banki kamat", interaction.user, color=SUCCESS)
        embed.add_field(name="💰 Jóváírt kamat", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{money(bank)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="scratch", description="Felhasználsz egy Sorsjegyet.")
    async def scratch(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "economy"): return
        try: label, reward, wallet = await self.extras.scratch(interaction.guild_id, interaction.user.id)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        embed = action_embed("🎟️ Sorsjegy", interaction.user, description=f"**{label}**", color=SUCCESS if reward else GOLD)
        embed.add_field(name="💰 Nyeremény", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="giveitem", description="Tárgyat adsz egy másik tagnak.")
    async def giveitem(self, interaction: discord.Interaction, member: discord.Member, item: str, mennyiseg: app_commands.Range[int, 1, 1000] = 1) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "economy"): return
        if member.bot: return await interaction.response.send_message(embed=error_embed(interaction.user, "Botnak nem adhatsz tárgyat."), ephemeral=True)
        try: name, emoji, qty = await self.extras.give_item(interaction.guild_id, interaction.user.id, member.id, item, mennyiseg)
        except (ValueError, LookupError) as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        await interaction.response.send_message(f"🎁 {interaction.user.mention} adott {member.mention} részére **{qty}× {emoji} {name}** tárgyat.")

    @staticmethod
    def _visual_embed(title: str, user: discord.abc.User, result: ExtrasCasinoResult | None, *, bet: int, image_filename: str, description: str) -> discord.Embed:
        color = BRAND if result is None else (SUCCESS if result.profit > 0 else (DANGER if result.profit < 0 else GOLD))
        embed = player_embed(title, user, color=color)
        embed.description = description
        embed.set_image(url=f"attachment://{image_filename}")
        embed.add_field(name="🎟️ Tét", value=f"**{money(bet)}**", inline=True)
        if result is None:
            embed.add_field(name="💸 P/L", value="**…**", inline=True)
            embed.add_field(name="💰 Egyenleg", value="**…**", inline=True)
        else:
            pnl = f"+{money(result.profit)}" if result.profit > 0 else (f"-{money(abs(result.profit))}" if result.profit < 0 else money(0))
            embed.add_field(name="💸 P/L", value=f"**{pnl}**", inline=True)
            embed.add_field(name="💰 Egyenleg", value=f"**{money(result.wallet)}**", inline=True)
        embed.set_footer(text="Yoru • Casino")
        return embed

    async def run_rps_interaction(self, interaction: discord.Interaction, choice: str, bet: int) -> None:
        result: ExtrasCasinoResult | None = None
        handed_off = False
        try:
            result = await self.extras.rps_visual(interaction.guild_id, interaction.user.id, choice, bet)
            player = result.details["player"]; bot = result.details["bot"]
            fp = await self._render_visual(render_rps_animation, player, bot, player_name=interaction.user.display_name)
            await interaction.response.send_message(embed=self._visual_embed("✂️ RPS", interaction.user, None, bet=bet, image_filename="rps.gif", description=f"🎯 Te: **{str(player).title()}** • Yoru választ…"), file=discord.File(fp=fp, filename="rps.gif"))
            msg = await interaction.original_response(); handed_off = True
            await asyncio.sleep(casino_cfg.QUICK_GAME_ANIMATION_SECONDS)
            final = await self._render_visual(render_rps, player, bot, player_name=interaction.user.display_name)
            await msg.edit(embed=self._visual_embed("✂️ RPS", interaction.user, result, bet=bet, image_filename="rps.png", description=f"Te: **{str(player).title()}** • Yoru: **{str(bot).title()}**"), attachments=[discord.File(fp=final, filename="rps.png")])
        except (JailError, ValueError) as e:
            text = f"Börtönben vagy még: <t:{int(e.ready_at.timestamp())}:R>" if isinstance(e, JailError) else str(e)
            if not interaction.response.is_done(): await interaction.response.send_message(embed=error_embed(interaction.user, text), ephemeral=True)
        finally:
            if result is not None:
                await self.extras.casino.release_player_game(result.game_id)

    async def run_rps_prefix(self, ctx: commands.Context, choice: str, bet: int) -> None:
        result: ExtrasCasinoResult | None = None
        try:
            result = await self.extras.rps_visual(ctx.guild.id, ctx.author.id, choice, bet)
            player=result.details["player"]; bot=result.details["bot"]
            fp=await self._render_visual(render_rps_animation,player,bot,player_name=ctx.author.display_name)
            msg=await ctx.send(embed=self._visual_embed("✂️ RPS",ctx.author,None,bet=bet,image_filename="rps.gif",description=f"🎯 Te: **{str(player).title()}** • Yoru választ…"),file=discord.File(fp=fp,filename="rps.gif"))
            await asyncio.sleep(casino_cfg.QUICK_GAME_ANIMATION_SECONDS)
            final=await self._render_visual(render_rps,player,bot,player_name=ctx.author.display_name)
            await msg.edit(embed=self._visual_embed("✂️ RPS",ctx.author,result,bet=bet,image_filename="rps.png",description=f"Te: **{str(player).title()}** • Yoru: **{str(bot).title()}**"),attachments=[discord.File(fp=final,filename="rps.png")])
        except (JailError,ValueError) as e:
            await ctx.send(embed=error_embed(ctx.author,str(e)))
        finally:
            if result is not None: await self.extras.casino.release_player_game(result.game_id)

    async def run_chicken_interaction(self, interaction: discord.Interaction, bet: int) -> None:
        result: ExtrasCasinoResult | None = None
        try:
            result = await self.extras.chickenfight_visual(interaction.guild_id, interaction.user.id, bet)
            opponent=str(result.details["opponent"]); frames=result.details["frames"]
            fp=await self._render_visual(render_chicken_animation,frames,opponent=opponent,player_name=interaction.user.display_name)
            await interaction.response.send_message(embed=self._visual_embed("🐔 CHICKEN FIGHT",interaction.user,None,bet=bet,image_filename="chicken.gif",description=f"⚔️ Ellenfél: **{opponent}**"),file=discord.File(fp=fp,filename="chicken.gif"))
            msg=await interaction.original_response()
            await asyncio.sleep(casino_cfg.CHICKEN_V2_ANIMATION_SECONDS)
            php,ohp,event=frames[-1]
            final=await self._render_visual(render_chicken,php,ohp,opponent=opponent,event=event,player_name=interaction.user.display_name)
            desc=f"⚔️ **{opponent}** • {'🏆 Győzelem' if result.result=='win' else '💀 Vereség — a Chickened elpusztult'}"
            await msg.edit(embed=self._visual_embed("🐔 CHICKEN FIGHT",interaction.user,result,bet=bet,image_filename="chicken.png",description=desc),attachments=[discord.File(fp=final,filename="chicken.png")])
        except (JailError,ValueError) as e:
            text=f"Börtönben vagy még: <t:{int(e.ready_at.timestamp())}:R>" if isinstance(e,JailError) else str(e)
            if not interaction.response.is_done(): await interaction.response.send_message(embed=error_embed(interaction.user,text),ephemeral=True)
        finally:
            if result is not None: await self.extras.casino.release_player_game(result.game_id)

    async def run_chicken_prefix(self, ctx: commands.Context, bet: int) -> None:
        result: ExtrasCasinoResult | None = None
        try:
            result=await self.extras.chickenfight_visual(ctx.guild.id,ctx.author.id,bet)
            opponent=str(result.details["opponent"]); frames=result.details["frames"]
            fp=await self._render_visual(render_chicken_animation,frames,opponent=opponent,player_name=ctx.author.display_name)
            msg=await ctx.send(embed=self._visual_embed("🐔 CHICKEN FIGHT",ctx.author,None,bet=bet,image_filename="chicken.gif",description=f"⚔️ Ellenfél: **{opponent}**"),file=discord.File(fp=fp,filename="chicken.gif"))
            await asyncio.sleep(casino_cfg.CHICKEN_V2_ANIMATION_SECONDS)
            php,ohp,event=frames[-1]; final=await self._render_visual(render_chicken,php,ohp,opponent=opponent,event=event,player_name=ctx.author.display_name)
            desc=f"⚔️ **{opponent}** • {'🏆 Győzelem' if result.result=='win' else '💀 Vereség — a Chickened elpusztult'}"
            await msg.edit(embed=self._visual_embed("🐔 CHICKEN FIGHT",ctx.author,result,bet=bet,image_filename="chicken.png",description=desc),attachments=[discord.File(fp=final,filename="chicken.png")])
        except (JailError,ValueError) as e: await ctx.send(embed=error_embed(ctx.author,str(e)))
        finally:
            if result is not None: await self.extras.casino.release_player_game(result.game_id)

    async def start_highlow_interaction(self, interaction: discord.Interaction, bet: int) -> None:
        session = None
        try:
            session = await self.extras.casino.begin(interaction.guild_id, interaction.user.id, "highlow", bet, config={"engine":"highlow_streak","defer_player_lock_release":True})
            await self.extras.casino.mark_waiting(session.game_id)
            view=HighLowView(self,interaction.user,session,random.randint(2,14))
            fp=await self._render_visual(render_highlow,view.current_rank,None,player_name=interaction.user.display_name,phase="CHOOSE",multiplier=1.0,streak=0,reveal=False)
            await interaction.response.send_message(embed=view.embed(image_filename="highlow.png"),file=discord.File(fp=fp,filename="highlow.png"),view=view)
            view.message=await interaction.original_response()
        except (JailError,ValueError) as e:
            if session is not None:
                try: await self.extras.casino.refund(session,"highlow_open_error")
                except Exception: pass
            if not interaction.response.is_done(): await interaction.response.send_message(embed=error_embed(interaction.user,str(e)),ephemeral=True)

    async def start_highlow_prefix(self, ctx: commands.Context, bet: int) -> None:
        session=None
        try:
            session=await self.extras.casino.begin(ctx.guild.id,ctx.author.id,"highlow",bet,config={"engine":"highlow_streak","defer_player_lock_release":True})
            await self.extras.casino.mark_waiting(session.game_id)
            view=HighLowView(self,ctx.author,session,random.randint(2,14))
            fp=await self._render_visual(render_highlow,view.current_rank,None,player_name=ctx.author.display_name,phase="CHOOSE",multiplier=1.0,streak=0,reveal=False)
            view.message=await ctx.send(embed=view.embed(image_filename="highlow.png"),file=discord.File(fp=fp,filename="highlow.png"),view=view)
        except (JailError,ValueError) as e:
            if session is not None:
                try: await self.extras.casino.refund(session,"highlow_open_error")
                except Exception: pass
            await ctx.send(embed=error_embed(ctx.author,str(e)))

    @app_commands.command(name="chickenfight", description="Animált Chicken Fight pénztétért.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def chickenfight(self, interaction: discord.Interaction, osszeg: str) -> None:
        if interaction.guild_id is None or not await self._guard(interaction,"gambling"): return
        wallet,_=await self.extras.economy.balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user,str(e)),ephemeral=True)
        await self.run_chicken_interaction(interaction,bet)

    @app_commands.command(name="highlow", description="Streak + cashout High / Low.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def highlow(self, interaction: discord.Interaction, osszeg: str) -> None:
        if interaction.guild_id is None or not await self._guard(interaction,"gambling"): return
        wallet,_=await self.extras.economy.balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user,str(e)),ephemeral=True)
        await self.start_highlow_interaction(interaction,bet)

    @app_commands.command(name="rps", description="Kő-papír-olló Yoru ellen, animált reveal-lel.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def rps(self, interaction: discord.Interaction, valasztas: str, osszeg: str) -> None:
        if interaction.guild_id is None or not await self._guard(interaction,"gambling"): return
        wallet,_=await self.extras.economy.balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user,str(e)),ephemeral=True)
        await self.run_rps_interaction(interaction,valasztas,bet)
