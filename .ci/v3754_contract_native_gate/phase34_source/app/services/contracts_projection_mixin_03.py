from __future__ import annotations
from app.services.contracts_projection_support import *

class ContractServiceMixin3:
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

        async def objectives(self, guild_id: int, contract_id: int) -> list[dict[str, Any]]:
            async with aiosqlite.connect(self.db.path) as conn:
                conn.row_factory = aiosqlite.Row
                cur = await conn.execute(
                    """SELECT objective_id,objective_key,objective_type,target_ref,required_value,current_value,
                              status,verification_mode,metadata_json,updated_at
                       FROM contract_objectives WHERE guild_id=? AND contract_id=? ORDER BY objective_id""",
                    (guild_id, int(contract_id)),
                )
                rows = await cur.fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                try:
                    item["metadata"] = json.loads(str(item.pop("metadata_json") or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    item["metadata"] = {}
                result.append(item)
            return result

        async def history(self, guild_id: int, contract_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
            async with aiosqlite.connect(self.db.path) as conn:
                conn.row_factory = aiosqlite.Row
                cur = await conn.execute(
                    """SELECT history_id,event_key,event_type,actor_id,metadata_json,created_at
                       FROM contract_history WHERE guild_id=? AND contract_id=?
                       ORDER BY history_id DESC LIMIT ?""",
                    (guild_id, int(contract_id), max(1, min(50, int(limit)))),
                )
                rows = await cur.fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                try:
                    item["metadata"] = json.loads(str(item.pop("metadata_json") or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    item["metadata"] = {}
                result.append(item)
            return result

        async def list_open_contracts(self, guild_id: int, viewer_id: int, *, limit: int = 20) -> list[ContractSnapshot]:
            await self.expire_due(guild_id)
            await self.ensure_freelance_sources(guild_id, viewer_id)
            async with aiosqlite.connect(self.db.path) as conn:
                cur = await conn.execute(
                    """SELECT c.contract_id FROM contracts c
                       LEFT JOIN contract_source_state s ON s.contract_id=c.contract_id AND s.guild_id=c.guild_id
                       WHERE c.guild_id=? AND c.status='open' AND (
                           (c.source_type='player' AND c.creator_id<>?) OR
                           c.source_type='public' OR
                           (c.source_type='private' AND s.target_user_id=?)
                       )
                       ORDER BY CASE c.source_type WHEN 'private' THEN 0 WHEN 'public' THEN 1 ELSE 2 END,
                                c.created_at DESC,c.contract_id DESC LIMIT ?""",
                    (guild_id, int(viewer_id), int(viewer_id), max(1, min(25, int(limit)))),
                )
                ids = [int(row[0]) for row in await cur.fetchall()]
            rows: list[ContractSnapshot] = []
            for contract_id in ids:
                item = await self.get_contract(guild_id, contract_id)
                if item is not None:
                    rows.append(item)
            return rows

        async def list_service_contracts(
            self, guild_id: int, viewer_id: int, *, service_family: str | None = None, limit: int = 20
        ) -> list[ContractSnapshot]:
            """Discover open service work without introducing a parallel service backend."""
            await self.expire_due(guild_id)
            await self.ensure_freelance_sources(guild_id, viewer_id)
            wanted_type = None
            if service_family:
                normalized = str(service_family).strip().casefold()
                reverse = {label.casefold(): key for key, label in cfg.SERVICE_LABEL_BY_OBJECTIVE.items()}
                reverse.update({key.casefold(): key for key in cfg.SERVICE_LABEL_BY_OBJECTIVE})
                wanted_type = reverse.get(normalized)
                if wanted_type not in cfg.SERVICE_OBJECTIVE_TYPES:
                    raise ValueError("Ismeretlen szolgáltatási kategória.")
            service_types = sorted(cfg.SERVICE_OBJECTIVE_TYPES)
            placeholders = ",".join("?" for _ in service_types)
            params: list[Any] = [int(guild_id), int(viewer_id), int(viewer_id), *service_types]
            objective_clause = f"o.objective_type IN ({placeholders})"
            if wanted_type:
                objective_clause += " AND o.objective_type=?"
                params.append(wanted_type)
            params.append(max(1, min(25, int(limit))))
            async with aiosqlite.connect(self.db.path) as conn:
                cur = await conn.execute(
                    f"""SELECT c.contract_id
                        FROM contracts c
                        LEFT JOIN contract_source_state s ON s.contract_id=c.contract_id AND s.guild_id=c.guild_id
                        WHERE c.guild_id=? AND c.status='open' AND (
                            (c.source_type='player' AND c.creator_id<>?) OR
                            c.source_type='public' OR
                            (c.source_type='private' AND s.target_user_id=?)
                        ) AND EXISTS (
                            SELECT 1 FROM contract_objectives o
                            WHERE o.guild_id=c.guild_id AND o.contract_id=c.contract_id AND {objective_clause}
                        )
                        ORDER BY CASE c.source_type WHEN 'private' THEN 0 WHEN 'public' THEN 1 ELSE 2 END,
                                 c.created_at DESC,c.contract_id DESC LIMIT ?""",
                    tuple(params),
                )
                ids = [int(row[0]) for row in await cur.fetchall()]
            result: list[ContractSnapshot] = []
            for contract_id in ids:
                snapshot = await self.get_contract(guild_id, contract_id)
                if snapshot is not None:
                    result.append(snapshot)
            return result

        async def list_user_contracts(self, guild_id: int, user_id: int, *, limit: int = 25) -> list[ContractSnapshot]:
            await self.expire_due(guild_id)
            await self.ensure_freelance_sources(guild_id, user_id)
            async with aiosqlite.connect(self.db.path) as conn:
                cur = await conn.execute(
                    """SELECT c.contract_id FROM contracts c
                       LEFT JOIN contract_source_state s ON s.contract_id=c.contract_id AND s.guild_id=c.guild_id
                       WHERE c.guild_id=? AND (c.creator_id=? OR c.assignee_id=? OR
                             (c.source_type='private' AND c.status='open' AND s.target_user_id=?))
                       ORDER BY CASE c.status WHEN 'active' THEN 0 WHEN 'open' THEN 1 ELSE 2 END,
                                COALESCE(c.accepted_at,c.created_at) DESC,c.contract_id DESC LIMIT ?""",
                    (guild_id, int(user_id), int(user_id), int(user_id), max(1, min(25, int(limit)))),
                )
                ids = [int(row[0]) for row in await cur.fetchall()]
            rows: list[ContractSnapshot] = []
            for contract_id in ids:
                item = await self.get_contract(guild_id, contract_id)
                if item is not None:
                    rows.append(item)
            return rows

        async def active_assignments(self, guild_id: int, user_id: int, *, limit: int = 3) -> list[ContractSnapshot]:
            await self.expire_due(guild_id)
            async with aiosqlite.connect(self.db.path) as conn:
                cur = await conn.execute(
                    """SELECT contract_id FROM contracts
                       WHERE guild_id=? AND assignee_id=? AND status='active' AND expires_at>?
                       ORDER BY expires_at,contract_id LIMIT ?""",
                    (guild_id, int(user_id), self._now_iso(), max(1, min(10, int(limit)))),
                )
                ids = [int(row[0]) for row in await cur.fetchall()]
            result: list[ContractSnapshot] = []
            for cid in ids:
                snap = await self.get_contract(guild_id, cid)
                if snap is not None:
                    result.append(snap)
            return result

