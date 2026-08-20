from __future__ import annotations
from app.services.contracts_projection_support import *

class ContractServiceMixin1:
        def __init__(self, database) -> None:
            self.db = database
            self.notifications = None
            self.opportunity_resolver = None

        def bind_notifications(self, notifications) -> None:
            self.notifications = notifications

        def bind_opportunity_resolver(self, resolver) -> None:
            self.opportunity_resolver = resolver

        @staticmethod
        def _now_iso() -> str:
            return datetime.now(timezone.utc).isoformat()

        @staticmethod
        def _validate_iso_future(expires_at: str) -> str:
            try:
                parsed = datetime.fromisoformat(str(expires_at))
            except ValueError as exc:
                raise ValueError("Érvénytelen megbízási határidő.") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed = parsed.astimezone(timezone.utc)
            now = datetime.now(timezone.utc)
            if parsed <= now:
                raise ValueError("A megbízás határidejének a jövőben kell lennie.")
            if parsed > now + timedelta(days=cfg.PLAYER_MAX_DEADLINE_DAYS):
                raise ValueError(f"A megbízás legfeljebb {cfg.PLAYER_MAX_DEADLINE_DAYS} napra adható fel.")
            return parsed.isoformat()

        @staticmethod
        def _normalize_specs(specs: Iterable[ObjectiveSpec]) -> tuple[ObjectiveSpec, ...]:
            normalized: list[ObjectiveSpec] = []
            seen: set[str] = set()
            for spec in specs:
                key = str(spec.key).strip().lower()
                objective_type = str(spec.objective_type).strip().lower()
                target_ref = str(spec.target_ref).strip().lower()
                required = int(spec.required_value)
                if not key or len(key) > 64:
                    raise ValueError("Érvénytelen objective kulcs.")
                if key in seen:
                    raise ValueError("Egy megbízáson belül az objective kulcsok legyenek egyediek.")
                if objective_type not in cfg.OBJECTIVE_BY_KEY:
                    raise ValueError("Nem támogatott megbízási objective típus.")
                if not target_ref or len(target_ref) > 128:
                    raise ValueError("Érvénytelen objective célhivatkozás.")
                if required < 1:
                    raise ValueError("Az objective elvárt értéke legalább 1.")
                seen.add(key)
                normalized.append(
                    ObjectiveSpec(
                        key=key,
                        objective_type=objective_type,
                        target_ref=target_ref,
                        required_value=required,
                        metadata=dict(spec.metadata or {}),
                    )
                )
            if not normalized:
                raise ValueError("A megbízáshoz legalább egy objective szükséges.")
            if len(normalized) > 8:
                raise ValueError("Egy megbízás legfeljebb 8 objective-et tartalmazhat.")
            return tuple(normalized)

        @staticmethod
        async def _history_tx(
            conn,
            guild_id: int,
            contract_id: int,
            *,
            event_key: str,
            event_type: str,
            actor_id: int | None,
            metadata: dict[str, Any] | None = None,
            now: str,
        ) -> None:
            await conn.execute(
                """INSERT INTO contract_history(
                       guild_id,contract_id,event_key,event_type,actor_id,metadata_json,created_at
                   ) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(guild_id,contract_id,event_key) DO NOTHING""",
                (
                    int(guild_id), int(contract_id), str(event_key)[:190], str(event_type)[:40],
                    (int(actor_id) if actor_id is not None else None),
                    json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")), now,
                ),
            )

        @staticmethod
        async def _telemetry_tx(
            conn, guild_id: int, *, event_key: str, event_type: str, contract_id: int | None = None,
            actor_id: int | None = None, counterparty_id: int | None = None, source_key: str = "",
            reward_amount: int = 0, details: dict[str, Any] | None = None, now: str,
        ) -> None:
            """Persist audit-only contract telemetry. This never blocks/punishes players."""
            await conn.execute(
                """INSERT INTO contract_telemetry(
                       guild_id,event_key,event_type,contract_id,actor_id,counterparty_id,source_key,reward_amount,details_json,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(guild_id,event_key) DO NOTHING""",
                (
                    int(guild_id), str(event_key)[:190], str(event_type)[:48],
                    (int(contract_id) if contract_id is not None else None),
                    (int(actor_id) if actor_id is not None else None),
                    (int(counterparty_id) if counterparty_id is not None else None),
                    str(source_key)[:64], int(reward_amount),
                    json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")), now,
                ),
            )

        async def _stat_add(self, guild_id: int, user_id: int, stat_name: str, amount: int = 1) -> None:
            now = self._now_iso()
            try:
                async with aiosqlite.connect(self.db.path) as conn:
                    await conn.execute(
                        """INSERT INTO user_statistics(guild_id,user_id,stat_name,value,updated_at)
                           VALUES(?,?,?,?,?)
                           ON CONFLICT(guild_id,user_id,stat_name)
                           DO UPDATE SET value=value+excluded.value,updated_at=excluded.updated_at""",
                        (int(guild_id), int(user_id), str(stat_name)[:96], int(amount), now),
                    )
                    await conn.commit()
            except Exception:
                log.exception("Contract telemetry failed guild=%s user=%s stat=%s", guild_id, user_id, stat_name)

        async def _notify(
            self,
            guild_id: int,
            user_id: int | None,
            *,
            contract_id: int,
            event_key: str,
            title: str,
            body: str,
            expires_at: str | None = None,
            important: bool = False,
        ) -> None:
            if self.notifications is None or user_id is None:
                return
            try:
                await self.notifications.contract_update(
                    int(guild_id), int(user_id), contract_id=int(contract_id), event_key=str(event_key),
                    title=str(title), body=str(body), expires_at=expires_at, important=important,
                )
            except Exception:
                log.exception("Contract notification failed guild=%s user=%s contract=%s", guild_id, user_id, contract_id)

        @staticmethod
        def _budget_period() -> str:
            return datetime.now(timezone.utc).date().isoformat()

        @staticmethod
        def _deterministic_route(guild_id: int, period: str, source_key: str, target_user_id: int = 0) -> tuple[str, str]:
            cities = tuple(character_config.STARTING_CITY_KEYS)
            if len(cities) < 2:
                raise RuntimeError("A városi freelance forráshoz legalább két aktív Yoru város kell.")
            digest = hashlib.sha256(f"{int(guild_id)}:{period}:{source_key}:{int(target_user_id)}".encode("utf-8")).digest()
            start_index = int(digest[0]) % len(cities)
            offset = 1 + (int(digest[1]) % (len(cities) - 1))
            end_index = (start_index + offset) % len(cities)
            return cities[start_index], cities[end_index]

        async def source_state(self, guild_id: int, contract_id: int) -> dict[str, Any] | None:
            async with aiosqlite.connect(self.db.path) as conn:
                conn.row_factory = aiosqlite.Row
                cur = await conn.execute(
                    """SELECT source_key,source_label,target_user_id,budget_key,budget_period,eligibility_json,modifier_json,created_at
                       FROM contract_source_state WHERE guild_id=? AND contract_id=?""",
                    (int(guild_id), int(contract_id)),
                )
                row = await cur.fetchone()
            if row is None:
                return None
            result = dict(row)
            for raw_key, target_key, fallback in (("eligibility_json", "eligibility", {}), ("modifier_json", "modifiers", [])):
                raw = result.pop(raw_key, None)
                try:
                    result[target_key] = json.loads(str(raw or ("{}" if isinstance(fallback, dict) else "[]")))
                except (TypeError, ValueError, json.JSONDecodeError):
                    result[target_key] = fallback
            return result

        async def _source_requirements_eligible(self, guild_id: int, user_id: int, state: dict[str, Any] | None) -> bool:
            if not state:
                return True
            eligibility = dict(state.get("eligibility") or {})
            if not eligibility:
                return True
            if self.opportunity_resolver is None:
                return False
            return bool(await self.opportunity_resolver.requirements_eligible(int(guild_id), int(user_id), **eligibility))

