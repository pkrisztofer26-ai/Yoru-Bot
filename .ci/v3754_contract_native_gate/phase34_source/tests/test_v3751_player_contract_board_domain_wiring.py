from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import db_backend as aiosqlite
from app.database import Database
from app.services.contracts import ContractService, ObjectiveSpec
from app.services.notification_contracts import GameplayNotificationContract


def _future(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def _stack(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "contracts_w142.db")
    db = Database(path, 1_000_000)
    await db.initialize()
    contracts = ContractService(db)
    return path, db, contracts


async def _set_balance(path: str, guild_id: int, user_id: int, wallet: int, bank: int = 0) -> None:
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "UPDATE users SET wallet=?,bank=? WHERE guild_id=? AND user_id=?",
            (wallet, bank, guild_id, user_id),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_board_lists_open_to_others_and_private_user_history(tmp_path: Path, monkeypatch) -> None:
    _path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    created = await contracts.create_player_contract(
        1, 10, title="Miskolc → Eger", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    open_for_other = await contracts.list_open_contracts(1, 20)
    assert created.contract_id in {row.contract_id for row in open_for_other}
    open_for_creator = await contracts.list_open_contracts(1, 10)
    assert created.contract_id not in {row.contract_id for row in open_for_creator}
    mine = await contracts.list_user_contracts(1, 10)
    assert mine and mine[0].contract_id == created.contract_id and mine[0].status == "open"
    history = await contracts.history(1, created.contract_id)
    assert [row["event_type"] for row in history] == ["created"]


@pytest.mark.asyncio
async def test_stable_travel_event_can_progress_only_one_matching_contract(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 11, 20):
        await db.ensure_user(1, uid)
    await _set_balance(path, 1, 10, 500_000)
    await _set_balance(path, 1, 11, 500_000)
    first = await contracts.create_player_contract(
        1, 10, title="Első fuvar", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    second = await contracts.create_player_contract(
        1, 11, title="Második fuvar", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    await contracts.accept_contract(1, first.contract_id, 20)
    await contracts.accept_contract(1, second.contract_id, 20)

    result = await contracts.record_matching_city_delivery(
        1, 20, travel_id=77, from_city_key="miskolc", to_city_key="eger"
    )
    assert result is not None and result.contract.contract_id == first.contract_id
    assert result.settled is True
    replay = await contracts.record_matching_city_delivery(
        1, 20, travel_id=77, from_city_key="miskolc", to_city_key="eger"
    )
    assert replay is not None and replay.contract.contract_id == first.contract_id and replay.replay is True
    second_snapshot = await contracts.get_contract(1, second.contract_id)
    assert second_snapshot is not None and second_snapshot.status == "active"

    result2 = await contracts.record_matching_city_delivery(
        1, 20, travel_id=78, from_city_key="miskolc", to_city_key="eger"
    )
    assert result2 is not None and result2.contract.contract_id == second.contract_id and result2.settled is True
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM contract_event_claims WHERE guild_id=1")
        assert int((await cur.fetchone())[0]) == 2


@pytest.mark.asyncio
async def test_audited_item_transfer_replay_never_moves_inventory_twice(tmp_path: Path, monkeypatch) -> None:
    path, db, _contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    await db.add_item(1, 20, "lottery_ticket", 5)
    first = await db.transfer_item_audited(
        1, 20, 10, "lottery_ticket", 3, source_ref="contract-item:55:9"
    )
    second = await db.transfer_item_audited(
        1, 20, 10, "lottery_ticket", 3, source_ref="contract-item:55:9"
    )
    assert first[0] == second[0]
    assert first[-1] is False and second[-1] is True
    assert await db.get_item_quantity(1, 20, "lottery_ticket") == 2
    assert await db.get_item_quantity(1, 10, "lottery_ticket") == 3
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM item_transfer_history WHERE source_ref='contract-item:55:9'")
        assert int((await cur.fetchone())[0]) == 1


@pytest.mark.asyncio
async def test_extras_item_delivery_settles_domain_then_contract(tmp_path: Path, monkeypatch) -> None:
    from app.services.extras import ExtrasService
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    await _set_balance(path, 1, 10, 500_000)
    await db.add_item(1, 20, "lottery_ticket", 4)
    created = await contracts.create_player_contract(
        1, 10, title="Adj át négy sorsjegyet", reward_amount=200_000, expires_at=_future(),
        objectives=[ObjectiveSpec("item", "item_delivery", "lottery_ticket", 4)],
    )
    await contracts.accept_contract(1, created.contract_id, 20)
    objective = (await contracts.objectives(1, created.contract_id))[0]
    extras = ExtrasService(db, object(), object())
    extras.bind_contracts(contracts)
    result = await extras.deliver_contract_item(1, 20, created.contract_id, int(objective["objective_id"]))
    assert result["paid"] is True
    assert result["quantity"] == 4
    assert await db.get_item_quantity(1, 20, "lottery_ticket") == 0
    assert await db.get_item_quantity(1, 10, "lottery_ticket") == 4
    snapshot = await contracts.get_contract(1, created.contract_id)
    assert snapshot is not None and snapshot.status == "settled"
    history = await contracts.history(1, created.contract_id)
    assert {row["event_type"] for row in history} >= {"created", "accepted", "progress", "settled"}


@pytest.mark.asyncio
async def test_active_assignment_limit_and_reciprocal_pair_telemetry(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20, 30, 31, 32):
        await db.ensure_user(1, uid)
        await _set_balance(path, 1, uid, 1_000_000)

    # First settle 20 -> 10 so the reversed pair can be observed later.
    a = await contracts.create_player_contract(
        1, 20, title="A", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "eger:miskolc")],
    )
    await contracts.accept_contract(1, a.contract_id, 10)
    await contracts.record_city_delivery(1, a.contract_id, 10, event_key="travel:a", route_key="eger:miskolc")
    await contracts.settle_ready_contract(1, a.contract_id)

    b = await contracts.create_player_contract(
        1, 10, title="B", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    await contracts.accept_contract(1, b.contract_id, 20)
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT value FROM user_statistics WHERE guild_id=1 AND user_id=20 AND stat_name='contract.reciprocal_pair'"
        )
        row = await cur.fetchone()
    assert row is not None and int(row[0]) >= 1

    # user 20 already owns B as assignee; add two more, then a fourth must fail.
    for owner in (30, 31):
        c = await contracts.create_player_contract(
            1, owner, title=f"C{owner}", reward_amount=100_000, expires_at=_future(),
            objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
        )
        await contracts.accept_contract(1, c.contract_id, 20)
    c = await contracts.create_player_contract(
        1, 32, title="Too many", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    with pytest.raises(ValueError, match="legfeljebb"):
        await contracts.accept_contract(1, c.contract_id, 20)


def test_w142_delivery_surfaces_are_present_without_new_slash_root() -> None:
    root = Path(__file__).resolve().parents[1]
    profile = (root / "app/cogs/character_views/profile.py").read_text(encoding="utf-8")
    board = (root / "app/cogs/character_views/contracts.py").read_text(encoding="utf-8")
    notifications = (root / "app/cogs/notifications.py").read_text(encoding="utf-8")
    world = (root / "app/cogs/character_views/world.py").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")
    assert 'label="Megbízások"' in profile
    assert "class ContractBoardView" in board and "class ContractDetailView" in board
    assert 'action_type == "contract"' in notifications
    assert 'action_key.startswith("contract:")' in world
    assert "self.contracts.bind_notifications" in main
    assert 'app_commands.Group(name="megbizasok"' not in "\n".join((profile, board, notifications, world, main))


@pytest.mark.asyncio
async def test_contract_notification_uses_semantic_existing_notification_backend() -> None:
    class FakeNotifications:
        def __init__(self) -> None:
            self.calls = []

        async def notify(self, **kwargs):
            self.calls.append(kwargs)
            return kwargs

    fake = FakeNotifications()
    contract = GameplayNotificationContract(fake)
    result = await contract.contract_update(
        1, 20, contract_id=77, event_key="accepted",
        title="Megbízás elvállalva", body="A megbízás most már nálad van.", important=True,
    )
    assert result["category"] == "contract"
    assert result["action_type"] == "contract"
    assert result["action_ref"] == 77
    assert result["event_key"] == "gameplay:contract.77.accepted:contract:contract-77"
    assert len(fake.calls) == 1
