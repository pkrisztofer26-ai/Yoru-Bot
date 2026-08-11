from __future__ import annotations

import asyncio
import io
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import discord
from discord.ext import commands

from app.cogs.settings import OwnedView, PagedGuildChannelSelect, PagedGuildRoleSelect
from app.database import Database
from app.services.server_settings import ServerSettingsService
from app.ui import BRAND, DANGER, SUCCESS, base_embed


TICKET_ENABLED_KEY = "tickets_enabled"
TICKET_CATEGORY_KEY = "tickets_category_id"
TICKET_LOG_CHANNEL_KEY = "tickets_log_channel_id"
TICKET_STAFF_ROLES_KEY = "tickets_staff_role_ids"
TICKET_MAX_OPEN_KEY = "tickets_max_open_per_user"
TICKET_DM_TRANSCRIPT_KEY = "tickets_dm_transcript"

DEFAULT_MAX_OPEN = 1
MAX_OPEN_LIMIT = 5
MAX_PANEL_TYPES = 5


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_channel_part(value: str, fallback: str = "user") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("_", "-")
    normalized = re.sub(r"[^a-z0-9-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return (normalized or fallback)[:55]


async def _ephemeral(interaction: discord.Interaction, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


class TicketStore:
    """Ticket-only persistence using the bot's existing SQLite database file."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.path = db.path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("PRAGMA foreign_keys=ON;")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_panels (
                    panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ticket_panels_guild ON ticket_panels(guild_id, active, panel_id)"
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_panel_types (
                    type_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    panel_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    emoji TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (panel_id) REFERENCES ticket_panels(panel_id) ON DELETE CASCADE
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ticket_panel_types_panel ON ticket_panel_types(panel_id, position, type_id)"
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    panel_id INTEGER NOT NULL,
                    type_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL UNIQUE,
                    control_message_id INTEGER,
                    opener_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    claimed_by INTEGER,
                    created_at TEXT NOT NULL,
                    closed_at TEXT,
                    closed_by INTEGER,
                    close_reason TEXT,
                    FOREIGN KEY (panel_id) REFERENCES ticket_panels(panel_id),
                    FOREIGN KEY (type_id) REFERENCES ticket_panel_types(type_id)
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tickets_open_user ON tickets(guild_id, opener_id, status)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tickets_guild_status ON tickets(guild_id, status, ticket_id)"
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_members (
                    ticket_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    added_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (ticket_id, user_id),
                    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE
                )
                """
            )
            await conn.commit()

    @staticmethod
    def _dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    async def _panel_types(self, conn: aiosqlite.Connection, panel_id: int) -> list[dict[str, Any]]:
        cursor = await conn.execute(
            "SELECT * FROM ticket_panel_types WHERE panel_id=? ORDER BY position ASC, type_id ASC",
            (panel_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def create_panel(
        self,
        guild_id: int,
        channel_id: int,
        title: str,
        description: str,
        created_by: int,
        types: list[dict[str, str]],
    ) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys=ON;")
            cursor = await conn.execute(
                """
                INSERT INTO ticket_panels
                    (guild_id, channel_id, message_id, title, description, active, created_by, created_at)
                VALUES (?, ?, NULL, ?, ?, 1, ?, ?)
                """,
                (guild_id, channel_id, title[:256], description[:4000], created_by, _utc_now()),
            )
            panel_id = int(cursor.lastrowid)
            for position, item in enumerate(types[:MAX_PANEL_TYPES]):
                await conn.execute(
                    """
                    INSERT INTO ticket_panel_types(panel_id, label, emoji, description, position)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        panel_id,
                        item["label"][:80],
                        (item.get("emoji") or "🎫")[:100],
                        (item.get("description") or "")[:1000],
                        position,
                    ),
                )
            await conn.commit()
            cursor = await conn.execute("SELECT * FROM ticket_panels WHERE panel_id=?", (panel_id,))
            panel = dict(await cursor.fetchone())
            panel["items"] = await self._panel_types(conn, panel_id)
            return panel

    async def set_panel_message(self, panel_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE ticket_panels SET message_id=? WHERE panel_id=?", (message_id, panel_id))
            await conn.commit()

    async def get_panel(self, panel_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM ticket_panels WHERE panel_id=?", (panel_id,))
            row = await cursor.fetchone()
            if row is None:
                return None
            panel = dict(row)
            panel["items"] = await self._panel_types(conn, panel_id)
            return panel

    async def list_panels(self, guild_id: int, *, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM ticket_panels WHERE guild_id=?"
        params: list[Any] = [guild_id]
        if active_only:
            sql += " AND active=1"
        sql += " ORDER BY panel_id DESC"
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(sql, params)
            rows = [dict(row) for row in await cursor.fetchall()]
            for row in rows:
                row["items"] = await self._panel_types(conn, int(row["panel_id"]))
            return rows

    async def list_active_panels_all(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM ticket_panels WHERE active=1 AND message_id IS NOT NULL ORDER BY panel_id ASC"
            )
            rows = [dict(row) for row in await cursor.fetchall()]
            for row in rows:
                row["items"] = await self._panel_types(conn, int(row["panel_id"]))
            return rows

    async def deactivate_panel(self, guild_id: int, panel_id: int) -> dict[str, Any] | None:
        panel = await self.get_panel(panel_id)
        if panel is None or int(panel["guild_id"]) != guild_id:
            return None
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE ticket_panels SET active=0 WHERE panel_id=?", (panel_id,))
            await conn.commit()
        panel["active"] = 0
        return panel

    async def create_ticket(
        self,
        guild_id: int,
        panel_id: int,
        type_id: int,
        channel_id: int,
        opener_id: int,
    ) -> int:
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO tickets
                    (guild_id, panel_id, type_id, channel_id, opener_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?)
                """,
                (guild_id, panel_id, type_id, channel_id, opener_id, _utc_now()),
            )
            await conn.commit()
            return int(cursor.lastrowid)

    async def set_control_message(self, ticket_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE tickets SET control_message_id=? WHERE ticket_id=?", (message_id, ticket_id))
            await conn.commit()

    async def get_ticket_by_channel(self, channel_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT t.*, pt.label AS type_label, pt.emoji AS type_emoji,
                       pt.description AS type_description, p.title AS panel_title
                FROM tickets t
                JOIN ticket_panel_types pt ON pt.type_id=t.type_id
                JOIN ticket_panels p ON p.panel_id=t.panel_id
                WHERE t.channel_id=?
                """,
                (channel_id,),
            )
            return self._dict(await cursor.fetchone())

    async def count_open_for_user(self, guild_id: int, opener_id: int) -> int:
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM tickets WHERE guild_id=? AND opener_id=? AND status='open'",
                (guild_id, opener_id),
            )
            row = await cursor.fetchone()
            return int(row[0] if row else 0)

    async def count_open_guild(self, guild_id: int) -> int:
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status='open'",
                (guild_id,),
            )
            row = await cursor.fetchone()
            return int(row[0] if row else 0)

    async def set_claimed(self, ticket_id: int, user_id: int | None) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE tickets SET claimed_by=? WHERE ticket_id=?", (user_id, ticket_id))
            await conn.commit()

    async def close_ticket(self, ticket_id: int, closed_by: int, reason: str) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                """
                UPDATE tickets
                SET status='closed', closed_at=?, closed_by=?, close_reason=?
                WHERE ticket_id=?
                """,
                (_utc_now(), closed_by, reason[:1000], ticket_id),
            )
            await conn.commit()

    async def reopen_ticket(self, ticket_id: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                """
                UPDATE tickets
                SET status='open', closed_at=NULL, closed_by=NULL, close_reason=NULL
                WHERE ticket_id=?
                """,
                (ticket_id,),
            )
            await conn.commit()

    async def add_member(self, ticket_id: int, user_id: int, added_by: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                """
                INSERT INTO ticket_members(ticket_id, user_id, added_by, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticket_id, user_id) DO UPDATE SET added_by=excluded.added_by
                """,
                (ticket_id, user_id, added_by, _utc_now()),
            )
            await conn.commit()

    async def remove_member(self, ticket_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                "DELETE FROM ticket_members WHERE ticket_id=? AND user_id=?",
                (ticket_id, user_id),
            )
            await conn.commit()
            return bool(cursor.rowcount)

    async def list_members(self, ticket_id: int) -> list[int]:
        async with aiosqlite.connect(self.path) as conn:
            cursor = await conn.execute(
                "SELECT user_id FROM ticket_members WHERE ticket_id=? ORDER BY created_at ASC",
                (ticket_id,),
            )
            return [int(row[0]) for row in await cursor.fetchall()]


class TicketPanelButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog", panel_id: int, item: dict[str, Any]) -> None:
        super().__init__(
            label=str(item["label"])[:80],
            emoji=str(item.get("emoji") or "🎫"),
            style=discord.ButtonStyle.secondary,
            custom_id=f"yoru:ticket:create:{panel_id}:{int(item['type_id'])}",
            row=min(int(item.get("position", 0)) // 5, 4),
        )
        self.cog = cog
        self.panel_id = panel_id
        self.type_id = int(item["type_id"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.create_ticket_from_panel(interaction, self.panel_id, self.type_id)


class TicketPanelView(discord.ui.View):
    def __init__(self, cog: "TicketCog", panel: dict[str, Any]) -> None:
        super().__init__(timeout=None)
        for item in panel.get("items", [])[:MAX_PANEL_TYPES]:
            self.add_item(TicketPanelButton(cog, int(panel["panel_id"]), item))


class OpenTicketControlsView(discord.ui.View):
    def __init__(self, cog: "TicketCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Claim", emoji="🙋", style=discord.ButtonStyle.primary, custom_id="yoru:ticket:claim", row=0)
    async def claim(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.claim_ticket(interaction)

    @discord.ui.button(label="Add User", emoji="➕", style=discord.ButtonStyle.secondary, custom_id="yoru:ticket:add-user", row=0)
    async def add_user(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.open_user_picker(interaction, "add")

    @discord.ui.button(label="Remove User", emoji="➖", style=discord.ButtonStyle.secondary, custom_id="yoru:ticket:remove-user", row=0)
    async def remove_user(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.open_user_picker(interaction, "remove")

    @discord.ui.button(label="Rename", emoji="📝", style=discord.ButtonStyle.secondary, custom_id="yoru:ticket:rename", row=1)
    async def rename(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.open_rename_modal(interaction)

    @discord.ui.button(label="Close", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="yoru:ticket:close", row=1)
    async def close(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.open_close_confirmation(interaction)


class ClosedTicketControlsView(discord.ui.View):
    def __init__(self, cog: "TicketCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Reopen", emoji="🔓", style=discord.ButtonStyle.success, custom_id="yoru:ticket:reopen")
    async def reopen(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.reopen_ticket(interaction)

    @discord.ui.button(label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="yoru:ticket:delete")
    async def delete(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.open_delete_confirmation(interaction)


class TicketUserSelect(discord.ui.UserSelect):
    def __init__(self, view: "TicketUserPickerView") -> None:
        super().__init__(placeholder="Válassz egy felhasználót…", min_values=1, max_values=1)
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        await self.parent_view.apply(interaction, selected.id)


class TicketUserPickerView(discord.ui.View):
    def __init__(self, cog: "TicketCog", owner_id: int, action: str) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.action = action
        self.add_item(TicketUserSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await _ephemeral(interaction, "❌ Ezt a választót nem te nyitottad meg.")
            return False
        return True

    async def apply(self, interaction: discord.Interaction, user_id: int) -> None:
        await self.cog.modify_ticket_user(interaction, user_id, self.action)


class RenameTicketModal(discord.ui.Modal, title="Ticket átnevezése"):
    new_name = discord.ui.TextInput(
        label="Új csatornanév",
        placeholder="pl. payment-proof",
        min_length=1,
        max_length=80,
    )

    def __init__(self, cog: "TicketCog") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.rename_ticket(interaction, str(self.new_name.value))


class ConfirmCloseView(discord.ui.View):
    def __init__(self, cog: "TicketCog", owner_id: int) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await _ephemeral(interaction, "❌ Ezt a megerősítést nem te nyitottad meg.")
            return False
        return True

    @discord.ui.button(label="Igen, bezárom", emoji="🔒", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.close_ticket(interaction)

    @discord.ui.button(label="Mégse", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Bezárás megszakítva.", view=None)


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, cog: "TicketCog", owner_id: int) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await _ephemeral(interaction, "❌ Ezt a megerősítést nem te nyitottad meg.")
            return False
        return True

    @discord.ui.button(label="Végleges törlés", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.delete_ticket(interaction)

    @discord.ui.button(label="Mégse", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Törlés megszakítva.", view=None)


class TicketCategorySelect(PagedGuildChannelSelect):
    def __init__(self, view: "TicketSettingsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="category_page",
            selection_key="ticket_category",
            placeholder="Ticket kategória…",
            channel_types=(discord.ChannelType.category,),
            row=2,
            max_values=1,
        )


class TicketLogChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "TicketSettingsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="log_page",
            selection_key="ticket_log",
            placeholder="Ticket log csatorna…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=3,
            max_values=1,
        )


class TicketStaffRoleSelect(PagedGuildRoleSelect):
    def __init__(self, view: "TicketSettingsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="staff_page",
            selection_key="ticket_staff",
            placeholder="Staff rang hozzáadás/törlés…",
            row=4,
            max_values=5,
        )


class TicketLimitModal(discord.ui.Modal, title="Ticket limit"):
    limit = discord.ui.TextInput(label="Max nyitott ticket / user", min_length=1, max_length=1)

    def __init__(self, view: "TicketSettingsView") -> None:
        super().__init__()
        self.parent_view = view
        self.limit.default = str(view.max_open)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = int(str(self.limit.value).strip())
            if value < 1 or value > MAX_OPEN_LIMIT:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                f"❌ A limit 1 és {MAX_OPEN_LIMIT} között legyen.", ephemeral=True
            )
        await self.parent_view.cog.config.set_int(interaction.guild_id, TICKET_MAX_OPEN_KEY, value)
        self.parent_view.max_open = value
        await self.parent_view.refresh(interaction)


class DeactivatePanelModal(discord.ui.Modal, title="Ticket panel kikapcsolása"):
    panel_id = discord.ui.TextInput(label="Panel ID", placeholder="pl. 3", min_length=1, max_length=10)

    def __init__(self, view: "TicketSettingsView") -> None:
        super().__init__()
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            panel_id = int(str(self.panel_id.value).strip())
        except ValueError:
            return await interaction.response.send_message("❌ Érvénytelen panel ID.", ephemeral=True)
        panel = await self.parent_view.cog.store.deactivate_panel(interaction.guild_id, panel_id)
        if panel is None:
            return await interaction.response.send_message("❌ Nincs ilyen ticket panel ezen a szerveren.", ephemeral=True)
        channel = interaction.guild.get_channel(int(panel["channel_id"])) if interaction.guild else None
        if channel is not None and panel.get("message_id"):
            try:
                message = await channel.fetch_message(int(panel["message_id"]))
                embed = message.embeds[0] if message.embeds else base_embed("🎫 Ticket panel")
                embed.set_footer(text="Yoru • Tickets • Ez a panel ki lett kapcsolva")
                await message.edit(embed=embed, view=None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self.parent_view.refresh(interaction)


class TicketSettingsView(OwnedView):
    def __init__(
        self,
        cog: "TicketCog",
        owner_id: int,
        guild: discord.Guild,
        *,
        enabled: bool,
        dm_transcript: bool,
        max_open: int,
        category_page: int = 0,
        log_page: int = 0,
        staff_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.enabled = enabled
        self.dm_transcript = dm_transcript
        self.max_open = max_open
        self.category_page = category_page
        self.log_page = log_page
        self.staff_page = staff_page
        self.toggle.label = "Tickets: ON" if enabled else "Tickets: OFF"
        self.toggle.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
        self.dm_toggle.label = "DM transcript: ON" if dm_transcript else "DM transcript: OFF"
        self.dm_toggle.style = discord.ButtonStyle.success if dm_transcript else discord.ButtonStyle.secondary
        self.add_item(TicketCategorySelect(self))
        self.add_item(TicketLogChannelSelect(self))
        self.add_item(TicketStaffRoleSelect(self))

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_settings(interaction, self.owner_id, self)

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        channel = channels[0]
        if selection_key == "ticket_category":
            await self.cog.set_ticket_category(interaction.guild_id, int(channel.id))
        elif selection_key == "ticket_log":
            await self.cog.config.set_int(interaction.guild_id, TICKET_LOG_CHANNEL_KEY, int(channel.id))
        await self.refresh(interaction)

    async def handle_role_selection(
        self,
        interaction: discord.Interaction,
        _selection_key: str,
        roles: list[discord.Role],
    ) -> None:
        current = await self.cog.get_staff_role_ids(interaction.guild_id)
        for role in roles:
            if role.id in current:
                current.remove(role.id)
            else:
                current.append(role.id)
        await self.cog.config.set_list(interaction.guild_id, TICKET_STAFF_ROLES_KEY, current[:25])
        await self.refresh(interaction)

    @discord.ui.button(label="Tickets", emoji="⚡", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.enabled = not self.enabled
        await self.cog.config.set_bool(interaction.guild_id, TICKET_ENABLED_KEY, self.enabled)
        await self.refresh(interaction)

    @discord.ui.button(label="DM transcript", emoji="✉️", style=discord.ButtonStyle.secondary, row=0)
    async def dm_toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.dm_transcript = not self.dm_transcript
        await self.cog.config.set_bool(interaction.guild_id, TICKET_DM_TRANSCRIPT_KEY, self.dm_transcript)
        await self.refresh(interaction)

    @discord.ui.button(label="Limit", emoji="📏", style=discord.ButtonStyle.secondary, row=0)
    async def limit(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketLimitModal(self))

    @discord.ui.button(label="Új panel", emoji="➕", style=discord.ButtonStyle.primary, row=1)
    async def new_panel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_panel_builder(interaction, self.owner_id)

    @discord.ui.button(label="Panel kikapcsolása", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def disable_panel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(DeactivatePanelModal(self))

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.back_to_settings(interaction, self.owner_id)


class PanelTargetChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "TicketPanelBuilderView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="channel_page",
            selection_key="panel_channel",
            placeholder="Panel célcsatornája…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=2,
            max_values=1,
        )


class PanelEmbedModal(discord.ui.Modal, title="Ticket panel szövege"):
    title_input = discord.ui.TextInput(label="Embed cím", min_length=1, max_length=256)
    description_input = discord.ui.TextInput(
        label="Embed leírás",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=4000,
    )

    def __init__(self, view: "TicketPanelBuilderView") -> None:
        super().__init__()
        self.parent_view = view
        self.title_input.default = view.title
        self.description_input.default = view.description

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.parent_view.title = str(self.title_input.value).strip()[:256]
        self.parent_view.description = str(self.description_input.value).strip()[:4000]
        await self.parent_view.refresh(interaction)


class TicketTypesModal(discord.ui.Modal):
    def __init__(self, view: "TicketPanelBuilderView") -> None:
        super().__init__(title="Ticket típusok")
        self.parent_view = view
        self.inputs: list[discord.ui.TextInput] = []
        for index in range(MAX_PANEL_TYPES):
            default = ""
            if index < len(view.types):
                item = view.types[index]
                default = f"{item['emoji']} | {item['label']} | {item['description']}".strip()
            field = discord.ui.TextInput(
                label=f"{index + 1}. típus • emoji | név | leírás",
                placeholder="🛠️ | Support | Segítségkérés",
                required=index == 0,
                max_length=180,
                default=default,
            )
            self.inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parsed: list[dict[str, str]] = []
        for field in self.inputs:
            raw = str(field.value).strip()
            if not raw:
                continue
            parts = [part.strip() for part in raw.split("|", 2)]
            if len(parts) == 1:
                emoji, label, description = "🎫", parts[0], ""
            elif len(parts) == 2:
                emoji, label = parts
                description = ""
            else:
                emoji, label, description = parts
            if not label:
                continue
            parsed.append(
                {
                    "emoji": (emoji or "🎫")[:100],
                    "label": label[:80],
                    "description": description[:1000],
                }
            )
        if not parsed:
            return await interaction.response.send_message("❌ Legalább egy ticket típus kell.", ephemeral=True)
        self.parent_view.types = parsed[:MAX_PANEL_TYPES]
        await self.parent_view.refresh(interaction)


class TicketPanelBuilderView(OwnedView):
    def __init__(
        self,
        cog: "TicketCog",
        owner_id: int,
        guild: discord.Guild,
        *,
        target_channel_id: int | None = None,
        title: str = "🎫 Support Tickets",
        description: str = "Válaszd ki lent, milyen ticketet szeretnél nyitni.",
        types: list[dict[str, str]] | None = None,
        channel_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.target_channel_id = target_channel_id
        self.title = title
        self.description = description
        self.types = types or [
            {"emoji": "🛠️", "label": "Support", "description": "Általános segítségkérés"},
            {"emoji": "🚨", "label": "Report", "description": "Felhasználó vagy probléma jelentése"},
            {"emoji": "💰", "label": "Purchase", "description": "Vásárlással kapcsolatos ügy"},
            {"emoji": "❓", "label": "Other", "description": "Minden más"},
        ]
        self.channel_page = channel_page
        self.add_item(PanelTargetChannelSelect(self))

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_panel_builder(interaction, self.owner_id, self)

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        _selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        self.target_channel_id = int(channels[0].id)
        await self.refresh(interaction)

    async def handle_role_selection(self, *_args: Any) -> None:
        return None

    @discord.ui.button(label="Embed", emoji="✏️", style=discord.ButtonStyle.secondary, row=0)
    async def edit_embed(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(PanelEmbedModal(self))

    @discord.ui.button(label="Ticket típusok", emoji="🧩", style=discord.ButtonStyle.secondary, row=0)
    async def edit_types(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketTypesModal(self))

    @discord.ui.button(label="Panel kiküldése", emoji="🚀", style=discord.ButtonStyle.success, row=1)
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.publish_panel(interaction, self)

    @discord.ui.button(label="Tickets", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_settings(interaction, self.owner_id)


class TicketCog(commands.Cog):
    """Yoru v3.9 ticket panels + private ticket channels."""

    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db
        self.config = ServerSettingsService(db)
        self.store = TicketStore(db)
        self._create_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._ticket_action_locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self) -> None:
        await self.store.initialize()
        self.bot.add_view(OpenTicketControlsView(self))
        self.bot.add_view(ClosedTicketControlsView(self))
        for panel in await self.store.list_active_panels_all():
            try:
                self.bot.add_view(TicketPanelView(self, panel), message_id=int(panel["message_id"]))
            except (TypeError, ValueError):
                continue

    async def is_enabled(self, guild_id: int) -> bool:
        return await self.config.get_bool(guild_id, TICKET_ENABLED_KEY, False)

    async def get_max_open(self, guild_id: int) -> int:
        raw = await self.config.get_int(guild_id, TICKET_MAX_OPEN_KEY)
        return max(1, min(MAX_OPEN_LIMIT, raw or DEFAULT_MAX_OPEN))

    async def get_staff_role_ids(self, guild_id: int) -> list[int]:
        values = await self.config.get_list(guild_id, TICKET_STAFF_ROLES_KEY, [])
        return list(dict.fromkeys(int(v) for v in values if str(v).isdigit()))[:25]

    async def set_ticket_category(self, guild_id: int, category_id: int) -> None:
        old_id = await self.config.get_int(guild_id, TICKET_CATEGORY_KEY)
        if old_id and old_id != category_id:
            await self.config.remove_exemption(guild_id, "invite", "category", old_id)
            await self.config.remove_exemption(guild_id, "links", "category", old_id)
        await self.config.set_int(guild_id, TICKET_CATEGORY_KEY, category_id)
        # Ticket channels intentionally allow invite links / normal links.
        await self.config.add_exemption(guild_id, "invite", "category", category_id)
        await self.config.add_exemption(guild_id, "links", "category", category_id)

    async def is_staff(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild or member.guild_permissions.manage_channels:
            return True
        role_ids = set(await self.get_staff_role_ids(member.guild.id))
        return any(role.id in role_ids for role in member.roles)

    async def home_status(self, guild: discord.Guild) -> str:
        enabled = await self.is_enabled(guild.id)
        panels = await self.store.list_panels(guild.id, active_only=True)
        open_count = await self.store.count_open_guild(guild.id)
        prefix = "🟢" if enabled else "⚪"
        return f"{prefix} {len(panels)} panel • {open_count} nyitott"

    async def settings_embed(self, guild: discord.Guild) -> discord.Embed:
        enabled = await self.is_enabled(guild.id)
        category_id = await self.config.get_int(guild.id, TICKET_CATEGORY_KEY)
        log_id = await self.config.get_int(guild.id, TICKET_LOG_CHANNEL_KEY)
        category = guild.get_channel(category_id) if category_id else None
        log_channel = guild.get_channel(log_id) if log_id else None
        staff_ids = await self.get_staff_role_ids(guild.id)
        staff_roles = [guild.get_role(role_id) for role_id in staff_ids]
        staff_text = " • ".join(role.mention for role in staff_roles if role is not None) or "Nincs beállítva"
        max_open = await self.get_max_open(guild.id)
        dm_transcript = await self.config.get_bool(guild.id, TICKET_DM_TRANSCRIPT_KEY, False)
        panels = await self.store.list_panels(guild.id, active_only=True)
        open_count = await self.store.count_open_guild(guild.id)

        embed = base_embed(
            "🎫 Yoru • Tickets",
            "Reaction-role jellegű ticket panelek privát ticket szobákkal. A ticket kategória automatikusan invite/link AutoMod kivételt kap.",
        )
        embed.add_field(name="Állapot", value="🟢 Bekapcsolva" if enabled else "🔴 Kikapcsolva", inline=True)
        embed.add_field(name="Ticket kategória", value=category.mention if category else "Nincs beállítva", inline=True)
        embed.add_field(name="Log csatorna", value=log_channel.mention if hasattr(log_channel, "mention") else "Nincs beállítva", inline=True)
        embed.add_field(name="Staff rangok", value=staff_text[:1024], inline=False)
        embed.add_field(name="Max nyitott / user", value=str(max_open), inline=True)
        embed.add_field(name="DM transcript", value="✅ Igen" if dm_transcript else "❌ Nem", inline=True)
        embed.add_field(name="Nyitott ticketek", value=str(open_count), inline=True)
        if panels:
            lines = []
            for panel in panels[:10]:
                channel = guild.get_channel(int(panel["channel_id"]))
                where = channel.mention if hasattr(channel, "mention") else f"#{panel['channel_id']}"
                lines.append(f"`#{panel['panel_id']}` • {panel['title']} • {where} • {len(panel['items'])} típus")
            embed.add_field(name="Aktív panelek", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Aktív panelek", value="Még nincs ticket panel.", inline=False)
        embed.set_footer(text="Yoru • Tickets • Staff rang választásnál ugyanarra kattintva törlöd")
        return embed

    async def show_settings(
        self,
        interaction: discord.Interaction,
        owner_id: int,
        existing: TicketSettingsView | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        view = TicketSettingsView(
            self,
            owner_id,
            interaction.guild,
            enabled=await self.is_enabled(interaction.guild_id),
            dm_transcript=await self.config.get_bool(interaction.guild_id, TICKET_DM_TRANSCRIPT_KEY, False),
            max_open=await self.get_max_open(interaction.guild_id),
            category_page=existing.category_page if existing else 0,
            log_page=existing.log_page if existing else 0,
            staff_page=existing.staff_page if existing else 0,
        )
        await interaction.response.edit_message(embed=await self.settings_embed(interaction.guild), view=view)

    async def back_to_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        settings_cog = self.bot.get_cog("SettingsCog")
        if settings_cog is None or not hasattr(settings_cog, "show_home"):
            return await _ephemeral(interaction, "❌ A Settings modul nem elérhető.")
        await settings_cog.show_home(interaction, owner_id)

    async def builder_embed(self, guild: discord.Guild, view: TicketPanelBuilderView) -> discord.Embed:
        channel = guild.get_channel(view.target_channel_id) if view.target_channel_id else None
        embed = base_embed(
            "🎫 Ticket panel builder",
            "Állítsd be a panel helyét, szövegét és a gombokat, majd küldd ki.",
        )
        embed.add_field(name="Célcsatorna", value=channel.mention if hasattr(channel, "mention") else "Nincs kiválasztva", inline=False)
        embed.add_field(name="Cím", value=view.title, inline=False)
        embed.add_field(name="Leírás", value=view.description[:1024], inline=False)
        type_lines = [f"{item['emoji']} **{item['label']}** — {item['description'] or '—'}" for item in view.types]
        embed.add_field(name="Ticket típusok", value="\n".join(type_lines)[:1024], inline=False)
        embed.set_footer(text="Yoru • Tickets • Maximum 5 gomb / panel")
        return embed

    async def show_panel_builder(
        self,
        interaction: discord.Interaction,
        owner_id: int,
        existing: TicketPanelBuilderView | None = None,
    ) -> None:
        if interaction.guild is None:
            return
        if existing is None:
            view = TicketPanelBuilderView(self, owner_id, interaction.guild)
        else:
            view = TicketPanelBuilderView(
                self,
                owner_id,
                interaction.guild,
                target_channel_id=existing.target_channel_id,
                title=existing.title,
                description=existing.description,
                types=[dict(item) for item in existing.types],
                channel_page=existing.channel_page,
            )
        await interaction.response.edit_message(embed=await self.builder_embed(interaction.guild, view), view=view)

    def public_panel_embed(self, panel: dict[str, Any]) -> discord.Embed:
        embed = base_embed(str(panel["title"]), str(panel["description"]), BRAND)
        for item in panel.get("items", []):
            embed.add_field(
                name=f"{item.get('emoji') or '🎫'} {item['label']}",
                value=item.get("description") or "Ticket nyitása",
                inline=False,
            )
        embed.set_footer(text=f"Yoru • Tickets • Panel #{panel['panel_id']}")
        return embed

    async def publish_panel(self, interaction: discord.Interaction, view: TicketPanelBuilderView) -> None:
        if interaction.guild is None:
            return
        if view.target_channel_id is None:
            return await interaction.response.send_message("❌ Előbb válaszd ki a panel célcsatornáját.", ephemeral=True)
        category_id = await self.config.get_int(interaction.guild_id, TICKET_CATEGORY_KEY)
        category = interaction.guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("❌ Előbb állíts be egy Ticket kategóriát.", ephemeral=True)
        channel = interaction.guild.get_channel(view.target_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("❌ A panel célja hagyományos szöveges csatorna legyen.", ephemeral=True)
        if not view.types:
            return await interaction.response.send_message("❌ Legalább egy ticket típus kell.", ephemeral=True)

        panel = await self.store.create_panel(
            interaction.guild_id,
            channel.id,
            view.title,
            view.description,
            interaction.user.id,
            view.types,
        )
        panel_view = TicketPanelView(self, panel)
        try:
            message = await channel.send(
                embed=self.public_panel_embed(panel),
                view=panel_view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            await self.store.deactivate_panel(interaction.guild_id, int(panel["panel_id"]))
            return await interaction.response.send_message("❌ Yoru nem tud üzenetet küldeni ebbe a csatornába.", ephemeral=True)

        await self.store.set_panel_message(int(panel["panel_id"]), message.id)
        await self.config.set_bool(interaction.guild_id, TICKET_ENABLED_KEY, True)
        self.bot.add_view(panel_view, message_id=message.id)
        await self.show_settings(interaction, view.owner_id)
        await interaction.followup.send(f"✅ Ticket panel kiküldve: {message.jump_url}", ephemeral=True)

    async def create_ticket_from_panel(self, interaction: discord.Interaction, panel_id: int, type_id: int) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await _ephemeral(interaction, "❌ Ticket csak szerveren nyitható.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        lock_key = (interaction.guild.id, interaction.user.id)
        lock = self._create_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            if not await self.is_enabled(interaction.guild.id):
                return await interaction.followup.send("❌ A ticket rendszer jelenleg ki van kapcsolva.", ephemeral=True)
            panel = await self.store.get_panel(panel_id)
            if panel is None or not panel["active"] or int(panel["guild_id"]) != interaction.guild.id:
                return await interaction.followup.send("❌ Ez a ticket panel már nem aktív.", ephemeral=True)
            item = next((x for x in panel["items"] if int(x["type_id"]) == type_id), None)
            if item is None:
                return await interaction.followup.send("❌ Ez a ticket típus már nem elérhető.", ephemeral=True)
            max_open = await self.get_max_open(interaction.guild.id)
            open_count = await self.store.count_open_for_user(interaction.guild.id, interaction.user.id)
            if open_count >= max_open:
                return await interaction.followup.send(
                    f"❌ Már elérted a nyitott ticket limitedet (**{open_count}/{max_open}**).",
                    ephemeral=True,
                )
            category_id = await self.config.get_int(interaction.guild.id, TICKET_CATEGORY_KEY)
            category = interaction.guild.get_channel(category_id) if category_id else None
            if not isinstance(category, discord.CategoryChannel):
                return await interaction.followup.send("❌ Nincs érvényes Ticket kategória beállítva.", ephemeral=True)

            me = interaction.guild.me
            if me is None and self.bot.user is not None:
                me = interaction.guild.get_member(self.bot.user.id)
            if me is None or not me.guild_permissions.manage_channels:
                return await interaction.followup.send("❌ Yoru-nak **Manage Channels** jogosultság kell.", ephemeral=True)

            overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                    add_reactions=True,
                ),
                me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_channels=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True,
                ),
            }
            for role_id in await self.get_staff_role_ids(interaction.guild.id):
                role = interaction.guild.get_role(role_id)
                if role is not None:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        embed_links=True,
                        add_reactions=True,
                        manage_messages=True,
                    )

            type_part = _safe_channel_part(str(item["label"]), "ticket")[:20]
            user_part = _safe_channel_part(interaction.user.display_name, f"user-{interaction.user.id}")
            channel_name = f"{type_part}-{user_part}"[:95]
            try:
                channel = await interaction.guild.create_text_channel(
                    channel_name,
                    category=category,
                    overwrites=overwrites,
                    reason=f"Yoru ticket • {interaction.user} • {item['label']}",
                )
            except (discord.Forbidden, discord.HTTPException):
                return await interaction.followup.send("❌ Nem sikerült létrehozni a ticket csatornát.", ephemeral=True)

            try:
                ticket_id = await self.store.create_ticket(
                    interaction.guild.id,
                    panel_id,
                    type_id,
                    channel.id,
                    interaction.user.id,
                )
                await channel.edit(topic=f"Yoru Ticket #{ticket_id} • opener={interaction.user.id} • type={type_id}")
                ticket = await self.store.get_ticket_by_channel(channel.id)
                control = await channel.send(
                    content=interaction.user.mention,
                    embed=self.ticket_embed(interaction.guild, ticket),
                    view=OpenTicketControlsView(self),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                await self.store.set_control_message(ticket_id, control.id)
            except Exception:
                try:
                    await channel.delete(reason="Yoru ticket létrehozás rollback")
                except discord.HTTPException:
                    pass
                raise

            await interaction.followup.send(f"✅ Ticket létrehozva: {channel.mention}", ephemeral=True)

    def ticket_embed(self, guild: discord.Guild, ticket: dict[str, Any] | None) -> discord.Embed:
        if ticket is None:
            return base_embed("🎫 Ticket", "A ticket adatai nem tölthetők be.", DANGER)
        opener = guild.get_member(int(ticket["opener_id"]))
        claimed = guild.get_member(int(ticket["claimed_by"])) if ticket.get("claimed_by") else None
        status = str(ticket["status"])
        color = SUCCESS if status == "open" else DANGER
        embed = base_embed(
            f"🎫 Ticket #{ticket['ticket_id']} • {ticket.get('type_emoji') or '🎫'} {ticket.get('type_label') or 'Ticket'}",
            ticket.get("type_description") or "Írd le részletesen, miben van szükséged segítségre. Linket, invite-ot, képet és fájlt is küldhetsz ide.",
            color,
        )
        embed.add_field(name="Megnyitotta", value=opener.mention if opener else f"<@{ticket['opener_id']}>", inline=True)
        embed.add_field(name="Claim", value=claimed.mention if claimed else "Nincs", inline=True)
        embed.add_field(name="Állapot", value="🟢 Nyitott" if status == "open" else "🔒 Lezárt", inline=True)
        if status == "closed" and ticket.get("close_reason"):
            embed.add_field(name="Lezárás", value=str(ticket["close_reason"])[:1024], inline=False)
        embed.set_footer(text="Yoru • Tickets")
        return embed

    async def _current_ticket(self, interaction: discord.Interaction) -> tuple[discord.TextChannel, dict[str, Any]] | None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await _ephemeral(interaction, "❌ Ez nem ticket csatorna.")
            return None
        ticket = await self.store.get_ticket_by_channel(interaction.channel.id)
        if ticket is None:
            await _ephemeral(interaction, "❌ Ehhez a csatornához nincs Yoru ticket rekord.")
            return None
        return interaction.channel, ticket

    async def claim_ticket(self, interaction: discord.Interaction) -> None:
        current = await self._current_ticket(interaction)
        if current is None or not isinstance(interaction.user, discord.Member):
            return
        _channel, ticket = current
        if ticket["status"] != "open":
            return await _ephemeral(interaction, "❌ Ez a ticket már le van zárva.")
        if not await self.is_staff(interaction.user):
            return await _ephemeral(interaction, "❌ Ezt csak ticket staff használhatja.")
        new_claim = None if ticket.get("claimed_by") == interaction.user.id else interaction.user.id
        await self.store.set_claimed(int(ticket["ticket_id"]), new_claim)
        updated = await self.store.get_ticket_by_channel(int(ticket["channel_id"]))
        await interaction.response.edit_message(embed=self.ticket_embed(interaction.guild, updated), view=OpenTicketControlsView(self))

    async def open_user_picker(self, interaction: discord.Interaction, action: str) -> None:
        current = await self._current_ticket(interaction)
        if current is None or not isinstance(interaction.user, discord.Member):
            return
        _channel, ticket = current
        if ticket["status"] != "open":
            return await _ephemeral(interaction, "❌ Ez a ticket le van zárva.")
        if not await self.is_staff(interaction.user):
            return await _ephemeral(interaction, "❌ Ezt csak ticket staff használhatja.")
        label = "hozzáadni" if action == "add" else "eltávolítani"
        await interaction.response.send_message(
            f"Válaszd ki, kit szeretnél {label}:",
            view=TicketUserPickerView(self, interaction.user.id, action),
            ephemeral=True,
        )

    async def modify_ticket_user(self, interaction: discord.Interaction, user_id: int, action: str) -> None:
        current = await self._current_ticket(interaction)
        if current is None or not isinstance(interaction.user, discord.Member):
            return
        channel, ticket = current
        if not await self.is_staff(interaction.user):
            return await _ephemeral(interaction, "❌ Ezt csak ticket staff használhatja.")
        member = interaction.guild.get_member(user_id)
        if member is None:
            return await interaction.response.edit_message(content="❌ A felhasználó nincs a szerveren.", view=None)
        if member.bot and action == "add":
            return await interaction.response.edit_message(content="❌ Botot nem adok hozzá ticket résztvevőként.", view=None)
        if action == "remove" and member.id == int(ticket["opener_id"]):
            return await interaction.response.edit_message(content="❌ A ticket megnyitóját nem lehet eltávolítani.", view=None)

        if action == "add":
            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                add_reactions=True,
                reason=f"Yoru Ticket #{ticket['ticket_id']} add user by {interaction.user}",
            )
            await self.store.add_member(int(ticket["ticket_id"]), member.id, interaction.user.id)
            text = f"✅ {member.mention} hozzáadva a tickethez."
        else:
            await channel.set_permissions(
                member,
                overwrite=None,
                reason=f"Yoru Ticket #{ticket['ticket_id']} remove user by {interaction.user}",
            )
            await self.store.remove_member(int(ticket["ticket_id"]), member.id)
            text = f"✅ {member.mention} eltávolítva a ticketből."
        await interaction.response.edit_message(content=text, view=None, allowed_mentions=discord.AllowedMentions.none())

    async def open_rename_modal(self, interaction: discord.Interaction) -> None:
        current = await self._current_ticket(interaction)
        if current is None or not isinstance(interaction.user, discord.Member):
            return
        _channel, ticket = current
        allowed = interaction.user.id == int(ticket["opener_id"]) or await self.is_staff(interaction.user)
        if not allowed:
            return await _ephemeral(interaction, "❌ Nincs jogosultságod átnevezni ezt a ticketet.")
        await interaction.response.send_modal(RenameTicketModal(self))

    async def rename_ticket(self, interaction: discord.Interaction, raw_name: str) -> None:
        current = await self._current_ticket(interaction)
        if current is None or not isinstance(interaction.user, discord.Member):
            return
        channel, ticket = current
        allowed = interaction.user.id == int(ticket["opener_id"]) or await self.is_staff(interaction.user)
        if not allowed:
            return await _ephemeral(interaction, "❌ Nincs jogosultságod átnevezni ezt a ticketet.")
        name = _safe_channel_part(raw_name, f"ticket-{ticket['ticket_id']}")[:95]
        if ticket["status"] == "closed" and not name.startswith("closed-"):
            name = f"closed-{name}"[:95]
        try:
            await channel.edit(name=name, reason=f"Yoru Ticket rename by {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.response.send_message("❌ Nem sikerült átnevezni a csatornát.", ephemeral=True)
        await interaction.response.send_message(f"✅ Új ticket név: `#{name}`", ephemeral=True)

    async def open_close_confirmation(self, interaction: discord.Interaction) -> None:
        current = await self._current_ticket(interaction)
        if current is None or not isinstance(interaction.user, discord.Member):
            return
        _channel, ticket = current
        allowed = interaction.user.id == int(ticket["opener_id"]) or await self.is_staff(interaction.user)
        if not allowed:
            return await _ephemeral(interaction, "❌ Nincs jogosultságod bezárni ezt a ticketet.")
        if ticket["status"] != "open":
            return await _ephemeral(interaction, "❌ Ez a ticket már le van zárva.")
        await interaction.response.send_message(
            "Biztosan bezárod ezt a ticketet? A transcript ekkor készül el.",
            view=ConfirmCloseView(self, interaction.user.id),
            ephemeral=True,
        )

    async def _transcript_bytes(self, channel: discord.TextChannel, ticket_id: int) -> tuple[bytes, str]:
        lines = [f"Yoru Ticket #{ticket_id}", f"Channel: #{channel.name} ({channel.id})", "=" * 72, ""]
        async for message in channel.history(limit=None, oldest_first=True):
            stamp = message.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            content = message.clean_content or ""
            lines.append(f"[{stamp}] {message.author} ({message.author.id}): {content}")
            for attachment in message.attachments:
                lines.append(f"    attachment: {attachment.filename} -> {attachment.url}")
            for embed in message.embeds:
                title = embed.title or ""
                description = embed.description or ""
                if title or description:
                    lines.append(f"    embed: {title} | {description[:500]}")
        data = "\n".join(lines).encode("utf-8")
        filename = f"ticket-{ticket_id}-{_safe_channel_part(channel.name, 'transcript')}.txt"
        return data, filename

    async def _edit_control_message(self, channel: discord.TextChannel, ticket: dict[str, Any], *, closed: bool) -> None:
        message_id = ticket.get("control_message_id")
        if not message_id:
            return
        try:
            message = await channel.fetch_message(int(message_id))
            updated = await self.store.get_ticket_by_channel(channel.id)
            view = ClosedTicketControlsView(self) if closed else OpenTicketControlsView(self)
            await message.edit(embed=self.ticket_embed(channel.guild, updated), view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def _send_close_log(
        self,
        guild: discord.Guild,
        ticket: dict[str, Any],
        transcript: bytes,
        filename: str,
        actor_id: int,
    ) -> None:
        log_id = await self.config.get_int(guild.id, TICKET_LOG_CHANNEL_KEY)
        log_channel = guild.get_channel(log_id) if log_id else None
        if not isinstance(log_channel, discord.TextChannel):
            return
        actor = guild.get_member(actor_id)
        embed = base_embed(
            f"🔒 Ticket #{ticket['ticket_id']} lezárva",
            f"**Típus:** {ticket.get('type_emoji') or '🎫'} {ticket.get('type_label') or 'Ticket'}\n"
            f"**Megnyitó:** <@{ticket['opener_id']}>\n"
            f"**Lezárta:** {actor.mention if actor else f'<@{actor_id}>'}",
            DANGER,
        )
        try:
            await log_channel.send(
                embed=embed,
                file=discord.File(io.BytesIO(transcript), filename=filename),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _send_opener_transcript(
        self,
        guild: discord.Guild,
        ticket: dict[str, Any],
        transcript: bytes,
        filename: str,
    ) -> None:
        if not await self.config.get_bool(guild.id, TICKET_DM_TRANSCRIPT_KEY, False):
            return
        opener = guild.get_member(int(ticket["opener_id"])) or self.bot.get_user(int(ticket["opener_id"]))
        if opener is None:
            return
        embed = base_embed(
            f"🎫 Ticket #{ticket['ticket_id']} transcript",
            f"A **{guild.name}** szerveren lezárt ticketed másolata.",
        )
        try:
            await opener.send(embed=embed, file=discord.File(io.BytesIO(transcript), filename=filename))
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def close_ticket(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel) or not isinstance(interaction.user, discord.Member):
            return await _ephemeral(interaction, "❌ Ez nem egy érvényes ticket csatorna.")
        channel = interaction.channel
        lock = self._ticket_action_locks.setdefault(channel.id, asyncio.Lock())
        if lock.locked():
            return await _ephemeral(interaction, "⏳ Ezen a ticketen már fut egy művelet.")
        async with lock:
            ticket = await self.store.get_ticket_by_channel(channel.id)
            if ticket is None:
                return await _ephemeral(interaction, "❌ Ehhez a csatornához nem tartozik ticket.")
            allowed = interaction.user.id == int(ticket["opener_id"]) or await self.is_staff(interaction.user)
            if not allowed:
                return await _ephemeral(interaction, "❌ Nincs jogosultságod bezárni ezt a ticketet.")
            if ticket["status"] != "open":
                return await interaction.response.edit_message(content="❌ Ez a ticket már le van zárva.", view=None)

            # A teljes history + transcript több másodperc is lehet, ezért az interakciót
            # azonnal nyugtázzuk, majd az ephemeral confirmation üzenetet frissítjük.
            await interaction.response.defer()
            transcript, filename = await self._transcript_bytes(channel, int(ticket["ticket_id"]))
            await self.store.close_ticket(int(ticket["ticket_id"]), interaction.user.id, "Ticket panelről lezárva")

            opener = interaction.guild.get_member(int(ticket["opener_id"]))
            if opener is not None:
                try:
                    await channel.set_permissions(
                        opener,
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True,
                        add_reactions=False,
                        reason=f"Yoru Ticket #{ticket['ticket_id']} closed",
                    )
                except discord.HTTPException:
                    pass
            for user_id in await self.store.list_members(int(ticket["ticket_id"])):
                member = interaction.guild.get_member(user_id)
                if member is not None:
                    try:
                        await channel.set_permissions(
                            member,
                            view_channel=True,
                            send_messages=False,
                            read_message_history=True,
                            add_reactions=False,
                            reason=f"Yoru Ticket #{ticket['ticket_id']} closed",
                        )
                    except discord.HTTPException:
                        pass
            if not channel.name.startswith("closed-"):
                try:
                    await channel.edit(name=f"closed-{channel.name}"[:95])
                except discord.HTTPException:
                    pass
            updated = await self.store.get_ticket_by_channel(channel.id)
            if updated is not None:
                await self._edit_control_message(channel, updated, closed=True)
                await self._send_close_log(interaction.guild, updated, transcript, filename, interaction.user.id)
                await self._send_opener_transcript(interaction.guild, updated, transcript, filename)
            await interaction.edit_original_response(content="🔒 Ticket lezárva. A transcript elkészült.", view=None)

    async def reopen_ticket(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel) or not isinstance(interaction.user, discord.Member):
            return await _ephemeral(interaction, "❌ Ez nem egy érvényes ticket csatorna.")
        channel = interaction.channel
        lock = self._ticket_action_locks.setdefault(channel.id, asyncio.Lock())
        if lock.locked():
            return await _ephemeral(interaction, "⏳ Ezen a ticketen már fut egy művelet.")
        async with lock:
            ticket = await self.store.get_ticket_by_channel(channel.id)
            if ticket is None:
                return await _ephemeral(interaction, "❌ Ehhez a csatornához nem tartozik ticket.")
            if not await self.is_staff(interaction.user):
                return await _ephemeral(interaction, "❌ Ezt csak ticket staff használhatja.")
            if ticket["status"] != "closed":
                return await _ephemeral(interaction, "❌ Ez a ticket nincs lezárva.")

            await interaction.response.defer()
            await self.store.reopen_ticket(int(ticket["ticket_id"]))
            opener = interaction.guild.get_member(int(ticket["opener_id"]))
            if opener is not None:
                try:
                    await channel.set_permissions(
                        opener,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        embed_links=True,
                        add_reactions=True,
                        reason=f"Yoru Ticket #{ticket['ticket_id']} reopened",
                    )
                except discord.HTTPException:
                    pass
            for user_id in await self.store.list_members(int(ticket["ticket_id"])):
                member = interaction.guild.get_member(user_id)
                if member is not None:
                    try:
                        await channel.set_permissions(
                            member,
                            view_channel=True,
                            send_messages=True,
                            read_message_history=True,
                            attach_files=True,
                            embed_links=True,
                            add_reactions=True,
                            reason=f"Yoru Ticket #{ticket['ticket_id']} reopened",
                        )
                    except discord.HTTPException:
                        pass
            if channel.name.startswith("closed-"):
                try:
                    await channel.edit(name=channel.name[7:][:95] or f"ticket-{ticket['ticket_id']}")
                except discord.HTTPException:
                    pass
            updated = await self.store.get_ticket_by_channel(channel.id)
            if updated is not None:
                await interaction.edit_original_response(
                    embed=self.ticket_embed(interaction.guild, updated),
                    view=OpenTicketControlsView(self),
                )

    async def open_delete_confirmation(self, interaction: discord.Interaction) -> None:
        current = await self._current_ticket(interaction)
        if current is None or not isinstance(interaction.user, discord.Member):
            return
        _channel, ticket = current
        if not await self.is_staff(interaction.user):
            return await _ephemeral(interaction, "❌ Ezt csak ticket staff használhatja.")
        if ticket["status"] != "closed":
            return await _ephemeral(interaction, "❌ Előbb zárd le a ticketet.")
        await interaction.response.send_message(
            "⚠️ Biztosan végleg törlöd ezt a ticket csatornát?",
            view=ConfirmDeleteView(self, interaction.user.id),
            ephemeral=True,
        )

    async def delete_ticket(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel) or not isinstance(interaction.user, discord.Member):
            return await _ephemeral(interaction, "❌ Ez nem egy érvényes ticket csatorna.")
        channel = interaction.channel
        lock = self._ticket_action_locks.setdefault(channel.id, asyncio.Lock())
        if lock.locked():
            return await _ephemeral(interaction, "⏳ Ezen a ticketen már fut egy művelet.")
        async with lock:
            ticket = await self.store.get_ticket_by_channel(channel.id)
            if ticket is None:
                return await _ephemeral(interaction, "❌ Ehhez a csatornához nem tartozik ticket.")
            if not await self.is_staff(interaction.user):
                return await _ephemeral(interaction, "❌ Ezt csak ticket staff használhatja.")
            if ticket["status"] != "closed":
                return await interaction.response.edit_message(content="❌ Előbb zárd le a ticketet.", view=None)
            await interaction.response.edit_message(content="🗑️ Ticket csatorna törlése…", view=None)
            try:
                await channel.delete(reason=f"Yoru Ticket #{ticket['ticket_id']} deleted by {interaction.user}")
            except (discord.Forbidden, discord.HTTPException):
                await interaction.followup.send("❌ Nem sikerült törölni a csatornát.", ephemeral=True)

