from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import random

import discord
from discord import app_commands
from discord.ext import commands

from app import casino_config as casino_cfg
from app.amounts import parse_amount
from app.casino_games import RouletteBet, parse_roulette_choice, roulette_result_emoji
from app.casino_visuals import render_slots, render_slots_animation, render_roulette, render_roulette_animation
from app.casino_quick_visuals import render_coinflip, render_coinflip_animation, render_dice, render_dice_animation
from app.services.gambling import GambleResult, GamblingService, QuickGameResult, RouletteRound, SlotsGameResult
from app.services.casino import CasinoSession
from app.ui import DANGER, GOLD, SUCCESS, BRAND, error_embed, gambling_result_embed, money, player_embed


# ---------------------------------------------------------------------------
# Blackjack
# ---------------------------------------------------------------------------


CARD_VALUES = {"A": 11, "K": 10, "Q": 10, "J": 10, **{str(i): i for i in range(2, 11)}}
SUITS = ["♠️", "♥️", "♦️", "♣️"]
Card = tuple[str, str, int]


def make_deck() -> list[Card]:
    deck = [(rank, suit, value) for rank, value in CARD_VALUES.items() for suit in SUITS]
    random.shuffle(deck)
    return deck


def card_text(card: Card) -> str:
    return f"{card[0]}{card[1]}"


def _card_face_lines(card: Card | None = None, *, hidden: bool = False) -> tuple[str, ...]:
    """Render a large monospace card face for Discord embed fields."""
    if hidden or card is None:
        return (
            "╭───────╮",
            "│░░░░░░░│",
            "│░ YORU░│",
            "│░░░░░░░│",
            "╰───────╯",
        )
    rank, suit, _ = card
    suit = suit.replace("\ufe0f", "")
    return (
        "╭───────╮",
        f"│{rank:<7}│",
        f"│   {suit}   │",
        f"│{rank:>7}│",
        "╰───────╯",
    )


def blackjack_cards_block(
    cards: list[Card],
    *,
    visible_count: int | None = None,
    hidden_indexes: set[int] | None = None,
    max_per_row: int = 4,
) -> str:
    """Large card layout, wrapping long hands so Discord never becomes unreadable."""
    hidden_indexes = hidden_indexes or set()
    faces: list[tuple[str, ...]] = []
    for index, card in enumerate(cards):
        hidden = index in hidden_indexes or (visible_count is not None and index >= visible_count)
        faces.append(_card_face_lines(card, hidden=hidden))
    if not faces:
        faces.append(_card_face_lines(hidden=True))

    rendered: list[str] = []
    for start in range(0, len(faces), max_per_row):
        chunk = faces[start:start + max_per_row]
        for row in range(5):
            rendered.append(" ".join(face[row] for face in chunk))
        if start + max_per_row < len(faces):
            rendered.append("")
    return "```\n" + "\n".join(rendered) + "\n```"


def draw_card(deck: list[Card]) -> Card:
    if not deck:
        deck.extend(make_deck())
    return deck.pop()


def hand_value(cards: list[Card]) -> int:
    value = sum(card[2] for card in cards)
    aces = sum(1 for card in cards if card[0] == "A")
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


def split_value(card: Card) -> int:
    return card[2]


@dataclass(slots=True)
class BlackjackHand:
    cards: list[Card]
    bet: int
    from_split: bool = False
    doubled: bool = False
    stood: bool = False

    @property
    def value(self) -> int:
        return hand_value(self.cards)

    @property
    def busted(self) -> bool:
        return self.value > 21


class BlackjackView(discord.ui.View):
    def __init__(self, gambling: GamblingService, session: CasinoSession, player_name: str, avatar_url: str | None) -> None:
        super().__init__(timeout=casino_cfg.BLACKJACK_TIMEOUT_SECONDS)
        self.gambling = gambling
        self.session = session
        self.guild_id = session.guild_id
        self.user_id = session.user_id
        self.base_bet = session.bet
        self.player_name = player_name
        self.avatar_url = avatar_url
        self.deck = make_deck()
        self.hands = [BlackjackHand([draw_card(self.deck), draw_card(self.deck)], session.bet)]
        self.dealer = [draw_card(self.deck), draw_card(self.deck)]
        self.active_index = 0
        self.insurance_bet = 0
        self.insurance_offered = self.dealer[0][0] == "A"
        self.insurance_decided = not self.insurance_offered
        self.finished = False
        self.dealing = True
        self.animating = False
        self.message: discord.Message | None = None
        self._action_lock = asyncio.Lock()
        self._sync_buttons()

    @property
    def active_hand(self) -> BlackjackHand:
        return self.hands[self.active_index]

    def total_reserved(self) -> int:
        return sum(hand.bet for hand in self.hands) + self.insurance_bet

    def opening_is_finished(self) -> bool:
        if self.insurance_offered and not self.insurance_decided:
            return False
        return self._dealer_natural() or self._player_natural()

    def _player_natural(self) -> bool:
        return len(self.hands) == 1 and not self.hands[0].from_split and len(self.hands[0].cards) == 2 and self.hands[0].value == 21

    def _dealer_natural(self) -> bool:
        return len(self.dealer) == 2 and hand_value(self.dealer) == 21

    def _can_split(self) -> bool:
        hand = self.active_hand
        return (
            len(self.hands) == 1
            and len(hand.cards) == 2
            and not hand.doubled
            and split_value(hand.cards[0]) == split_value(hand.cards[1])
        )

    def _sync_buttons(self) -> None:
        pending_insurance = self.insurance_offered and not self.insurance_decided and not self.finished
        hand = self.active_hand if self.hands else None
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            if self.finished or self.dealing or self.animating:
                child.disabled = True
            elif child.custom_id == "bj:insurance":
                child.disabled = not pending_insurance
            elif child.custom_id == "bj:no_insurance":
                child.disabled = not pending_insurance
            elif pending_insurance:
                child.disabled = True
            elif child.custom_id == "bj:double":
                child.disabled = hand is None or len(hand.cards) != 2 or hand.doubled or hand.stood
            elif child.custom_id == "bj:split":
                child.disabled = not self._can_split()
            else:
                child.disabled = hand is None or hand.stood

    def embed(
        self,
        reveal: bool = False,
        result_text: str | None = None,
        color: discord.Color | None = None,
        *,
        phase: str | None = None,
        deal_stage: int | None = None,
        hide_active_last: bool = False,
    ) -> discord.Embed:
        if deal_stage is not None:
            # 0: backs, 1: first player card, 2: dealer upcard, 3: full player hand.
            player_visible = (0, 1, 1, 2)[max(0, min(3, deal_stage))]
            dealer_visible = (0, 0, 1, 1)[max(0, min(3, deal_stage))]
            dealer_hidden = set()
        else:
            player_visible = None
            dealer_visible = None
            dealer_hidden = set() if reveal else ({1} if len(self.dealer) > 1 else set())

        if phase is None:
            if self.dealing:
                phase = "🔀 **Keverés és osztás…**"
            elif self.finished:
                phase = "🏁 **A kör véget ért.**"
            elif self.insurance_offered and not self.insurance_decided:
                phase = "🛡️ **Az osztó Ászt mutat — döntsd el, kérsz-e insurance-t.**"
            else:
                phase = f"▶️ **Te jössz — Hand {self.active_index + 1}**"

        embed = discord.Embed(
            title="🃏 BLACKJACK",
            description=phase,
            color=color or BRAND,
        )
        embed.set_author(name=self.player_name, icon_url=self.avatar_url)

        if deal_stage is not None:
            dealer_block = blackjack_cards_block(self.dealer, visible_count=dealer_visible)
            dealer_value = "?" if dealer_visible < 1 else str(self.dealer[0][2])
        else:
            dealer_block = blackjack_cards_block(self.dealer, hidden_indexes=dealer_hidden)
            dealer_value = str(hand_value(self.dealer)) if reveal else (str(hand_value(self.dealer[:1])) if self.dealer else "?")

        embed.add_field(
            name=f"🎴 OSZTÓ  •  {dealer_value}",
            value=dealer_block,
            inline=False,
        )

        for index, hand in enumerate(self.hands):
            marker = "▶ " if index == self.active_index and not self.finished and not self.dealing else ""
            tags: list[str] = []
            if hand.from_split:
                tags.append("Split")
            if hand.doubled:
                tags.append("Double")
            tag_text = f"  •  {' / '.join(tags)}" if tags else ""

            hidden_indexes: set[int] = set()
            visible_count = player_visible if deal_stage is not None and index == 0 else None
            if hide_active_last and index == self.active_index and hand.cards:
                hidden_indexes.add(len(hand.cards) - 1)
            block = blackjack_cards_block(
                hand.cards,
                visible_count=visible_count,
                hidden_indexes=hidden_indexes,
            )
            embed.add_field(
                name=f"{marker}👤 HAND {index + 1}  •  {hand.value}{tag_text}",
                value=f"{block}**Tét:** {money(hand.bet)}",
                inline=False,
            )

        info = f"**Aktív tét:** {money(self.total_reserved())}"
        if self.insurance_offered:
            if not self.insurance_decided:
                insurance = "választásra vár"
            elif self.insurance_bet:
                insurance = money(self.insurance_bet)
            else:
                insurance = "nincs"
            info += f"  •  **Insurance:** {insurance}"
        embed.add_field(name="🎟️ Kör", value=info, inline=False)

        if result_text:
            embed.add_field(name="🏁 VÉGEREDMÉNY", value=result_text, inline=False)
        elif self.insurance_offered and not self.insurance_decided:
            embed.add_field(
                name="🛡️ Insurance",
                value="Az insurance ára az alaptét fele. Ha az osztónak Blackjackje van, 2:1 profitot fizet.",
                inline=False,
            )

        embed.set_footer(text="Yoru • Ász: 1 vagy 11 • Natural: 3:2")
        return embed

    async def animate_opening(self) -> None:
        if self.message is None or not self.dealing:
            self.dealing = False
            self._sync_buttons()
            return
        phases = (
            (1, "🃏 **Első lap…**"),
            (2, "🎴 **Az osztó lapja…**"),
            (3, "✨ **Kezdő kéz kész.**"),
        )
        try:
            for stage, phase in phases:
                await asyncio.sleep(casino_cfg.BLACKJACK_DEAL_FRAME_DELAY)
                await self.message.edit(embed=self.embed(deal_stage=stage, phase=phase), view=self)
        except discord.HTTPException:
            pass
        finally:
            self.dealing = False
            self._sync_buttons()
            try:
                await self.message.edit(embed=self.embed(), view=self)
            except discord.HTTPException:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Ez nem a te Blackjack játékod.", ephemeral=True)
            return False
        return True

    async def _edit(self, *, interaction: discord.Interaction | None = None, embed: discord.Embed | None = None) -> None:
        self._sync_buttons()
        embed = embed or self.embed()
        if interaction is not None and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        elif interaction is not None and interaction.message is not None:
            await interaction.message.edit(embed=embed, view=self)
        elif self.message is not None:
            await self.message.edit(embed=embed, view=self)

    async def _advance_or_finish(self, interaction: discord.Interaction) -> None:
        while self.active_index < len(self.hands) and (self.active_hand.stood or self.active_hand.busted or self.active_hand.value == 21):
            self.active_hand.stood = True
            if self.active_index + 1 < len(self.hands):
                self.active_index += 1
            else:
                await self.finish(interaction)
                return
        await self._edit(interaction=interaction)

    async def _animate_dealer(self, interaction: discord.Interaction | None) -> None:
        if all(hand.busted for hand in self.hands):
            return
        target_message = interaction.message if interaction is not None else self.message
        if target_message is None:
            return
        self.animating = True
        self._sync_buttons()
        try:
            # First frame keeps the hole card covered, then flips it. The large
            # card layout makes the reveal visible without spamming Discord edits.
            await target_message.edit(
                embed=self.embed(reveal=False, phase="🎴 **Az osztó felfedi a lapját…**"),
                view=self,
            )
            await asyncio.sleep(casino_cfg.BLACKJACK_DEALER_FRAME_DELAY)
            await target_message.edit(
                embed=self.embed(reveal=True, phase="🎴 **Az osztó játszik…**"),
                view=self,
            )
            frames = 2
            while hand_value(self.dealer) < 17:
                self.dealer.append(draw_card(self.deck))
                frames += 1
                await asyncio.sleep(casino_cfg.BLACKJACK_DEALER_FRAME_DELAY)
                await target_message.edit(
                    embed=self.embed(reveal=True, phase="🃏 **Az osztó húz…**"),
                    view=self,
                )
                if frames >= casino_cfg.BLACKJACK_DEALER_MAX_FRAMES:
                    while hand_value(self.dealer) < 17:
                        self.dealer.append(draw_card(self.deck))
                    break
        except discord.HTTPException:
            while hand_value(self.dealer) < 17:
                self.dealer.append(draw_card(self.deck))
        finally:
            self.animating = False


    async def finish(self, interaction: discord.Interaction | None = None, *, auto: bool = False) -> None:
        async with self._action_lock:
            if self.finished:
                return
            self.finished = True
            if interaction is not None and not interaction.response.is_done():
                await interaction.response.defer()

            dealer_natural = self._dealer_natural()
            player_natural = self._player_natural()
            if not dealer_natural and not all(hand.busted for hand in self.hands) and not player_natural:
                await self._animate_dealer(interaction)
            dealer_value = hand_value(self.dealer)

            payout = 0
            result_lines: list[str] = []
            if player_natural:
                if dealer_natural:
                    payout += self.base_bet
                    result_lines.append("🤝 **Natural vs natural:** push.")
                else:
                    total = self.gambling.casino.scaled_total_payout(casino_cfg.BLACKJACK_NATURAL_TOTAL_PAYOUT, self.session)
                    payout += int(round(self.base_bet * total))
                    result_lines.append("✨ **BLACKJACK!** — **3:2 profit**")
            else:
                for index, hand in enumerate(self.hands, start=1):
                    if hand.busted:
                        result_lines.append(f"Hand {index}: 💥 bust — vereség")
                    elif dealer_natural:
                        result_lines.append(f"Hand {index}: ❌ dealer Blackjack")
                    elif dealer_value > 21 or hand.value > dealer_value:
                        total = self.gambling.casino.scaled_total_payout(casino_cfg.BLACKJACK_WIN_TOTAL_PAYOUT, self.session)
                        payout += int(round(hand.bet * total))
                        result_lines.append(f"Hand {index}: ✅ nyert")
                    elif hand.value == dealer_value:
                        payout += hand.bet
                        result_lines.append(f"Hand {index}: 🤝 push")
                    else:
                        result_lines.append(f"Hand {index}: ❌ veszített")

            if self.insurance_bet:
                if dealer_natural:
                    total = self.gambling.casino.scaled_total_payout(casino_cfg.BLACKJACK_INSURANCE_TOTAL_PAYOUT, self.session)
                    insurance_payout = int(round(self.insurance_bet * total))
                    payout += insurance_payout
                    result_lines.append(f"🛡️ Insurance nyert: **{money(insurance_payout)}**")
                else:
                    result_lines.append("🛡️ Insurance elveszett.")

            settlement = await self.gambling.resolve_blackjack(self.session, payout, " | ".join(result_lines))
            if settlement.profit > 0:
                color = SUCCESS
                summary = f"\n💵 Profit: **+{money(settlement.profit)}**"
            elif settlement.profit < 0:
                color = DANGER
                summary = f"\n💵 Veszteség: **-{money(abs(settlement.profit))}**"
            else:
                color = GOLD
                summary = f"\n💵 Eredmény: **{money(0)}**"
            summary += f"\n💸 Kifizetés: **{money(settlement.payout)}**\n💰 Egyenleg: **{money(settlement.wallet)}**"
            self._sync_buttons()
            for child in self.children:
                child.disabled = True
            final_embed = self.embed(True, "\n".join(result_lines) + summary, color)
            target = interaction.message if interaction is not None else self.message
            if target is not None:
                await target.edit(embed=final_embed, view=self)
            self.stop()

    @discord.ui.button(label="Hit", emoji="🃏", style=discord.ButtonStyle.primary, custom_id="bj:hit", row=0)
    async def hit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            if self.finished:
                return
            self.active_hand.cards.append(draw_card(self.deck))
            self.animating = True
        await self._edit(
            interaction=interaction,
            embed=self.embed(hide_active_last=True, phase="🃏 **Lap húzása…**"),
        )
        await asyncio.sleep(casino_cfg.BLACKJACK_PLAYER_DRAW_DELAY)
        self.animating = False
        await self._advance_or_finish(interaction)

    @discord.ui.button(label="Stand", emoji="✋", style=discord.ButtonStyle.secondary, custom_id="bj:stand", row=0)
    async def stand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            if self.finished:
                return
            self.active_hand.stood = True
        await self._advance_or_finish(interaction)

    @discord.ui.button(label="Double", emoji="✖️", style=discord.ButtonStyle.success, custom_id="bj:double", row=0)
    async def double(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            if self.finished:
                return
            hand = self.active_hand
            if len(hand.cards) != 2 or hand.doubled:
                return await interaction.response.send_message("❌ Ezt a handet már nem duplázhatod.", ephemeral=True)
            try:
                await self.gambling.reserve_blackjack_extra(self.session, hand.bet, key=f"double:{self.active_index}", kind="double")
            except ValueError as exc:
                return await interaction.response.send_message(str(exc), ephemeral=True)
            hand.bet *= 2
            hand.doubled = True
            hand.cards.append(draw_card(self.deck))
            hand.stood = True
            self.animating = True
        await self._edit(
            interaction=interaction,
            embed=self.embed(hide_active_last=True, phase="✖️ **Double — utolsó lap…**"),
        )
        await asyncio.sleep(casino_cfg.BLACKJACK_PLAYER_DRAW_DELAY)
        self.animating = False
        await self._advance_or_finish(interaction)

    @discord.ui.button(label="Split", emoji="↔️", style=discord.ButtonStyle.success, custom_id="bj:split", row=0)
    async def split(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            if self.finished:
                return
            if not self._can_split():
                return await interaction.response.send_message("❌ A két kezdő lap értékének azonosnak kell lennie a Splithez.", ephemeral=True)
            hand = self.active_hand
            try:
                await self.gambling.reserve_blackjack_extra(self.session, hand.bet, key="split:1", kind="split")
            except ValueError as exc:
                return await interaction.response.send_message(str(exc), ephemeral=True)
            first, second = hand.cards
            self.hands = [
                BlackjackHand([first, draw_card(self.deck)], hand.bet, from_split=True),
                BlackjackHand([second, draw_card(self.deck)], hand.bet, from_split=True),
            ]
            self.active_index = 0
        await self._advance_or_finish(interaction)

    @discord.ui.button(label="Insurance", emoji="🛡️", style=discord.ButtonStyle.primary, custom_id="bj:insurance", row=1)
    async def insurance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            if not self.insurance_offered or self.insurance_decided or self.finished:
                return
            amount = max(1, self.base_bet // 2)
            try:
                await self.gambling.reserve_blackjack_extra(self.session, amount, key="insurance", kind="insurance")
            except ValueError as exc:
                return await interaction.response.send_message(str(exc), ephemeral=True)
            self.insurance_bet = amount
            self.insurance_decided = True
        if self._dealer_natural() or self._player_natural():
            await self.finish(interaction)
        else:
            await self._edit(interaction=interaction)

    @discord.ui.button(label="Nincs insurance", emoji="➡️", style=discord.ButtonStyle.secondary, custom_id="bj:no_insurance", row=1)
    async def no_insurance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            self.insurance_decided = True
        if self._dealer_natural() or self._player_natural():
            await self.finish(interaction)
        else:
            await self._edit(interaction=interaction)

    async def on_timeout(self) -> None:
        if self.finished:
            return
        self.insurance_decided = True
        for hand in self.hands:
            hand.stood = True
        await self.finish(auto=True)


# ---------------------------------------------------------------------------
# Slots UI — game-first visual framework
# ---------------------------------------------------------------------------


def _slot_winning_positions(spin) -> set[tuple[int, int]]:
    positions: set[tuple[int, int]] = set()
    for win in spin.line_wins:
        try:
            line = casino_cfg.SLOTS_V2_PAYLINES[win.line_index - 1]
        except (IndexError, TypeError):
            continue
        for column in range(min(win.count, len(line))):
            positions.add((int(line[column]), column))
    return positions


def slots_embed(
    user: discord.abc.User,
    result: SlotsGameResult,
    *,
    spin_index: int = 0,
    stopped_columns: int = 5,
    final: bool = False,
    image_filename: str = "slots.png",
) -> discord.Embed:
    spin = result.spins[min(spin_index, len(result.spins) - 1)]
    color = (SUCCESS if result.profit > 0 else (DANGER if result.profit < 0 else GOLD)) if final else BRAND
    embed = player_embed("🎰 SLOTS", user, color=color)
    free_total = max(0, len(result.spins) - 1)
    label = "Alap spin" if not spin.is_free_spin else f"Free Spin {spin.spin_number}/{free_total}"
    if final:
        embed.description = f"**{label}**" + (" • ✨ Nyerő sorok kiemelve" if spin.line_wins else "")
    else:
        embed.description = "🎰 **A tárcsák pörögnek…**"
    embed.set_image(url=f"attachment://{image_filename}")

    embed.add_field(name="🎟️ Tét", value=f"**{money(result.bet)}**", inline=True)
    if final:
        embed.add_field(name="💸 Win", value=f"**{money(result.payout)}**", inline=True)
        embed.add_field(name="✖️ Multiplier", value=f"**x{result.multiplier:.2f}**", inline=True)
    else:
        # Never reveal the already-computed result before the client animation ends.
        embed.add_field(name="💸 Win", value="**…**", inline=True)
        embed.add_field(name="✖️ Multiplier", value="**…**", inline=True)

    if final and free_total:
        embed.add_field(name="🎁 Free Spins", value=f"**{free_total}** lefutott", inline=True)
    if final:
        pnl = f"+{money(result.profit)}" if result.profit > 0 else (f"-{money(abs(result.profit))}" if result.profit < 0 else money(0))
        embed.add_field(name="📈 Nettó P/L", value=f"**{pnl}**", inline=True)
        embed.add_field(name="💰 Egyenleg", value=f"**{money(result.wallet)}**", inline=True)
        all_wins = [win for item in result.spins for win in item.line_wins]
        if all_wins:
            best = sorted(all_wins, key=lambda win: win.multiplier, reverse=True)[:3]
            lines = " • ".join(f"#{win.line_index} {win.symbol}×{win.count}" for win in best)
            embed.add_field(name="🏆 Nyerő sorok", value=lines, inline=False)
    embed.set_footer(text=f"Yoru • 5×3 • {len(casino_cfg.SLOTS_V2_PAYLINES)} payline")
    return embed


def slots_file(result: SlotsGameResult, *, spin_index: int = 0, stopped_columns: int = 5, final: bool = False) -> discord.File:
    """Static renderer kept for tests/fallbacks; runtime uses one-upload GIF animation."""
    spin = result.spins[min(spin_index, len(result.spins) - 1)]
    winners = _slot_winning_positions(spin) if final else set()
    free_total = max(0, len(result.spins) - 1)
    spin_label = "FREE SPIN" if spin.is_free_spin else "SPIN"
    if spin.is_free_spin:
        spin_label += f" {spin.spin_number}/{free_total}"
    fp = render_slots(spin.grid, stopped_columns=stopped_columns, winning_positions=winners, spin_label=spin_label)
    return discord.File(fp=fp, filename="slots.png")

# ---------------------------------------------------------------------------
# Roulette — individual multi-bet table
# ---------------------------------------------------------------------------


ROULETTE_LABELS = {
    "red": "🔴 Piros",
    "black": "⚫ Fekete",
    "green": "🟢 Zöld / 0",
    "even": "Páros",
    "odd": "Páratlan",
    "number": "🎯 Konkrét szám",
}


class RouletteBetModal(discord.ui.Modal):
    def __init__(self, view: "RouletteView", kind: str) -> None:
        super().__init__(title="🎡 Roulette", timeout=120)
        self.table = view
        self.kind = kind
        self.amount = discord.ui.TextInput(label="Tét", placeholder="pl. 250k, 2m vagy all", max_length=32)
        self.add_item(self.amount)
        self.number: discord.ui.TextInput | None = None
        if kind == "number":
            self.number = discord.ui.TextInput(label="Szám", placeholder="0–36", min_length=1, max_length=2)
            self.add_item(self.number)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or self.table.finished or self.table.spinning:
            return
        # Acknowledge the modal immediately. Balance lookup + SQLite reservation may
        # take longer under concurrent casino load; deferring prevents Discord's
        # 3-second interaction window from turning a valid bet into a failed UI.
        await interaction.response.defer()
        try:
            wallet, _ = await self.table.cog.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
            bet = parse_amount(str(self.amount.value), wallet)
            if self.kind == "green":
                choice = "0"
            elif self.kind == "number":
                raw = str(self.number.value if self.number else "").strip()
                if not raw.isdigit() or not 0 <= int(raw) <= 36:
                    raise ValueError("A szám 0 és 36 között legyen.")
                choice = raw
            else:
                choice = self.kind
            await self.table.add_bet(choice, bet)
        except ValueError as exc:
            await interaction.followup.send(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
            return
        await self.table.refresh_message()


class RouletteView(discord.ui.View):
    def __init__(self, cog: "GamblingCog", owner: discord.abc.User, guild_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.owner = owner
        self.owner_id = owner.id
        self.guild_id = guild_id
        self.session_id: str | None = None
        self.bets: list[RouletteBet] = []
        self.message: discord.Message | None = None
        self.spinning = False
        self.finished = False
        self._action_lock = asyncio.Lock()
        self._sync_buttons()

    @property
    def total_bet(self) -> int:
        return sum(item.amount for item in self.bets)

    def _sync_buttons(self) -> None:
        disabled = self.spinning or self.finished
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            child.disabled = disabled
            # Do not rely on the decorated callback attribute being the runtime
            # Button instance. This is stable across discord.py View internals.
            if child.label == "Pörgetés":
                child.disabled = disabled or not self.bets

    def bets_text(self, *, max_rows: int = 8) -> str:
        if not self.bets:
            return "Még nincs fogadás. Válassz lent egy típust."
        grouped: dict[str, int] = {}
        for item in self.bets:
            grouped[item.label] = grouped.get(item.label, 0) + item.amount
        rows = [f"**{label}:** {money(amount)}" for label, amount in grouped.items()]
        if len(rows) > max_rows:
            hidden = len(rows) - max_rows
            rows = rows[:max_rows] + [f"… és még **{hidden}** típus"]
        return "\n".join(rows)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ez nem a te Roulette játékod.", ephemeral=True)
            return False
        return True

    async def add_bet(self, choice: str, bet: int) -> None:
        if len(self.bets) >= casino_cfg.ROULETTE_V2_MAX_BETS_PER_PLAYER:
            raise ValueError(f"Egy körben legfelj {casino_cfg.ROULETTE_V2_MAX_BETS_PER_PLAYER} külön fogadás lehet.")
        session_id, roulette_bet = await self.cog.gambling.reserve_roulette_bet(
            self.guild_id,
            self.owner_id,
            choice,
            bet,
            session_id=self.session_id,
            bet_index=len(self.bets) + 1,
        )
        self.session_id = session_id
        self.bets.append(roulette_bet)
        self._sync_buttons()

    async def refresh_message(self) -> None:
        if self.message is None:
            return
        self._sync_buttons()
        try:
            await self.message.edit(embed=self.cog.roulette_lobby_embed(self.owner, self.bets), view=self)
        except discord.HTTPException:
            pass

    async def _finish_with_error(self, reason: str) -> None:
        if self.session_id is not None:
            try:
                await self.cog.gambling.refund_roulette_session(self.session_id, reason)
            except ValueError:
                pass
        self.finished = True
        self._sync_buttons()

    @discord.ui.button(label="Piros", emoji="🔴", style=discord.ButtonStyle.danger, row=0)
    async def red(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RouletteBetModal(self, "red"))

    @discord.ui.button(label="Fekete", emoji="⚫", style=discord.ButtonStyle.secondary, row=0)
    async def black(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RouletteBetModal(self, "black"))

    @discord.ui.button(label="Zöld / 0", emoji="🟢", style=discord.ButtonStyle.success, row=0)
    async def green(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RouletteBetModal(self, "green"))

    @discord.ui.button(label="Páros", style=discord.ButtonStyle.primary, row=1)
    async def even(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RouletteBetModal(self, "even"))

    @discord.ui.button(label="Páratlan", style=discord.ButtonStyle.primary, row=1)
    async def odd(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RouletteBetModal(self, "odd"))

    @discord.ui.button(label="Konkrét szám", emoji="🎯", style=discord.ButtonStyle.primary, row=1)
    async def number(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RouletteBetModal(self, "number"))

    @discord.ui.button(label="Pörgetés", emoji="🎡", style=discord.ButtonStyle.success, row=2)
    async def spin(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            if self.spinning or self.finished:
                return
            if not self.bets or self.session_id is None:
                return await interaction.response.send_message("Tegyél legalább egy fogadást a pörgetés előtt.", ephemeral=True)
            self.spinning = True
            self._sync_buttons()
            await interaction.response.defer()
            try:
                result = await self.cog.gambling.settle_roulette_bets(self.session_id, list(self.bets))
            except ValueError as exc:
                self.spinning = False
                self._sync_buttons()
                return await interaction.followup.send(embed=error_embed(interaction.user, str(exc)), ephemeral=True)

            number = int(result.details.get("number", 0))
            try:
                fp = await self.cog._render_visual(
                    render_roulette_animation,
                    number,
                    frame_count=casino_cfg.ROULETTE_V2_SPIN_FRAMES,
                    player_name=self.owner.display_name,
                )
                file = discord.File(fp=fp, filename="roulette.gif")
                if self.message is not None:
                    await self.message.edit(
                        embed=self.cog.roulette_spin_embed(self.owner, self.bets, result=None, image_filename="roulette.gif"),
                        attachments=[file],
                        view=self,
                    )
                    await asyncio.sleep(casino_cfg.ROULETTE_V2_ANIMATION_SECONDS)
                    final_fp = await self.cog._render_visual(
                        render_roulette,
                        ball_number=number,
                        result_number=number,
                        phase="RESULT",
                        player_name=self.owner.display_name,
                    )
                    final_file = discord.File(fp=final_fp, filename="roulette.png")
                    self.finished = True
                    self.spinning = False
                    self._sync_buttons()
                    await self.message.edit(
                        embed=self.cog.roulette_spin_embed(self.owner, self.bets, result=result, number=number, image_filename="roulette.png"),
                        attachments=[final_file],
                        view=self,
                    )
            except discord.HTTPException:
                self.finished = True
                self.spinning = False
                self._sync_buttons()
            finally:
                if self.session_id is not None:
                    await self.cog.gambling.casino.release_player_game(self.session_id)

    @discord.ui.button(label="Mégse", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            if self.spinning or self.finished:
                return
            if self.session_id is not None:
                try:
                    await self.cog.gambling.refund_roulette_session(self.session_id, "roulette_user_cancel")
                except ValueError:
                    pass
            self.finished = True
            self._sync_buttons()
            await interaction.response.edit_message(
                embed=self.cog.roulette_cancel_embed(self.owner, self.total_bet),
                view=self,
            )

    async def on_timeout(self) -> None:
        if self.finished or self.spinning:
            return
        await self._finish_with_error("roulette_timeout")
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class GamblingCog(commands.Cog):
    def __init__(self, bot: commands.Bot, gambling: GamblingService) -> None:
        self.bot = bot
        self.gambling = gambling
        # Pillow/GIF encoding is CPU-bound. Keep it off the asyncio event loop
        # and cap parallel renders so 5+ players do not make the whole bot stutter.
        self._visual_render_semaphore = asyncio.Semaphore(max(1, int(casino_cfg.SLOTS_V2_RENDER_CONCURRENCY)))

    async def _render_visual(self, func, *args, **kwargs):
        async with self._visual_render_semaphore:
            return await asyncio.to_thread(func, *args, **kwargs)

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

    # ------------------------------------------------------------- quick games
    @staticmethod
    def _quick_result_embed(title: str, user: discord.abc.User, result: QuickGameResult | None, *, bet: int, image_filename: str, detail: str = "") -> discord.Embed:
        color = BRAND if result is None else (SUCCESS if result.profit > 0 else (DANGER if result.profit < 0 else GOLD))
        embed = player_embed(title, user, color=color)
        embed.set_image(url=f"attachment://{image_filename}")
        if detail:
            embed.description = detail
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

    async def _finish_quick_visual(self, message: discord.Message, user: discord.abc.User, result: QuickGameResult, *, title: str, final_renderer, final_args: tuple, final_kwargs: dict, detail: str) -> None:
        try:
            await asyncio.sleep(casino_cfg.QUICK_GAME_ANIMATION_SECONDS)
            fp = await self._render_visual(final_renderer, *final_args, **final_kwargs)
            final_file = discord.File(fp=fp, filename=f"{result.game}.png")
            await message.edit(
                embed=self._quick_result_embed(title, user, result, bet=result.bet, image_filename=f"{result.game}.png", detail=detail),
                attachments=[final_file],
            )
        except discord.HTTPException:
            pass
        finally:
            await self.gambling.casino.release_player_game(result.game_id)

    async def run_coinflip_interaction(self, interaction: discord.Interaction, choice: str, bet: int) -> None:
        result: QuickGameResult | None = None
        handed_off = False
        try:
            result = await self.gambling.coinflip_visual(interaction.guild_id, interaction.user.id, choice, bet)
            rolled = str(result.details["rolled"])
            fp = await self._render_visual(render_coinflip_animation, rolled, player_name=interaction.user.display_name)
            file = discord.File(fp=fp, filename="coinflip.gif")
            await interaction.response.send_message(
                embed=self._quick_result_embed("🪙 COINFLIP", interaction.user, None, bet=bet, image_filename="coinflip.gif", detail=f"🎯 Tipp: **{str(result.details['choice']).title()}**"),
                file=file,
            )
            message = await interaction.original_response()
            handed_off = True
            await self._finish_quick_visual(
                message, interaction.user, result, title="🪙 COINFLIP", final_renderer=render_coinflip,
                final_args=(rolled,), final_kwargs={"player_name": interaction.user.display_name},
                detail=f"🎯 Tipp: **{str(result.details['choice']).title()}** • Eredmény: **{rolled.title()}**",
            )
        except ValueError as exc:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        finally:
            if result is not None and not handed_off:
                await self.gambling.casino.release_player_game(result.game_id)

    async def run_coinflip_prefix(self, ctx: commands.Context, choice: str, bet: int) -> None:
        result: QuickGameResult | None = None
        handed_off = False
        try:
            result = await self.gambling.coinflip_visual(ctx.guild.id, ctx.author.id, choice, bet)
            rolled = str(result.details["rolled"])
            fp = await self._render_visual(render_coinflip_animation, rolled, player_name=ctx.author.display_name)
            msg = await ctx.send(
                embed=self._quick_result_embed("🪙 COINFLIP", ctx.author, None, bet=bet, image_filename="coinflip.gif", detail=f"🎯 Tipp: **{str(result.details['choice']).title()}**"),
                file=discord.File(fp=fp, filename="coinflip.gif"),
            )
            handed_off = True
            await self._finish_quick_visual(msg, ctx.author, result, title="🪙 COINFLIP", final_renderer=render_coinflip, final_args=(rolled,), final_kwargs={"player_name": ctx.author.display_name}, detail=f"🎯 Tipp: **{str(result.details['choice']).title()}** • Eredmény: **{rolled.title()}**")
        except ValueError as exc:
            await ctx.send(embed=error_embed(ctx.author, str(exc)))
        finally:
            if result is not None and not handed_off:
                await self.gambling.casino.release_player_game(result.game_id)

    async def run_dice_interaction(self, interaction: discord.Interaction, mode: str, bet: int, guess: int | None = None) -> None:
        result: QuickGameResult | None = None
        handed_off = False
        try:
            result = await self.gambling.dice_visual(interaction.guild_id, interaction.user.id, mode, bet, guess)
            values = tuple(int(v) for v in result.details["dice"])
            mode_label = str(result.details["mode"]).upper()
            fp = await self._render_visual(render_dice_animation, values, player_name=interaction.user.display_name, mode_label=mode_label)
            detail = f"🎯 Mód: **{mode_label}**" + (f" • Tipp: **{guess}**" if guess is not None else "")
            await interaction.response.send_message(embed=self._quick_result_embed("🎲 DICE", interaction.user, None, bet=bet, image_filename="dice.gif", detail=detail), file=discord.File(fp=fp, filename="dice.gif"))
            msg = await interaction.original_response(); handed_off = True
            final_detail = detail + f" • Dobás: **{' + '.join(map(str, values))}**"
            await self._finish_quick_visual(msg, interaction.user, result, title="🎲 DICE", final_renderer=render_dice, final_args=(values,), final_kwargs={"player_name": interaction.user.display_name, "mode_label": mode_label}, detail=final_detail)
        except ValueError as exc:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        finally:
            if result is not None and not handed_off:
                await self.gambling.casino.release_player_game(result.game_id)

    async def run_dice_prefix(self, ctx: commands.Context, mode: str, bet: int, guess: int | None = None) -> None:
        result: QuickGameResult | None = None
        handed_off = False
        try:
            result = await self.gambling.dice_visual(ctx.guild.id, ctx.author.id, mode, bet, guess)
            values = tuple(int(v) for v in result.details["dice"]); mode_label = str(result.details["mode"]).upper()
            fp = await self._render_visual(render_dice_animation, values, player_name=ctx.author.display_name, mode_label=mode_label)
            detail = f"🎯 Mód: **{mode_label}**" + (f" • Tipp: **{guess}**" if guess is not None else "")
            msg = await ctx.send(embed=self._quick_result_embed("🎲 DICE", ctx.author, None, bet=bet, image_filename="dice.gif", detail=detail), file=discord.File(fp=fp, filename="dice.gif")); handed_off = True
            await self._finish_quick_visual(msg, ctx.author, result, title="🎲 DICE", final_renderer=render_dice, final_args=(values,), final_kwargs={"player_name": ctx.author.display_name, "mode_label": mode_label}, detail=detail + f" • Dobás: **{' + '.join(map(str, values))}**")
        except ValueError as exc:
            await ctx.send(embed=error_embed(ctx.author, str(exc)))
        finally:
            if result is not None and not handed_off:
                await self.gambling.casino.release_player_game(result.game_id)

    @app_commands.command(name="coinflip", description="Fej vagy írás pénztétért.")
    @app_commands.choices(oldal=[app_commands.Choice(name="Fej", value="fej"), app_commands.Choice(name="Írás", value="írás")])
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def coinflip(self, interaction: discord.Interaction, oldal: app_commands.Choice[str], osszeg: str) -> None:
        if interaction.guild_id is None or not await self._guard(interaction):
            return
        wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            bet = parse_amount(osszeg, wallet)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await self.run_coinflip_interaction(interaction, oldal.value, bet)

    DICE_MODE_CHOICES = [
        app_commands.Choice(name="Exact 1–6", value="exact"),
        app_commands.Choice(name="High (4–6)", value="high"),
        app_commands.Choice(name="Low (1–3)", value="low"),
        app_commands.Choice(name="Odd", value="odd"),
        app_commands.Choice(name="Even", value="even"),
        app_commands.Choice(name="Over 7 (2 dice)", value="over7"),
        app_commands.Choice(name="Under 7 (2 dice)", value="under7"),
        app_commands.Choice(name="Exactly 7 (2 dice)", value="seven"),
    ]

    @app_commands.command(name="dice", description="Dice: exact, high/low, odd/even vagy 2 kockás módok.")
    @app_commands.choices(mod=DICE_MODE_CHOICES)
    @app_commands.describe(osszeg="Tét", tipped="Exact módnál 1–6")
    async def dice(self, interaction: discord.Interaction, mod: app_commands.Choice[str], osszeg: str, tipped: app_commands.Range[int, 1, 6] | None = None) -> None:
        if interaction.guild_id is None or not await self._guard(interaction):
            return
        wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            bet = parse_amount(osszeg, wallet)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await self.run_dice_interaction(interaction, mod.value, bet, int(tipped) if tipped is not None else None)

    # ---------------------------------------------------------------- Slots
    async def _slots_animation_file(self, result: SlotsGameResult, user: discord.abc.User) -> discord.File:
        base_spin = result.spins[0]
        fp = await self._render_visual(
            render_slots_animation,
            base_spin.grid,
            winning_positions=_slot_winning_positions(base_spin),
            spin_label="SPIN",
            player_name=user.display_name,
        )
        return discord.File(fp=fp, filename="slots.gif")

    async def _slots_final_file(self, result: SlotsGameResult, user: discord.abc.User) -> discord.File:
        spin = result.spins[-1]
        free_total = max(0, len(result.spins) - 1)
        label = "SPIN" if not spin.is_free_spin else f"FREE SPIN {spin.spin_number}/{free_total}"
        fp = await self._render_visual(
            render_slots,
            spin.grid,
            stopped_columns=5,
            winning_positions=_slot_winning_positions(spin),
            spin_label=label,
            player_name=user.display_name,
        )
        return discord.File(fp=fp, filename="slots.png")

    async def run_slots_interaction(self, interaction: discord.Interaction, bet: int) -> None:
        if interaction.guild_id is None:
            return
        await interaction.response.defer()
        result: SlotsGameResult | None = None
        handed_off = False
        try:
            result = await self.gambling.slots_v2(interaction.guild_id, interaction.user.id, bet)
            animation = await self._slots_animation_file(result, interaction.user)
            await interaction.edit_original_response(
                embed=slots_embed(interaction.user, result, stopped_columns=0, image_filename="slots.gif"),
                attachments=[animation],
                view=None,
            )
            message = await interaction.original_response()
            handed_off = True
            await self._animate_slots_message(message, interaction.user, result)
        except ValueError as exc:
            return await interaction.edit_original_response(embed=error_embed(interaction.user, str(exc)), view=None)
        except Exception:
            if result is not None:
                try:
                    final_file = await self._slots_final_file(result, interaction.user)
                    await interaction.edit_original_response(
                        embed=slots_embed(interaction.user, result, spin_index=len(result.spins)-1, final=True, image_filename="slots.png"),
                        attachments=[final_file],
                        view=None,
                    )
                except Exception:
                    pass
            raise
        finally:
            if result is not None and not handed_off:
                await self.gambling.casino.release_player_game(result.game_id)

    async def run_slots_prefix(self, ctx: commands.Context, bet: int) -> None:
        result: SlotsGameResult | None = None
        handed_off = False
        try:
            result = await self.gambling.slots_v2(ctx.guild.id, ctx.author.id, bet)
            animation = await self._slots_animation_file(result, ctx.author)
            message = await ctx.send(
                embed=slots_embed(ctx.author, result, stopped_columns=0, image_filename="slots.gif"),
                file=animation,
            )
            handed_off = True
            await self._animate_slots_message(message, ctx.author, result)
        except ValueError as exc:
            return await ctx.send(embed=error_embed(ctx.author, str(exc)))
        finally:
            if result is not None and not handed_off:
                await self.gambling.casino.release_player_game(result.game_id)

    async def _animate_slots_message(self, message: discord.Message, user: discord.abc.User, result: SlotsGameResult) -> None:
        """Play the GIF once, then replace it with a static final PNG."""
        try:
            await asyncio.sleep(casino_cfg.SLOTS_V2_ANIMATION_SECONDS)
            final_index = len(result.spins) - 1
            final_file = await self._slots_final_file(result, user)
            await message.edit(
                embed=slots_embed(
                    user, result, spin_index=final_index, stopped_columns=5,
                    final=True, image_filename="slots.png",
                ),
                attachments=[final_file],
            )
        except discord.HTTPException:
            pass
        finally:
            await self.gambling.casino.release_player_game(result.game_id)

    @app_commands.command(name="slots", description="Slots: 5×3 grid, Wild, Scatter és Free Spins.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def slots(self, interaction: discord.Interaction, osszeg: str) -> None:
        if interaction.guild_id is None or not await self._guard(interaction):
            return
        wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            bet = parse_amount(osszeg, wallet)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await self.run_slots_interaction(interaction, bet)

    # ------------------------------------------------------------- Roulette
    def roulette_lobby_embed(self, user: discord.abc.User, bets: list[RouletteBet] | None = None) -> discord.Embed:
        bets = bets or []
        embed = player_embed("🎡 ROULETTE", user, color=BRAND)
        embed.description = "**Rakj több fogadást ugyanarra a körre, majd nyomd meg a Pörgetés gombot.**"
        embed.set_image(url="attachment://roulette.png")
        if bets:
            grouped: dict[str, int] = {}
            for item in bets:
                grouped[item.label] = grouped.get(item.label, 0) + item.amount
            text = "\n".join(f"**{label}:** {money(amount)}" for label, amount in list(grouped.items())[:8])
            embed.add_field(name=f"🎟️ Fogadások • {len(bets)}/{casino_cfg.ROULETTE_V2_MAX_BETS_PER_PLAYER}", value=text, inline=False)
            embed.add_field(name="💵 Össztét", value=f"**{money(sum(item.amount for item in bets))}**", inline=True)
        else:
            embed.add_field(name="🎟️ Fogadások", value="🔴 Piros • ⚫ Fekete • 🟢 0 • Páros • Páratlan • 🎯 0–36", inline=False)
        embed.add_field(name="💸 Kifizetés", value="Szín/Páros/Páratlan: **2×** • Konkrét szám: **36×**", inline=False)
        embed.set_footer(text="Yoru • Európai roulette • egyéni kör • multi-bet")
        return embed

    def roulette_spin_embed(
        self,
        user: discord.abc.User,
        bets: list[RouletteBet],
        *,
        result: GambleResult | None = None,
        number: int | None = None,
        image_filename: str = "roulette.png",
    ) -> discord.Embed:
        total_bet = sum(item.amount for item in bets)
        if result is None:
            embed = player_embed("🎡 ROULETTE", user, color=BRAND)
            embed.description = "🎡 **A kerék pörög…**"
            embed.set_image(url=f"attachment://{image_filename}")
            embed.add_field(name="🎟️ Fogadások", value=f"**{len(bets)}**", inline=True)
            embed.add_field(name="💵 Össztét", value=f"**{money(total_bet)}**", inline=True)
            embed.set_footer(text="Yoru • a golyó még mozgásban van")
            return embed
        color = SUCCESS if result.profit > 0 else (DANGER if result.profit < 0 else GOLD)
        embed = player_embed("🎡 ROULETTE", user, color=color)
        emoji = roulette_result_emoji(int(number or 0))
        embed.description = f"# {emoji} **{number}**"
        embed.set_image(url=f"attachment://{image_filename}")
        pnl = f"+{money(result.profit)}" if result.profit > 0 else (f"-{money(abs(result.profit))}" if result.profit < 0 else money(0))
        embed.add_field(name="🎟️ Össztét", value=f"**{money(total_bet)}**", inline=True)
        embed.add_field(name="💵 P/L", value=f"**{pnl}**", inline=True)
        embed.add_field(name="💰 Egyenleg", value=f"**{money(result.wallet)}**", inline=True)
        winning = result.details.get("winning_bets", [])
        if winning:
            grouped: dict[str, int] = {}
            for item in winning:
                grouped[item.label] = grouped.get(item.label, 0) + item.amount
            embed.add_field(name="✅ Nyertes fogadások", value=" • ".join(grouped.keys()), inline=False)
        embed.set_footer(text="Yoru • Roulette")
        return embed

    def roulette_cancel_embed(self, user: discord.abc.User, total_bet: int) -> discord.Embed:
        embed = player_embed("🎡 ROULETTE", user, color=GOLD)
        embed.description = "↩️ **A kör megszakítva.**"
        if total_bet:
            embed.add_field(name="💵 Visszatérítve", value=f"**{money(total_bet)}**", inline=True)
        embed.set_footer(text="Yoru • Roulette")
        return embed

    async def _roulette_lobby_file(self, user: discord.abc.User) -> discord.File:
        fp = await self._render_visual(render_roulette, phase="PLACE YOUR BET", player_name=user.display_name)
        return discord.File(fp=fp, filename="roulette.png")

    async def _create_roulette_view(
        self,
        user: discord.abc.User,
        guild_id: int,
        *,
        choice: str | None = None,
        bet: int | None = None,
    ) -> RouletteView:
        view = RouletteView(self, user, guild_id)
        if choice is not None and bet is not None:
            await view.add_bet(choice, bet)
        return view

    async def open_roulette_interaction(self, interaction: discord.Interaction, *, choice: str | None = None, bet: int | None = None) -> None:
        if interaction.guild_id is None:
            return
        try:
            view = await self._create_roulette_view(interaction.user, interaction.guild_id, choice=choice, bet=bet)
            file = await self._roulette_lobby_file(interaction.user)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await interaction.response.send_message(embed=self.roulette_lobby_embed(interaction.user, view.bets), file=file, view=view)
        view.message = await interaction.original_response()

    async def open_roulette_prefix(self, ctx: commands.Context, *, choice: str | None = None, bet: int | None = None) -> None:
        try:
            view = await self._create_roulette_view(ctx.author, ctx.guild.id, choice=choice, bet=bet)
            file = await self._roulette_lobby_file(ctx.author)
        except ValueError as exc:
            return await ctx.send(embed=error_embed(ctx.author, str(exc)))
        view.message = await ctx.send(embed=self.roulette_lobby_embed(ctx.author, view.bets), file=file, view=view)

    @app_commands.command(name="roulette", description="Egyéni Roulette: több fogadás egy pörgetésre.")
    @app_commands.describe(valasztas="opcionális: piros, fekete, zöld/0, páros, páratlan vagy 0–36", osszeg="opcionális kezdő tét vagy all")
    async def roulette(self, interaction: discord.Interaction, valasztas: str | None = None, osszeg: str | None = None) -> None:
        if interaction.guild_id is None or not await self._guard(interaction):
            return
        if (valasztas is None) != (osszeg is None):
            return await interaction.response.send_message(embed=error_embed(interaction.user, "A választást és a tétet együtt add meg, vagy hagyd üresen mindkettőt."), ephemeral=True)
        choice = None
        bet = None
        if valasztas is not None and osszeg is not None:
            wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
            try:
                parse_roulette_choice(valasztas)
                bet = parse_amount(osszeg, wallet)
                choice = valasztas
            except ValueError as exc:
                return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await self.open_roulette_interaction(interaction, choice=choice, bet=bet)

    # ------------------------------------------------------------- Blackjack
    async def start_blackjack(self, guild_id: int, user: discord.abc.User, bet: int) -> BlackjackView:
        session = await self.gambling.reserve_blackjack(guild_id, user.id, bet)
        await self.gambling.casino.mark_waiting(session.game_id)
        return BlackjackView(self.gambling, session, user.display_name, getattr(user.display_avatar, "url", None))

    async def open_blackjack_interaction(self, interaction: discord.Interaction, bet: int) -> None:
        if interaction.guild_id is None:
            return
        try:
            view = await self.start_blackjack(interaction.guild_id, interaction.user, bet)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await interaction.response.send_message(embed=view.embed(deal_stage=0), view=view)
        view.message = await interaction.original_response()
        await view.animate_opening()
        if view.opening_is_finished():
            await view.finish(auto=True)

    @app_commands.command(name="blackjack", description="Blackjack: Double, Split, Insurance és 3:2 natural.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def blackjack(self, interaction: discord.Interaction, osszeg: str) -> None:
        if interaction.guild_id is None or not await self._guard(interaction):
            return
        wallet, _ = await self.gambling.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            bet = parse_amount(osszeg, wallet)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await self.open_blackjack_interaction(interaction, bet)
