from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app import contract_config as cfg
from app import character_config
from app import db_backend as aiosqlite
from app.services.contracts_models import ObjectiveSpec, ContractSnapshot, ContractDomainEventResult, ContractRecoveryReport

log = logging.getLogger("vaultbot.contracts")

class ContractsEventMixin:

    async def accept_contract(self, guild_id: int, contract_id: int, assignee_id: int) -> ContractSnapshot:
        now = self._now_iso()
        pre = await self.get_contract(guild_id, contract_id)
        if pre is None:
            raise ValueError("Nincs ilyen megbízás.")
        state = await self.source_state(guild_id, contract_id)
        if pre.source_type == "private":
            if not state or int(state.get("target_user_id") or 0) != int(assignee_id):
                raise ValueError("Ez a privát megbízás nem neked szól.")
            if not await self._source_requirements_eligible(guild_id, assignee_id, state):
                raise ValueError("Ez a privát megbízás jelenleg nem elérhető számodra.")
        creator_id = pre.creator_id
        title = pre.title
        expires_at = pre.expires_at
        reciprocal = False
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cur = await conn.execute(
                    """SELECT creator_id,status,expires_at,title,source_type FROM contracts
                       WHERE guild_id=? AND contract_id=?""",
                    (guild_id, int(contract_id)),
                )
                row = await cur.fetchone()
                if row is None:
                    raise ValueError("Nincs ilyen megbízás.")
                source_type = str(row[4])
                if source_type not in ({"player"} | set(cfg.SYSTEM_SOURCE_TYPES)):
                    raise ValueError("Ez a megbízás nem vállalható el.")
                creator_id = int(row[0]) if row[0] is not None else None
                status, expires_at, title = str(row[1]), str(row[2]), str(row[3])
                if creator_id is not None and creator_id == int(assignee_id):
                    raise ValueError("A saját megbízásodat nem vállalhatod el.")
                if status != "open":
                    raise ValueError("Ez a megbízás már nem vállalható el.")
                if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
                    raise ValueError("Ez a megbízás lejárt.")
                if source_type == "private":
                    cur = await conn.execute(
                        "SELECT target_user_id FROM contract_source_state WHERE guild_id=? AND contract_id=?",
                        (guild_id, int(contract_id)),
                    )
                    private_row = await cur.fetchone()
                    if private_row is None or int(private_row[0]) != int(assignee_id):
                        raise ValueError("Ez a privát megbízás nem neked szól.")
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM contracts WHERE guild_id=? AND assignee_id=? AND status='active'",
                    (guild_id, int(assignee_id)),
                )
                if int((await cur.fetchone())[0]) >= cfg.PLAYER_MAX_ACTIVE_ASSIGNED:
                    raise ValueError(f"Egyszerre legfeljebb {cfg.PLAYER_MAX_ACTIVE_ASSIGNED} megbízást vállalhatsz.")
                await self.db.ensure_user_tx(conn, guild_id, assignee_id)
                cur = await conn.execute(
                    """UPDATE contracts SET assignee_id=?,status='active',accepted_at=?
                       WHERE guild_id=? AND contract_id=? AND status='open' AND assignee_id IS NULL""",
                    (assignee_id, now, guild_id, int(contract_id)),
                )
                if not cur.rowcount:
                    raise ValueError("Ezt a megbízást közben más vállalta el.")
                await self._history_tx(
                    conn, guild_id, contract_id, event_key=f"accepted:{assignee_id}", event_type="accepted",
                    actor_id=assignee_id, metadata={"creator_id": creator_id, "source_type": source_type}, now=now,
                )
                source_key = str((state or {}).get("source_key") or pre.source_ref or "player_board")
                await self._telemetry_tx(
                    conn, guild_id, event_key=f"accepted:{contract_id}:{assignee_id}", event_type="accepted",
                    contract_id=contract_id, actor_id=assignee_id, counterparty_id=creator_id,
                    source_key=source_key, reward_amount=pre.reward_amount, details={"source_type": source_type}, now=now,
                )
                if pre.reward_amount >= cfg.CONTRACT_HIGH_VALUE_THRESHOLD:
                    await self._telemetry_tx(
                        conn, guild_id, event_key=f"high_value_accept:{contract_id}:{assignee_id}", event_type="high_value",
                        contract_id=contract_id, actor_id=assignee_id, counterparty_id=creator_id, source_key=source_key,
                        reward_amount=pre.reward_amount, details={"stage": "accepted"}, now=now,
                    )
                if creator_id is not None:
                    cutoff = (datetime.now(timezone.utc) - timedelta(days=cfg.RECIPROCAL_TELEMETRY_DAYS)).isoformat()
                    cur = await conn.execute(
                        """SELECT 1 FROM contracts WHERE guild_id=? AND creator_id=? AND assignee_id=?
                           AND status='settled' AND resolved_at>=? LIMIT 1""",
                        (guild_id, int(assignee_id), int(creator_id), cutoff),
                    )
                    reciprocal = await cur.fetchone() is not None
                    if reciprocal:
                        await self._telemetry_tx(
                            conn, guild_id, event_key=f"reciprocal:{contract_id}:{creator_id}:{assignee_id}",
                            event_type="reciprocal_pair", contract_id=contract_id, actor_id=assignee_id,
                            counterparty_id=creator_id, source_key=source_key, reward_amount=pre.reward_amount,
                            details={"window_days": cfg.RECIPROCAL_TELEMETRY_DAYS}, now=now,
                        )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        await self._stat_add(guild_id, assignee_id, "contract.accepted")
        if reciprocal and creator_id is not None:
            await self._stat_add(guild_id, assignee_id, "contract.reciprocal_pair")
            await self._stat_add(guild_id, creator_id, "contract.reciprocal_pair")
        snapshot = await self.get_contract(guild_id, contract_id)
        if snapshot is None:
            raise RuntimeError("A megbízás elfogadása után nem olvasható vissza.")
        if creator_id is not None:
            await self._notify(
                guild_id, creator_id, contract_id=contract_id, event_key=f"accepted.{assignee_id}",
                title="📦 Elvállalták a megbízásodat", body=f"A **{title}** megbízásodat egy játékos elvállalta.",
                expires_at=expires_at, important=True,
            )
        return snapshot

    async def _record_verified_event(
        self,
        guild_id: int,
        contract_id: int,
        actor_id: int,
        *,
        event_key: str,
        event_type: str,
        target_ref: str,
        delta: int = 1,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        objective_type = cfg.EVENT_TO_OBJECTIVE.get(str(event_type))
        if objective_type is None:
            raise ValueError("Nem támogatott contract domain event.")
        event_key = str(event_key).strip()[:190]
        target_ref = str(target_ref).strip().lower()
        delta = int(delta)
        if not event_key:
            raise ValueError("Érvénytelen domain event kulcs.")
        if not target_ref or len(target_ref) > 128 or delta < 1:
            raise ValueError("Érvénytelen domain event tartalom.")
        now = self._now_iso()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cur = await conn.execute(
                    "SELECT contract_id FROM contract_event_claims WHERE guild_id=? AND event_key=?",
                    (guild_id, event_key),
                )
                claim = await cur.fetchone()
                if claim is not None:
                    await conn.rollback()
                    return False
                cur = await conn.execute(
                    "SELECT assignee_id,status,expires_at FROM contracts WHERE guild_id=? AND contract_id=?",
                    (guild_id, int(contract_id)),
                )
                row = await cur.fetchone()
                if row is None:
                    raise ValueError("Nincs ilyen megbízás.")
                if str(row[1]) != "active" or row[0] is None or int(row[0]) != int(actor_id):
                    raise ValueError("Ez az esemény nem írható erre a megbízásra.")
                if datetime.fromisoformat(str(row[2])) <= datetime.now(timezone.utc):
                    raise ValueError("A megbízás lejárt.")
                cur = await conn.execute(
                    """SELECT objective_id,required_value,current_value FROM contract_objectives
                       WHERE guild_id=? AND contract_id=? AND objective_type=? AND target_ref=? AND status='pending'
                       ORDER BY objective_id""",
                    (guild_id, int(contract_id), objective_type, target_ref),
                )
                objectives = await cur.fetchall()
                if not objectives:
                    raise ValueError("Ehhez a domain eseményhez nincs nyitott objective.")
                await conn.execute(
                    """INSERT INTO contract_event_claims(guild_id,event_key,contract_id,event_type,actor_id,created_at)
                       VALUES(?,?,?,?,?,?)""",
                    (guild_id, event_key, int(contract_id), str(event_type), int(actor_id), now),
                )
                await conn.execute(
                    """INSERT INTO contract_events(guild_id,contract_id,event_key,event_type,actor_id,target_ref,delta,payload_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        guild_id, int(contract_id), event_key, str(event_type), int(actor_id), target_ref, delta,
                        json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")), now,
                    ),
                )
                remaining_delta = delta
                for objective_id, required_value, current_value in objectives:
                    if remaining_delta <= 0:
                        break
                    required = int(required_value)
                    current = int(current_value)
                    applied = min(remaining_delta, max(0, required - current))
                    new_value = current + applied
                    new_status = "completed" if new_value >= required else "pending"
                    await conn.execute(
                        """UPDATE contract_objectives SET current_value=?,status=?,updated_at=?
                           WHERE objective_id=? AND status='pending'""",
                        (new_value, new_status, now, int(objective_id)),
                    )
                    remaining_delta -= applied
                await self._history_tx(
                    conn, guild_id, contract_id, event_key=f"domain:{event_key}", event_type="progress",
                    actor_id=actor_id, metadata={"event_type": event_type, "target_ref": target_ref, "delta": delta}, now=now,
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        return True

    async def record_city_delivery(self, guild_id: int, contract_id: int, actor_id: int, *, event_key: str, route_key: str) -> bool:
        return await self._record_verified_event(
            guild_id, contract_id, actor_id, event_key=event_key,
            event_type="city_delivery_completed", target_ref=route_key,
        )

    async def record_matching_domain_event(
        self,
        guild_id: int,
        actor_id: int,
        *,
        event_key: str,
        event_type: str,
        target_ref: str,
        delta: int = 1,
        payload: dict[str, Any] | None = None,
    ) -> ContractDomainEventResult | None:
        """Apply one owning-domain event to at most one active contract.

        The stable event key is globally claimed per guild, so the same travel,
        transfer or service event can never progress two different contracts.
        """
        objective_type = cfg.EVENT_TO_OBJECTIVE.get(str(event_type))
        if objective_type is None:
            raise ValueError("Nem támogatott contract domain event.")
        now = self._now_iso()
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT contract_id FROM contract_event_claims WHERE guild_id=? AND event_key=?",
                (guild_id, str(event_key)[:190]),
            )
            claimed = await cur.fetchone()
            if claimed is not None:
                snapshot = await self.get_contract(guild_id, int(claimed[0]))
                if snapshot is None:
                    return None
                return ContractDomainEventResult(snapshot, progressed=False, settled=snapshot.status == "settled", replay=True)
            cur = await conn.execute(
                """SELECT c.contract_id
                   FROM contracts c
                   JOIN contract_objectives o ON o.contract_id=c.contract_id AND o.guild_id=c.guild_id
                   WHERE c.guild_id=? AND c.assignee_id=? AND c.status='active'
                     AND c.expires_at>? AND o.status='pending' AND o.objective_type=? AND o.target_ref=?
                   ORDER BY c.accepted_at,c.contract_id,o.objective_id LIMIT 1""",
                (guild_id, int(actor_id), now, objective_type, str(target_ref).strip().lower()),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        contract_id = int(row[0])
        progressed = await self._record_verified_event(
            guild_id, contract_id, actor_id, event_key=str(event_key), event_type=event_type,
            target_ref=target_ref, delta=delta, payload=payload,
        )
        if not progressed:
            async with aiosqlite.connect(self.db.path) as conn:
                cur = await conn.execute(
                    "SELECT contract_id FROM contract_event_claims WHERE guild_id=? AND event_key=?",
                    (guild_id, str(event_key)[:190]),
                )
                claimed = await cur.fetchone()
            if claimed is None:
                return None
            snapshot = await self.get_contract(guild_id, int(claimed[0]))
            if snapshot is None:
                return None
            return ContractDomainEventResult(
                snapshot, progressed=False, settled=snapshot.status == "settled", replay=True
            )
        snapshot, paid = await self.settle_if_ready(guild_id, contract_id)
        return ContractDomainEventResult(snapshot, progressed=True, settled=paid or snapshot.status == "settled")

    async def record_matching_city_delivery(
        self, guild_id: int, actor_id: int, *, travel_id: int, from_city_key: str, to_city_key: str
    ) -> ContractDomainEventResult | None:
        return await self.record_matching_domain_event(
            guild_id, actor_id, event_key=f"travel:{int(travel_id)}", event_type="city_delivery_completed",
            target_ref=f"{str(from_city_key).lower()}:{str(to_city_key).lower()}",
            payload={"travel_id": int(travel_id), "from": str(from_city_key), "to": str(to_city_key)},
        )
