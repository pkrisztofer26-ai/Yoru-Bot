from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from app.amounts import parse_amount
from app.cogs.access_utils import handle_wrong_economy_channel
from app.database import Database
from app.services.economy import EconomyService
from app.services.social_economy import SocialEconomyService, Duel
from app import social_config as cfg
from app import casino_config as casino_cfg
from app.casino_pvp_visuals import (
    render_duel_challenge, render_pvp_coinflip_animation, render_pvp_coinflip,
    render_pvp_dice_animation, render_pvp_dice, render_pvp_rps_wait,
    render_pvp_rps_animation, render_pvp_rps,
)
from app.ui import base_embed, error_embed, money, SUCCESS, GOLD


def _category_id(channel: Any) -> int | None:
    category = getattr(channel, "category", None)
    return int(category.id) if category is not None else None


def _fmt_dt(dt: datetime) -> str:
    return f"<t:{int(dt.timestamp())}:R>"


def _game_label(game: str) -> str:
    return {"coinflip":"🪙 Coinflip Duel","dice":"🎲 Dice Duel","rps":"✊ RPS Duel"}.get(game, game)


class DuelChallengeView(discord.ui.View):
    def __init__(self, cog: "SocialEconomyCog", duel: Duel, *, timeout: float = cfg.PVP_CHALLENGE_SECONDS) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.duel = duel
        self.message: discord.Message | None = None
        self._lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.duel.target_id:
            await interaction.response.send_message("❌ Ezt a kihívást csak a megjelölt játékos kezelheti.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Elfogadom", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async with self._lock:
            try:
                duel = await self.cog.social.accept_duel(self.duel.id, interaction.user.id)
            except ValueError as exc:
                return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            self.duel = duel
            await interaction.response.defer()
            left_name, right_name = self.cog._duel_names(duel)

            if duel.game == "rps":
                fp = await self.cog._render_pvp(render_pvp_rps_wait, left_name, right_name, duel.stake)
                embed = self.cog._rps_wait_embed(duel, image_filename="pvp_rps_wait.png")
                runtime = await self.cog.social.gameplay.social(duel.guild_id)
                view = RPSDuelView(self.cog, duel, timeout=runtime.pvp_rps_seconds)
                view.message = interaction.message
                await interaction.message.edit(embed=embed, attachments=[discord.File(fp=fp, filename="pvp_rps_wait.png")], view=view)
                self.stop()
                return

            if duel.game == "coinflip":
                winner = random.choice([duel.challenger_id, duel.target_id])
                winner_name = left_name if winner == duel.challenger_id else right_name
                anim = await self.cog._render_pvp(render_pvp_coinflip_animation, left_name, right_name, duel.stake, winner_name)
                anim_name = "pvp_coinflip.gif"
                embed = self.cog._duel_live_embed(duel, "🪙 Feldobás…", anim_name)
                await interaction.message.edit(embed=embed, attachments=[discord.File(fp=anim, filename=anim_name)], view=None)
                await asyncio.sleep(cfg.PVP_VISUAL_ANIMATION_SECONDS)
                result = await self.cog.social.settle_duel(duel.id, winner)
                final = await self.cog._render_pvp(render_pvp_coinflip, left_name, right_name, duel.stake, winner_name)
                embed = self.cog._duel_result_embed(duel, winner, result, image_filename="pvp_coinflip.png")
                await interaction.message.edit(embed=embed, attachments=[discord.File(fp=final, filename="pvp_coinflip.png")], view=None)
            else:
                a = random.randint(1, 100); b = random.randint(1, 100)
                while a == b:
                    a = random.randint(1, 100); b = random.randint(1, 100)
                winner = duel.challenger_id if a > b else duel.target_id
                winner_name = left_name if winner == duel.challenger_id else right_name
                anim = await self.cog._render_pvp(render_pvp_dice_animation, left_name, right_name, duel.stake, a, b, winner_name)
                await interaction.message.edit(embed=self.cog._duel_live_embed(duel, "🎲 Dobás…", "pvp_dice.gif"), attachments=[discord.File(fp=anim, filename="pvp_dice.gif")], view=None)
                await asyncio.sleep(cfg.PVP_VISUAL_ANIMATION_SECONDS)
                result = await self.cog.social.settle_duel(duel.id, winner)
                final = await self.cog._render_pvp(render_pvp_dice, left_name, right_name, duel.stake, a, b, winner_name)
                embed = self.cog._duel_result_embed(duel, winner, result, image_filename="pvp_dice.png", detail=f"🎲 **{left_name}: {a}** • **{right_name}: {b}**")
                await interaction.message.edit(embed=embed, attachments=[discord.File(fp=final, filename="pvp_dice.png")], view=None)
            self.stop()

    @discord.ui.button(label="Elutasítom", emoji="✖️", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        ok = await self.cog.social.decline_duel(self.duel.id, interaction.user.id)
        if not ok:
            return await interaction.response.send_message("❌ Ez a duel már nem aktív.", ephemeral=True)
        embed = base_embed("⚔️ Duel elutasítva", f"<@{self.duel.target_id}> elutasította a kihívást.")
        await interaction.response.edit_message(embed=embed, view=None, attachments=[])
        self.stop()

    async def on_timeout(self) -> None:
        await self.cog.social.cleanup_duels()
        if self.message:
            try:
                await self.message.edit(embed=base_embed("⌛ Duel lejárt", "A kihívást nem fogadták el időben."), view=None, attachments=[])
            except discord.HTTPException:
                pass


class RPSDuelView(discord.ui.View):
    def __init__(self, cog: "SocialEconomyCog", duel: Duel, *, timeout: float = cfg.PVP_RPS_SECONDS) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.duel = duel
        self.message: discord.Message | None = None
        self._lock = asyncio.Lock()

    async def _choose(self, interaction: discord.Interaction, choice: str) -> None:
        if interaction.user.id not in {self.duel.challenger_id, self.duel.target_id}:
            return await interaction.response.send_message("❌ Nem vagy résztvevő ebben a duelben.", ephemeral=True)
        async with self._lock:
            try:
                duel = await self.cog.social.choose_rps(self.duel.id, interaction.user.id, choice)
            except ValueError as exc:
                return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            self.duel = duel
            if not duel.challenger_choice or not duel.target_choice:
                return await interaction.response.send_message("✅ Választás rögzítve. Várjuk a másik játékost.", ephemeral=True)

            await interaction.response.defer()
            a, b = duel.challenger_choice, duel.target_choice
            if a == b:
                winner = None
            else:
                wins = {("rock","scissors"), ("scissors","paper"), ("paper","rock")}
                winner = duel.challenger_id if (a,b) in wins else duel.target_id
            left_name, right_name = self.cog._duel_names(duel)
            winner_name = None if winner is None else (left_name if winner == duel.challenger_id else right_name)
            anim = await self.cog._render_pvp(render_pvp_rps_animation, left_name, right_name, duel.stake, a, b, winner_name)
            if self.message is not None:
                await self.message.edit(embed=self.cog._duel_live_embed(duel, "✊ Reveal…", "pvp_rps.gif"), attachments=[discord.File(fp=anim, filename="pvp_rps.gif")], view=None)
            await asyncio.sleep(cfg.PVP_RPS_VISUAL_ANIMATION_SECONDS)
            result = await self.cog.social.settle_duel(duel.id, winner)
            final = await self.cog._render_pvp(render_pvp_rps, left_name, right_name, duel.stake, a, b, winner_name)
            if self.message is not None:
                detail = f"**{left_name}: {a.title()}** • **{right_name}: {b.title()}**"
                await self.message.edit(embed=self.cog._duel_result_embed(duel, winner, result, image_filename="pvp_rps.png", detail=detail), attachments=[discord.File(fp=final, filename="pvp_rps.png")], view=None)
            self.stop()

    @discord.ui.button(emoji="🪨", label="Kő", style=discord.ButtonStyle.secondary)
    async def rock(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._choose(interaction, "rock")

    @discord.ui.button(emoji="📄", label="Papír", style=discord.ButtonStyle.primary)
    async def paper(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._choose(interaction, "paper")

    @discord.ui.button(emoji="✂️", label="Olló", style=discord.ButtonStyle.danger)
    async def scissors(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._choose(interaction, "scissors")

    async def on_timeout(self) -> None:
        await self.cog.social.cleanup_duels()
        if self.message:
            try:
                await self.message.edit(embed=base_embed("⌛ RPS Duel lejárt", "A duel nem fejeződött be. **Mindkét tét visszajárt.**"), view=None, attachments=[])
            except discord.HTTPException:
                pass


class SocialOwnedView(discord.ui.View):
    def __init__(self, cog: "SocialEconomyCog", owner_id: int, *, admin: bool = False, timeout: float = 600) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = int(owner_id)
        self.admin = admin
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a panelt nem te nyitottad meg.", ephemeral=True)
            return False
        if self.admin and (not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message("❌ Ehhez **Szerver kezelése** jogosultság kell.", ephemeral=True)
            return False
        return True


class MarketListingSelect(discord.ui.Select):
    def __init__(self, view: "PlayerMarketView", rows: list[Any]) -> None:
        self.parent_view = view
        options = []
        for row in rows:
            desc = f"{money(row.unit_price)}/db • {row.quantity_remaining} db • eladó {row.seller_id}"
            options.append(discord.SelectOption(
                label=f"#{row.id} • {row.item_name}"[:100],
                value=str(row.id),
                emoji=row.emoji,
                description=desc[:100],
                default=view.selected_id == row.id,
            ))
        super().__init__(placeholder="Válassz egy hirdetést…", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_id = int(self.values[0])
        await self.parent_view.refresh(interaction)


class MarketSearchModal(discord.ui.Modal, title="Marketplace keresés"):
    query = discord.ui.TextInput(
        label="Keresés",
        placeholder="Item neve vagy ID • üresen = minden",
        required=False,
        max_length=80,
    )

    def __init__(self, view: "PlayerMarketView") -> None:
        super().__init__(timeout=300)
        self.parent_view = view
        if view.search:
            self.query.default = view.search

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.parent_view.search = str(self.query.value).strip() or None
        self.parent_view.page = 0
        self.parent_view.selected_id = None
        await interaction.response.defer()
        await self.parent_view.refresh_external()


class MarketBuyModal(discord.ui.Modal, title="Marketplace vásárlás"):
    quantity = discord.ui.TextInput(label="Mennyiség", default="1", min_length=1, max_length=4)

    def __init__(self, view: "PlayerMarketView", listing_id: int) -> None:
        super().__init__(timeout=300)
        self.parent_view = view
        self.listing_id = int(listing_id)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            quantity = int(str(self.quantity.value).strip())
            result = await self.parent_view.cog.social.buy_listing(
                self.parent_view.guild_id, interaction.user.id, self.listing_id, quantity
            )
        except (ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(
            f"✅ {result['emoji']} **{result['item_name']} ×{result['quantity']}** megvéve • "
            f"**{money(result['gross'])}** • market adó: {money(result['tax'])}",
            ephemeral=True,
        )
        await self.parent_view.refresh_external()


class MarketSellModal(discord.ui.Modal, title="Item eladása"):
    quantity = discord.ui.TextInput(label="Mennyiség", default="1", min_length=1, max_length=4)
    unit_price = discord.ui.TextInput(label="Egységár", placeholder="pl. 125k / 2m", min_length=1, max_length=30)

    def __init__(self, sell_view: "MarketSellInventoryView", item_id: str, item_name: str) -> None:
        super().__init__(timeout=300)
        self.sell_view = sell_view
        self.item_id = item_id
        self.item_name = item_name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            quantity = int(str(self.quantity.value).strip())
            price = parse_amount(str(self.unit_price.value).strip())
            listing_id = await self.sell_view.cog.social.create_listing(
                self.sell_view.guild_id, interaction.user.id, self.item_id, quantity, price
            )
        except (ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(
            f"✅ **#{listing_id} • {self.item_name} ×{quantity}** felrakva • **{money(price)}/db**",
            ephemeral=True,
        )
        await self.sell_view.market_view.refresh_external()


class MarketInventorySelect(discord.ui.Select):
    def __init__(self, view: "MarketSellInventoryView", rows: list[tuple[str, str, str, int, str, str]]) -> None:
        self.parent_view = view
        options = [
            discord.SelectOption(
                label=name[:100], value=item_id, emoji=emoji,
                description=f"Nálad: {qty} db • {rarity} • {category}"[:100],
            )
            for item_id, name, emoji, qty, rarity, category in rows
        ]
        super().__init__(placeholder="Mit szeretnél eladni?", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        item_id = self.values[0]
        row = next((r for r in self.parent_view.rows if r[0] == item_id), None)
        if row is None:
            return await interaction.response.send_message("❌ Az item már nem található.", ephemeral=True)
        await interaction.response.send_modal(MarketSellModal(self.parent_view, row[0], row[1]))


class MarketSellInventoryView(SocialOwnedView):
    PAGE_SIZE = 20

    def __init__(self, cog: "SocialEconomyCog", owner_id: int, guild_id: int, market_view: "PlayerMarketView") -> None:
        super().__init__(cog, owner_id, timeout=600)
        self.guild_id = guild_id
        self.market_view = market_view
        self.page = 0
        self.rows: list[tuple[str, str, str, int, str, str]] = []
        self.all_rows: list[tuple[str, str, str, int, str, str]] = []

    async def load(self) -> discord.Embed:
        all_rows = await self.cog.db.get_inventory_detailed(self.guild_id, self.owner_id)
        self.all_rows = [r for r in all_rows if str(r[5]).lower() != "reward"]
        max_page = max(0, (len(self.all_rows) - 1) // self.PAGE_SIZE) if self.all_rows else 0
        self.page = max(0, min(self.page, max_page))
        start = self.page * self.PAGE_SIZE
        self.rows = self.all_rows[start:start + self.PAGE_SIZE]
        for item in list(self.children):
            if isinstance(item, MarketInventorySelect):
                self.remove_item(item)
        if self.rows:
            self.add_item(MarketInventorySelect(self, self.rows))
        self.prev_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= max_page
        if not self.all_rows:
            desc = "Nincs eladható item az inventorydban. A premium/reward itemek nem tehetők Player Marketre."
        else:
            desc = "Válassz itemet a listából, majd add meg a mennyiséget és az egységárat a felugró ablakban."
        embed = base_embed("💸 Marketplace • Eladás", desc)
        embed.set_footer(text=f"Yoru • Player Market • Inventory {self.page + 1}/{max_page + 1}")
        return embed

    @discord.ui.button(label="Előző", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page -= 1
        await interaction.response.edit_message(embed=await self.load(), view=self)

    @discord.ui.button(label="Következő", emoji="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page += 1
        await interaction.response.edit_message(embed=await self.load(), view=self)


class MarketHistoryView(SocialOwnedView):
    PAGE_SIZE = 8

    def __init__(self, cog: "SocialEconomyCog", owner_id: int, guild_id: int) -> None:
        super().__init__(cog, owner_id, timeout=600)
        self.guild_id = guild_id
        self.page = 0
        self.has_next = False

    async def load(self) -> discord.Embed:
        rows = await self.cog.social.market_history(
            self.guild_id, self.owner_id, self.PAGE_SIZE + 1, self.page * self.PAGE_SIZE
        )
        self.has_next = len(rows) > self.PAGE_SIZE
        rows = rows[:self.PAGE_SIZE]
        self.prev_page.disabled = self.page <= 0
        self.next_page.disabled = not self.has_next
        lines = []
        for row in rows:
            side = "Eladás" if row["seller_id"] == self.owner_id else "Vétel"
            amount = row["net"] if side == "Eladás" else row["gross"]
            lines.append(
                f"`#{row['id']}` **{side}** • `{row['item_id']}` ×{row['quantity']} • **{money(amount)}** • {_fmt_dt(row['created_at'])}"
            )
        embed = base_embed("📜 Marketplace • Előzmények", "\n".join(lines) if lines else "Nincs tranzakció ezen az oldalon.")
        embed.set_footer(text=f"Yoru • Player Market • oldal {self.page + 1}")
        return embed

    @discord.ui.button(label="Előző", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(embed=await self.load(), view=self)

    @discord.ui.button(label="Következő", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page += 1
        await interaction.response.edit_message(embed=await self.load(), view=self)


class PlayerMarketView(SocialOwnedView):
    PAGE_SIZE = 8

    def __init__(self, cog: "SocialEconomyCog", owner_id: int, guild_id: int, *, search: str | None = None) -> None:
        super().__init__(cog, owner_id, timeout=600)
        self.guild_id = guild_id
        self.page = 0
        self.search = search
        self.mine = False
        self.selected_id: int | None = None
        self.rows: list[Any] = []
        self.has_next = False

    async def load(self) -> discord.Embed:
        seller_id = self.owner_id if self.mine else None
        rows = await self.cog.social.list_market(
            self.guild_id, seller_id=seller_id, search=self.search,
            limit=self.PAGE_SIZE + 1, offset=self.page * self.PAGE_SIZE,
        )
        self.has_next = len(rows) > self.PAGE_SIZE
        self.rows = rows[:self.PAGE_SIZE]
        if self.selected_id not in {r.id for r in self.rows}:
            self.selected_id = self.rows[0].id if self.rows else None
        for item in list(self.children):
            if isinstance(item, MarketListingSelect):
                self.remove_item(item)
        if self.rows:
            self.add_item(MarketListingSelect(self, self.rows))
        self.prev_page.disabled = self.page <= 0
        self.next_page.disabled = not self.has_next
        self.buy_or_cancel.disabled = self.selected_id is None
        self.buy_or_cancel.label = "Visszavonás" if self.mine else "Vásárlás"
        self.buy_or_cancel.emoji = "🗑️" if self.mine else "🛍️"
        self.buy_or_cancel.style = discord.ButtonStyle.danger if self.mine else discord.ButtonStyle.success
        self.mine_button.label = "Minden hirdetés" if self.mine else "Saját hirdetések"
        self.mine_button.emoji = "🌐" if self.mine else "👤"
        title = "🛒 Player Marketplace • Saját hirdetések" if self.mine else "🛒 Player Marketplace"
        if not self.rows:
            desc = "Nincs aktív hirdetés ezen az oldalon."
        else:
            lines = []
            for row in self.rows:
                marker = "➤" if row.id == self.selected_id else "•"
                lines.append(
                    f"{marker} `#{row.id}` {row.emoji} **{row.item_name}** ×{row.quantity_remaining} • **{money(row.unit_price)}/db**\n"
                    f"   └ <@{row.seller_id}> • lejár {_fmt_dt(row.expires_at)}"
                )
            desc = "\n".join(lines)
        embed = base_embed(title, desc)
        selected = next((r for r in self.rows if r.id == self.selected_id), None)
        if selected is not None:
            embed.add_field(
                name="Kiválasztva",
                value=(
                    f"{selected.emoji} **#{selected.id} • {selected.item_name}**\n"
                    f"Készlet: **{selected.quantity_remaining} db** • Egységár: **{money(selected.unit_price)}**\n"
                    f"Teljes készlet értéke: **{money(selected.quantity_remaining * selected.unit_price)}**"
                ),
                inline=False,
            )
        filter_text = f" • keresés: {self.search}" if self.search else ""
        runtime=await self.cog.social.gameplay.social(self.guild_id)
        embed.set_footer(
            text=f"Yoru • Player Market • oldal {self.page + 1}{filter_text} • {runtime.market_tax_rate*100:g}% tranzakciós adó"
        )
        return embed

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=await self.load(), view=self)

    async def refresh_external(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(embed=await self.load(), view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    @discord.ui.button(label="Előző", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1); self.selected_id = None
        await self.refresh(interaction)

    @discord.ui.button(label="Következő", emoji="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page += 1; self.selected_id = None
        await self.refresh(interaction)

    @discord.ui.button(label="Vásárlás", emoji="🛍️", style=discord.ButtonStyle.success, row=1)
    async def buy_or_cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.selected_id is None:
            return await interaction.response.send_message("❌ Előbb válassz hirdetést.", ephemeral=True)
        if self.mine:
            try:
                returned = await self.cog.social.cancel_listing(self.guild_id, interaction.user.id, self.selected_id)
            except ValueError as exc:
                return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            await interaction.response.send_message(f"✅ Hirdetés visszavonva • **{returned} db** visszakerült.", ephemeral=True)
            self.selected_id = None
            await self.refresh_external()
            return
        await interaction.response.send_modal(MarketBuyModal(self, self.selected_id))

    @discord.ui.button(label="Frissítés", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.refresh(interaction)

    @discord.ui.button(label="Keresés", emoji="🔎", style=discord.ButtonStyle.primary, row=2)
    async def search_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(MarketSearchModal(self))

    @discord.ui.button(label="Eladás", emoji="💸", style=discord.ButtonStyle.success, row=2)
    async def sell_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        view = MarketSellInventoryView(self.cog, self.owner_id, self.guild_id, self)
        await interaction.response.send_message(embed=await view.load(), view=view, ephemeral=True)

    @discord.ui.button(label="Saját hirdetések", emoji="👤", style=discord.ButtonStyle.secondary, row=2)
    async def mine_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.mine = not self.mine; self.page = 0; self.selected_id = None
        await self.refresh(interaction)

    @discord.ui.button(label="Előzmények", emoji="📜", style=discord.ButtonStyle.secondary, row=2)
    async def history_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        view = MarketHistoryView(self.cog, self.owner_id, self.guild_id)
        await interaction.response.send_message(embed=await view.load(), view=view, ephemeral=True)


class ServerShopSelect(discord.ui.Select):
    def __init__(self, view: "ServerShopView", rows: list[dict[str, Any]]) -> None:
        self.parent_view = view
        options = []
        for row in rows:
            stock = "∞" if int(row["stock"]) < 0 else str(row["stock"])
            options.append(discord.SelectOption(
                label=f"#{row['id']} • {row['name']}"[:100], value=str(row["id"]), emoji=str(row["emoji"]),
                description=f"{money(int(row['price']))} • stock {stock}"[:100],
                default=view.selected_id == int(row["id"]),
            ))
        super().__init__(placeholder="Válassz rewardot…", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_id = int(self.values[0])
        await self.parent_view.refresh(interaction)


class CustomRolePurchaseModal(discord.ui.Modal, title="Custom Role beállítása"):
    def __init__(
        self,
        cog: "SocialEconomyCog",
        guild_id: int,
        owner_id: int,
        reward_id: int,
        *,
        shop_view: "ServerShopView | None" = None,
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = int(guild_id)
        self.owner_id = int(owner_id)
        self.reward_id = int(reward_id)
        self.shop_view = shop_view
        self.role_name = discord.ui.TextInput(
            label="Role neve",
            placeholder="pl. Pajkos Paripa",
            min_length=1,
            max_length=100,
        )
        self.role_color = discord.ui.TextInput(
            label="Role színe (HEX, opcionális)",
            placeholder="#ff4da6",
            required=False,
            max_length=7,
        )
        self.add_item(self.role_name)
        self.add_item(self.role_color)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild_id != self.guild_id or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Ez a vásárlás már nem érvényes.", ephemeral=True)
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Ezt a custom role-t csak a vásárló állíthatja be.", ephemeral=True)
        try:
            role_name = self.cog._validate_custom_role_name(interaction.guild, str(self.role_name.value))
            role_color = self.cog._parse_custom_role_color(str(self.role_color.value))
            await self.cog._validate_reward_before_purchase(interaction.guild, interaction.user, self.reward_id)
            purchase = await self.cog.social.begin_server_shop_purchase(self.guild_id, interaction.user.id, self.reward_id)
            delivered = await self.cog._deliver_server_shop(
                interaction.guild,
                interaction.user,
                purchase,
                custom_role_name=role_name,
                custom_role_color=role_color,
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        except (discord.Forbidden, discord.HTTPException) as exc:
            return await interaction.response.send_message(f"❌ A custom role létrehozása nem sikerült, a pénzt visszaadtam. `{exc}`", ephemeral=True)
        await interaction.response.send_message(
            f"✅ {purchase['emoji']} **{purchase['name']}** megvéve • {money(purchase['price'])}\nRole: {delivered}",
            ephemeral=True,
        )
        if self.shop_view is not None:
            await self.shop_view.refresh_external()


class ServerShopView(SocialOwnedView):
    PAGE_SIZE = 8

    def __init__(self, cog: "SocialEconomyCog", owner_id: int, guild_id: int) -> None:
        super().__init__(cog, owner_id, timeout=600)
        self.guild_id = guild_id
        self.page = 0
        self.selected_id: int | None = None
        self.rows: list[dict[str, Any]] = []
        self.all_rows: list[dict[str, Any]] = []

    async def load(self) -> discord.Embed:
        self.all_rows = await self.cog.social.list_server_shop(self.guild_id)
        max_page = max(0, (len(self.all_rows) - 1) // self.PAGE_SIZE) if self.all_rows else 0
        self.page = max(0, min(self.page, max_page))
        start = self.page * self.PAGE_SIZE
        self.rows = self.all_rows[start:start + self.PAGE_SIZE]
        if self.selected_id not in {int(r["id"]) for r in self.rows}:
            self.selected_id = int(self.rows[0]["id"]) if self.rows else None
        for item in list(self.children):
            if isinstance(item, ServerShopSelect): self.remove_item(item)
        if self.rows: self.add_item(ServerShopSelect(self, self.rows))
        self.prev_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= max_page
        self.buy_button.disabled = self.selected_id is None
        embed = base_embed("🏪 Server Shop", "A szerver saját reward shopja. Válassz rewardot, nézd meg a részleteket, majd vásárold meg a gombbal.")
        if not self.rows:
            embed.description = "A szerver adminjai még nem hoztak létre aktív rewardot."
        else:
            listing = []
            for row in self.rows:
                marker = "➤" if int(row["id"]) == self.selected_id else "•"
                stock = "∞" if int(row["stock"]) < 0 else str(row["stock"])
                listing.append(f"{marker} `#{row['id']}` {row['emoji']} **{row['name']}** • **{money(int(row['price']))}** • stock {stock}")
            embed.description = "\n".join(listing)
        selected = next((r for r in self.rows if int(r["id"]) == self.selected_id), None)
        if selected is not None:
            req = []
            if int(selected["required_activity_level"]): req.append(f"Activity Lv. {selected['required_activity_level']}")
            if int(selected["required_progression_level"]): req.append(f"Yoru Lv. {selected['required_progression_level']}")
            if int(selected["per_user_limit"]):
                bought = await self.cog.social.server_shop_purchase_count(self.guild_id, int(selected["id"]), self.owner_id)
                req.append(f"Limit: {bought}/{selected['per_user_limit']}")
            duration = f" • {int(selected['duration_minutes'])} perc" if selected["reward_type"] in {"temporary_role", "temporary_custom_role"} else ""
            embed.add_field(
                name=f"{selected['emoji']} #{selected['id']} • {selected['name']}",
                value=(
                    f"{selected['description'] or 'Nincs leírás.'}\n\n"
                    f"💰 Ár: **{money(int(selected['price']))}**\n"
                    f"🎁 Típus: **{selected['reward_type']}**{duration}\n"
                    f"📋 Feltétel: **{' • '.join(req) if req else 'Nincs'}**"
                ),
                inline=False,
            )
        embed.set_footer(text=f"Yoru • Server Shop • {self.page + 1}/{max_page + 1}. oldal")
        return embed

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=await self.load(), view=self)

    async def refresh_external(self) -> None:
        if self.message:
            try: await self.message.edit(embed=await self.load(), view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException): pass

    @discord.ui.button(label="Előző", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page -= 1; self.selected_id = None; await self.refresh(interaction)

    @discord.ui.button(label="Következő", emoji="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page += 1; self.selected_id = None; await self.refresh(interaction)

    @discord.ui.button(label="Megveszem", emoji="🛍️", style=discord.ButtonStyle.success, row=1)
    async def buy_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.selected_id is None or interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Előbb válassz rewardot.", ephemeral=True)
        selected = next((r for r in self.rows if int(r["id"]) == self.selected_id), None)
        if selected is None:
            return await interaction.response.send_message("❌ A kiválasztott reward már nem elérhető.", ephemeral=True)
        if str(selected["reward_type"]) in {"custom_role", "temporary_custom_role"}:
            return await interaction.response.send_modal(
                CustomRolePurchaseModal(self.cog, self.guild_id, self.owner_id, self.selected_id, shop_view=self)
            )
        try:
            await self.cog._validate_reward_before_purchase(interaction.guild, interaction.user, self.selected_id)
            purchase = await self.cog.social.begin_server_shop_purchase(self.guild_id, interaction.user.id, self.selected_id)
            delivered = await self.cog._deliver_server_shop(interaction.guild, interaction.user, purchase)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        except (discord.Forbidden, discord.HTTPException) as exc:
            return await interaction.response.send_message(f"❌ Reward delivery fail, refund megtörtént: `{exc}`", ephemeral=True)
        await interaction.response.send_message(
            f"✅ {purchase['emoji']} **{purchase['name']}** megvéve • {money(purchase['price'])}\nReward: {delivered}",
            ephemeral=True,
        )
        await self.refresh_external()

    @discord.ui.button(label="Frissítés", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.refresh(interaction)


class SocialMarketTuningModal(discord.ui.Modal, title="Social • Player Market"):
    tax = discord.ui.TextInput(label="Tranzakciós adó %", max_length=10)
    listing_hours = discord.ui.TextInput(label="Listing idő (óra)", max_length=10)
    max_active = discord.ui.TextInput(label="Max aktív listing / user", max_length=10)
    max_quantity = discord.ui.TextInput(label="Max quantity / listing", max_length=12)
    min_price = discord.ui.TextInput(label="Minimum egységár", max_length=30)

    def __init__(self, view: "SocialSettingsHomeView", runtime) -> None:
        super().__init__(timeout=300); self.parent_view=view
        self.tax.default=f"{runtime.market_tax_rate*100:g}"
        self.listing_hours.default=str(runtime.market_listing_hours)
        self.max_active.default=str(runtime.market_max_active_per_user)
        self.max_quantity.default=str(runtime.market_max_quantity)
        self.min_price.default=str(runtime.market_min_unit_price)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.cog.social.gameplay.set_social(
                interaction.guild_id,
                market_tax_rate=float(str(self.tax.value).replace(",","."))/100.0,
                market_listing_hours=int(str(self.listing_hours.value).strip()),
                market_max_active_per_user=int(str(self.max_active.value).strip()),
                market_max_quantity=int(str(self.max_quantity.value).strip()),
                market_min_unit_price=parse_amount(str(self.min_price.value)),
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.defer()
        await self.parent_view.cog.show_settings_after_defer(interaction,self.parent_view.owner_id)


class SocialPvpShopTuningModal(discord.ui.Modal, title="Social • PvP / Server Shop"):
    shop_max = discord.ui.TextInput(label="Server Shop max aktív reward", max_length=10)
    pvp_min = discord.ui.TextInput(label="PvP minimum tét", max_length=30)
    challenge = discord.ui.TextInput(label="Duel elfogadási idő (mp)", max_length=10)
    rps = discord.ui.TextInput(label="RPS döntési idő (mp)", max_length=10)

    def __init__(self, view: "SocialSettingsHomeView", runtime) -> None:
        super().__init__(timeout=300); self.parent_view=view
        self.shop_max.default=str(runtime.server_shop_max_items)
        self.pvp_min.default=str(runtime.pvp_min_stake)
        self.challenge.default=str(runtime.pvp_challenge_seconds)
        self.rps.default=str(runtime.pvp_rps_seconds)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.cog.social.gameplay.set_social(
                interaction.guild_id,
                server_shop_max_items=int(str(self.shop_max.value).strip()),
                pvp_min_stake=parse_amount(str(self.pvp_min.value)),
                pvp_challenge_seconds=int(str(self.challenge.value).strip()),
                pvp_rps_seconds=int(str(self.rps.value).strip()),
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.defer()
        await self.parent_view.cog.show_settings_after_defer(interaction,self.parent_view.owner_id)


class SocialSettingsHomeView(SocialOwnedView):
    def __init__(self, cog: "SocialEconomyCog", owner_id: int) -> None:
        super().__init__(cog, owner_id, admin=True, timeout=600)

    @discord.ui.button(label="Server Shop", emoji="🏪", style=discord.ButtonStyle.primary, row=0)
    async def shop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_server_shop_admin(interaction, self.owner_id)

    @discord.ui.button(label="Analytics", emoji="📊", style=discord.ButtonStyle.primary, row=0)
    async def analytics(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_analytics_settings(interaction, self.owner_id, 24)

    @discord.ui.button(label="Market balance", emoji="🛒", style=discord.ButtonStyle.primary, row=1)
    async def market_balance(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        runtime=await self.cog.social.gameplay.social(interaction.guild_id)
        await interaction.response.send_modal(SocialMarketTuningModal(self,runtime))

    @discord.ui.button(label="PvP / Shop", emoji="⚔️", style=discord.ButtonStyle.primary, row=1)
    async def pvp_shop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        runtime=await self.cog.social.gameplay.social(interaction.guild_id)
        await interaction.response.send_modal(SocialPvpShopTuningModal(self,runtime))

    @discord.ui.button(label="Balance default", emoji="♻️", style=discord.ButtonStyle.secondary, row=1)
    async def reset_balance(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self.cog.social.gameplay.reset_social(interaction.guild_id)
        await self.cog.show_settings_after_defer(interaction,self.owner_id)

    @discord.ui.button(label="Vissza", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.back_to_settings(interaction, self.owner_id)


class AdminShopSelect(discord.ui.Select):
    def __init__(self, view: "ServerShopAdminView", rows: list[dict[str, Any]]) -> None:
        self.parent_view = view
        options = []
        for row in rows:
            active = "ON" if int(row["active"]) else "OFF"
            options.append(discord.SelectOption(
                label=f"#{row['id']} • {row['name']}"[:100], value=str(row["id"]), emoji=str(row["emoji"]),
                description=f"{active} • {money(int(row['price']))} • {row['reward_type']}"[:100],
                default=view.selected_id == int(row["id"]),
            ))
        super().__init__(placeholder="Válassz szerver-shop rewardot…", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_id = int(self.values[0])
        await self.parent_view.refresh(interaction)


def _parse_int_field(value: str, name: str) -> int:
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"A(z) {name} mező egész szám legyen.") from exc


class ServerShopCreateModal(discord.ui.Modal, title="Új Server Shop reward"):
    name = discord.ui.TextInput(label="Név", max_length=80)
    price = discord.ui.TextInput(label="Ár", placeholder="pl. 5m", max_length=30)
    reward_type = discord.ui.TextInput(label="Típus", placeholder="existing_role / temporary_existing_role / custom_role / temporary_custom_role", max_length=30)
    reward_ref = discord.ui.TextInput(label="Reward", placeholder="Meglévő role ID / item ID / custom szöveg; custom role-nál üres", required=False, max_length=300)
    description = discord.ui.TextInput(label="Leírás", style=discord.TextStyle.paragraph, required=False, max_length=300)

    def __init__(self, view: "ServerShopAdminView") -> None:
        super().__init__(timeout=300); self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            typ = self.parent_view.cog._normalize_reward_type(str(self.reward_type.value))
            ref = self.parent_view.cog._normalize_reward_ref(typ, str(self.reward_ref.value))
            price = parse_amount(str(self.price.value))
            duration = 1440 if typ in {"temporary_role", "temporary_custom_role"} else 0
            reward_id = await self.parent_view.cog.social.create_server_shop_item(
                self.parent_view.guild_id, name=str(self.name.value), description=str(self.description.value), emoji="🎁",
                price=price, reward_type=typ, reward_ref=ref, duration_minutes=duration,
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        self.parent_view.selected_id = reward_id
        self.parent_view.page = 10**6  # load() safely clamps this to the last page where the new ID lives.
        await interaction.response.send_message(f"✅ Reward **#{reward_id}** létrehozva. A gombokkal minden további mező állítható.", ephemeral=True)
        await self.parent_view.refresh_external()


class ServerShopBasicsModal(discord.ui.Modal, title="Reward • Alapadatok"):
    def __init__(self, view: "ServerShopAdminView", item: dict[str, Any]) -> None:
        super().__init__(timeout=300); self.parent_view = view; self.item_id = int(item["id"])
        self.name = discord.ui.TextInput(label="Név", default=str(item["name"]), max_length=80)
        self.description = discord.ui.TextInput(label="Leírás", default=str(item["description"]), style=discord.TextStyle.paragraph, required=False, max_length=300)
        self.emoji = discord.ui.TextInput(label="Emoji", default=str(item["emoji"]), max_length=16)
        self.price = discord.ui.TextInput(label="Ár", default=str(item["price"]), max_length=30)
        for field in (self.name, self.description, self.emoji, self.price): self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            price = parse_amount(str(self.price.value))
            await self.parent_view.cog.social.update_server_shop_item(
                self.parent_view.guild_id, self.item_id, name=str(self.name.value), description=str(self.description.value),
                emoji=str(self.emoji.value), price=price,
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message("✅ Alapadatok mentve.", ephemeral=True)
        await self.parent_view.refresh_external()


class ServerShopRewardModal(discord.ui.Modal, title="Reward • Kiosztás"):
    def __init__(self, view: "ServerShopAdminView", item: dict[str, Any]) -> None:
        super().__init__(timeout=300); self.parent_view = view; self.item_id = int(item["id"])
        self.reward_type = discord.ui.TextInput(label="Típus", default=str(item["reward_type"]), max_length=30)
        self.reward_ref = discord.ui.TextInput(label="Reward / ID", default="" if str(item["reward_type"]) in {"custom_role", "temporary_custom_role"} else str(item["reward_ref"]), style=discord.TextStyle.paragraph, required=False, placeholder="Custom role-nál hagyd üresen", max_length=300)
        self.quantity = discord.ui.TextInput(label="Mennyiség", default=str(item["reward_quantity"]), max_length=8)
        self.duration = discord.ui.TextInput(label="Időtartam perc (temporary típusok)", default=str(item["duration_minutes"]), max_length=10)
        for field in (self.reward_type, self.reward_ref, self.quantity, self.duration): self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            typ = self.parent_view.cog._normalize_reward_type(str(self.reward_type.value))
            ref = self.parent_view.cog._normalize_reward_ref(typ, str(self.reward_ref.value))
            quantity = _parse_int_field(str(self.quantity.value), "mennyiség")
            duration = _parse_int_field(str(self.duration.value), "időtartam")
            await self.parent_view.cog.social.update_server_shop_item(
                self.parent_view.guild_id, self.item_id, reward_type=typ, reward_ref=ref,
                reward_quantity=quantity, duration_minutes=duration,
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message("✅ Reward kiosztás mentve.", ephemeral=True)
        await self.parent_view.refresh_external()


class ServerShopLimitsModal(discord.ui.Modal, title="Reward • Korlátok"):
    def __init__(self, view: "ServerShopAdminView", item: dict[str, Any]) -> None:
        super().__init__(timeout=300); self.parent_view = view; self.item_id = int(item["id"])
        self.stock = discord.ui.TextInput(label="Stock (-1 = végtelen)", default=str(item["stock"]), max_length=10)
        self.per_user = discord.ui.TextInput(label="Limit / user (0 = nincs)", default=str(item["per_user_limit"]), max_length=10)
        self.activity = discord.ui.TextInput(label="Minimum Activity Level", default=str(item["required_activity_level"]), max_length=8)
        self.yoru_level = discord.ui.TextInput(label="Minimum Yoru Level", default=str(item["required_progression_level"]), max_length=8)
        for field in (self.stock, self.per_user, self.activity, self.yoru_level): self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.cog.social.update_server_shop_item(
                self.parent_view.guild_id, self.item_id,
                stock=_parse_int_field(str(self.stock.value), "stock"),
                per_user_limit=_parse_int_field(str(self.per_user.value), "user limit"),
                required_activity_level=_parse_int_field(str(self.activity.value), "Activity Level"),
                required_progression_level=_parse_int_field(str(self.yoru_level.value), "Yoru Level"),
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message("✅ Korlátok és követelmények mentve.", ephemeral=True)
        await self.parent_view.refresh_external()


class ServerShopAdminView(SocialOwnedView):
    PAGE_SIZE = 8

    def __init__(self, cog: "SocialEconomyCog", owner_id: int, guild_id: int) -> None:
        super().__init__(cog, owner_id, admin=True, timeout=600)
        self.guild_id = guild_id; self.page = 0; self.selected_id: int | None = None
        self.rows: list[dict[str, Any]] = []; self.all_rows: list[dict[str, Any]] = []

    async def load(self) -> discord.Embed:
        self.all_rows = await self.cog.social.list_server_shop(self.guild_id, include_inactive=True)
        max_page = max(0, (len(self.all_rows) - 1) // self.PAGE_SIZE) if self.all_rows else 0
        self.page = max(0, min(self.page, max_page)); start = self.page * self.PAGE_SIZE
        self.rows = self.all_rows[start:start + self.PAGE_SIZE]
        if self.selected_id not in {int(r["id"]) for r in self.rows}:
            self.selected_id = int(self.rows[0]["id"]) if self.rows else None
        for child in list(self.children):
            if isinstance(child, AdminShopSelect): self.remove_item(child)
        if self.rows: self.add_item(AdminShopSelect(self, self.rows))
        selected = next((r for r in self.rows if int(r["id"]) == self.selected_id), None)
        disabled = selected is None
        self.edit_basics.disabled = disabled; self.edit_reward.disabled = disabled; self.edit_limits.disabled = disabled; self.toggle_active.disabled = disabled
        self.prev_page.disabled = self.page <= 0; self.next_page.disabled = self.page >= max_page
        if selected is not None:
            self.toggle_active.label = "Kikapcsolás" if int(selected["active"]) else "Bekapcsolás"
            self.toggle_active.emoji = "🔴" if int(selected["active"]) else "🟢"
        embed = base_embed("🏪 Settings • Server Shop", "A rewardok teljes konfigurációja Discordon belül kezelhető. Válassz elemet, majd használd a szerkesztő gombokat.")
        if self.rows:
            lines = []
            for row in self.rows:
                marker = "➤" if int(row["id"]) == self.selected_id else "•"
                status = "🟢" if int(row["active"]) else "🔴"
                lines.append(f"{marker} {status} `#{row['id']}` {row['emoji']} **{row['name']}** • {money(int(row['price']))}")
            embed.description += "\n\n" + "\n".join(lines)
        else:
            embed.description += "\n\n*Még nincs Server Shop reward.*"
        if selected is not None:
            stock = "∞" if int(selected["stock"]) < 0 else str(selected["stock"])
            embed.add_field(name="Kiválasztott reward", value=(
                f"**#{selected['id']} • {selected['emoji']} {selected['name']}**\n{selected['description'] or 'Nincs leírás.'}\n\n"
                f"💰 **{money(int(selected['price']))}** • Stock: **{stock}** • User limit: **{selected['per_user_limit'] or 'nincs'}**\n"
                f"🎁 `{selected['reward_type']}` → `{str(selected['reward_ref'])[:120]}` ×{selected['reward_quantity']}\n"
                f"📈 Activity: **{selected['required_activity_level']}** • Yoru Level: **{selected['required_progression_level']}** • Temp: **{selected['duration_minutes']} perc**"
            ), inline=False)
        embed.set_footer(text=f"Yoru • Settings • Server Shop • {self.page + 1}/{max_page + 1}. oldal")
        return embed

    def selected(self) -> dict[str, Any] | None:
        return next((r for r in self.rows if int(r["id"]) == self.selected_id), None)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=await self.load(), view=self)

    async def refresh_external(self) -> None:
        if self.message:
            try: await self.message.edit(embed=await self.load(), view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException): pass

    @discord.ui.button(label="Előző", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page -= 1; self.selected_id = None; await self.refresh(interaction)

    @discord.ui.button(label="Következő", emoji="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page += 1; self.selected_id = None; await self.refresh(interaction)

    @discord.ui.button(label="Új reward", emoji="➕", style=discord.ButtonStyle.success, row=1)
    async def new_reward(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ServerShopCreateModal(self))

    @discord.ui.button(label="Alapadatok", emoji="✏️", style=discord.ButtonStyle.primary, row=1)
    async def edit_basics(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        item = self.selected()
        if item is None: return await interaction.response.send_message("❌ Nincs kiválasztott reward.", ephemeral=True)
        await interaction.response.send_modal(ServerShopBasicsModal(self, item))

    @discord.ui.button(label="Reward", emoji="🎁", style=discord.ButtonStyle.primary, row=1)
    async def edit_reward(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        item = self.selected()
        if item is None: return await interaction.response.send_message("❌ Nincs kiválasztott reward.", ephemeral=True)
        await interaction.response.send_modal(ServerShopRewardModal(self, item))

    @discord.ui.button(label="Korlátok", emoji="🎚️", style=discord.ButtonStyle.secondary, row=2)
    async def edit_limits(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        item = self.selected()
        if item is None: return await interaction.response.send_message("❌ Nincs kiválasztott reward.", ephemeral=True)
        await interaction.response.send_modal(ServerShopLimitsModal(self, item))

    @discord.ui.button(label="Kikapcsolás", emoji="🔴", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_active(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        item = self.selected()
        if item is None: return await interaction.response.send_message("❌ Nincs kiválasztott reward.", ephemeral=True)
        new_state = not bool(int(item["active"]))
        try: await self.cog.social.set_server_shop_item_active(self.guild_id, int(item["id"]), new_state)
        except ValueError as exc: return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(f"✅ Reward **{'bekapcsolva' if new_state else 'kikapcsolva'}**.", ephemeral=True)
        await self.refresh_external()

    @discord.ui.button(label="Pending claimek", emoji="📨", style=discord.ButtonStyle.secondary, row=2)
    async def claims(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_claims_settings(interaction, self.owner_id)

    @discord.ui.button(label="Social menü", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_settings(interaction, self.owner_id)


class ClaimSelect(discord.ui.Select):
    def __init__(self, view: "ServerShopClaimsView", rows: list[dict[str, Any]]) -> None:
        self.parent_view = view
        options = [
            discord.SelectOption(label=f"Claim #{r['id']} • user {r['user_id']}"[:100], value=str(r["id"]), description=str(r["reward_text"])[:100], default=view.selected_id == int(r["id"]))
            for r in rows
        ]
        super().__init__(placeholder="Válassz pending claimet…", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_id = int(self.values[0]); await self.parent_view.refresh(interaction)


class ServerShopClaimsView(SocialOwnedView):
    PAGE_SIZE = 10
    def __init__(self, cog: "SocialEconomyCog", owner_id: int, guild_id: int) -> None:
        super().__init__(cog, owner_id, admin=True, timeout=600); self.guild_id=guild_id; self.page=0; self.rows=[]; self.selected_id=None; self.has_next=False

    async def load(self) -> discord.Embed:
        rows = await self.cog.social.list_pending_claims(self.guild_id, self.PAGE_SIZE + 1, self.page * self.PAGE_SIZE)
        self.has_next = len(rows) > self.PAGE_SIZE; self.rows = rows[:self.PAGE_SIZE]
        if self.selected_id not in {int(r["id"]) for r in self.rows}: self.selected_id = int(self.rows[0]["id"]) if self.rows else None
        for child in list(self.children):
            if isinstance(child, ClaimSelect): self.remove_item(child)
        if self.rows: self.add_item(ClaimSelect(self, self.rows))
        self.prev_page.disabled=self.page<=0; self.next_page.disabled=not self.has_next; self.fulfill.disabled=self.selected_id is None
        lines=[f"`#{r['id']}` <@{r['user_id']}> • {str(r['reward_text'])[:140]} • {_fmt_dt(r['created_at'])}" for r in self.rows]
        embed=base_embed("📨 Settings • Pending reward claims", "\n".join(lines) if lines else "Nincs függőben lévő custom reward claim.")
        embed.set_footer(text=f"Yoru • Server Shop Claims • oldal {self.page+1}"); return embed

    async def refresh(self, interaction: discord.Interaction) -> None: await interaction.response.edit_message(embed=await self.load(), view=self)

    @discord.ui.button(label="Előző", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: self.page=max(0,self.page-1); self.selected_id=None; await self.refresh(interaction)
    @discord.ui.button(label="Következő", emoji="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: self.page+=1; self.selected_id=None; await self.refresh(interaction)
    @discord.ui.button(label="Teljesítve", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def fulfill(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.selected_id is None: return await interaction.response.send_message("❌ Nincs kiválasztott claim.", ephemeral=True)
        ok=await self.cog.social.fulfill_claim(self.guild_id,self.selected_id,interaction.user.id)
        await interaction.response.send_message("✅ Claim teljesítettnek jelölve." if ok else "❌ A claim már nem pending.",ephemeral=True)
        if self.message:
            try: await self.message.edit(embed=await self.load(),view=self)
            except discord.HTTPException: pass
    @discord.ui.button(label="Vissza", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_server_shop_admin(interaction,self.owner_id)


class AnalyticsSettingsView(SocialOwnedView):
    def __init__(self, cog: "SocialEconomyCog", owner_id: int, hours: int = 24) -> None:
        super().__init__(cog, owner_id, admin=True, timeout=600); self.hours=hours

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=await self.cog._analytics_embed(interaction.guild_id,self.hours),view=self)

    @discord.ui.button(label="24 óra", emoji="🕐", style=discord.ButtonStyle.primary, row=0)
    async def day(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: self.hours=24; await self.refresh(interaction)
    @discord.ui.button(label="7 nap", emoji="📅", style=discord.ButtonStyle.secondary, row=0)
    async def week(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: self.hours=168; await self.refresh(interaction)
    @discord.ui.button(label="30 nap", emoji="🗓️", style=discord.ButtonStyle.secondary, row=0)
    async def month(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: self.hours=720; await self.refresh(interaction)
    @discord.ui.button(label="Frissítés", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.refresh(interaction)
    @discord.ui.button(label="Social menü", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None: await self.cog.show_settings(interaction,self.owner_id)


class SocialEconomyCog(commands.GroupCog, group_name="social", group_description="Player market, server shop, PvP duel és economy analytics."):
    def __init__(self, bot: commands.Bot, db: Database, economy: EconomyService) -> None:
        self.bot = bot
        self.db = db
        self.economy = economy
        self.social = SocialEconomyService(db)
        self.cleanup_task: asyncio.Task | None = None
        self._pvp_render_semaphore = asyncio.Semaphore(max(1, int(cfg.PVP_RENDER_CONCURRENCY)))

    async def cog_load(self) -> None:
        await self.social.initialize()
        # Any RPS escrow left by a previous killed process is refunded at startup.
        await self.social.refund_all_accepted_duels()
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def cog_unload(self) -> None:
        if self.cleanup_task:
            self.cleanup_task.cancel()

    @staticmethod
    def _normalize_reward_type(raw: str) -> str:
        value = str(raw).strip().lower().replace(" ", "_")
        aliases = {
            "temp": "temporary_role", "temprole": "temporary_role", "temporary": "temporary_role",
            "temporary_existing_role": "temporary_role", "existing_role": "role",
            "role": "role",
            "customrole": "custom_role", "custom_role": "custom_role", "buyerrole": "custom_role",
            "tempcustomrole": "temporary_custom_role", "temporary_custom_role": "temporary_custom_role",
            "temp_custom_role": "temporary_custom_role", "temporarybuyerrole": "temporary_custom_role",
            "item": "item", "custom": "custom", "manual": "custom",
        }
        value = aliases.get(value, value)
        if value not in cfg.SERVER_SHOP_REWARD_TYPES:
            raise ValueError("Típus: existing_role / temporary_existing_role / custom_role / temporary_custom_role / item / custom.")
        return value

    @staticmethod
    def _normalize_reward_ref(reward_type: str, raw: str) -> str:
        value = str(raw).strip()
        if reward_type in {"role", "temporary_role"}:
            value = value.strip("<@&>")
            if not value.isdigit():
                raise ValueError("Meglévő role rewardnál jelöld meg a rangot vagy add meg a role ID-t.")
        if reward_type in {"custom_role", "temporary_custom_role"}:
            return "buyer_custom_role"
        if not value:
            raise ValueError("A reward hivatkozás/szöveg nem lehet üres.")
        return value

    @staticmethod
    def _parse_custom_role_color(raw: str) -> discord.Colour:
        value = str(raw).strip().lower()
        if not value:
            return discord.Colour.default()
        if value.startswith("#"):
            value = value[1:]
        if len(value) != 6 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("A role színe 6 jegyű HEX legyen, pl. `#ff4da6`.")
        return discord.Colour(int(value, 16))

    @staticmethod
    def _validate_custom_role_name(guild: discord.Guild, raw: str) -> str:
        name = " ".join(str(raw).replace("\n", " ").replace("\r", " ").split()).strip()
        if not name:
            raise ValueError("A custom role neve nem lehet üres.")
        if len(name) > 100:
            raise ValueError("A custom role neve maximum 100 karakter lehet.")
        if name.casefold() in {"@everyone", "@here"}:
            raise ValueError("Ez a role név nem használható.")
        if any(role.name.casefold() == name.casefold() for role in guild.roles):
            raise ValueError("Már létezik ilyen nevű role ezen a szerveren.")
        return name

    async def home_status(self, guild: discord.Guild) -> str:
        rewards = await self.social.list_server_shop(guild.id)
        return f"🟢 Market • {len(rewards)} server reward"

    async def settings_embed(self, guild: discord.Guild) -> discord.Embed:
        rewards = await self.social.list_server_shop(guild.id)
        market_rows = await self.social.list_market(guild.id, limit=1)
        claims = await self.social.list_pending_claims(guild.id, limit=1)
        runtime = await self.social.gameplay.social(guild.id)
        embed = base_embed(
            "🛒 Yoru • Social Economy",
            "A Yoru DB settings az elsődleges Social balance source; a kódbeli értékek fallback defaultok.",
        )
        embed.add_field(name="🛒 Player Market", value=f"🟢 Aktív • **{runtime.market_tax_rate*100:g}% adó** • **{runtime.market_listing_hours}h** listing\nMax **{runtime.market_max_active_per_user}/user** • max qty **{runtime.market_max_quantity}** • min ár **{money(runtime.market_min_unit_price)}**" + (" • van aktív listing" if market_rows else " • nincs listing"), inline=False)
        embed.add_field(name="🏪 Server Shop", value=f"**{len(rewards)}** aktív reward • max **{runtime.server_shop_max_items}**", inline=True)
        embed.add_field(name="⚔️ PvP", value=f"Min tét **{money(runtime.pvp_min_stake)}** • accept **{runtime.pvp_challenge_seconds}s** • RPS **{runtime.pvp_rps_seconds}s**", inline=False)
        embed.add_field(name="📨 Pending claims", value="Van függő claim" if claims else "Nincs", inline=True)
        embed.add_field(name="📊 Analytics", value="24h / 7 nap / 30 nap • supply, source/sink, koncentráció, Social volume", inline=False)
        embed.set_footer(text="Yoru • Settings • Social Economy")
        return embed

    async def show_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        view = SocialSettingsHomeView(self, owner_id)
        view.message = interaction.message
        await interaction.edit_original_response(embed=await self.settings_embed(interaction.guild), view=view)

    async def show_settings_after_defer(self, interaction: discord.Interaction, owner_id: int) -> None:
        view = SocialSettingsHomeView(self, owner_id)
        view.message = interaction.message
        await interaction.edit_original_response(embed=await self.settings_embed(interaction.guild), view=view, attachments=[])

    async def show_server_shop_admin(self, interaction: discord.Interaction, owner_id: int) -> None:
        view = ServerShopAdminView(self, owner_id, interaction.guild_id)
        view.message = interaction.message
        await interaction.response.edit_message(embed=await view.load(), view=view)

    async def show_claims_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        view = ServerShopClaimsView(self, owner_id, interaction.guild_id)
        view.message = interaction.message
        await interaction.response.edit_message(embed=await view.load(), view=view)

    async def show_analytics_settings(self, interaction: discord.Interaction, owner_id: int, hours: int = 24) -> None:
        view = AnalyticsSettingsView(self, owner_id, hours)
        view.message = interaction.message
        await interaction.response.edit_message(embed=await self._analytics_embed(interaction.guild_id, hours), view=view)

    async def back_to_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        settings_cog = self.bot.get_cog("SettingsCog")
        if settings_cog is None or not hasattr(settings_cog, "show_home"):
            return await interaction.response.send_message("❌ A Settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, owner_id)

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(cfg.SOCIAL_CLEANUP_SECONDS)
                await self.social.expire_market_listings()
                await self.social.cleanup_duels()
                await self._cleanup_temp_roles()
            except asyncio.CancelledError:
                return
            except Exception:
                # Maintenance must never take the whole bot down.
                continue

    async def _cleanup_temp_roles(self) -> None:
        for guild_id, user_id, role_id, purchase_id, delete_on_expire in await self.social.expired_temporary_roles():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            member = guild.get_member(user_id)
            role = guild.get_role(role_id)
            if role is not None and delete_on_expire:
                try:
                    await role.delete(reason="Yoru temporary custom role lejárt")
                except (discord.Forbidden, discord.HTTPException):
                    continue
            elif member is not None and role is not None:
                try:
                    await member.remove_roles(role, reason="Yoru temporary server shop role lejárt")
                except (discord.Forbidden, discord.HTTPException):
                    continue
            await self.social.delete_temporary_role_grant(guild_id, user_id, role_id, purchase_id)

    async def _gate_interaction(self, interaction: discord.Interaction, feature: str = "economy") -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Ez csak szerveren használható.", ephemeral=True); return False
        try:
            await self.economy.require_access(interaction.guild.id, feature, interaction.channel_id, _category_id(interaction.channel))
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True); return False
        return True

    async def _gate_ctx(self, ctx: commands.Context, feature: str = "economy") -> bool:
        if ctx.guild is None:
            return False
        try:
            await self.economy.guild_settings.require_feature(ctx.guild.id, feature)
            await self.economy.guild_settings.require_channel(ctx.guild.id, ctx.channel.id, _category_id(ctx.channel))
        except ValueError as exc:
            if "engedélyezett hely" in str(exc) or "csak az" in str(exc):
                await handle_wrong_economy_channel(ctx, self.economy, kind="gambling" if feature == "gambling" else "economy")
            else:
                await ctx.send(embed=error_embed(ctx.author, str(exc)))
            return False
        return True

    async def _silent_admin(self, ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return False
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
        if not ctx.author.guild_permissions.manage_guild:
            try: await ctx.author.send("⛔ Ehhez a Yoru server-shop admin művelethez **Szerver kezelése** jogosultság kell.")
            except discord.HTTPException: pass
            return False
        return True

    async def _dm_admin(self, member: discord.Member, text: str) -> None:
        try: await member.send(text)
        except discord.HTTPException: pass

    # ---------- renderers ----------

    async def _market_embed(self, guild_id: int, seller_id: int | None = None, search: str | None = None, page: int = 1) -> discord.Embed:
        page=max(1,int(page)); page_size=10
        rows = await self.social.list_market(guild_id, seller_id=seller_id, search=search, limit=page_size, offset=(page-1)*page_size)
        if not rows:
            suffix=f" a(z) `{search}` keresésre" if search else ""
            return base_embed("🛒 Player Marketplace", f"Nincs aktív listing{suffix} ezen az oldalon.")
        lines = [
            f"`#{r.id}` {r.emoji} **{r.item_name}** ×{r.quantity_remaining} • **{money(r.unit_price)}/db**\n"
            f"└ eladó: <@{r.seller_id}> • lejár {_fmt_dt(r.expires_at)}"
            for r in rows
        ]
        embed = base_embed("🛒 Player Marketplace", "\n".join(lines))
        filter_text=f" • keresés: {search}" if search else ""
        runtime=await self.social.gameplay.social(guild_id)
        embed.set_footer(text=f"Yoru • Player Market • oldal {page}{filter_text} • {runtime.market_tax_rate*100:g}% tranzakciós adó")
        return embed

    async def _server_shop_embed(self, guild_id: int) -> discord.Embed:
        rows = await self.social.list_server_shop(guild_id)
        if not rows:
            return base_embed("🏪 Server Shop", "A szerver adminjai még nem hoztak létre egyedi rewardot.")
        lines=[]
        for r in rows[:20]:
            stock="∞" if int(r["stock"]) < 0 else str(r["stock"])
            req=[]
            if int(r["required_activity_level"]): req.append(f"Activity {r['required_activity_level']}")
            if int(r["required_progression_level"]): req.append(f"Level {r['required_progression_level']}")
            limit=f" • limit {r['per_user_limit']}/fő" if int(r["per_user_limit"]) else ""
            requirements=f" • {' + '.join(req)}" if req else ""
            lines.append(f"`#{r['id']}` {r['emoji']} **{r['name']}** • **{money(int(r['price']))}** • stock {stock}{limit}{requirements}\n└ {str(r['description'])[:120] or str(r['reward_type'])}")
        embed=base_embed("🏪 Server Shop","\n".join(lines))
        embed.set_footer(text="Yoru • Social Economy • Server-specific rewards")
        return embed

    async def _render_pvp(self, func, *args, **kwargs):
        async with self._pvp_render_semaphore:
            return await asyncio.to_thread(func, *args, **kwargs)

    def _duel_names(self, duel: Duel) -> tuple[str, str]:
        guild = self.bot.get_guild(int(duel.guild_id))
        left = guild.get_member(int(duel.challenger_id)) if guild else None
        right = guild.get_member(int(duel.target_id)) if guild else None
        return (getattr(left, "display_name", f"Player {duel.challenger_id}"), getattr(right, "display_name", f"Player {duel.target_id}"))

    def _duel_challenge_embed(self, duel: Duel, *, image_filename: str = "pvp_challenge.png") -> discord.Embed:
        embed=base_embed(
            f"⚔️ {_game_label(duel.game)}",
            f"<@{duel.challenger_id}> vs <@{duel.target_id}>\n💰 Tét / fő: **{money(duel.stake)}** • 🏆 Pot: **{money(duel.stake*2)}**\n⏳ Elfogadás: {_fmt_dt(duel.expires_at)}",
            GOLD,
        )
        embed.set_image(url=f"attachment://{image_filename}")
        embed.set_footer(text="A tét csak elfogadáskor kerül escrow-ba • 1 aktív Casino game / player")
        return embed

    def _duel_live_embed(self, duel: Duel, phase: str, image_filename: str) -> discord.Embed:
        embed = base_embed(_game_label(duel.game), f"{phase}\n💰 Pot: **{money(duel.stake*2)}**", GOLD)
        embed.set_image(url=f"attachment://{image_filename}")
        embed.set_footer(text="Yoru Casino • PvP")
        return embed

    def _duel_result_embed(self, duel: Duel, winner: int | None, result: dict[str, Any], *, image_filename: str, detail: str = "") -> discord.Embed:
        if winner is None:
            text = f"🤝 **Döntetlen** • mindkét tét visszajárt.\n💰 Tét / fő: **{money(duel.stake)}**"
            color = GOLD
        else:
            text = f"🏆 <@{winner}> nyert!\n💰 Pot: **{money(int(result['stake'])*2)}** • Profit: **+{money(int(result['stake']))}**"
            color = SUCCESS
        if detail:
            text += f"\n{detail}"
        embed = base_embed(f"{_game_label(duel.game)} • Eredmény", text, color)
        embed.set_image(url=f"attachment://{image_filename}")
        embed.set_footer(text="Yoru Casino • PvP • Game-first final state")
        return embed

    def _rps_wait_embed(self, duel: Duel, *, image_filename: str = "pvp_rps_wait.png") -> discord.Embed:
        embed = base_embed(
            "✊ RPS Duel • Válasszatok",
            f"<@{duel.challenger_id}> vs <@{duel.target_id}> • 💰 Pot: **{money(duel.stake*2)}**\nMindketten válasszatok. A másik fél nem látja a döntésedet.",
            GOLD,
        )
        embed.set_image(url=f"attachment://{image_filename}")
        return embed

    async def _deliver_server_shop(
        self,
        guild: discord.Guild,
        member: discord.Member,
        purchase: dict[str, Any],
        *,
        custom_role_name: str | None = None,
        custom_role_color: discord.Colour | None = None,
    ) -> str:
        p_id=int(purchase["purchase_id"]); typ=str(purchase["reward_type"]); ref=str(purchase["reward_ref"]); qty=int(purchase["reward_quantity"])
        added_role: discord.Role | None = None
        created_role: discord.Role | None = None
        added_item: str | None = None
        temp_grant: tuple[int,int,int,int] | None = None
        try:
            if typ in {"role","temporary_role"}:
                try: role_id=int(ref)
                except ValueError: raise ValueError("A rewardhoz tartozó Discord role ID hibás.")
                role=guild.get_role(role_id)
                me=guild.me
                if role is None: raise ValueError("A reward Discord role már nem létezik.")
                if role.is_default() or role.managed or me is None or role >= me.top_role:
                    raise ValueError("Yoru nem tudja kiosztani ezt a role-t. Ellenőrizd a role hierarchy-t.")
                if role in member.roles:
                    raise ValueError("Ez a role már rajtad van.")
                await member.add_roles(role, reason=f"Yoru Server Shop purchase #{p_id}")
                added_role=role
                if typ=="temporary_role":
                    expires=await self.social.add_temporary_role_grant(guild.id,member.id,role.id,p_id,int(purchase["duration_minutes"]))
                    temp_grant=(guild.id,member.id,role.id,p_id)
                    await self.social.complete_server_shop_purchase(p_id)
                    return f"{role.mention} • lejár {_fmt_dt(expires)}"
                await self.social.complete_server_shop_purchase(p_id)
                return role.mention
            if typ in {"custom_role", "temporary_custom_role"}:
                if custom_role_name is None:
                    raise ValueError("Ehhez a rewardhoz a `!servershop` interaktív vásárlását használd, hogy megadd a custom role nevét.")
                me = guild.me
                if me is None or not me.guild_permissions.manage_roles:
                    raise ValueError("Yorunak `Manage Roles / Rangok kezelése` jogosultság kell a custom role létrehozásához.")
                role_name = self._validate_custom_role_name(guild, custom_role_name)
                colour = custom_role_color or discord.Colour.default()
                role = await guild.create_role(
                    name=role_name,
                    colour=colour,
                    permissions=discord.Permissions.none(),
                    hoist=False,
                    mentionable=False,
                    reason=f"Yoru Server Shop custom role purchase #{p_id}",
                )
                created_role = role
                await member.add_roles(role, reason=f"Yoru Server Shop custom role purchase #{p_id}")
                added_role = role
                if typ == "temporary_custom_role":
                    expires = await self.social.add_temporary_role_grant(
                        guild.id, member.id, role.id, p_id, int(purchase["duration_minutes"]), delete_on_expire=True,
                    )
                    temp_grant=(guild.id,member.id,role.id,p_id)
                    await self.social.complete_server_shop_purchase(p_id)
                    return f"{role.mention} • lejár {_fmt_dt(expires)} • utána a role automatikusan törlődik"
                await self.social.complete_server_shop_purchase(p_id)
                return role.mention
            if typ=="item":
                info=await self.db.get_shop_item(ref)
                if info is None: raise ValueError("A rewardhoz tartozó Yoru item már nem létezik.")
                await self.db.add_item(guild.id,member.id,ref,qty)
                added_item=ref
                await self.social.complete_server_shop_purchase(p_id)
                return f"{info[1]} **{info[0]} ×{qty}**"
            if typ=="custom":
                await self.social.complete_server_shop_purchase(p_id,status="claimed")
                return f"📨 **Claim #{purchase['claim_id']}** létrehozva • staff teljesíti: {ref}"
            raise ValueError("Ismeretlen reward type.")
        except Exception:
            if added_item is not None:
                try: await self.db.consume_item(guild.id,member.id,added_item,qty)
                except Exception: pass
            if temp_grant is not None:
                try: await self.social.delete_temporary_role_grant(*temp_grant)
                except Exception: pass
            if created_role is not None:
                try: await created_role.delete(reason=f"Yoru Server Shop rollback #{p_id}")
                except (discord.Forbidden,discord.HTTPException): pass
            elif added_role is not None:
                try: await member.remove_roles(added_role,reason=f"Yoru Server Shop rollback #{p_id}")
                except (discord.Forbidden,discord.HTTPException): pass
            await self.social.refund_server_shop_purchase(p_id)
            raise

    async def _validate_reward_before_purchase(self, guild: discord.Guild, member: discord.Member, item_id: int) -> None:
        item=await self.social.get_server_shop_item(guild.id,item_id)
        if item is None or not int(item["active"]): raise ValueError("Nincs ilyen aktív server shop reward.")
        typ=str(item["reward_type"]); ref=str(item["reward_ref"])
        if typ in {"role","temporary_role"}:
            try: role_id=int(ref)
            except ValueError: raise ValueError("A reward role konfiguráció hibás.")
            role=guild.get_role(role_id); me=guild.me
            if role is None: raise ValueError("A reward role már nem létezik.")
            if role.is_default() or role.managed or me is None or role >= me.top_role: raise ValueError("Yoru nem tudja kiosztani ezt a role-t a role hierarchy miatt.")
            if role in member.roles: raise ValueError("Ez a role már rajtad van; temporary role-t sem lehet egymásra stackelni.")
        elif typ in {"custom_role", "temporary_custom_role"}:
            me = guild.me
            if me is None or not me.guild_permissions.manage_roles:
                raise ValueError("Yorunak `Manage Roles / Rangok kezelése` jogosultság kell a custom role létrehozásához.")
        elif typ=="item" and await self.db.get_shop_item(ref) is None:
            raise ValueError("A reward Yoru item már nem létezik.")

    # ---------- slash: marketplace ----------

    @app_commands.command(name="market", description="Interaktív Player Marketplace.")
    async def market_slash(self, interaction: discord.Interaction, kereses: str | None = None, oldal: app_commands.Range[int,1,100] = 1) -> None:
        if not await self._gate_interaction(interaction): return
        view = PlayerMarketView(self, interaction.user.id, interaction.guild_id, search=kereses)
        view.page = max(0, int(oldal) - 1)
        await interaction.response.send_message(embed=await view.load(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="marketlist", description="Item felrakása a Player Marketplace-re.")
    async def market_list_slash(self, interaction: discord.Interaction, item_id: str, mennyiseg: app_commands.Range[int,1,999], egysegar: str) -> None:
        if not await self._gate_interaction(interaction): return
        try:
            price=parse_amount(egysegar)
            listing_id=await self.social.create_listing(interaction.guild_id,interaction.user.id,item_id,mennyiseg,price)
        except ValueError as exc: return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        await interaction.response.send_message(f"✅ Listing **#{listing_id}** létrehozva • `{item_id}` ×{mennyiseg} • **{money(price)}/db**")

    @app_commands.command(name="marketbuy", description="Vásárlás a Player Marketplace-ről.")
    async def market_buy_slash(self, interaction: discord.Interaction, listing_id: int, mennyiseg: app_commands.Range[int,1,999]=1) -> None:
        if not await self._gate_interaction(interaction): return
        try: result=await self.social.buy_listing(interaction.guild_id,interaction.user.id,listing_id,mennyiseg)
        except ValueError as exc: return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        await interaction.response.send_message(f"✅ {result['emoji']} **{result['item_name']} ×{result['quantity']}** megvéve • {money(result['gross'])} • market adó: {money(result['tax'])}")

    @app_commands.command(name="marketcancel", description="Saját marketplace listing visszavonása.")
    async def market_cancel_slash(self, interaction: discord.Interaction, listing_id: int) -> None:
        if not await self._gate_interaction(interaction): return
        try: returned=await self.social.cancel_listing(interaction.guild_id,interaction.user.id,listing_id)
        except ValueError as exc: return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        await interaction.response.send_message(f"✅ Listing **#{listing_id}** törölve • **{returned} db** visszakerült az inventorydba.")

    @app_commands.command(name="markethistory", description="Saját Player Marketplace tranzakcióid.")
    async def market_history_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction): return
        rows=await self.social.market_history(interaction.guild_id,interaction.user.id,10)
        if not rows: return await interaction.response.send_message("📭 Még nincs Player Marketplace tranzakciód.",ephemeral=True)
        lines=[]
        for r in rows:
            side="Eladás" if r["seller_id"]==interaction.user.id else "Vétel"
            amount=r["net"] if side=="Eladás" else r["gross"]
            lines.append(f"`#{r['id']}` **{side}** • `{r['item_id']}` ×{r['quantity']} • {money(amount)} • {_fmt_dt(r['created_at'])}")
        await interaction.response.send_message(embed=base_embed("📜 Marketplace history","\n".join(lines)),ephemeral=True)

    # ---------- slash: server shop ----------

    @app_commands.command(name="shop", description="Interaktív szerver-specifikus reward shop.")
    async def server_shop_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction): return
        view = ServerShopView(self, interaction.user.id, interaction.guild_id)
        await interaction.response.send_message(embed=await view.load(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="shopbuy", description="Vásárlás a szerver egyedi reward shopjából.")
    async def server_shop_buy_slash(self, interaction: discord.Interaction, reward_id: int) -> None:
        if not await self._gate_interaction(interaction): return
        if not isinstance(interaction.user,discord.Member): return
        item = await self.social.get_server_shop_item(interaction.guild_id, reward_id)
        if item is not None and str(item["reward_type"]) in {"custom_role", "temporary_custom_role"}:
            return await interaction.response.send_modal(
                CustomRolePurchaseModal(self, interaction.guild_id, interaction.user.id, reward_id)
            )
        try:
            await self._validate_reward_before_purchase(interaction.guild,interaction.user,reward_id)
            purchase=await self.social.begin_server_shop_purchase(interaction.guild_id,interaction.user.id,reward_id)
            delivered=await self._deliver_server_shop(interaction.guild,interaction.user,purchase)
        except ValueError as exc: return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        except (discord.Forbidden,discord.HTTPException) as exc: return await interaction.response.send_message(f"❌ A reward kiosztása nem sikerült, a pénzt visszaadtam. `{exc}`",ephemeral=True)
        await interaction.response.send_message(f"✅ {purchase['emoji']} **{purchase['name']}** megvéve {money(purchase['price'])}-ért.\nReward: {delivered}")

    @app_commands.command(name="shopadd", description="[Admin] Egyedi server-shop reward létrehozása.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(reward_type=[
        app_commands.Choice(name="Permanent Discord role",value="role"),
        app_commands.Choice(name="Temporary existing Discord role",value="temporary_role"),
        app_commands.Choice(name="Custom role created for buyer",value="custom_role"),
        app_commands.Choice(name="Temporary custom role created for buyer",value="temporary_custom_role"),
        app_commands.Choice(name="Yoru inventory item",value="item"),
        app_commands.Choice(name="Custom/manual reward",value="custom"),
    ])
    async def server_shop_add_slash(
        self, interaction: discord.Interaction, nev: str, ar: str, reward_type: app_commands.Choice[str],
        role: discord.Role | None = None, item_id: str | None = None, custom_reward: str | None = None,
        leiras: str = "", emoji: str = "🎁", stock: int = -1, per_user_limit: int = 0,
        activity_level: int = 0, yoru_level: int = 0, duration_minutes: int = 0, reward_quantity: int = 1,
    ) -> None:
        if interaction.guild is None: return await interaction.response.send_message("❌ Szerveren használd.",ephemeral=True)
        typ=reward_type.value
        if typ in {"role","temporary_role"}: ref=str(role.id) if role else ""
        elif typ in {"custom_role", "temporary_custom_role"}: ref="buyer_custom_role"
        elif typ=="item": ref=(item_id or "").strip()
        else: ref=(custom_reward or "").strip()
        try:
            price=parse_amount(ar)
            reward_id=await self.social.create_server_shop_item(interaction.guild_id,name=nev,description=leiras,emoji=emoji,price=price,reward_type=typ,reward_ref=ref,reward_quantity=reward_quantity,stock=stock,per_user_limit=per_user_limit,required_activity_level=activity_level,required_progression_level=yoru_level,duration_minutes=duration_minutes)
        except ValueError as exc: return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        await interaction.response.send_message(f"✅ Server Shop reward létrehozva: **#{reward_id} • {nev}** • {money(price)}",ephemeral=True)

    @app_commands.command(name="shopremove", description="[Admin] Server-shop reward kikapcsolása.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def server_shop_remove_slash(self, interaction: discord.Interaction, reward_id: int) -> None:
        ok=await self.social.disable_server_shop_item(interaction.guild_id,reward_id)
        await interaction.response.send_message("✅ Reward kikapcsolva." if ok else "❌ Nincs ilyen aktív reward.",ephemeral=True)

    @app_commands.command(name="shopclaims", description="[Admin] Függőben lévő custom reward claimek.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def server_shop_claims_slash(self, interaction: discord.Interaction) -> None:
        rows=await self.social.list_pending_claims(interaction.guild_id)
        if not rows: return await interaction.response.send_message("✅ Nincs függőben lévő custom reward claim.",ephemeral=True)
        text="\n".join(f"`#{r['id']}` <@{r['user_id']}> • {r['reward_text'][:120]} • {_fmt_dt(r['created_at'])}" for r in rows)
        await interaction.response.send_message(embed=base_embed("📨 Pending reward claims",text),ephemeral=True)

    @app_commands.command(name="shopfulfill", description="[Admin] Custom reward claim teljesítettnek jelölése.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def server_shop_fulfill_slash(self, interaction: discord.Interaction, claim_id: int) -> None:
        ok=await self.social.fulfill_claim(interaction.guild_id,claim_id,interaction.user.id)
        await interaction.response.send_message("✅ Claim teljesítettnek jelölve." if ok else "❌ Nincs ilyen pending claim.",ephemeral=True)

    # ---------- slash: PvP ----------

    @app_commands.command(name="duel", description="Kihívsz valakit Coinflip/Dice/RPS PvP duelre.")
    @app_commands.choices(game=[
        app_commands.Choice(name="Coinflip",value="coinflip"),
        app_commands.Choice(name="Dice",value="dice"),
        app_commands.Choice(name="Rock Paper Scissors",value="rps"),
    ])
    async def duel_slash(self, interaction: discord.Interaction, ellenfel: discord.Member, tet: str, game: app_commands.Choice[str]) -> None:
        if not await self._gate_interaction(interaction,"gambling"): return
        if ellenfel.bot: return await interaction.response.send_message("❌ Botot nem hívhatsz ki.",ephemeral=True)
        try:
            if await self.bot.casino.active_player_game(interaction.guild_id, interaction.user.id) or await self.bot.casino.active_player_game(interaction.guild_id, ellenfel.id):
                raise ValueError("Valamelyik játékosnak már fut egy Casino játéka.")
            wallet,_=await self.economy.balance(interaction.guild_id,interaction.user.id)
            stake=parse_amount(tet,maximum=wallet)
            duel=await self.social.create_duel(interaction.guild_id,interaction.user.id,ellenfel.id,game.value,stake,interaction.channel_id)
            left_name, right_name = self._duel_names(duel)
            fp = await self._render_pvp(render_duel_challenge, duel.game, left_name, right_name, duel.stake)
        except ValueError as exc: return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        runtime=await self.social.gameplay.social(interaction.guild_id)
        view=DuelChallengeView(self,duel,timeout=runtime.pvp_challenge_seconds)
        await interaction.response.send_message(content=ellenfel.mention,embed=self._duel_challenge_embed(duel),file=discord.File(fp=fp,filename="pvp_challenge.png"),view=view,allowed_mentions=discord.AllowedMentions(users=True,roles=False,everyone=False))
        msg=await interaction.original_response(); view.message=msg; await self.social.set_duel_message(duel.id,msg.id)

    @app_commands.command(name="duelstats", description="PvP duel statisztikák.")
    async def duel_stats_slash(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target=user or interaction.user; s=await self.social.duel_stats(interaction.guild_id,target.id)
        embed=base_embed("⚔️ PvP Duel Stats",f"**{target.display_name}**\n\n🎮 Duels: **{s['social.pvp.duels']}**\n🏆 W/L/T: **{s['social.pvp.wins']} / {s['social.pvp.losses']} / {s['social.pvp.ties']}**\n💸 Wagered: **{money(s['social.pvp.wagered'])}**\n📈 Profit: **{money(s['social.pvp.profit'])}**")
        await interaction.response.send_message(embed=embed)

    # ---------- slash: analytics ----------

    @app_commands.command(name="analytics", description="[Admin] Economy supply és sink/source analytics.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(period=[app_commands.Choice(name="24 óra",value=24),app_commands.Choice(name="7 nap",value=168),app_commands.Choice(name="30 nap",value=720)])
    async def analytics_slash(self, interaction: discord.Interaction, period: app_commands.Choice[int]) -> None:
        await interaction.response.send_message(embed=await self._analytics_embed(interaction.guild_id,period.value),ephemeral=True)

    async def _analytics_embed(self,guild_id:int,hours:int)->discord.Embed:
        a=await self.social.analytics(guild_id,hours)
        period="24h" if hours==24 else ("7d" if hours==168 else f"{hours//24}d")
        embed=base_embed(f"📊 Economy Analytics • {period}",f"👥 Economy userek: **{a['users']}**\n💰 Teljes supply: **{money(a['supply'])}**\n├ Wallet: {money(a['wallet_total'])}\n└ Bank: {money(a['bank_total'])}\n\n🟢 Nettó létrehozott pénz: **{money(a['created'])}**\n🔴 Nettó elégetett pénz: **{money(a['burned'])}**\n⚖️ Supply-változás: **{money(a['net'])}**\n-# Gross credit/debit: {money(a['credits'])} / {money(a['debits'])}")
        embed.add_field(name="💎 Koncentráció",value=f"Top 1: **{a['top1_share']:.1f}%**\nTop 10%: **{a['top10_share']:.1f}%**",inline=True)
        embed.add_field(name="🛒 Social volume",value=f"Market: **{money(a['market_volume'])}** / {a['market_trades']} trade\nPvP: **{money(a['duel_volume'])}** / {a['duels']} duel",inline=True)
        buckets="\n".join(f"**{name}:** {money(value)}" for name,value in list(a['buckets'].items())[:8]) or "Nincs tranzakció."
        embed.add_field(name="🔎 Nettó source / sink kategóriák",value=buckets,inline=False)
        embed.set_footer(text="Pozitív = nettó source • negatív = nettó sink • belső transfer párok kioltják egymást")
        return embed

    # ---------- prefix: marketplace ----------

    @commands.group(name="market",aliases=["marketplace","pmarket","mp"],invoke_without_command=True)
    async def market_prefix(self,ctx:commands.Context,*,query:str="")->None:
        if not await self._gate_ctx(ctx): return
        parts=query.split(maxsplit=1); page=1; search=query or None
        if parts and parts[0].isdigit():
            page=max(1,int(parts[0])); search=parts[1] if len(parts)>1 else None
        view = PlayerMarketView(self, ctx.author.id, ctx.guild.id, search=search)
        view.page = page - 1
        msg = await ctx.send(embed=await view.load(), view=view)
        view.message = msg

    @market_prefix.command(name="list",aliases=["sell","add"])
    async def market_list_prefix(self,ctx:commands.Context,item_id:str,quantity:int,unit_price:str)->None:
        if not await self._gate_ctx(ctx): return
        try: price=parse_amount(unit_price); lid=await self.social.create_listing(ctx.guild.id,ctx.author.id,item_id,quantity,price)
        except ValueError as exc: return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        await ctx.send(f"✅ Listing **#{lid}** létrehozva • `{item_id}` ×{quantity} • **{money(price)}/db**")

    @market_prefix.command(name="buy",aliases=["b"])
    async def market_buy_prefix(self,ctx:commands.Context,listing_id:int,quantity:int=1)->None:
        if not await self._gate_ctx(ctx): return
        try:r=await self.social.buy_listing(ctx.guild.id,ctx.author.id,listing_id,quantity)
        except ValueError as exc:return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        await ctx.send(f"✅ {r['emoji']} **{r['item_name']} ×{r['quantity']}** megvéve • {money(r['gross'])} • adó {money(r['tax'])}")

    @market_prefix.command(name="cancel",aliases=["remove"])
    async def market_cancel_prefix(self,ctx:commands.Context,listing_id:int)->None:
        if not await self._gate_ctx(ctx): return
        try:q=await self.social.cancel_listing(ctx.guild.id,ctx.author.id,listing_id)
        except ValueError as exc:return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        await ctx.send(f"✅ Listing **#{listing_id}** törölve • {q} db visszakerült.")

    @market_prefix.command(name="history",aliases=["hist"])
    async def market_history_prefix(self,ctx:commands.Context)->None:
        if not await self._gate_ctx(ctx): return
        rows=await self.social.market_history(ctx.guild.id,ctx.author.id,10)
        if not rows:return await ctx.send("📭 Még nincs marketplace tranzakciód.")
        lines=[]
        for r in rows:
            side="Eladás" if r['seller_id']==ctx.author.id else "Vétel"; amt=r['net'] if side=="Eladás" else r['gross']
            lines.append(f"`#{r['id']}` **{side}** • `{r['item_id']}` ×{r['quantity']} • {money(amt)}")
        await ctx.send(embed=base_embed("📜 Marketplace history","\n".join(lines)))

    # ---------- prefix: server shop ----------

    @commands.group(name="servershop",aliases=["sshop","customshop"],invoke_without_command=True)
    async def server_shop_prefix(self,ctx:commands.Context)->None:
        if not await self._gate_ctx(ctx):return
        view = ServerShopView(self, ctx.author.id, ctx.guild.id)
        msg = await ctx.send(embed=await view.load(), view=view)
        view.message = msg

    @server_shop_prefix.command(name="buy",aliases=["b"])
    async def server_shop_buy_prefix(self,ctx:commands.Context,reward_id:int)->None:
        if not await self._gate_ctx(ctx):return
        if not isinstance(ctx.author,discord.Member):return
        item = await self.social.get_server_shop_item(ctx.guild.id, reward_id)
        if item is not None and str(item["reward_type"]) in {"custom_role", "temporary_custom_role"}:
            return await ctx.send(embed=error_embed(ctx.author,"Custom role vásárlásnál használd a `!servershop` interaktív panel **Megveszem** gombját, mert ott tudod megadni a role nevét és színét."))
        try:
            await self._validate_reward_before_purchase(ctx.guild,ctx.author,reward_id)
            p=await self.social.begin_server_shop_purchase(ctx.guild.id,ctx.author.id,reward_id)
            delivered=await self._deliver_server_shop(ctx.guild,ctx.author,p)
        except ValueError as exc:return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        except (discord.Forbidden,discord.HTTPException) as exc:return await ctx.send(embed=error_embed(ctx.author,f"Reward delivery fail, refund megtörtént: {exc}"))
        await ctx.send(f"✅ {p['emoji']} **{p['name']}** megvéve • {delivered}")

    @server_shop_prefix.command(name="add")
    async def server_shop_add_prefix(self,ctx:commands.Context,reward_type:str,reward_ref:str,price_raw:str,*,name:str="Custom Reward")->None:
        if not await self._silent_admin(ctx):return
        typ={"temp":"temporary_role","temprole":"temporary_role","role":"role","customrole":"custom_role","tempcustomrole":"temporary_custom_role","item":"item","custom":"custom"}.get(reward_type.lower(),reward_type.lower())
        ref=reward_ref.strip("<@&>") if typ in {"role","temporary_role"} else ("buyer_custom_role" if typ in {"custom_role","temporary_custom_role"} else reward_ref)
        try: price=parse_amount(price_raw); rid=await self.social.create_server_shop_item(ctx.guild.id,name=name,description="",emoji="🎁",price=price,reward_type=typ,reward_ref=ref,duration_minutes=1440 if typ in {"temporary_role","temporary_custom_role"} else 0)
        except ValueError as exc:return await self._dm_admin(ctx.author,f"❌ {exc}")
        await self._dm_admin(ctx.author,f"✅ Server Shop reward létrehozva: #{rid} • {name} • {money(price)}. Részletes követelményekhez használd a `/social shopadd` parancsot.")

    @server_shop_prefix.command(name="remove",aliases=["delete"])
    async def server_shop_remove_prefix(self,ctx:commands.Context,reward_id:int)->None:
        if not await self._silent_admin(ctx):return
        ok=await self.social.disable_server_shop_item(ctx.guild.id,reward_id);await self._dm_admin(ctx.author,"✅ Reward kikapcsolva." if ok else "❌ Nincs ilyen aktív reward.")

    @server_shop_prefix.command(name="claims")
    async def server_shop_claims_prefix(self,ctx:commands.Context)->None:
        if not await self._silent_admin(ctx):return
        rows=await self.social.list_pending_claims(ctx.guild.id)
        text="\n".join(f"#{r['id']} • <@{r['user_id']}> • {r['reward_text']}" for r in rows) or "Nincs pending claim."
        await self._dm_admin(ctx.author,f"📨 **Yoru pending reward claims**\n{text}")

    @server_shop_prefix.command(name="fulfill")
    async def server_shop_fulfill_prefix(self,ctx:commands.Context,claim_id:int)->None:
        if not await self._silent_admin(ctx):return
        ok=await self.social.fulfill_claim(ctx.guild.id,claim_id,ctx.author.id);await self._dm_admin(ctx.author,"✅ Claim teljesítettnek jelölve." if ok else "❌ Nincs ilyen pending claim.")

    # ---------- prefix: PvP / analytics ----------

    @commands.command(name="duel",aliases=["pvp"])
    async def duel_prefix(self,ctx:commands.Context,target:discord.Member,stake_raw:str,game:str="coinflip")->None:
        if not await self._gate_ctx(ctx,"gambling"):return
        if target.bot:return await ctx.send(embed=error_embed(ctx.author,"Botot nem hívhatsz ki."))
        try:
            if await self.bot.casino.active_player_game(ctx.guild.id, ctx.author.id) or await self.bot.casino.active_player_game(ctx.guild.id, target.id): raise ValueError("Valamelyik játékosnak már fut egy Casino játéka.")
            wallet,_=await self.economy.balance(ctx.guild.id,ctx.author.id);stake=parse_amount(stake_raw,maximum=wallet);duel=await self.social.create_duel(ctx.guild.id,ctx.author.id,target.id,game,stake,ctx.channel.id)
            left_name,right_name=self._duel_names(duel);fp=await self._render_pvp(render_duel_challenge,duel.game,left_name,right_name,duel.stake)
        except ValueError as exc:return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        runtime=await self.social.gameplay.social(ctx.guild.id);view=DuelChallengeView(self,duel,timeout=runtime.pvp_challenge_seconds);msg=await ctx.send(content=target.mention,embed=self._duel_challenge_embed(duel),file=discord.File(fp=fp,filename="pvp_challenge.png"),view=view,allowed_mentions=discord.AllowedMentions(users=True,roles=False,everyone=False));view.message=msg;await self.social.set_duel_message(duel.id,msg.id)

    @commands.command(name="duelstats",aliases=["pvpstats"])
    async def duel_stats_prefix(self,ctx:commands.Context,target:discord.Member|None=None)->None:
        target=target or ctx.author;s=await self.social.duel_stats(ctx.guild.id,target.id);await ctx.send(embed=base_embed("⚔️ PvP Duel Stats",f"**{target.display_name}**\n🎮 {s['social.pvp.duels']} duel • 🏆 {s['social.pvp.wins']}W / {s['social.pvp.losses']}L / {s['social.pvp.ties']}T\n💸 Wagered {money(s['social.pvp.wagered'])} • 📈 Profit {money(s['social.pvp.profit'])}"))

    @commands.command(name="ecoanalytics",aliases=["economyanalytics","eanalytics"])
    async def analytics_prefix(self,ctx:commands.Context,period:str="24h")->None:
        if not await self._silent_admin(ctx):return
        hours=168 if period.lower() in {"7d","week","weekly"} else (720 if period.lower() in {"30d","month"} else 24)
        # Admin prefix commands are silent: send analytics by DM.
        try:await ctx.author.send(embed=await self._analytics_embed(ctx.guild.id,hours))
        except discord.HTTPException:pass

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error,app_commands.MissingPermissions):
            text="❌ Ehhez **Szerver kezelése** jogosultság kell."
        else:
            text=f"❌ {getattr(error,'original',error)}"
        if interaction.response.is_done(): await interaction.followup.send(text,ephemeral=True)
        else: await interaction.response.send_message(text,ephemeral=True)
