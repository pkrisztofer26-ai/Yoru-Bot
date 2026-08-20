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

class ContractsSettleMixin:

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

    async def settle_ready_contract(self, guild_id: int, contract_id: int) -> tuple[ContractSnapshot, bool]:
        now = self._now_iso()
        creator_id: int | None = None
        assignee_id: int | None = None
        title = ""
        reward_amount = 0
        source_type = ""
        source_key = ""
        accepted_at: str | None = None
        budget_key = ""
        budget_period = ""
        rapid_completion = False
        repeated_pair = False
        high_value = False
        paid = False
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cur = await conn.execute(
                    """SELECT creator_id,assignee_id,reward_amount,status,escrow_state,title,source_type,accepted_at,source_ref
                       FROM contracts WHERE guild_id=? AND contract_id=?""",
                    (guild_id, int(contract_id)),
                )
                row = await cur.fetchone()
                if row is None:
                    raise ValueError("Nincs ilyen megbízás.")
                creator_id = int(row[0]) if row[0] is not None else None
                assignee_id = int(row[1]) if row[1] is not None else None
                reward_amount, status, escrow_state, title, source_type = int(row[2]), str(row[3]), str(row[4]), str(row[5]), str(row[6])
                accepted_at = str(row[7]) if row[7] is not None else None
                source_key = str(row[8] or "player_board")
                high_value = reward_amount >= cfg.CONTRACT_HIGH_VALUE_THRESHOLD
                if status == "settled":
                    await conn.rollback()
                    snapshot = await self.get_contract(guild_id, contract_id)
                    if snapshot is None:
                        raise RuntimeError("A lezárt megbízás nem olvasható vissza.")
                    return snapshot, False
                if status != "active" or assignee_id is None or escrow_state != "held":
                    raise ValueError("Ez a megbízás még nem zárható le.")
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM contract_objectives WHERE guild_id=? AND contract_id=? AND status<>'completed'",
                    (guild_id, int(contract_id)),
                )
                if int((await cur.fetchone())[0]) != 0:
                    raise ValueError("A megbízás objective-jei még nincsenek teljesítve.")
                if creator_id is None:
                    cur = await conn.execute(
                        """SELECT budget_key,budget_period,source_key FROM contract_source_state
                           WHERE guild_id=? AND contract_id=?""",
                        (guild_id, int(contract_id)),
                    )
                    source_row = await cur.fetchone()
                    if source_row is None or not source_row[0] or not source_row[1]:
                        raise RuntimeError("A Yoru-funded megbízás reward-budget forrása hiányzik.")
                    budget_key, period = str(source_row[0]), str(source_row[1])
                    budget_period = period
                    source_key = str(source_row[2] or source_key)
                    cur = await conn.execute(
                        """UPDATE contract_reward_budgets
                           SET reserved_amount=reserved_amount-?,spent_amount=spent_amount+?,updated_at=?
                           WHERE guild_id=? AND budget_key=? AND period_key=? AND reserved_amount>=?""",
                        (reward_amount, reward_amount, now, guild_id, budget_key, period, reward_amount),
                    )
                    if not cur.rowcount:
                        raise RuntimeError("A Yoru-funded megbízás reward-budget reservationje nem érvényes.")
                elif source_type != "player":
                    raise RuntimeError("Nem támogatott contract settlement source.")
                await self.db.credit_wallet_tx(
                    conn, guild_id, assignee_id, reward_amount, reason=f"contract_settlement:{int(contract_id)}", now=now,
                )
                cur = await conn.execute(
                    """UPDATE contracts SET status='settled',escrow_state='released',resolved_at=?
                       WHERE guild_id=? AND contract_id=? AND status='active' AND escrow_state='held'""",
                    (now, guild_id, int(contract_id)),
                )
                if not cur.rowcount:
                    raise RuntimeError("A megbízás settlement race miatt nem zárható le.")
                await self._history_tx(
                    conn, guild_id, contract_id, event_key="settled", event_type="settled", actor_id=assignee_id,
                    metadata={"reward_amount": reward_amount, "reward_source": "player_escrow" if creator_id is not None else "yoru_budget"}, now=now,
                )
                if accepted_at:
                    try:
                        accepted_dt = datetime.fromisoformat(accepted_at)
                        if accepted_dt.tzinfo is None:
                            accepted_dt = accepted_dt.replace(tzinfo=timezone.utc)
                        rapid_completion = (datetime.fromisoformat(now) - accepted_dt.astimezone(timezone.utc)).total_seconds() <= cfg.CONTRACT_RAPID_COMPLETION_SECONDS
                    except ValueError:
                        rapid_completion = False
                if creator_id is not None:
                    pair_cutoff = (datetime.now(timezone.utc) - timedelta(days=cfg.CONTRACT_REPEATED_PAIR_DAYS)).isoformat()
                    cur = await conn.execute(
                        """SELECT COUNT(*) FROM contracts
                           WHERE guild_id=? AND status='settled' AND resolved_at>=? AND (
                               (creator_id=? AND assignee_id=?) OR (creator_id=? AND assignee_id=?)
                           )""",
                        (guild_id, pair_cutoff, creator_id, assignee_id, assignee_id, creator_id),
                    )
                    repeated_pair = int((await cur.fetchone())[0]) >= cfg.CONTRACT_REPEATED_PAIR_THRESHOLD
                await self._telemetry_tx(
                    conn, guild_id, event_key=f"settled:{contract_id}", event_type="settled",
                    contract_id=contract_id, actor_id=assignee_id, counterparty_id=creator_id,
                    source_key=source_key, reward_amount=reward_amount, details={
                        "source_type": source_type,
                        "reward_source": "player_escrow" if creator_id is not None else "yoru_budget",
                    }, now=now,
                )
                if creator_id is None and budget_key and budget_period:
                    cur = await conn.execute(
                        """SELECT reserved_amount,spent_amount,limit_amount FROM contract_reward_budgets
                           WHERE guild_id=? AND budget_key=? AND period_key=?""",
                        (guild_id, budget_key, budget_period),
                    )
                    budget_row = await cur.fetchone()
                    await self._telemetry_tx(
                        conn, guild_id, event_key=f"budget_spent:{contract_id}", event_type="reward_budget",
                        contract_id=contract_id, actor_id=assignee_id, source_key=source_key, reward_amount=reward_amount,
                        details={
                            "action": "spent", "budget_key": budget_key, "budget_period": budget_period,
                            "reserved_after": int(budget_row[0]) if budget_row else None,
                            "spent_after": int(budget_row[1]) if budget_row else None,
                            "limit_amount": int(budget_row[2]) if budget_row else None,
                        }, now=now,
                    )
                if rapid_completion:
                    await self._telemetry_tx(
                        conn, guild_id, event_key=f"rapid_completion:{contract_id}", event_type="rapid_completion",
                        contract_id=contract_id, actor_id=assignee_id, counterparty_id=creator_id,
                        source_key=source_key, reward_amount=reward_amount,
                        details={"threshold_seconds": cfg.CONTRACT_RAPID_COMPLETION_SECONDS, "accepted_at": accepted_at}, now=now,
                    )
                if repeated_pair and creator_id is not None:
                    await self._telemetry_tx(
                        conn, guild_id, event_key=f"repeated_pair:{contract_id}:{creator_id}:{assignee_id}", event_type="repeated_pair",
                        contract_id=contract_id, actor_id=assignee_id, counterparty_id=creator_id,
                        source_key=source_key, reward_amount=reward_amount, details={
                            "window_days": cfg.CONTRACT_REPEATED_PAIR_DAYS,
                            "threshold": cfg.CONTRACT_REPEATED_PAIR_THRESHOLD,
                        }, now=now,
                    )
                if high_value:
                    await self._telemetry_tx(
                        conn, guild_id, event_key=f"high_value_settled:{contract_id}", event_type="high_value",
                        contract_id=contract_id, actor_id=assignee_id, counterparty_id=creator_id,
                        source_key=source_key, reward_amount=reward_amount, details={"stage": "settled"}, now=now,
                    )
                await conn.commit()
                paid = True
            except Exception:
                await conn.rollback()
                raise
        snapshot = await self.get_contract(guild_id, contract_id)
        if snapshot is None:
            raise RuntimeError("A lezárt megbízás nem olvasható vissza.")
        if paid:
            await self._stat_add(guild_id, assignee_id, "contract.settled")
            if rapid_completion:
                await self._stat_add(guild_id, assignee_id, "contract.rapid_completion")
            if repeated_pair:
                await self._stat_add(guild_id, assignee_id, "contract.repeated_pair")
                if creator_id is not None:
                    await self._stat_add(guild_id, creator_id, "contract.repeated_pair")
            if high_value:
                await self._stat_add(guild_id, assignee_id, "contract.high_value")
            await self._notify(
                guild_id, assignee_id, contract_id=contract_id, event_key="settled.assignee",
                title="✅ Megbízás teljesítve",
                body=f"A **{title}** megbízás lezárult, a díj jóváíródott: **{reward_amount:,}**.".replace(",", " "),
                important=True,
            )
            if creator_id is not None:
                await self._notify(
                    guild_id, creator_id, contract_id=contract_id, event_key="settled.creator",
                    title="✅ A megbízásod teljesült",
                    body=f"A **{title}** megbízás teljesült, a letétből a díj kifizetésre került.", important=True,
                )
        return snapshot, paid

    async def recover_ready_contracts(self, guild_id: int) -> int:
        """Settle verified-complete contracts left between event commit and payout.

        Domain verification and payout intentionally live in separate
        transactions. A process stop between them must not turn a legitimate
        pre-deadline completion into an expiry/refund. Only contracts whose
        every objective is complete and whose last objective update happened
        no later than the contract deadline are eligible for recovery.
        """
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                """SELECT c.contract_id
                   FROM contracts c
                   WHERE c.guild_id=? AND c.status='active' AND c.escrow_state='held'
                     AND NOT EXISTS (
                         SELECT 1 FROM contract_objectives o
                         WHERE o.guild_id=c.guild_id AND o.contract_id=c.contract_id AND o.status<>'completed'
                     )
                     AND EXISTS (
                         SELECT 1 FROM contract_objectives o
                         WHERE o.guild_id=c.guild_id AND o.contract_id=c.contract_id
                     )
                     AND COALESCE((
                         SELECT MAX(o.updated_at) FROM contract_objectives o
                         WHERE o.guild_id=c.guild_id AND o.contract_id=c.contract_id
                     ), c.created_at) <= c.expires_at
                   ORDER BY c.contract_id""",
                (int(guild_id),),
            )
            contract_ids = [int(row[0]) for row in await cur.fetchall()]
        settled = 0
        for contract_id in contract_ids:
            try:
                _snapshot, paid = await self.settle_ready_contract(guild_id, contract_id)
                settled += int(bool(paid))
            except ValueError:
                snap = await self.get_contract(guild_id, contract_id)
                if snap is None or snap.status not in cfg.TERMINAL_STATUSES:
                    raise
        return settled
