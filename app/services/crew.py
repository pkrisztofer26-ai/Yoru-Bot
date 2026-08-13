from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import crew_config as cfg
from app.database import Database
from app.services.statistics import StatisticsService
from app.services.server_settings import ServerSettingsService


@dataclass(frozen=True)
class CrewInfo:
    crew_id: int
    guild_id: int
    name: str
    owner_id: int
    bank: int
    level: int
    total_contributed: int
    description: str
    discord_role_id: int | None
    created_at: datetime
    member_count: int

    @property
    def member_cap(self) -> int:
        return cfg.member_cap(self.level)

    @property
    def income_bonus(self) -> float:
        return cfg.income_bonus(self.level)

    @property
    def upgrade_cost(self) -> int | None:
        return cfg.upgrade_cost(self.level)


@dataclass(frozen=True)
class CrewMember:
    user_id: int
    role: str
    contributed: int
    joined_at: datetime


@dataclass(frozen=True)
class CrewMembership:
    crew: CrewInfo
    member: CrewMember


class CrewService:
    ROLE_RANK = {"member": 0, "officer": 1, "leader": 2}

    def __init__(self, database: Database, statistics: StatisticsService) -> None:
        self.db = database
        self.stats = statistics
        self.settings = ServerSettingsService(database)
        self.faction = None
        self.bot = None

    async def create_cost(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.CREW_CREATE_COST_KEY)
        return max(0, min(10**15, int(cfg.CREW_CREATE_COST if value is None else value)))

    async def invite_hours(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.CREW_INVITE_HOURS_KEY)
        return max(1, min(720, int(cfg.CREW_INVITE_HOURS if value is None else value)))

    async def set_core_settings(self, guild_id: int, *, create_cost: int, invite_hours: int) -> None:
        if not 0 <= int(create_cost) <= 10**15:
            raise ValueError("Frakció alapítási ár: 0–1 quadrillion.")
        if not 1 <= int(invite_hours) <= 720:
            raise ValueError("Frakció meghívó lejárat: 1–720 óra.")
        await self.settings.set_int(guild_id, cfg.CREW_CREATE_COST_KEY, int(create_cost))
        await self.settings.set_int(guild_id, cfg.CREW_INVITE_HOURS_KEY, int(invite_hours))

    async def reset_core_settings(self, guild_id: int) -> None:
        await self.db.set_guild_state(guild_id, cfg.CREW_CREATE_COST_KEY, "")
        await self.db.set_guild_state(guild_id, cfg.CREW_INVITE_HOURS_KEY, "")

    def bind_bot(self, bot) -> None:
        self.bot = bot

    def bind_faction(self, faction_service) -> None:
        self.faction = faction_service

    async def _has_permission(self, guild_id: int, user_id: int, permission: str, *, legacy_role: str | None = None) -> bool:
        if self.faction is not None:
            return await self.faction.has_permission(guild_id, user_id, permission)
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            return False
        if membership.member.role == "leader":
            return True
        if legacy_role == "officer":
            return self.ROLE_RANK.get(membership.member.role, 0) >= self.ROLE_RANK["officer"]
        return False

    @staticmethod
    def normalize_name(name: str) -> tuple[str, str]:
        clean = " ".join(str(name).strip().split())
        if not 3 <= len(clean) <= 24:
            raise ValueError("A Frakció neve **3–24 karakter** lehet.")
        if not all(ch.isalnum() or ch in " _-" for ch in clean):
            raise ValueError("A Frakció név csak betűt, számot, szóközt, `_` vagy `-` jelet tartalmazhat.")
        return clean, clean.casefold()

    @staticmethod
    def _parse_dt(raw: str) -> datetime:
        value = datetime.fromisoformat(raw)
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def _crew_from_dict(self, data: dict[str, object]) -> CrewInfo:
        return CrewInfo(
            crew_id=int(data["crew_id"]),
            guild_id=int(data["guild_id"]),
            name=str(data["name"]),
            owner_id=int(data["owner_id"]),
            bank=int(data["bank"]),
            level=int(data["level"]),
            total_contributed=int(data["total_contributed"]),
            description=str(data.get("description") or ""),
            discord_role_id=int(data["discord_role_id"]) if data.get("discord_role_id") else None,
            created_at=self._parse_dt(str(data["created_at"])),
            member_count=int(data.get("member_count", 0)),
        )

    def _member_from_dict(self, data: dict[str, object]) -> CrewMember:
        return CrewMember(
            user_id=int(data["user_id"]),
            role=str(data["role"]),
            contributed=int(data["contributed"]),
            joined_at=self._parse_dt(str(data["joined_at"])),
        )

    async def _discord_guild(self, guild_id: int):
        if self.bot is None:
            return None
        return self.bot.get_guild(guild_id)

    async def _ensure_discord_role(self, crew: CrewInfo):
        """Return/create the hoisted Discord role for a Frakció.

        Existing exact-name roles are adopted first, which also repairs Frakciók
        created before v3.17.4 without making duplicates.
        """
        guild = await self._discord_guild(crew.guild_id)
        if guild is None:
            return None
        role = guild.get_role(int(crew.discord_role_id)) if crew.discord_role_id else None
        if role is None:
            role = next(
                (candidate for candidate in reversed(guild.roles)
                 if not candidate.managed and candidate.name.casefold() == crew.name.casefold()),
                None,
            )
        if role is None:
            me = guild.me
            if me is None or not me.guild_permissions.manage_roles:
                return None
            try:
                import discord
                role = await guild.create_role(
                    name=crew.name,
                    permissions=discord.Permissions.none(),
                    hoist=True,
                    mentionable=False,
                    reason=f"Yoru Frakció role • {crew.name}",
                )
            except Exception:
                return None
        else:
            me = guild.me
            manageable = bool(me and me.guild_permissions.manage_roles and not role.managed and role < me.top_role)
            if manageable and (role.name != crew.name or not role.hoist):
                try:
                    await role.edit(name=crew.name, hoist=True, reason=f"Yoru Frakció role sync • {crew.name}")
                except Exception:
                    pass
        if crew.discord_role_id != role.id:
            await self.db.set_crew_discord_role_id(crew.guild_id, crew.crew_id, role.id)
        return role

    async def _sync_member_discord_role(self, membership: CrewMembership) -> bool:
        guild = await self._discord_guild(membership.crew.guild_id)
        if guild is None:
            return False
        role = await self._ensure_discord_role(membership.crew)
        if role is None:
            return False
        member = guild.get_member(membership.member.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(membership.member.user_id)
            except Exception:
                return False
        if role in member.roles:
            return True
        try:
            await member.add_roles(role, reason=f"Yoru Frakció tagság • {membership.crew.name}")
            return True
        except Exception:
            return False

    async def _remove_member_discord_role(self, crew: CrewInfo, user_id: int) -> None:
        guild = await self._discord_guild(crew.guild_id)
        if guild is None:
            return
        role = guild.get_role(int(crew.discord_role_id)) if crew.discord_role_id else None
        if role is None:
            role = next((r for r in guild.roles if not r.managed and r.name.casefold() == crew.name.casefold()), None)
        member = guild.get_member(user_id)
        if role is None or member is None or role not in member.roles:
            return
        try:
            await member.remove_roles(role, reason=f"Yoru Frakció tagság vége • {crew.name}")
        except Exception:
            pass

    async def reconcile_discord_roles(self, guild_id: int) -> tuple[int, int, int]:
        """Repair/create hoisted Frakció roles and membership assignments."""
        crews = [self._crew_from_dict(row) for row in await self.db.crew_leaderboard(guild_id, 1000)]
        roles_ready = members_added = failed = 0
        for crew in crews:
            role = await self._ensure_discord_role(crew)
            if role is None:
                failed += 1
                continue
            roles_ready += 1
            rows = await self.members(guild_id, crew.crew_id)
            member_ids = {row.user_id for row in rows}
            for row in rows:
                membership = CrewMembership(crew, row)
                guild = await self._discord_guild(guild_id)
                member = guild.get_member(row.user_id) if guild else None
                already = bool(member and role in member.roles)
                if await self._sync_member_discord_role(membership) and not already:
                    members_added += 1
            # Remove stale role holders who are no longer database members.
            for member in list(getattr(role, "members", [])):
                if member.id not in member_ids:
                    try:
                        await member.remove_roles(role, reason=f"Yoru Frakció role reconcile • {crew.name}")
                    except Exception:
                        failed += 1
        return roles_ready, members_added, failed

    async def get_membership(self, guild_id: int, user_id: int) -> CrewMembership | None:
        row = await self.db.get_crew_membership(guild_id, user_id)
        if row is None:
            return None
        crew_data, member_data = row
        return CrewMembership(self._crew_from_dict(crew_data), self._member_from_dict(member_data))

    async def get_crew(self, guild_id: int, crew_id: int) -> CrewInfo | None:
        row = await self.db.get_crew(guild_id, crew_id)
        return self._crew_from_dict(row) if row else None

    async def members(self, guild_id: int, crew_id: int) -> list[CrewMember]:
        return [self._member_from_dict(row) for row in await self.db.get_crew_members(guild_id, crew_id)]

    async def create(self, guild_id: int, user_id: int, name: str) -> CrewMembership:
        clean, normalized = self.normalize_name(name)
        create_cost = await self.create_cost(guild_id)
        crew_data = await self.db.create_crew(guild_id, user_id, clean, normalized, create_cost)
        await self.stats.increment(guild_id, user_id, "crew.created")
        await self.stats.increment(guild_id, user_id, "crew.joined")
        await self.stats.add(guild_id, user_id, "crew.creation_spent", create_cost)
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            raise RuntimeError("A Frakció létrejött, de a tagság betöltése sikertelen volt.")
        await self._sync_member_discord_role(membership)
        return membership

    async def invite(self, guild_id: int, actor_id: int, target_id: int) -> datetime:
        if actor_id == target_id:
            raise ValueError("Saját magadat nem kell meghívnod.")
        membership = await self.get_membership(guild_id, actor_id)
        if membership is None:
            raise ValueError("Nem vagy Frakció tagja.")
        if not await self._has_permission(guild_id, actor_id, "invite", legacy_role="officer"):
            raise ValueError("Nincs jogosultságod új tagot meghívni a Frakcióba.")
        if await self.get_membership(guild_id, target_id) is not None:
            raise ValueError("Ez a játékos már egy Frakció tagja.")
        if membership.crew.member_count >= membership.crew.member_cap:
            raise ValueError(f"A Frakció megtelt (**{membership.crew.member_count}/{membership.crew.member_cap}**). Előbb fejlesszétek.")
        expires = datetime.now(timezone.utc) + timedelta(hours=await self.invite_hours(guild_id))
        await self.db.set_crew_invite(guild_id, membership.crew.crew_id, target_id, actor_id, expires)
        await self.stats.increment(guild_id, actor_id, "crew.invites_sent")
        return expires

    async def pending_invite(self, guild_id: int, user_id: int) -> tuple[CrewInfo, datetime] | None:
        row = await self.db.get_crew_invite(guild_id, user_id)
        if row is None:
            return None
        crew_data, expires_raw = row
        return self._crew_from_dict(crew_data), self._parse_dt(expires_raw)

    async def accept(self, guild_id: int, user_id: int) -> CrewMembership:
        invite = await self.db.get_crew_invite(guild_id, user_id)
        if invite is None:
            raise ValueError("Nincs aktív Frakció meghívód.")
        crew_data, _expires = invite
        crew = self._crew_from_dict(crew_data)
        await self.db.accept_crew_invite(guild_id, user_id, crew.member_cap)
        await self.stats.increment(guild_id, user_id, "crew.joined")
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            raise RuntimeError("A Frakció tagság létrejött, de nem tölthető be.")
        await self._sync_member_discord_role(membership)
        return membership

    async def leave(self, guild_id: int, user_id: int) -> str:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            raise ValueError("Nem vagy Frakció tagja.")
        if membership.member.role == "leader":
            raise ValueError("Leaderként nem léphetsz ki. Add át a vezetést (`!crewtransfer`) vagy oszlasd fel a Frakciót.")
        await self.db.remove_crew_member(guild_id, membership.crew.crew_id, user_id)
        await self._remove_member_discord_role(membership.crew, user_id)
        await self.stats.increment(guild_id, user_id, "crew.left")
        return membership.crew.name

    async def kick(self, guild_id: int, actor_id: int, target_id: int) -> CrewInfo:
        actor = await self.get_membership(guild_id, actor_id)
        target = await self.get_membership(guild_id, target_id)
        if actor is None:
            raise ValueError("Nem vagy Frakció tagja.")
        if target is None or target.crew.crew_id != actor.crew.crew_id:
            raise ValueError("Ez a játékos nem a Frakció tagja.")
        if actor_id == target_id:
            raise ValueError("Saját magadat nem kickelheted.")
        if target.member.role == "leader" or not await self._has_permission(guild_id, actor_id, "kick", legacy_role="officer"):
            raise ValueError("Nincs jogosultságod ezt a tagot eltávolítani.")
        await self.db.remove_crew_member(guild_id, actor.crew.crew_id, target_id)
        await self._remove_member_discord_role(actor.crew, target_id)
        await self.stats.increment(guild_id, actor_id, "crew.kicks")
        await self.stats.increment(guild_id, target_id, "crew.kicked")
        return actor.crew

    async def set_role(self, guild_id: int, actor_id: int, target_id: int, role: str) -> CrewMembership:
        if role not in {"officer", "member"}:
            raise ValueError("Érvénytelen Frakció rang.")
        actor = await self.get_membership(guild_id, actor_id)
        target = await self.get_membership(guild_id, target_id)
        if actor is None or not await self._has_permission(guild_id, actor_id, "manage_ranks"):
            raise ValueError("Nincs jogosultságod Frakció rangokat módosítani.")
        if target is None or target.crew.crew_id != actor.crew.crew_id:
            raise ValueError("Ez a játékos nem a Frakció tagja.")
        if target_id == actor_id:
            raise ValueError("A Leader rangot ezzel nem módosíthatod.")
        await self.db.set_crew_member_role(guild_id, actor.crew.crew_id, target_id, role)
        refreshed = await self.get_membership(guild_id, target_id)
        if refreshed is None:
            raise RuntimeError("A Frakció rang frissítése sikertelen volt.")
        return refreshed

    async def transfer(self, guild_id: int, actor_id: int, target_id: int) -> CrewMembership:
        actor = await self.get_membership(guild_id, actor_id)
        target = await self.get_membership(guild_id, target_id)
        if actor is None or actor.member.role != "leader":
            raise ValueError("Csak a Frakció **Leader** adhatja át a vezetést.")
        if target is None or target.crew.crew_id != actor.crew.crew_id:
            raise ValueError("A célpont nem a Frakció tagja.")
        if target_id == actor_id:
            raise ValueError("Már te vagy a Leader.")
        await self.db.transfer_crew_ownership(guild_id, actor.crew.crew_id, actor_id, target_id)
        await self.stats.increment(guild_id, actor_id, "crew.leadership_transfers")
        refreshed = await self.get_membership(guild_id, target_id)
        if refreshed is None:
            raise RuntimeError("A vezetés átadása sikertelen volt.")
        return refreshed

    async def deposit(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int, CrewInfo]:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            raise ValueError("Nem vagy Frakció tagja.")
        wallet, bank = await self.db.deposit_to_crew(guild_id, membership.crew.crew_id, user_id, int(amount))
        await self.stats.increment(guild_id, user_id, "crew.deposits")
        await self.stats.add(guild_id, user_id, "crew.contributed", int(amount))
        crew = await self.get_crew(guild_id, membership.crew.crew_id)
        if crew is None:
            raise RuntimeError("A Frakció nem tölthető be.")
        return wallet, bank, crew

    async def withdraw(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int, CrewInfo]:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None or not await self._has_permission(guild_id, user_id, "bank_withdraw"):
            raise ValueError("Nincs jogosultságod pénzt kivenni a Frakció Bankból.")
        wallet, bank = await self.db.withdraw_from_crew(guild_id, membership.crew.crew_id, user_id, int(amount))
        await self.stats.increment(guild_id, user_id, "crew.withdrawals")
        await self.stats.add(guild_id, user_id, "crew.withdrawn", int(amount))
        crew = await self.get_crew(guild_id, membership.crew.crew_id)
        if crew is None:
            raise RuntimeError("A Frakció nem tölthető be.")
        return wallet, bank, crew

    async def upgrade(self, guild_id: int, user_id: int) -> tuple[CrewInfo, int]:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None or not await self._has_permission(guild_id, user_id, "upgrade"):
            raise ValueError("Nincs jogosultságod a Frakció infrastructure fejlesztéséhez.")
        cost = cfg.upgrade_cost(membership.crew.level)
        if cost is None:
            raise ValueError("A Frakció Infrastructure már elérte a maximális szintet.")
        await self.db.upgrade_crew(guild_id, membership.crew.crew_id, membership.crew.level, cost)
        await self.stats.increment(guild_id, user_id, "crew.upgrades")
        await self.stats.add(guild_id, user_id, "crew.upgrade_spent", cost)
        await self.stats.set_max(guild_id, user_id, "crew.highest_level_upgraded", membership.crew.level + 1)
        crew = await self.get_crew(guild_id, membership.crew.crew_id)
        if crew is None:
            raise RuntimeError("A Frakció nem tölthető be.")
        return crew, cost

    async def set_description(self, guild_id: int, user_id: int, description: str) -> CrewInfo:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None or not await self._has_permission(guild_id, user_id, "manage_profile"):
            raise ValueError("Nincs jogosultságod a Frakció leírását szerkeszteni.")
        clean = " ".join(str(description).strip().split())
        if len(clean) > 160:
            raise ValueError("A Frakció leírás legfeljebb **160 karakter** lehet.")
        await self.db.set_crew_description(guild_id, membership.crew.crew_id, clean)
        crew = await self.get_crew(guild_id, membership.crew.crew_id)
        if crew is None:
            raise RuntimeError("A Frakció nem tölthető be.")
        return crew

    async def disband(self, guild_id: int, user_id: int) -> tuple[str, int]:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None or membership.member.role != "leader":
            raise ValueError("Csak a Frakció **Leader** oszlathatja fel a Frakciót.")
        guild = await self._discord_guild(guild_id)
        role = None
        if guild is not None:
            role = guild.get_role(int(membership.crew.discord_role_id)) if membership.crew.discord_role_id else None
            if role is None:
                role = next((r for r in guild.roles if not r.managed and r.name.casefold() == membership.crew.name.casefold()), None)
        name, refunded = await self.db.disband_crew(guild_id, membership.crew.crew_id, user_id)
        if role is not None:
            try:
                await role.delete(reason=f"Yoru Frakció feloszlatva • {membership.crew.name}")
            except Exception:
                pass
        await self.stats.increment(guild_id, user_id, "crew.disbanded")
        return name, refunded

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[CrewInfo]:
        return [self._crew_from_dict(row) for row in await self.db.crew_leaderboard(guild_id, limit)]

    async def reward_multiplier(self, guild_id: int, user_id: int, source: str) -> float:
        if source not in cfg.CREW_BONUS_SOURCES:
            return 1.0
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            return 1.0
        bonus = membership.crew.income_bonus
        if self.faction is not None:
            bonus += await self.faction.income_bonus(guild_id, membership.crew.crew_id)
        return 1.0 + bonus

    async def boost_reward(self, guild_id: int, user_id: int, amount: int, source: str) -> tuple[int, int]:
        amount = int(amount)
        if amount <= 0 or source not in cfg.CREW_BONUS_SOURCES:
            return amount, 0
        multiplier = await self.reward_multiplier(guild_id, user_id, source)
        boosted = max(amount, int(round(amount * multiplier)))
        bonus = max(0, boosted - amount)
        if bonus:
            await self.stats.add(guild_id, user_id, "crew.bonus_earned", bonus)
            await self.stats.add(guild_id, user_id, f"crew.bonus.{source}", bonus)
        return boosted, bonus
