from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from app import business_config as cfg
from app.cogs.access_utils import handle_wrong_economy_channel
from app.ui import BRAND, DANGER, GOLD, SUCCESS, base_embed, error_embed, money, progress_bar


def _short_dt(raw: str | None) -> str:
    if not raw:
        return "—"
    try:
        value = datetime.fromisoformat(str(raw))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return f"<t:{int(value.timestamp())}:R>"
    except ValueError:
        return "—"


class PlayerBusinessView(discord.ui.View):
    def __init__(
        self,
        cog: "BusinessCog",
        owner_id: int,
        *,
        mode: str = "home",
        selected_property_id: int | None = None,
        selected_worker_key: str | None = None,
        selected_offer_id: int | None = None,
        selected_offer_direction: str | None = None,
        market_page: int = 0,
    ) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.mode = mode
        self.selected_property_id = selected_property_id
        self.selected_worker_key = selected_worker_key
        self.selected_offer_id = selected_offer_id
        self.selected_offer_direction = selected_offer_direction
        self.market_page = max(0, int(market_page))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a Biznisz panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    async def rebuild(self, interaction: discord.Interaction) -> None:
        embed, view = await self.cog.build_player_panel(
            interaction.guild,
            interaction.user,
            mode=self.mode,
            selected_property_id=self.selected_property_id,
            selected_worker_key=self.selected_worker_key,
            selected_offer_id=self.selected_offer_id,
            selected_offer_direction=self.selected_offer_direction,
            market_page=self.market_page,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class PropertySelect(discord.ui.Select):
    def __init__(self, view: PlayerBusinessView, properties: list[dict], *, row: int = 0, placeholder: str = "Válassz propertyt…") -> None:
        self.parent_view = view
        options = []
        for prop in properties[:25]:
            options.append(
                discord.SelectOption(
                    label=f"#{prop['property_id']} • {prop['name']}"[:100],
                    value=str(prop["property_id"]),
                    emoji=str(prop.get("emoji") or "🏢"),
                    description=f"{prop['city']} • Lv.{prop['level']} • Rep {prop['reputation']}"[:100],
                    default=view.selected_property_id == int(prop["property_id"]),
                )
            )
        if not options:
            options = [discord.SelectOption(label="Nincs property", value="none", description="Előbb szerezz egy bizniszt.")]
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1, row=row, disabled=not properties)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "none":
            return
        self.parent_view.selected_property_id = int(self.values[0])
        await self.parent_view.rebuild(interaction)


class MarketPropertySelect(discord.ui.Select):
    def __init__(self, view: PlayerBusinessView, properties: list[dict], *, row: int = 0) -> None:
        self.parent_view = view
        options = []
        for prop in properties[:25]:
            owner = prop.get("owner_id")
            status = "Szabad" if owner is None else ("Saját" if int(owner) == view.owner_id else "Player-owned")
            options.append(
                discord.SelectOption(
                    label=f"#{prop['property_id']} • {prop['name']}"[:100],
                    value=str(prop["property_id"]),
                    emoji=str(prop.get("emoji") or "🏢"),
                    description=f"{prop['city']} • {status} • {money(prop['base_price'])}"[:100],
                    default=view.selected_property_id == int(prop["property_id"]),
                )
            )
        super().__init__(placeholder="Válassz propertyt a piacról…", options=options, min_values=1, max_values=1, row=row, disabled=not options)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_property_id = int(self.values[0])
        await self.parent_view.rebuild(interaction)


class WorkerSelect(discord.ui.Select):
    def __init__(self, view: PlayerBusinessView, workers: list[cfg.WorkerDefinition], *, row: int = 1) -> None:
        self.parent_view = view
        options = [
            discord.SelectOption(
                label=worker.name[:100],
                value=worker.key,
                emoji=worker.emoji,
                description=f"{worker.tier} • +{worker.revenue_bonus_percent}% • {money(worker.hire_fee)}"[:100],
                default=view.selected_worker_key == worker.key,
            )
            for worker in workers[:25]
        ]
        super().__init__(placeholder="Mai dolgozói rotáció…", options=options, min_values=1, max_values=1, row=row, disabled=not options)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_worker_key = self.values[0]
        await self.parent_view.rebuild(interaction)


class OfferSelect(discord.ui.Select):
    def __init__(self, view: PlayerBusinessView, incoming: list[dict], outgoing: list[dict], *, row: int = 0) -> None:
        self.parent_view = view
        options: list[discord.SelectOption] = []
        for offer in incoming[:12]:
            options.append(discord.SelectOption(
                label=f"BE #{offer['offer_id']} • {offer['property_name']}"[:100],
                value=f"in:{offer['offer_id']}", emoji="📥",
                description=f"<@{offer['buyer_id']}> • {money(offer['amount'])}"[:100],
                default=view.selected_offer_id == int(offer["offer_id"]) and view.selected_offer_direction == "in",
            ))
        for offer in outgoing[:12]:
            options.append(discord.SelectOption(
                label=f"KI #{offer['offer_id']} • {offer['property_name']}"[:100],
                value=f"out:{offer['offer_id']}", emoji="📤",
                description=f"{money(offer['amount'])} escrow"[:100],
                default=view.selected_offer_id == int(offer["offer_id"]) and view.selected_offer_direction == "out",
            ))
        if not options:
            options = [discord.SelectOption(label="Nincs aktív ajánlat", value="none")]
        super().__init__(placeholder="Válassz aktív ajánlatot…", options=options, min_values=1, max_values=1, row=row, disabled=(options[0].value == "none"))

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "none":
            return
        direction, raw = self.values[0].split(":", 1)
        self.parent_view.selected_offer_direction = direction
        self.parent_view.selected_offer_id = int(raw)
        await self.parent_view.rebuild(interaction)


class OfferAmountModal(discord.ui.Modal, title="🏢 Property ajánlat"):
    amount = discord.ui.TextInput(label="Ajánlat összege", placeholder="pl. 150m", min_length=1, max_length=32)

    def __init__(self, cog: "BusinessCog", owner_id: int, property_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.owner_id = owner_id
        self.property_id = property_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = self.cog.parse_money(str(self.amount.value))
            result = await self.cog.service.create_offer(interaction.guild_id, self.owner_id, self.property_id, amount)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await interaction.response.send_message(
            f"📨 Ajánlat escrow-ba rakva: **{result['property_name']}** • **{money(result['amount'])}**. "
            f"A tulaj az Ajánlatok panelen elfogadhatja vagy elutasíthatja.",
            ephemeral=True,
        )


class UnlockSettingsModal(discord.ui.Modal, title="Biznisz unlock"):
    activity = discord.ui.TextInput(label="Minimum Activity Level", min_length=1, max_length=4)
    prestige = discord.ui.TextInput(label="Minimum Prestige", min_length=1, max_length=3)
    license_price = discord.ui.TextInput(label="Business License ára", placeholder="pl. 15m", min_length=1, max_length=32)

    def __init__(self, cog: "BusinessCog", owner_id: int, settings) -> None:
        super().__init__(); self.cog = cog; self.owner_id = owner_id
        self.activity.default = str(settings.required_activity_level)
        self.prestige.default = str(settings.required_prestige)
        self.license_price.default = str(settings.license_price)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.service.set_unlock_settings(
                interaction.guild_id,
                activity_level=int(str(self.activity.value)),
                prestige=int(str(self.prestige.value)),
                license_price=self.cog.parse_money(str(self.license_price.value)),
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.cog.show_settings(interaction, self.owner_id)


class EconomySettingsModal(discord.ui.Modal, title="Biznisz economy"):
    tax = discord.ui.TextInput(label="Business adó %", min_length=1, max_length=3)
    offline = discord.ui.TextInput(label="Offline termelési cap (óra)", min_length=1, max_length=3)
    multiplier = discord.ui.TextInput(label="Bevételi szorzó %", min_length=1, max_length=4)
    worker_days = discord.ui.TextInput(label="Worker contract (nap)", min_length=1, max_length=2)

    def __init__(self, cog: "BusinessCog", owner_id: int, settings) -> None:
        super().__init__(); self.cog = cog; self.owner_id = owner_id
        self.tax.default = str(settings.tax_percent); self.offline.default = str(settings.offline_cap_hours)
        self.multiplier.default = str(settings.income_multiplier_percent); self.worker_days.default = str(settings.worker_contract_days)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.service.set_economy_settings(
                interaction.guild_id,
                tax_percent=int(str(self.tax.value)), offline_cap_hours=int(str(self.offline.value)),
                income_multiplier_percent=int(str(self.multiplier.value)), worker_contract_days=int(str(self.worker_days.value)),
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.cog.show_settings(interaction, self.owner_id)


class LimitSettingsModal(discord.ui.Modal, title="Biznisz anti-monopoly"):
    base_cap = discord.ui.TextInput(label="Alap property limit", min_length=1, max_length=2)
    prestige_step = discord.ui.TextInput(label="+1 property / ennyi Prestige", min_length=1, max_length=2)
    absolute_cap = discord.ui.TextInput(label="Abszolút property limit", min_length=1, max_length=2)
    city_cap = discord.ui.TextInput(label="Maximum property / város", min_length=1, max_length=2)

    def __init__(self, cog: "BusinessCog", owner_id: int, settings) -> None:
        super().__init__(); self.cog = cog; self.owner_id = owner_id
        self.base_cap.default = str(settings.base_property_cap); self.prestige_step.default = str(settings.prestige_step)
        self.absolute_cap.default = str(settings.absolute_cap); self.city_cap.default = str(settings.city_cap)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.service.set_limit_settings(
                interaction.guild_id,
                base_cap=int(str(self.base_cap.value)), prestige_step=int(str(self.prestige_step.value)),
                absolute_cap=int(str(self.absolute_cap.value)), city_cap=int(str(self.city_cap.value)),
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.cog.show_settings(interaction, self.owner_id)


class MarketSettingsModal(discord.ui.Modal, title="Biznisz market / Frakció"):
    offer_hours=discord.ui.TextInput(label="Property offer lejárat (óra)",max_length=5)
    transfer_tax=discord.ui.TextInput(label="Property transfer tax %",max_length=3)
    faction_bonus=discord.ui.TextInput(label="Frakció payout bonus %",max_length=3)
    faction_xp=discord.ui.TextInput(label="Frakció XP / claim",max_length=10)
    def __init__(self,cog:"BusinessCog",owner_id:int,settings)->None:
        super().__init__();self.cog,self.owner_id=cog,owner_id
        self.offer_hours.default=str(settings.property_offer_hours);self.transfer_tax.default=str(settings.transfer_tax_percent);self.faction_bonus.default=str(settings.faction_bonus_percent);self.faction_xp.default=str(settings.faction_xp_per_claim)
    async def on_submit(self,interaction:discord.Interaction)->None:
        try:await self.cog.service.set_market_settings(interaction.guild_id,offer_hours=int(str(self.offer_hours.value)),transfer_tax_percent=int(str(self.transfer_tax.value)),faction_bonus_percent=int(str(self.faction_bonus.value)),faction_xp_per_claim=int(str(self.faction_xp.value)))
        except ValueError as exc:return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        await self.cog.show_settings(interaction,self.owner_id)


class BusinessAdminView(discord.ui.View):
    def __init__(self, cog: "BusinessCog", owner_id: int, enabled: bool) -> None:
        super().__init__(timeout=600); self.cog = cog; self.owner_id = owner_id; self.enabled = enabled
        self.toggle.label = "Biznisz: ON" if enabled else "Biznisz: OFF"
        self.toggle.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a settings panelt nem te nyitottad meg.", ephemeral=True); return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Ehhez **Szerver kezelése** jogosultság kell.", ephemeral=True); return False
        return True

    @discord.ui.button(label="Biznisz", emoji="🏢", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.service.set_enabled(interaction.guild_id, not self.enabled)
        await self.cog.show_settings(interaction, self.owner_id)

    @discord.ui.button(label="Unlock", emoji="🔓", style=discord.ButtonStyle.secondary, row=0)
    async def unlock(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(UnlockSettingsModal(self.cog, self.owner_id, await self.cog.service.get_settings(interaction.guild_id)))

    @discord.ui.button(label="Economy", emoji="💰", style=discord.ButtonStyle.secondary, row=0)
    async def economy(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(EconomySettingsModal(self.cog, self.owner_id, await self.cog.service.get_settings(interaction.guild_id)))

    @discord.ui.button(label="Anti-monopoly", emoji="⚖️", style=discord.ButtonStyle.secondary, row=0)
    async def limits(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(LimitSettingsModal(self.cog, self.owner_id, await self.cog.service.get_settings(interaction.guild_id)))

    @discord.ui.button(label="Market / Frakció", emoji="🤝", style=discord.ButtonStyle.secondary, row=1)
    async def market_tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(MarketSettingsModal(self.cog,self.owner_id,await self.cog.service.get_settings(interaction.guild_id)))

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        settings_cog = self.cog.bot.get_cog("SettingsCog")
        if settings_cog is None:
            return await interaction.response.send_message("❌ Settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, self.owner_id)


class BusinessCog(commands.Cog):
    business = app_commands.Group(name="business", description="Biznisz Empire – ingatlanok, dolgozók és property piac.")

    def __init__(self, bot, database, economy, service) -> None:
        self.bot = bot
        self.db = database
        self.economy = economy
        self.service = service

    async def home_status(self, guild: discord.Guild) -> str:
        settings = await self.service.get_settings(guild.id)
        return (
            f"{'🟢 ON' if settings.enabled else '🔴 OFF'} • "
            f"Activity Lv.{settings.required_activity_level} • Prestige {settings.required_prestige}"
        )

    @staticmethod
    def parse_money(raw: str) -> int:
        value = raw.strip().lower().replace(" ", "").replace("_", "").replace(",", ".")
        multipliers = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "t": 1_000_000_000_000}
        multiplier = 1
        if value and value[-1] in multipliers:
            multiplier = multipliers[value[-1]]; value = value[:-1]
        try:
            amount = int(float(value) * multiplier)
        except (TypeError, ValueError):
            raise ValueError("Érvénytelen összeg. Példa: `15m`, `25000000`.")
        if amount <= 0:
            raise ValueError("Az összeg legyen pozitív.")
        return amount

    async def _prefix_access(self, ctx: commands.Context) -> bool:
        try:
            await self.economy.prepare_context(ctx.guild.id)
            await self.economy.guild_settings.require_channel(ctx.guild.id, ctx.channel.id, getattr(ctx.channel, "category_id", None))
            return True
        except ValueError:
            await handle_wrong_economy_channel(ctx, self.economy)
            return False

    async def _slash_access(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None or interaction.channel is None:
            await interaction.response.send_message("❌ Ez csak szerveren használható.", ephemeral=True); return False
        try:
            await self.economy.prepare_context(interaction.guild_id)
            await self.economy.guild_settings.require_channel(interaction.guild_id, interaction.channel.id, getattr(interaction.channel, "category_id", None))
            return True
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True); return False

    async def build_player_panel(
        self, guild: discord.Guild, user: discord.abc.User, *, mode: str = "home",
        selected_property_id: int | None = None, selected_worker_key: str | None = None,
        selected_offer_id: int | None = None, selected_offer_direction: str | None = None,
        market_page: int = 0,
    ) -> tuple[discord.Embed, PlayerBusinessView]:
        guild_id, user_id = guild.id, user.id
        settings = await self.service.get_settings(guild_id)
        owned = await self.service.properties(guild_id, owner_id=user_id)
        if selected_property_id is None and owned:
            selected_property_id = int(owned[0]["property_id"])
        view = PlayerBusinessView(
            self, user_id, mode=mode, selected_property_id=selected_property_id,
            selected_worker_key=selected_worker_key, selected_offer_id=selected_offer_id,
            selected_offer_direction=selected_offer_direction, market_page=market_page,
        )

        if mode == "market":
            all_props = await self.service.properties(guild_id)
            page_size = 6
            page_count = max(1, (len(all_props) + page_size - 1) // page_size)
            view.market_page = max(0, min(view.market_page, page_count - 1))
            visible = all_props[view.market_page * page_size:(view.market_page + 1) * page_size]
            if selected_property_id is None and visible:
                selected_property_id = int(visible[0]["property_id"]); view.selected_property_id = selected_property_id
            embed = base_embed("🏙️ Biznisz Empire • Ingatlanpiac", "A helyszínek valódi magyar címkék; minden üzlet és property fikciós game-world tartalom.", GOLD)
            for prop in visible:
                owner = prop.get("owner_id")
                status = "🟢 Szabad" if owner is None else ("👑 Saját" if int(owner) == user_id else f"🔒 <@{int(owner)}>")
                embed.add_field(
                    name=f"{prop['emoji']} #{prop['property_id']} • {prop['name']}",
                    value=f"**{prop['city']} • {prop['district']}**\n{prop['street']}\n{status} • **{money(prop['base_price'])}**\nAlap: {money(prop['base_hourly_revenue'])}/óra",
                    inline=True,
                )
            embed.set_footer(text=f"Yoru • Biznisz Empire • {view.market_page + 1}/{page_count}. oldal • Player-owned propertyre escrow ajánlat küldhető")
            if all_props:
                view.add_item(MarketPropertySelect(view, visible))
            selected = await self.service.get_property(guild_id, selected_property_id) if selected_property_id else None
            buy = discord.ui.Button(label="Megveszem" if selected and selected.get("owner_id") is None else "Ajánlat küldése", emoji="💸", style=discord.ButtonStyle.success, row=1)
            if selected and selected.get("owner_id") is not None and int(selected["owner_id"]) == user_id:
                buy.disabled = True; buy.label = "Ez már a tiéd"
            async def buy_cb(interaction: discord.Interaction) -> None:
                prop = await self.service.get_property(guild_id, view.selected_property_id)
                if prop is None: return await interaction.response.send_message("❌ Válassz propertyt.", ephemeral=True)
                if prop.get("owner_id") is None:
                    try:
                        result = await self.service.buy_property(guild_id, user_id, int(prop["property_id"]))
                    except ValueError as exc:
                        return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
                    await interaction.response.send_message(f"🏢 Megvetted: **{result['name']}** • {money(result['price'])}.", ephemeral=True)
                elif int(prop["owner_id"]) != user_id:
                    await interaction.response.send_modal(OfferAmountModal(self, user_id, int(prop["property_id"])))
                else:
                    await interaction.response.send_message("❌ Ez már a te propertyd.", ephemeral=True)
            buy.callback = buy_cb; view.add_item(buy)
            prev = discord.ui.Button(label="Előző", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1, disabled=view.market_page <= 0)
            nxt = discord.ui.Button(label="Következő", emoji="➡️", style=discord.ButtonStyle.secondary, row=1, disabled=view.market_page >= page_count - 1)
            async def prev_cb(interaction): view.market_page -= 1; await view.rebuild(interaction)
            async def next_cb(interaction): view.market_page += 1; await view.rebuild(interaction)
            prev.callback = prev_cb; nxt.callback = next_cb; view.add_item(prev); view.add_item(nxt)
            back = discord.ui.Button(label="Birodalmam", emoji="🏢", style=discord.ButtonStyle.primary, row=1)
            async def back_cb(interaction): view.mode="home"; await view.rebuild(interaction)
            back.callback = back_cb; view.add_item(back)
            return embed, view

        if mode == "workers":
            embed = base_embed("👷 Biznisz Empire • Dolgozók", "A worker pool naponta rotálódik. A szerződés lejár, a bér pedig termelés közben költségként számolódik.", BRAND)
            if owned:
                view.add_item(PropertySelect(view, owned, row=0, placeholder="Melyik propertyre veszel fel dolgozót?"))
                prop = await self.service.get_property(guild_id, view.selected_property_id)
                active = await self.service.active_workers(guild_id, int(prop["property_id"])) if prop else []
                slots = (int(prop["max_workers"]) + max(0, int(prop["level"]) - 1) // 2) if prop else 0
                embed.add_field(name=f"{prop['emoji']} {prop['name']}", value=f"Worker slot: **{len(active)}/{slots}**", inline=False)
                if active:
                    embed.add_field(name="Aktív csapat", value="\n".join(f"• **{w['name']}** • +{w['revenue_bonus_percent']}% • {money(w['wage_per_hour'])}/h • {_short_dt(w['expires_at'])}" for w in active)[:1024], inline=False)
                pool = await self.service.worker_pool(guild_id)
                view.add_item(WorkerSelect(view, pool, row=1))
                selected_worker = cfg.WORKER_BY_KEY.get(view.selected_worker_key or "")
                if selected_worker is None and pool:
                    selected_worker = pool[0]; view.selected_worker_key = selected_worker.key
                if selected_worker:
                    embed.add_field(name="Kiválasztott jelölt", value=f"{selected_worker.emoji} **{selected_worker.name}** • {selected_worker.tier}\n+{selected_worker.revenue_bonus_percent}% bevétel • Hire: {money(selected_worker.hire_fee)} • Bér: {money(selected_worker.wage_per_hour)}/h", inline=False)
                hire = discord.ui.Button(label="Felveszem", emoji="➕", style=discord.ButtonStyle.success, row=2, disabled=selected_worker is None)
                async def hire_cb(interaction):
                    try:
                        result = await self.service.hire_worker(guild_id, user_id, view.selected_property_id, view.selected_worker_key)
                    except ValueError as exc:
                        return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
                    await interaction.response.send_message(f"👷 **{result['worker'].name}** felvéve. Lejár: <t:{int(result['expires_at'].timestamp())}:R>.", ephemeral=True)
                hire.callback = hire_cb; view.add_item(hire)
            else:
                embed.description = "Még nincs propertyd. Az Ingatlanpiacon tudsz vásárolni."
            market = discord.ui.Button(label="Ingatlanpiac", emoji="🏙️", style=discord.ButtonStyle.secondary, row=2)
            async def market_cb(interaction): view.mode="market"; await view.rebuild(interaction)
            market.callback = market_cb; view.add_item(market)
            back = discord.ui.Button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
            async def back_cb(interaction): view.mode="home"; await view.rebuild(interaction)
            back.callback = back_cb; view.add_item(back)
            return embed, view

        if mode == "offers":
            incoming = await self.service.offers(guild_id, user_id, incoming=True)
            outgoing = await self.service.offers(guild_id, user_id, incoming=False)
            embed = base_embed("🤝 Biznisz Empire • Property ajánlatok", "Az ajánlat összege azonnal escrow-ba kerül. Elutasítás/lejárat/cancel esetén visszajár.", GOLD)
            embed.add_field(name="📥 Bejövő", value="\n".join(f"`#{o['offer_id']}` {o['emoji']} **{o['property_name']}** • <@{o['buyer_id']}> • {money(o['amount'])}" for o in incoming[:8]) or "Nincs.", inline=False)
            embed.add_field(name="📤 Kimenő", value="\n".join(f"`#{o['offer_id']}` {o['emoji']} **{o['property_name']}** • {money(o['amount'])} • {_short_dt(o['expires_at'])}" for o in outgoing[:8]) or "Nincs.", inline=False)
            view.add_item(OfferSelect(view, incoming, outgoing, row=0))
            accept = discord.ui.Button(label="Elfogad", emoji="✅", style=discord.ButtonStyle.success, row=1, disabled=not (view.selected_offer_id and view.selected_offer_direction == "in"))
            reject = discord.ui.Button(label="Elutasít", emoji="❌", style=discord.ButtonStyle.danger, row=1, disabled=not (view.selected_offer_id and view.selected_offer_direction == "in"))
            cancel = discord.ui.Button(label="Visszavon", emoji="↩️", style=discord.ButtonStyle.secondary, row=1, disabled=not (view.selected_offer_id and view.selected_offer_direction == "out"))
            async def accept_cb(interaction):
                try: result = await self.service.resolve_offer(guild_id, user_id, view.selected_offer_id, accept=True)
                except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
                await interaction.response.send_message(f"✅ **{result['property_name']}** eladva <@{result['buyer_id']}> részére. Nettó: **{money(result['seller_net'])}**.", ephemeral=True)
            async def reject_cb(interaction):
                try: result = await self.service.resolve_offer(guild_id, user_id, view.selected_offer_id, accept=False)
                except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
                await interaction.response.send_message(f"❌ **{result['property_name']}** ajánlat elutasítva; escrow refundolva.", ephemeral=True)
            async def cancel_cb(interaction):
                try: amount = await self.service.cancel_offer(guild_id, user_id, view.selected_offer_id)
                except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
                await interaction.response.send_message(f"↩️ Ajánlat visszavonva, **{money(amount)}** visszakerült.", ephemeral=True)
            accept.callback=accept_cb; reject.callback=reject_cb; cancel.callback=cancel_cb
            view.add_item(accept); view.add_item(reject); view.add_item(cancel)
            market = discord.ui.Button(label="Új ajánlat", emoji="🏙️", style=discord.ButtonStyle.primary, row=1)
            async def market_cb(interaction): view.mode="market"; await view.rebuild(interaction)
            market.callback=market_cb; view.add_item(market)
            back = discord.ui.Button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
            async def back_cb(interaction): view.mode="home"; await view.rebuild(interaction)
            back.callback=back_cb; view.add_item(back)
            return embed, view

        if mode == "leaderboard":
            board = await self.service.leaderboard(guild_id, 10)
            lines = []
            for idx, row in enumerate(board, 1):
                lines.append(f"**#{idx}** <@{row['user_id']}> • **{money(row['empire_value'])}** • {row['properties']} property • {row['reputation']} Rep")
            embed = base_embed("🏆 Biznisz Empire • Ranglista", "\n".join(lines) if lines else "Még nincs üzleti birodalom ezen a szerveren.", GOLD)
            back = discord.ui.Button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
            async def back_cb(interaction): view.mode="home"; await view.rebuild(interaction)
            back.callback=back_cb; view.add_item(back)
            return embed, view

        # Home / empire view.
        eligibility = await self.service.eligibility(guild_id, user_id)
        cap = await self.service.property_cap(guild_id, user_id)
        embed = base_embed("🏢 Biznisz Empire", "Építs magyar game-world helyszíneken saját üzleti birodalmat, fejlessz, alkalmazz dolgozókat és kereskedj propertykkel.", BRAND)
        embed.add_field(
            name="📜 Business License",
            value=("✅ Permanent license aktív" if eligibility["has_license"] else f"❌ Nincs • Ár: **{money(eligibility['license_price'])}**\nKell: Activity **{eligibility['required_activity_level']}** + Prestige **{eligibility['required_prestige']}**"),
            inline=False,
        )
        embed.add_field(name="🏙️ Birodalom", value=f"**{len(owned)}/{cap}** property • Anti-monopoly városi limit: **{settings.city_cap}**", inline=False)
        if owned:
            view.add_item(PropertySelect(view, owned, row=0))
            selected = await self.service.get_property(guild_id, view.selected_property_id)
            if selected:
                preview = await self.service.claim_preview(guild_id, user_id, int(selected["property_id"]))
                rep = int(selected["reputation"])
                next_rep = cfg.upgrade_required_reputation(int(selected["level"])) if int(selected["level"]) < cfg.MAX_BUSINESS_LEVEL else cfg.MAX_REPUTATION
                workers = preview["workers"]
                embed.add_field(
                    name=f"{selected['emoji']} #{selected['property_id']} • {selected['name']}",
                    value=(f"**{selected['city']} • {selected['district']}** • {selected['street']}\n"
                           f"Level **{selected['level']}/{cfg.MAX_BUSINESS_LEVEL}** • Rep **{rep}/{cfg.MAX_REPUTATION}**\n"
                           f"{progress_bar(rep, max(1,next_rep), 12)}\n"
                           f"Dolgozók: **{len(workers)}** • Bevételi boost: **+{preview['worker_bonus_percent'] + preview['level_bonus_percent'] + preview['reputation_bonus_percent']}%**"),
                    inline=False,
                )
                embed.add_field(name="💵 Felgyűlt", value=f"Bruttó: **{money(preview['gross'])}**\nFenntartás+bér: **-{money(preview['upkeep'])}**\nAdó: **-{money(preview['tax'])}**\nNettó: **{money(preview['net'])}**", inline=True)
                embed.add_field(name="⚔️ Frakció", value=(f"+**{money(preview['faction_bonus'])}** neked és ugyanennyi matching dividend a Frakció Bankba" if preview["faction_bonus"] else "Nincs aktív Frakció bonusz."), inline=True)
        else:
            embed.add_field(name="Első property", value="Menj az **Ingatlanpiac** oldalra. Előtte permanent Business License szükséges.", inline=False)

        market = discord.ui.Button(label="Ingatlanpiac", emoji="🏙️", style=discord.ButtonStyle.primary, row=1)
        workers_btn = discord.ui.Button(label="Dolgozók", emoji="👷", style=discord.ButtonStyle.secondary, row=1)
        offers_btn = discord.ui.Button(label="Ajánlatok", emoji="🤝", style=discord.ButtonStyle.secondary, row=1)
        top_btn = discord.ui.Button(label="Ranglista", emoji="🏆", style=discord.ButtonStyle.secondary, row=1)
        async def market_cb(interaction): view.mode="market"; await view.rebuild(interaction)
        async def workers_cb(interaction): view.mode="workers"; await view.rebuild(interaction)
        async def offers_cb(interaction): view.mode="offers"; await view.rebuild(interaction)
        async def top_cb(interaction): view.mode="leaderboard"; await view.rebuild(interaction)
        market.callback=market_cb; workers_btn.callback=workers_cb; offers_btn.callback=offers_cb; top_btn.callback=top_cb
        view.add_item(market); view.add_item(workers_btn); view.add_item(offers_btn); view.add_item(top_btn)
        license_btn = discord.ui.Button(label="License ✓" if eligibility["has_license"] else "Business License", emoji="📜", style=discord.ButtonStyle.success, row=2, disabled=bool(eligibility["has_license"]))
        async def license_cb(interaction):
            try: price = await self.service.buy_license(guild_id, user_id)
            except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
            await interaction.response.send_message(f"📜 Permanent **Business License** megvásárolva: **{money(price)}**.", ephemeral=True)
        license_btn.callback=license_cb; view.add_item(license_btn)
        claim_btn = discord.ui.Button(label="Bevétel begyűjtése", emoji="💵", style=discord.ButtonStyle.success, row=2, disabled=not owned)
        async def claim_cb(interaction):
            try: result = await self.service.claim(guild_id, user_id, view.selected_property_id)
            except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
            await interaction.response.send_message(f"💵 Begyűjtve **{money(result['total_payout'])}** • +{result['reputation_gain']} Reputation.", ephemeral=True)
        claim_btn.callback=claim_cb; view.add_item(claim_btn)
        selected_home = await self.service.get_property(guild_id, view.selected_property_id) if view.selected_property_id else None
        upgrade_disabled = not selected_home or int(selected_home["level"]) >= cfg.MAX_BUSINESS_LEVEL
        upgrade_btn = discord.ui.Button(label="Fejlesztés", emoji="⬆️", style=discord.ButtonStyle.secondary, row=2, disabled=upgrade_disabled)
        if selected_home and not upgrade_disabled:
            upgrade_btn.label = f"Fejlesztés • {money(cfg.upgrade_cost(int(selected_home['base_price']), int(selected_home['level'])))}"
        async def upgrade_cb(interaction):
            try: result = await self.service.upgrade_property(guild_id, user_id, view.selected_property_id)
            except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
            await interaction.response.send_message(f"⬆️ **{result['name']}** most Level **{result['new_level']}** • {money(result['cost'])}.", ephemeral=True)
        upgrade_btn.callback=upgrade_cb; view.add_item(upgrade_btn)
        embed.set_footer(text="Yoru • Biznisz Empire • Interaction-first • A Business License Prestige reseten is megmarad")
        return embed, view

    async def send_panel(self, target, user) -> None:
        embed, view = await self.build_player_panel(target.guild, user)
        await target.send(embed=embed, view=view)

    @commands.command(name="biznisz", aliases=["business", "empire", "biz"])
    @commands.guild_only()
    async def business_prefix(self, ctx: commands.Context) -> None:
        if not await self._prefix_access(ctx): return
        embed, view = await self.build_player_panel(ctx.guild, ctx.author)
        await ctx.send(embed=embed, view=view)

    @business.command(name="panel", description="Megnyitja a Biznisz Empire interaktív panelt.")
    async def business_panel(self, interaction: discord.Interaction) -> None:
        if not await self._slash_access(interaction): return
        embed, view = await self.build_player_panel(interaction.guild, interaction.user)
        await interaction.response.send_message(embed=embed, view=view)

    @business.command(name="top", description="Megmutatja a Biznisz Empire ranglistát.")
    async def business_top(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        embed, view = await self.build_player_panel(interaction.guild, interaction.user, mode="leaderboard")
        await interaction.response.send_message(embed=embed, view=view)

    @commands.command(name="biztop", aliases=["businesstop", "empiretop"])
    @commands.guild_only()
    async def business_top_prefix(self, ctx: commands.Context) -> None:
        embed, view = await self.build_player_panel(ctx.guild, ctx.author, mode="leaderboard")
        await ctx.send(embed=embed, view=view)

    async def settings_embed(self, guild: discord.Guild) -> discord.Embed:
        settings = await self.service.get_settings(guild.id)
        embed = base_embed("🏢 Settings • Biznisz Empire", "A teljes late-game business rendszer szerverenként konfigurálható Discordon belül.", BRAND)
        embed.add_field(name="Állapot", value="✅ ON" if settings.enabled else "❌ OFF", inline=True)
        embed.add_field(name="Unlock", value=f"Activity **{settings.required_activity_level}** • Prestige **{settings.required_prestige}**\nLicense: **{money(settings.license_price)}**", inline=True)
        embed.add_field(name="Economy", value=f"Adó **{settings.tax_percent}%** • Income **{settings.income_multiplier_percent}%**\nOffline cap **{settings.offline_cap_hours}h** • Worker **{settings.worker_contract_days} nap**", inline=True)
        embed.add_field(name="Anti-monopoly", value=f"Alap **{settings.base_property_cap}** • +1 / **{settings.prestige_step} Prestige**\nMax **{settings.absolute_cap}** • Városonként **{settings.city_cap}**", inline=False)
        embed.add_field(name="Market / Frakció", value=f"Offer **{settings.property_offer_hours}h** • transfer tax **{settings.transfer_tax_percent}%** • Frakció bonus **{settings.faction_bonus_percent}%** • **{settings.faction_xp_per_claim} XP/claim**", inline=False)
        embed.add_field(name="Game-world", value=f"**{len(cfg.PROPERTY_TEMPLATES)}** egyedi, fikciós property • magyar város/negyed/utca címkékkel.", inline=False)
        embed.set_footer(text="Yoru • Settings • Biznisz Empire")
        return embed

    async def show_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        if interaction.guild is None: return
        if not interaction.response.is_done():
            await interaction.response.defer()
        settings = await self.service.get_settings(interaction.guild.id)
        embed = await self.settings_embed(interaction.guild)
        view = BusinessAdminView(self, owner_id, settings.enabled)
        await interaction.edit_original_response(embed=embed, view=view)
