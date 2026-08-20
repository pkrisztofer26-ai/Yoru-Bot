from __future__ import annotations
from app.services.contracts_projection_support import *

class ContractServiceMixin7:
        async def reconcile_reward_budgets(self, guild_id: int, *, repair: bool = True) -> dict[str, int]:
            """Audit/reconcile NPC reward-budget aggregates from canonical contracts.

            ``reserved_amount`` is exact live liability and can therefore be
            repaired to the sum of held system contracts. ``spent_amount`` is a
            monotonic audit counter: recovery may raise it to the canonical settled
            sum but never lowers a larger historical value.
            """
            now = self._now_iso()
            checked = repaired = violations = 0
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    cur = await conn.execute(
                        """SELECT s.budget_key,s.budget_period,
                                  SUM(CASE WHEN c.status IN ('open','active') AND c.escrow_state='held'
                                           THEN c.reward_amount ELSE 0 END) AS expected_reserved,
                                  SUM(CASE WHEN c.status='settled' AND c.escrow_state='released'
                                           THEN c.reward_amount ELSE 0 END) AS expected_spent
                           FROM contract_source_state s
                           JOIN contracts c ON c.guild_id=s.guild_id AND c.contract_id=s.contract_id
                           WHERE s.guild_id=? AND s.budget_key<>'' AND s.budget_period<>''
                           GROUP BY s.budget_key,s.budget_period""",
                        (int(guild_id),),
                    )
                    expected_rows = {
                        (str(row[0]), str(row[1])): (int(row[2] or 0), int(row[3] or 0))
                        for row in await cur.fetchall()
                    }
                    cur = await conn.execute(
                        """SELECT budget_key,period_key,limit_amount,reserved_amount,spent_amount
                           FROM contract_reward_budgets WHERE guild_id=?""",
                        (int(guild_id),),
                    )
                    stored_rows = {
                        (str(row[0]), str(row[1])): (int(row[2]), int(row[3]), int(row[4]))
                        for row in await cur.fetchall()
                    }
                    keys = set(expected_rows) | set(stored_rows)
                    for key in sorted(keys):
                        checked += 1
                        budget_key, period = key
                        expected_reserved, expected_spent = expected_rows.get(key, (0, 0))
                        stored = stored_rows.get(key)
                        if stored is None:
                            limits = [
                                int(source.budget_daily_limit) for source in cfg.SOURCE_DEFINITIONS
                                if source.budget_key == budget_key
                            ]
                            limit_amount = max(limits, default=expected_reserved + expected_spent)
                            current_reserved = current_spent = 0
                        else:
                            limit_amount, current_reserved, current_spent = stored
                        target_reserved = expected_reserved
                        target_spent = max(current_spent, expected_spent)
                        if target_reserved + target_spent > limit_amount:
                            violations += 1
                            # Never hide an over-limit historical condition by
                            # shrinking liabilities or spent audit state.
                            continue
                        if current_reserved == target_reserved and current_spent == target_spent and stored is not None:
                            continue
                        if repair:
                            await conn.execute(
                                """INSERT INTO contract_reward_budgets(
                                       guild_id,budget_key,period_key,limit_amount,reserved_amount,spent_amount,updated_at
                                   ) VALUES(?,?,?,?,?,?,?)
                                   ON CONFLICT(guild_id,budget_key,period_key) DO UPDATE SET
                                       reserved_amount=excluded.reserved_amount,
                                       spent_amount=MAX(spent_amount,excluded.spent_amount),
                                       updated_at=excluded.updated_at""",
                                (
                                    int(guild_id), budget_key, period, int(limit_amount),
                                    int(target_reserved), int(target_spent), now,
                                ),
                            )
                            repaired += 1
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise
            return {"checked": checked, "repaired": repaired, "violations": violations}

        async def telemetry_summary(self, guild_id: int, *, days: int = 7) -> dict[str, int]:
            """Return bounded aggregate audit counts; never raw player-facing scores."""
            safe_days = max(1, min(int(days), cfg.CONTRACT_TELEMETRY_RETENTION_DAYS))
            cutoff = (datetime.now(timezone.utc) - timedelta(days=safe_days)).isoformat()
            async with aiosqlite.connect(self.db.path) as conn:
                cur = await conn.execute(
                    """SELECT event_type,COUNT(*) FROM contract_telemetry
                       WHERE guild_id=? AND created_at>=? GROUP BY event_type""",
                    (int(guild_id), cutoff),
                )
                return {str(row[0]): int(row[1]) for row in await cur.fetchall()}

        async def prune_telemetry(self, guild_id: int) -> int:
            """Apply retention + hard row cap to audit-only contract telemetry."""
            cutoff = (datetime.now(timezone.utc) - timedelta(days=cfg.CONTRACT_TELEMETRY_RETENTION_DAYS)).isoformat()
            deleted = 0
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    cur = await conn.execute(
                        "DELETE FROM contract_telemetry WHERE guild_id=? AND created_at<?",
                        (int(guild_id), cutoff),
                    )
                    deleted += max(0, int(cur.rowcount))
                    cur = await conn.execute(
                        "SELECT COUNT(*) FROM contract_telemetry WHERE guild_id=?", (int(guild_id),)
                    )
                    count = int((await cur.fetchone())[0])
                    excess = max(0, count - cfg.CONTRACT_TELEMETRY_MAX_ROWS_PER_GUILD)
                    if excess:
                        cur = await conn.execute(
                            """SELECT telemetry_id FROM contract_telemetry
                               WHERE guild_id=? ORDER BY telemetry_id ASC LIMIT ?""",
                            (int(guild_id), int(excess)),
                        )
                        ids = [int(row[0]) for row in await cur.fetchall()]
                        if ids:
                            # IDs come from our own SELECT, so bounded placeholder
                            # expansion is safe and backend-neutral.
                            placeholders = ",".join("?" for _ in ids)
                            cur = await conn.execute(
                                f"DELETE FROM contract_telemetry WHERE guild_id=? AND telemetry_id IN ({placeholders})",
                                (int(guild_id), *ids),
                            )
                            deleted += max(0, int(cur.rowcount))
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise
            return deleted

        async def recover_restart_state(self, guild_id: int) -> ContractRecoveryReport:
            """Idempotent startup recovery for Phase 4 contract state."""
            before = await self.reconcile_reward_budgets(guild_id, repair=True)
            settled = await self.recover_ready_contracts(guild_id)
            expired = await self.expire_due(guild_id)
            after = await self.reconcile_reward_budgets(guild_id, repair=True)
            pruned = await self.prune_telemetry(guild_id)
            return ContractRecoveryReport(
                ready_settled=settled,
                expired=expired,
                budget_rows_checked=max(int(before["checked"]), int(after["checked"])),
                budget_rows_repaired=int(before["repaired"]) + int(after["repaired"]),
                telemetry_pruned=pruned,
            )

        async def maintain_contracts(self, guild_id: int) -> ContractRecoveryReport:
            """Cheap periodic maintenance; full budget reconciliation is startup-only."""
            settled = await self.recover_ready_contracts(guild_id)
            expired = await self.expire_due(guild_id)
            pruned = await self.prune_telemetry(guild_id)
            return ContractRecoveryReport(ready_settled=settled, expired=expired, telemetry_pruned=pruned)

        async def cancel_open_contract(self, guild_id: int, contract_id: int, creator_id: int) -> int:
            now = self._now_iso()
            reward = 0
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    cur = await conn.execute(
                        """SELECT creator_id,status,escrow_state,escrow_wallet_amount,escrow_bank_amount,reward_amount
                           FROM contracts WHERE guild_id=? AND contract_id=?""",
                        (guild_id, int(contract_id)),
                    )
                    row = await cur.fetchone()
                    if row is None or row[0] is None or int(row[0]) != int(creator_id):
                        raise ValueError("Ezt a megbízást nem te kezelheted.")
                    if str(row[1]) != "open" or str(row[2]) != "held":
                        raise ValueError("Csak még el nem vállalt megbízás vonható vissza.")
                    await self.db.refund_wallet_and_bank_tx(
                        conn, guild_id, creator_id, int(row[3]), int(row[4]),
                        reason=f"contract_refund_cancelled:{int(contract_id)}", now=now,
                    )
                    await conn.execute(
                        """UPDATE contracts SET status='cancelled',escrow_state='refunded',resolved_at=?
                           WHERE guild_id=? AND contract_id=? AND status='open' AND escrow_state='held'""",
                        (now, guild_id, int(contract_id)),
                    )
                    reward = int(row[5])
                    await self._history_tx(
                        conn, guild_id, contract_id, event_key="cancelled", event_type="cancelled",
                        actor_id=creator_id, metadata={"refund": reward}, now=now,
                    )
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise
            await self._stat_add(guild_id, creator_id, "contract.cancelled")
            return reward

