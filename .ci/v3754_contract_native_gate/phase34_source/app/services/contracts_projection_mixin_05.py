from __future__ import annotations
from app.services.contracts_projection_support import *

class ContractServiceMixin5:
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
                # A concurrent/retried domain delivery may have claimed the stable
                # event after the optimistic lookup above. Follow the canonical
                # claim instead of attempting settlement on a stale candidate.
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

        async def settle_if_ready(self, guild_id: int, contract_id: int) -> tuple[ContractSnapshot, bool]:
            snapshot = await self.get_contract(guild_id, contract_id)
            if snapshot is None:
                raise ValueError("Nincs ilyen megbízás.")
            if snapshot.status == "settled":
                return snapshot, False
            if snapshot.status != "active":
                return snapshot, False
            async with aiosqlite.connect(self.db.path) as conn:
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM contract_objectives WHERE guild_id=? AND contract_id=? AND status<>'completed'",
                    (guild_id, int(contract_id)),
                )
                if int((await cur.fetchone())[0]) != 0:
                    return snapshot, False
            return await self.settle_ready_contract(guild_id, contract_id)

