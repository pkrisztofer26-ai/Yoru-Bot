from __future__ import annotations

import math

import discord

from app.services.shop import ShopService
from app.ui import money
from app import economy_config as eco


CATEGORY_LABELS = {
    "all": "🛒 Összes",
    "market": "📈 Napi piac",
    "game": "🎮 Játék",
    "lootbox": "📦 Ládák",
    "booster": "⚡ Boosterek",
    "utility": "🧰 Utility",
    "reward": "🎁 Jutalmak",
}

RARITY_LABELS = {
    "common": "⚪ Common",
    "rare": "🔵 Rare",
    "epic": "🟣 Epic",
    "legendary": "🟡 Legendary",
    "mythic": "🔴 Mythic",
}

ITEMS_PER_PAGE = 5


def _price_button_label(price: int) -> str:
    # money() includes the currency symbol. Keeping the button compact makes the
    # right-hand accessory feel much closer to Discord's native store layout.
    return money(price)


class BuyItemButton(discord.ui.Button):
    def __init__(
        self,
        *,
        shop: ShopService,
        guild_id: int,
        item_id: str,
        price: int,
        category: str,
        page: int,
    ) -> None:
        super().__init__(
            label=_price_button_label(price),
            emoji="💰",
            style=discord.ButtonStyle.success,
            custom_id=f"yoru_shop_buy:{guild_id}:{item_id}",
        )
        self.shop = shop
        self.guild_id = guild_id
        self.item_id = item_id
        self.category = category
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            return await interaction.response.send_message("❌ Ez a shop nem ehhez a szerverhez tartozik.", ephemeral=True)

        try:
            name, emoji, total_price, new_wallet, stock = await self.shop.buy(
                self.guild_id,
                interaction.user.id,
                self.item_id,
                1,
            )
        except (ValueError, LookupError) as error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)

        if self.item_id in eco.PREMIUM_REWARD_RULES and stock is not None:
            stock_text = f"\n🎁 Havi szerverkészlet: **{stock} db**"
        else:
            stock_text = f"\n📦 Mai készlet: **{stock} db**" if stock is not None else ""
        await interaction.response.send_message(
            f"✅ Megvetted: **{emoji} {name}**\n"
            f"💰 Ár: **{money(total_price)}**\n"
            f"👛 Maradék: **{money(new_wallet)}**{stock_text}",
            ephemeral=True,
        )

        # Market stock changes instantly, so refresh the public shop message too.
        if interaction.message is not None:
            try:
                refreshed = await build_shop_view(
                    self.shop,
                    self.guild_id,
                    category=self.category,
                    page=self.page,
                )
                await interaction.message.edit(view=refreshed)
            except discord.HTTPException:
                pass


class ShopCategorySelect(discord.ui.Select):
    def __init__(self, *, shop: ShopService, guild_id: int, current: str) -> None:
        options = [
            discord.SelectOption(
                label=label.split(" ", 1)[1],
                value=value,
                emoji=label.split(" ", 1)[0],
                default=value == current,
            )
            for value, label in CATEGORY_LABELS.items()
        ]
        super().__init__(
            placeholder="Shop kategória",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"yoru_shop_category:{guild_id}",
        )
        self.shop = shop
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        category = self.values[0]
        view = await build_shop_view(self.shop, self.guild_id, category=category, page=0)
        await interaction.response.edit_message(view=view)


class ShopPageButton(discord.ui.Button):
    def __init__(
        self,
        *,
        shop: ShopService,
        guild_id: int,
        category: str,
        page: int,
        direction: int,
        disabled: bool,
    ) -> None:
        super().__init__(
            label="Előző" if direction < 0 else "Következő",
            emoji="◀️" if direction < 0 else "▶️",
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
            custom_id=f"yoru_shop_page:{guild_id}:{category}:{page}:{direction}",
        )
        self.shop = shop
        self.guild_id = guild_id
        self.category = category
        self.page = page
        self.direction = direction

    async def callback(self, interaction: discord.Interaction) -> None:
        view = await build_shop_view(
            self.shop,
            self.guild_id,
            category=self.category,
            page=max(0, self.page + self.direction),
        )
        await interaction.response.edit_message(view=view)


class InventoryButton(discord.ui.Button):
    def __init__(self, *, shop: ShopService, guild_id: int) -> None:
        super().__init__(
            label="Inventory",
            emoji="🎒",
            style=discord.ButtonStyle.secondary,
            custom_id=f"yoru_shop_inventory:{guild_id}",
        )
        self.shop = shop
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        items = await self.shop.inventory(self.guild_id, interaction.user.id)
        if not items:
            return await interaction.response.send_message("🎒 Az inventoryd jelenleg üres.", ephemeral=True)

        lines = [f"{emoji} **{name}** × `{quantity}` • `{item_id}`" for item_id, name, emoji, quantity in items]
        await interaction.response.send_message(
            "### 🎒 Inventory\n" + "\n".join(lines)[:3800],
            ephemeral=True,
        )


async def build_shop_view(
    shop: ShopService,
    guild_id: int,
    *,
    category: str | None = None,
    page: int = 0,
) -> discord.ui.LayoutView:
    selected_category = (category or "all").lower().strip()
    if selected_category not in CATEGORY_LABELS:
        selected_category = "all"

    items = await shop.list_for_guild(guild_id)
    if selected_category != "all":
        items = [item for item in items if str(item["category"]) == selected_category]

    total_pages = max(1, math.ceil(len(items) / ITEMS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * ITEMS_PER_PAGE
    visible_items = items[start : start + ITEMS_PER_PAGE]

    view = discord.ui.LayoutView(timeout=900)
    container = discord.ui.Container(accent_colour=discord.Colour.blurple())

    title = CATEGORY_LABELS[selected_category]
    container.add_item(discord.ui.TextDisplay(
        f"# 🌙 Yoru Store\n"
        f"**{title}**\n"
        "Kattints egy item jobb oldalán lévő **ár gombra** az 1 darabos azonnali vásárláshoz. "
        "Nagyobb mennyiséghez továbbra is használható a `!buy <id> <db>` vagy `/buy`."
    ))
    container.add_item(discord.ui.Separator())

    if not visible_items:
        container.add_item(discord.ui.TextDisplay("*Ebben a kategóriában jelenleg nincs megvásárolható item.*"))
    else:
        for index, item in enumerate(visible_items):
            extra = ""
            if bool(item["market"]):
                extra = f"\n📦 Mai készlet: **{item['stock']} db** • az ár naponta változik"
            elif str(item["category"]) == "reward":
                rule = eco.PREMIUM_REWARD_RULES.get(str(item["item_id"]))
                remaining = item.get("premium_remaining")
                if rule:
                    extra = (
                        f"\n🎁 Prémium jutalom • **{remaining} db** maradt ebben a hónapban"
                        f"\n🔒 {rule['min_account_age_days']} napos account • Level {rule['min_level']} • "
                        f"1 db / {rule['personal_cooldown_days']} nap / fő"
                    )
                else:
                    extra = "\n🎁 Prémium jutalom • pénzre nem váltható vissza"

            text = (
                f"### {item['emoji']} {item['name']}\n"
                f"{item['description']}\n"
                f"`{item['item_id']}` • {RARITY_LABELS.get(str(item['rarity']), str(item['rarity']))}{extra}"
            )
            button = BuyItemButton(
                shop=shop,
                guild_id=guild_id,
                item_id=str(item["item_id"]),
                price=int(item["price"]),
                category=selected_category,
                page=page,
            )
            if str(item["category"]) == "reward" and item.get("premium_remaining") == 0:
                button.disabled = True
            container.add_item(discord.ui.Section(discord.ui.TextDisplay(text), accessory=button))
            if index != len(visible_items) - 1:
                container.add_item(discord.ui.Separator())

    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(
        f"-# Oldal **{page + 1}/{total_pages}** • A napi piac UTC éjfélkor frissül • "
        "A gombos vásárlás mindig 1 darabot vesz."
    ))
    view.add_item(container)

    category_row = discord.ui.ActionRow(
        ShopCategorySelect(shop=shop, guild_id=guild_id, current=selected_category)
    )
    view.add_item(category_row)

    navigation = discord.ui.ActionRow(
        ShopPageButton(
            shop=shop,
            guild_id=guild_id,
            category=selected_category,
            page=page,
            direction=-1,
            disabled=page <= 0,
        ),
        ShopPageButton(
            shop=shop,
            guild_id=guild_id,
            category=selected_category,
            page=page,
            direction=1,
            disabled=page >= total_pages - 1,
        ),
        InventoryButton(shop=shop, guild_id=guild_id),
    )
    view.add_item(navigation)
    return view
