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

class ContractsCreateMixin:

    async def create_system_contract(
        self,
        guild_id: int,
        *,
        source: cfg.ContractSourceDefinition,
        target_user_id: int = 0,
        objectives: Iterable[ObjectiveSpec],
        period_key: str | None = None,
    ) -> ContractSnapshot:
        if source.source_type not in cfg.SYSTEM_SOURCE_TYPES:
            raise ValueError("Nem támogatott Yoru contract source.")
        if source.budget_key not in cfg.SYSTEM_BUDGET_KEYS:
            raise ValueError("Ismeretlen contract reward budget.")
        target_user_id = max(0, int(target_user_id))
        if source.source_type == "private" and target_user_id <= 0:
            raise ValueError("A privát megbízásnak konkrét címzett kell.")
        period = str(period_key or self._budget_period())[:32]
        specs = self._normalize_specs(objectives)
        modifier_effect = cfg.modifier_effect(source.modifiers, tuple(spec.objective_type for spec in specs))
        if modifier_effect.required_multiplier_bp != 10_000:
            specs = tuple(
                ObjectiveSpec(
                    key=spec.key, objective_type=spec.objective_type, target_ref=spec.target_ref,
                    required_value=max(1, (int(spec.required_value) * modifier_effect.required_multiplier_bp + 9_999) // 10_000),
                    metadata=spec.metadata,
                )
                for spec in specs
            )
        reward = max(1, int(source.reward_amount) * modifier_effect.reward_multiplier_bp // 10_000)
        deadline_hours = max(1, int(source.deadline_hours) * modifier_effect.deadline_multiplier_bp // 10_000)
        now = self._now_iso()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=deadline_hours)).isoformat()
        eligibility: dict[str, Any] = {}
        if source.required_trust_bands:
            if not source.npc_key:
                raise ValueError("Relationship eligibilityhez NPC source szükséges.")
            eligibility = {
                "subject_type": "npc",
                "subject_key": str(source.npc_key),
                "required_trust_bands": list(source.required_trust_bands),
            }
        if target_user_id and not await self._source_requirements_eligible(
            guild_id, target_user_id, {"eligibility": eligibility}
        ):
            raise ValueError("Ez a privát megbízás jelenleg nem elérhető számodra.")
        source_ref = f"{source.key}:{period}:{target_user_id}"[:64]
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cur = await conn.execute(
                    """SELECT contract_id FROM contract_source_state
                       WHERE guild_id=? AND source_key=? AND budget_period=? AND target_user_id=? LIMIT 1""",
                    (guild_id, source.key, period, target_user_id),
                )
                existing = await cur.fetchone()
                if existing is not None:
                    await conn.rollback()
                    snap = await self.get_contract(guild_id, int(existing[0]))
                    if snap is None:
                        raise RuntimeError("A freelance source cycle sérült.")
                    return snap
                cur = await conn.execute(
                    """SELECT limit_amount,reserved_amount,spent_amount FROM contract_reward_budgets
                       WHERE guild_id=? AND budget_key=? AND period_key=?""",
                    (guild_id, source.budget_key, period),
                )
                row = await cur.fetchone()
                if row is None:
                    limit_amount = int(source.budget_daily_limit)
                    reserved = spent = 0
                    await conn.execute(
                        """INSERT INTO contract_reward_budgets(
                               guild_id,budget_key,period_key,limit_amount,reserved_amount,spent_amount,updated_at
                           ) VALUES(?,?,?,?,0,0,?)""",
                        (guild_id, source.budget_key, period, limit_amount, now),
                    )
                else:
                    limit_amount, reserved, spent = int(row[0]), int(row[1]), int(row[2])
                    if limit_amount != int(source.budget_daily_limit):
                        limit_amount = min(limit_amount, int(source.budget_daily_limit))
                if reserved + spent + reward > limit_amount:
                    raise ValueError("A Yoru freelance napi kerete erre a forrásra elfogyott.")
                cur = await conn.execute(
                    """INSERT INTO contracts(
                           guild_id,source_type,source_ref,creator_id,assignee_id,title,reward_amount,
                           escrow_state,escrow_wallet_amount,escrow_bank_amount,status,created_at,expires_at
                       ) VALUES(?,?,?,NULL,NULL,?,?,'held',0,0,'open',?,?)""",
                    (guild_id, source.source_type, source_ref, source.title, reward, now, expires_at),
                )
                contract_id = int(cur.lastrowid)
                await conn.execute(
                    """INSERT INTO contract_source_state(
                           contract_id,guild_id,source_key,source_label,target_user_id,budget_key,budget_period,
                           eligibility_json,modifier_json,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (contract_id, guild_id, source.key, source.label, target_user_id, source.budget_key, period,
                     json.dumps(eligibility, ensure_ascii=False, separators=(",", ":")),
                     json.dumps(list(modifier_effect.keys), ensure_ascii=False, separators=(",", ":")), now),
                )
                await conn.execute(
                    """UPDATE contract_reward_budgets SET reserved_amount=reserved_amount+?,updated_at=?
                       WHERE guild_id=? AND budget_key=? AND period_key=?""",
                    (reward, now, guild_id, source.budget_key, period),
                )
                for spec in specs:
                    await conn.execute(
                        """INSERT INTO contract_objectives(
                               contract_id,guild_id,objective_key,objective_type,target_ref,required_value,
                               current_value,status,verification_mode,metadata_json,created_at,updated_at
                           ) VALUES(?,?,?,?,?,?,0,'pending','domain_event',?,?,?)""",
                        (contract_id, guild_id, spec.key, spec.objective_type, spec.target_ref, spec.required_value,
                         json.dumps(spec.metadata or {}, ensure_ascii=False, separators=(",", ":")), now, now),
                    )
                await self._history_tx(
                    conn, guild_id, contract_id, event_key="source_created", event_type="created", actor_id=None,
                    metadata={
                        "source": source.key, "reward_budget": source.budget_key, "period": period,
                        "modifiers": list(modifier_effect.keys), "base_reward": int(source.reward_amount),
                        "final_reward": reward, "deadline_hours": deadline_hours,
                    }, now=now,
                )
                await self._telemetry_tx(
                    conn, guild_id, event_key=f"source_created:{contract_id}", event_type="source_created",
                    contract_id=contract_id, actor_id=(target_user_id or None), source_key=source.key,
                    reward_amount=reward, details={
                        "budget_key": source.budget_key, "budget_period": period,
                        "modifiers": list(modifier_effect.keys), "reserved_before": reserved, "spent_before": spent,
                    }, now=now,
                )
                if reward >= cfg.CONTRACT_HIGH_VALUE_THRESHOLD:
                    await self._telemetry_tx(
                        conn, guild_id, event_key=f"high_value_created:{contract_id}", event_type="high_value",
                        contract_id=contract_id, actor_id=(target_user_id or None), source_key=source.key,
                        reward_amount=reward, details={"stage": "created", "source_type": source.source_type}, now=now,
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        snapshot = await self.get_contract(guild_id, contract_id)
        if snapshot is None:
            raise RuntimeError("A Yoru freelance megbízás nem olvasható vissza.")
        return snapshot

    async def create_player_contract(
        self,
        guild_id: int,
        creator_id: int,
        *,
        title: str,
        reward_amount: int,
        expires_at: str,
        objectives: Iterable[ObjectiveSpec],
        source_ref: str = "player_board",
    ) -> ContractSnapshot:
        title = " ".join(str(title).split()).strip()
        if not title or len(title) > 120:
            raise ValueError("A megbízás címe 1–120 karakter lehet.")
        reward_amount = int(reward_amount)
        if reward_amount < cfg.PLAYER_MIN_REWARD:
            raise ValueError(f"A megbízási díj legalább {cfg.PLAYER_MIN_REWARD:,} legyen.".replace(",", " "))
        if reward_amount > cfg.PLAYER_MAX_REWARD:
            raise ValueError(f"A megbízási díj legfeljebb {cfg.PLAYER_MAX_REWARD:,} lehet.".replace(",", " "))
        expires_at = self._validate_iso_future(expires_at)
        specs = self._normalize_specs(objectives)
        now = self._now_iso()
        recent_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cur = await conn.execute(
                    """SELECT COUNT(*) FROM contracts
                       WHERE guild_id=? AND creator_id=? AND source_type='player' AND status IN ('open','active')""",
                    (guild_id, creator_id),
                )
                if int((await cur.fetchone())[0]) >= cfg.PLAYER_MAX_ACTIVE_CREATED:
                    raise ValueError(f"Egyszerre legfeljebb {cfg.PLAYER_MAX_ACTIVE_CREATED} aktív megbízásod lehet.")
                cur = await conn.execute(
                    """SELECT COUNT(*) FROM contracts
                       WHERE guild_id=? AND creator_id=? AND source_type='player' AND created_at>=?""",
                    (guild_id, creator_id, recent_cutoff),
                )
                if int((await cur.fetchone())[0]) >= cfg.PLAYER_MAX_CREATES_24H:
                    raise ValueError("Túl sok megbízást adtál fel rövid idő alatt. Próbáld meg később.")

                cur = await conn.execute(
                    """INSERT INTO contracts(
                           guild_id,source_type,source_ref,creator_id,assignee_id,title,reward_amount,
                           escrow_state,escrow_wallet_amount,escrow_bank_amount,status,created_at,expires_at
                       ) VALUES(?,?,?, ?,NULL,?,?, 'held',0,0,'open',?,?)""",
                    (guild_id, "player", str(source_ref)[:64], creator_id, title, reward_amount, now, expires_at),
                )
                contract_id = int(cur.lastrowid)
                wallet_used, bank_used, _new_wallet, _new_bank = await self.db.reserve_wallet_and_bank_tx(
                    conn, guild_id, creator_id, reward_amount,
                    reason=f"contract_escrow:{contract_id}", now=now,
                )
                await conn.execute(
                    "UPDATE contracts SET escrow_wallet_amount=?,escrow_bank_amount=? WHERE contract_id=?",
                    (wallet_used, bank_used, contract_id),
                )
                for spec in specs:
                    await conn.execute(
                        """INSERT INTO contract_objectives(
                               contract_id,guild_id,objective_key,objective_type,target_ref,required_value,
                               current_value,status,verification_mode,metadata_json,created_at,updated_at
                           ) VALUES(?,?,?,?,?,?,0,'pending','domain_event',?,?,?)""",
                        (
                            contract_id, guild_id, spec.key, spec.objective_type, spec.target_ref,
                            spec.required_value,
                            json.dumps(spec.metadata or {}, ensure_ascii=False, separators=(",", ":")),
                            now, now,
                        ),
                    )
                await self._history_tx(
                    conn, guild_id, contract_id, event_key="created", event_type="created", actor_id=creator_id,
                    metadata={"reward_amount": reward_amount, "source_ref": str(source_ref)[:64]}, now=now,
                )
                await self._telemetry_tx(
                    conn, guild_id, event_key=f"player_created:{contract_id}", event_type="source_created",
                    contract_id=contract_id, actor_id=creator_id, source_key=str(source_ref)[:64],
                    reward_amount=reward_amount, details={"source_type": "player"}, now=now,
                )
                if reward_amount >= cfg.CONTRACT_HIGH_VALUE_THRESHOLD:
                    await self._telemetry_tx(
                        conn, guild_id, event_key=f"high_value_created:{contract_id}", event_type="high_value",
                        contract_id=contract_id, actor_id=creator_id, source_key=str(source_ref)[:64],
                        reward_amount=reward_amount, details={"stage": "created", "source_type": "player"}, now=now,
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        await self._stat_add(guild_id, creator_id, "contract.created")
        snapshot = await self.get_contract(guild_id, contract_id)
        if snapshot is None:
            raise RuntimeError("A megbízás létrejött, de nem olvasható vissza.")
        return snapshot

    async def get_contract(self, guild_id: int, contract_id: int) -> ContractSnapshot | None:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                """SELECT contract_id,guild_id,source_type,creator_id,assignee_id,title,reward_amount,status,
                          escrow_state,created_at,expires_at,accepted_at,resolved_at,source_ref
                   FROM contracts WHERE guild_id=? AND contract_id=?""",
                (guild_id, int(contract_id)),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return ContractSnapshot(
            contract_id=int(row[0]), guild_id=int(row[1]), source_type=str(row[2]),
            creator_id=int(row[3]) if row[3] is not None else None,
            assignee_id=int(row[4]) if row[4] is not None else None,
            title=str(row[5]), reward_amount=int(row[6]), status=str(row[7]), escrow_state=str(row[8]),
            created_at=str(row[9]), expires_at=str(row[10]),
            accepted_at=str(row[11]) if row[11] is not None else None,
            resolved_at=str(row[12]) if row[12] is not None else None, source_ref=str(row[13] or ""),
        )
