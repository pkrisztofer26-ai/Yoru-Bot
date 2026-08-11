from __future__ import annotations

import random
import discord
from discord import app_commands
from discord.ext import commands

from app.services.gambling import GambleResult, GamblingService
from app.amounts import parse_amount
from app.ui import DANGER, GOLD, SUCCESS, error_embed, gambling_result_embed, money, player_embed
from app import economy_config as eco


CARD_VALUES = {"A": 11, "K": 10, "Q": 10, "J": 10, **{str(i): i for i in range(2, 11)}}
SUITS = ["♠️", "♥️", "♦️", "♣️"]


def draw_card() -> tuple[str, int]:
    rank = random.choice(list(CARD_VALUES))
    return f"{rank}{random.choice(SUITS)}", CARD_VALUES[rank]


def hand_value(cards: list[tuple[str, int]]) -> int:
    value = sum(card[1] for card in cards)
    aces = sum(1 for card in cards if card[0].startswith("A"))
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


class BlackjackView(discord.ui.View):
    def __init__(
        self,
        gambling: GamblingService,
        guild_id: int,
        user_id: int,
        bet: int,
        player_name: str,
        avatar_url: str | None,
    ) -> None:
        super().__init__(timeout=90)
        self.gambling = gambling
        self.guild_id = guild_id
        self.user_id = user_id
        self.bet = bet
        self.player_name = player_name
        self.avatar_url = avatar_url
        self.player = [draw_card(), draw_card()]
        self.dealer = [draw_card(), draw_card()]
        self.finished = False
        self.message: discord.Message | None = None

    def opening_is_finished(self) -> bool:
        """A két kezdő lap alapján eldőlt-e már a kör."""
        return hand_value(self.player) == 21 or hand_value(self.dealer) == 21

    def embed(self, reveal: bool = False, footer: str | None = None, color: discord.Color | None = None) -> discord.Embed:
        dealer_cards = "  ".join(c[0] for c in self.dealer) if reveal else f"{self.dealer[0][0]}  ▰"
        dealer_value = str(hand_value(self.dealer)) if reveal else str(self.dealer[0][1])
        player_cards = "  ".join(c[0] for c in self.player)

        embed = discord.Embed(
            title="🃏 BLACKJACK",
            description="Próbálj minél közelebb kerülni **21-hez** anélkül, hogy túllépnéd.",
            color=color or discord.Color.from_rgb(88, 101, 242),
        )
        embed.set_author(name=self.player_name, icon_url=self.avatar_url)
        embed.add_field(name="🎟️ Tét", value=f"**{money(self.bet)}**", inline=True)
        embed.add_field(name="🎯 Cél", value="**21 pont**", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(
            name="🎴 Osztó",
            value=f"`{dealer_cards}`\nPont: **{dealer_value}**",
            inline=False,
        )
        embed.add_field(
            name="🃏 Te",
            value=f"`{player_cards}`\nPont: **{hand_value(self.player)}**",
            inline=False,
        )
        if footer:
            embed.add_field(name="📌 Eredmény", value=footer, inline=False)
        embed.set_footer(text="Yoru • Ász: 1 vagy 11")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Ez nem a te blackjack játékod.", ephemeral=True)
            return False
        return True

    async def finish(self, interaction: discord.Interaction | None = None, *, auto: bool = False) -> None:
        if self.finished:
            return
        self.finished = True
        player_value = hand_value(self.player)
        dealer_value = hand_value(self.dealer)
        player_natural = len(self.player) == 2 and player_value == 21
        dealer_natural = len(self.dealer) == 2 and dealer_value == 21

        # Kezdő 21-nél a kör azonnal lezárul. Ha mindketten 21-et kaptak, push.
        if player_natural or dealer_natural:
            if player_natural and dealer_natural:
                payout, text, color = self.bet, "🤝 **Mindketten BLACKJACK-et kaptatok.** A téted visszajárt.", GOLD
            elif player_natural:
                total_payout = await self.gambling.payout_total(self.guild_id, eco.BLACKJACK_WIN_TOTAL_PAYOUT)
                payout = int(self.bet * total_payout)
                text, color = "✨ **BLACKJACK! Azonnali győzelem.**", SUCCESS
            else:
                payout, text, color = 0, "🃏 **Az osztó BLACKJACK-et kapott.** Az osztó nyert.", DANGER
        else:
            while hand_value(self.dealer) < 17:
                self.dealer.append(draw_card())
            dealer_value = hand_value(self.dealer)
            if player_value > 21:
                payout, text, color = 0, "💥 **Besokalltál.** Az osztó nyert.", DANGER
            elif dealer_value > 21 or player_value > dealer_value:
                total_payout = await self.gambling.payout_total(self.guild_id, eco.BLACKJACK_WIN_TOTAL_PAYOUT)
                payout = int(self.bet * total_payout)
                text, color = "✅ **Megnyerted a kört!**", SUCCESS
            elif player_value == dealer_value:
                payout, text, color = self.bet, "🤝 **Döntetlen.** A téted visszajárt.", GOLD
            else:
                payout, text, color = 0, "❌ **Az osztó nyert.**", DANGER
        wallet = await self.gambling.resolve_blackjack(self.guild_id, self.user_id, self.bet, payout)
        profit = payout - self.bet
        if profit > 0:
            text += f"\n💵 Profit: **+{money(profit)}**"
        elif profit < 0:
            text += f"\n💵 Veszteség: **-{money(abs(profit))}**"
        else:
            text += f"\n💵 Eredmény: **{money(0)}**"
        text += f"\n💸 Kifizetés: **{money(payout)}**"
        text += f"\n💰 Egyenleg: **{money(wallet)}**"
        for child in self.children:
            child.disabled = True
        embed = self.embed(True, text, color)
        if interaction is not None:
            await interaction.response.edit_message(embed=embed, view=self)
        elif self.message is not None:
            await self.message.edit(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Lapot kérek", emoji="🃏", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.player.append(draw_card())
        if hand_value(self.player) >= 21:
            await self.finish(interaction)
        else:
            await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Megállok", emoji="✋", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.finish(interaction)

    async def on_timeout(self) -> None:
        await self.finish(auto=True)


class GamblingCog(commands.Cog):
    def __init__(self, bot: commands.Bot, gambling: GamblingService) -> None:
        self.bot = bot
        self.gambling = gambling

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            return False
        try:
            await self.gambling.guild_settings.prepare_currency(interaction.guild_id)
            await self.gambling.guild_settings.require_feature(interaction.guild_id, "gambling")
            await self.gambling.guild_settings.require_channel(interaction.guild_id, interaction.channel_id, getattr(interaction.channel, "category_id", None))
        except ValueError as error:
            await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
            return False
        return True

    @app_commands.command(name="coinflip", description="Fej vagy írás pénztétért.")
    @app_commands.choices(oldal=[app_commands.Choice(name="Fej", value="fej"), app_commands.Choice(name="Írás", value="írás")])
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def coinflip(self, interaction: discord.Interaction, oldal: app_commands.Choice[str], osszeg: str) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction):
            return
        wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            tet = parse_amount(osszeg, wallet)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await self._simple(interaction, "🪙 Coinflip", self.gambling.coinflip, tet, oldal.value, tet)

    @app_commands.command(name="dice", description="Tippelj egy számot 1 és 6 között.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def dice(self, interaction: discord.Interaction, tipped: app_commands.Range[int, 1, 6], osszeg: str) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction):
            return
        wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            tet = parse_amount(osszeg, wallet)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await self._simple(interaction, "🎲 Kockajáték", self.gambling.dice, tet, tipped, tet)

    @app_commands.command(name="slots", description="Pörgesd meg a nyerőgépet.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def slots(self, interaction: discord.Interaction, osszeg: str) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction):
            return
        wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            tet = parse_amount(osszeg, wallet)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await self._simple(interaction, "🎰 Slots", self.gambling.slots, tet, tet)

    @app_commands.command(name="roulette", description="Fogadj a rulett eredményére.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def roulette(self, interaction: discord.Interaction, valasztas: str, osszeg: str) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction):
            return
        wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            tet = parse_amount(osszeg, wallet)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await self._simple(interaction, "🎡 Roulette", self.gambling.roulette, tet, valasztas, tet)

    async def _simple(self, interaction: discord.Interaction, title: str, function, bet: int, *args) -> None:
        if interaction.guild_id is None:
            return
        try:
            result: GambleResult = await function(interaction.guild_id, interaction.user.id, *args)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(
            embed=gambling_result_embed(
                title,
                interaction.user,
                result_text=result.display,
                bet=bet,
                profit=result.profit,
                wallet=result.wallet,
            )
        )

    async def start_blackjack(self, guild_id: int, user: discord.abc.User, bet: int) -> BlackjackView:
        await self.gambling.reserve_blackjack(guild_id, user.id, bet)
        return BlackjackView(
            self.gambling,
            guild_id,
            user.id,
            bet,
            user.display_name,
            getattr(user.display_avatar, "url", None),
        )

    @app_commands.command(name="blackjack", description="Játssz blackjacket az osztó ellen.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def blackjack(self, interaction: discord.Interaction, osszeg: str) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction):
            return
        wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            tet = parse_amount(osszeg, wallet)
            view = await self.start_blackjack(interaction.guild_id, interaction.user, tet)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        if view.opening_is_finished():
            await view.finish(auto=True)
