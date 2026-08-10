from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import crew_config as cfg
from app.database import Database
from app.services.statistics import StatisticsService


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

    @staticmethod
    def normalize_name(name: str) -> tuple[str, str]:
        clean = " ".join(str(name).strip().split())
        if not 3 <= len(clean) <= 24:
            raise ValueError("A Crew neve **3–24 karakter** lehet.")
        if not all(ch.isalnum() or ch in " _-" for ch in clean):
            raise ValueError("A Crew név csak betűt, számot, szóközt, `_` vagy `-` jelet tartalmazhat.")
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
        crew_data = await self.db.create_crew(guild_id, user_id, clean, normalized, cfg.CREW_CREATE_COST)
        await self.stats.increment(guild_id, user_id, "crew.created")
        await self.stats.increment(guild_id, user_id, "crew.joined")
        await self.stats.add(guild_id, user_id, "crew.creation_spent", cfg.CREW_CREATE_COST)
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            raise RuntimeError("A Crew létrejött, de a tagság betöltése sikertelen volt.")
        return membership

    async def invite(self, guild_id: int, actor_id: int, target_id: int) -> datetime:
        if actor_id == target_id:
            raise ValueError("Saját magadat nem kell meghívnod.")
        membership = await self.get_membership(guild_id, actor_id)
        if membership is None:
            raise ValueError("Nem vagy Crew tagja.")
        if self.ROLE_RANK.get(membership.member.role, 0) < self.ROLE_RANK["officer"]:
            raise ValueError("Csak a **Leader** vagy **Officer** hívhat meg új tagot.")
        if await self.get_membership(guild_id, target_id) is not None:
            raise ValueError("Ez a játékos már egy Crew tagja.")
        if membership.crew.member_count >= membership.crew.member_cap:
            raise ValueError(f"A Crew megtelt (**{membership.crew.member_count}/{membership.crew.member_cap}**). Előbb fejlesszétek.")
        expires = datetime.now(timezone.utc) + timedelta(hours=cfg.CREW_INVITE_HOURS)
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
            raise ValueError("Nincs aktív Crew meghívód.")
        crew_data, _expires = invite
        crew = self._crew_from_dict(crew_data)
        await self.db.accept_crew_invite(guild_id, user_id, crew.member_cap)
        await self.stats.increment(guild_id, user_id, "crew.joined")
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            raise RuntimeError("A Crew tagság létrejött, de nem tölthető be.")
        return membership

    async def leave(self, guild_id: int, user_id: int) -> str:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            raise ValueError("Nem vagy Crew tagja.")
        if membership.member.role == "leader":
            raise ValueError("Leaderként nem léphetsz ki. Add át a vezetést (`!crewtransfer`) vagy oszlasd fel a Crew-t.")
        await self.db.remove_crew_member(guild_id, membership.crew.crew_id, user_id)
        await self.stats.increment(guild_id, user_id, "crew.left")
        return membership.crew.name

    async def kick(self, guild_id: int, actor_id: int, target_id: int) -> CrewInfo:
        actor = await self.get_membership(guild_id, actor_id)
        target = await self.get_membership(guild_id, target_id)
        if actor is None:
            raise ValueError("Nem vagy Crew tagja.")
        if target is None or target.crew.crew_id != actor.crew.crew_id:
            raise ValueError("Ez a játékos nem a Crew tagja.")
        if actor_id == target_id:
            raise ValueError("Saját magadat nem kickelheted.")
        actor_rank = self.ROLE_RANK.get(actor.member.role, 0)
        target_rank = self.ROLE_RANK.get(target.member.role, 0)
        if actor_rank < self.ROLE_RANK["officer"] or actor_rank <= target_rank:
            raise ValueError("Nincs jogosultságod ezt a tagot eltávolítani.")
        await self.db.remove_crew_member(guild_id, actor.crew.crew_id, target_id)
        await self.stats.increment(guild_id, actor_id, "crew.kicks")
        await self.stats.increment(guild_id, target_id, "crew.kicked")
        return actor.crew

    async def set_role(self, guild_id: int, actor_id: int, target_id: int, role: str) -> CrewMembership:
        if role not in {"officer", "member"}:
            raise ValueError("Érvénytelen Crew rang.")
        actor = await self.get_membership(guild_id, actor_id)
        target = await self.get_membership(guild_id, target_id)
        if actor is None or actor.member.role != "leader":
            raise ValueError("Csak a Crew **Leader** módosíthat rangokat.")
        if target is None or target.crew.crew_id != actor.crew.crew_id:
            raise ValueError("Ez a játékos nem a Crew tagja.")
        if target_id == actor_id:
            raise ValueError("A Leader rangot ezzel nem módosíthatod.")
        await self.db.set_crew_member_role(guild_id, actor.crew.crew_id, target_id, role)
        refreshed = await self.get_membership(guild_id, target_id)
        if refreshed is None:
            raise RuntimeError("A Crew rang frissítése sikertelen volt.")
        return refreshed

    async def transfer(self, guild_id: int, actor_id: int, target_id: int) -> CrewMembership:
        actor = await self.get_membership(guild_id, actor_id)
        target = await self.get_membership(guild_id, target_id)
        if actor is None or actor.member.role != "leader":
            raise ValueError("Csak a Crew **Leader** adhatja át a vezetést.")
        if target is None or target.crew.crew_id != actor.crew.crew_id:
            raise ValueError("A célpont nem a Crew tagja.")
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
            raise ValueError("Nem vagy Crew tagja.")
        wallet, bank = await self.db.deposit_to_crew(guild_id, membership.crew.crew_id, user_id, int(amount))
        await self.stats.increment(guild_id, user_id, "crew.deposits")
        await self.stats.add(guild_id, user_id, "crew.contributed", int(amount))
        crew = await self.get_crew(guild_id, membership.crew.crew_id)
        if crew is None:
            raise RuntimeError("A Crew nem tölthető be.")
        return wallet, bank, crew

    async def withdraw(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int, CrewInfo]:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None or membership.member.role != "leader":
            raise ValueError("Csak a Crew **Leader** vehet ki pénzt a Crew Bankból.")
        wallet, bank = await self.db.withdraw_from_crew(guild_id, membership.crew.crew_id, user_id, int(amount))
        await self.stats.increment(guild_id, user_id, "crew.withdrawals")
        await self.stats.add(guild_id, user_id, "crew.withdrawn", int(amount))
        crew = await self.get_crew(guild_id, membership.crew.crew_id)
        if crew is None:
            raise RuntimeError("A Crew nem tölthető be.")
        return wallet, bank, crew

    async def upgrade(self, guild_id: int, user_id: int) -> tuple[CrewInfo, int]:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None or membership.member.role != "leader":
            raise ValueError("Csak a Crew **Leader** fejlesztheti a Crew-t.")
        cost = cfg.upgrade_cost(membership.crew.level)
        if cost is None:
            raise ValueError("A Crew már elérte a maximális szintet.")
        await self.db.upgrade_crew(guild_id, membership.crew.crew_id, membership.crew.level, cost)
        await self.stats.increment(guild_id, user_id, "crew.upgrades")
        await self.stats.add(guild_id, user_id, "crew.upgrade_spent", cost)
        await self.stats.set_max(guild_id, user_id, "crew.highest_level_upgraded", membership.crew.level + 1)
        crew = await self.get_crew(guild_id, membership.crew.crew_id)
        if crew is None:
            raise RuntimeError("A Crew nem tölthető be.")
        return crew, cost

    async def set_description(self, guild_id: int, user_id: int, description: str) -> CrewInfo:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None or membership.member.role != "leader":
            raise ValueError("Csak a Crew **Leader** írhat leírást.")
        clean = " ".join(str(description).strip().split())
        if len(clean) > 160:
            raise ValueError("A Crew leírás legfeljebb **160 karakter** lehet.")
        await self.db.set_crew_description(guild_id, membership.crew.crew_id, clean)
        crew = await self.get_crew(guild_id, membership.crew.crew_id)
        if crew is None:
            raise RuntimeError("A Crew nem tölthető be.")
        return crew

    async def disband(self, guild_id: int, user_id: int) -> tuple[str, int]:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None or membership.member.role != "leader":
            raise ValueError("Csak a Crew **Leader** oszlathatja fel a Crew-t.")
        name, refunded = await self.db.disband_crew(guild_id, membership.crew.crew_id, user_id)
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
        return 1.0 + membership.crew.income_bonus

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
