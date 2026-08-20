from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app import contract_config as cfg
from app import character_config
from app import db_backend as aiosqlite

log = logging.getLogger("vaultbot.contracts")


@dataclass(frozen=True, slots=True)
class ObjectiveSpec:
    key: str
    objective_type: str
    target_ref: str
    required_value: int = 1
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ContractSnapshot:
    contract_id: int
    guild_id: int
    source_type: str
    creator_id: int | None
    assignee_id: int | None
    title: str
    reward_amount: int
    status: str
    escrow_state: str
    created_at: str
    expires_at: str
    accepted_at: str | None
    resolved_at: str | None
    source_ref: str = ""


@dataclass(frozen=True, slots=True)
class ContractDomainEventResult:
    contract: ContractSnapshot
    progressed: bool
    settled: bool
    replay: bool = False


@dataclass(frozen=True, slots=True)
class ContractRecoveryReport:
    ready_settled: int = 0
    expired: int = 0
    budget_rows_checked: int = 0
    budget_rows_repaired: int = 0
    telemetry_pruned: int = 0


