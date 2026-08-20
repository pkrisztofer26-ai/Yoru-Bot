from __future__ import annotations
from app.services.contracts_projection_support import *

class ContractServiceMixin8:
        async def expire_due(self, guild_id: int) -> int:
            now = self._now_iso()
            expired: list[tuple[int, int | None, int | None, str]] = []
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    cur = await conn.execute(
                        """SELECT c.contract_id,c.creator_id,c.assignee_id,c.escrow_wallet_amount,c.escrow_bank_amount,c.title,
                                  c.reward_amount,s.budget_key,s.budget_period,s.source_key
                           FROM contracts c LEFT JOIN contract_source_state s ON s.contract_id=c.contract_id AND s.guild_id=c.guild_id
                           WHERE c.guild_id=? AND c.status IN ('open','active') AND c.escrow_state='held' AND c.expires_at<=?
                             AND EXISTS (
                                 SELECT 1 FROM contract_objectives o
                                 WHERE o.guild_id=c.guild_id AND o.contract_id=c.contract_id AND o.status<>'completed'
                             )""",
                        (guild_id, now),
                    )
                    rows = await cur.fetchall()
                    for contract_id, creator_id, assignee_id, wallet_amount, bank_amount, title, reward, budget_key, budget_period, source_key in rows:
                        if creator_id is not None:
                            await self.db.refund_wallet_and_bank_tx(
                                conn, guild_id, int(creator_id), int(wallet_amount), int(bank_amount),
                                reason=f"contract_refund_expired:{int(contract_id)}", now=now,
                            )
                        elif budget_key and budget_period:
                            cur2 = await conn.execute(
                                """UPDATE contract_reward_budgets SET reserved_amount=reserved_amount-?,updated_at=?
                                   WHERE guild_id=? AND budget_key=? AND period_key=? AND reserved_amount>=?""",
                                (int(reward), now, guild_id, str(budget_key), str(budget_period), int(reward)),
                            )
                            if not cur2.rowcount:
                                raise RuntimeError("Lejárt Yoru contract reward-budget reservationje sérült.")
                            await self._telemetry_tx(
                                conn, guild_id, event_key=f"budget_released:{int(contract_id)}", event_type="reward_budget",
                                contract_id=int(contract_id), source_key=str(source_key or ""),
                                reward_amount=int(reward), details={
                                    "action": "released_expiry", "budget_key": str(budget_key), "budget_period": str(budget_period),
                                }, now=now,
                            )
                        await conn.execute(
                            """UPDATE contracts SET status='expired',escrow_state='refunded',resolved_at=?
                               WHERE guild_id=? AND contract_id=? AND status IN ('open','active') AND escrow_state='held'""",
                            (now, guild_id, int(contract_id)),
                        )
                        await self._history_tx(
                            conn, guild_id, int(contract_id), event_key="expired", event_type="expired", actor_id=None, metadata={}, now=now,
                        )
                        expired.append((int(contract_id), int(creator_id) if creator_id is not None else None,
                                        int(assignee_id) if assignee_id is not None else None, str(title)))
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise
            for contract_id, creator_id, assignee_id, title in expired:
                if creator_id is not None:
                    await self._notify(
                        guild_id, creator_id, contract_id=contract_id, event_key="expired.creator",
                        title="⌛ Lejárt a megbízásod", body=f"A **{title}** megbízás lejárt, a letét visszakerült hozzád.",
                    )
                if assignee_id is not None:
                    await self._notify(
                        guild_id, assignee_id, contract_id=contract_id, event_key="expired.assignee",
                        title="⌛ Lejárt egy vállalt megbízás", body=f"A **{title}** megbízás határideje lejárt.",
                    )
            return len(expired)

