from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
try:
    from mysql.connector.aio import connect
    from mysql.connector.errors import IntegrityError
except ImportError:  # local non-native preflight only
    connect = None
    class IntegrityError(Exception):
        pass

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / "PHASE9_SCHEMA.sql").read_text(encoding="utf-8")
FP = json.loads((ROOT / "SOURCE_FINGERPRINTS.json").read_text(encoding="utf-8"))
LOCK = "yoru:phase9-native-writer"
ACTIVE = 1
W19_TABLES = (
    "asset_instances", "asset_ownership_history", "asset_auction_listings",
    "asset_auction_bids", "asset_trophy_showcase",
)
DROP = (
    "asset_trophy_showcase", "asset_auction_bids", "asset_auction_listings",
    "asset_ownership_history", "asset_instances", "housing_garage", "vehicle_state",
    "character_vehicles", "housing_properties", "housing_state", "characters",
    "transactions", "users",
)


def creds() -> dict:
    if connect is None:
        pytest.skip("mysql-connector-python not installed in local non-native environment")
    if os.getenv("YORU_TEST_MYSQL_CONFIRM") != "DISPOSABLE_SCHEMA":
        pytest.skip("disposable MariaDB not confirmed")
    names = ["YORU_TEST_MYSQL_HOST", "YORU_TEST_MYSQL_USER", "YORU_TEST_MYSQL_PASSWORD", "YORU_TEST_MYSQL_DATABASE"]
    missing = [n for n in names if not os.getenv(n, "").strip()]
    if missing:
        pytest.skip("missing disposable MariaDB credentials: " + ",".join(missing))
    database = os.environ["YORU_TEST_MYSQL_DATABASE"].strip()
    if not re.search(r"(test|qa|staging|sandbox)", database, re.I):
        pytest.fail("refusing non-disposable schema")
    return {
        "host": os.environ["YORU_TEST_MYSQL_HOST"],
        "port": int(os.getenv("YORU_TEST_MYSQL_PORT", "3306")),
        "user": os.environ["YORU_TEST_MYSQL_USER"],
        "password": os.environ["YORU_TEST_MYSQL_PASSWORD"],
        "database": database,
        "autocommit": False,
        "use_pure": True,
        "ssl_disabled": True,
    }


async def raw(conn, sql: str, params=()):
    cur = await conn.cursor()
    await cur.execute(sql, params)
    return cur


async def scalar(conn, sql: str, params=()):
    cur = await raw(conn, sql, params)
    row = await cur.fetchone()
    await cur.close()
    return None if row is None else row[0]


async def rows(conn, sql: str, params=()):
    cur = await raw(conn, sql, params)
    result = await cur.fetchall()
    await cur.close()
    return result


async def writer_lock(conn):
    if int(await scalar(conn, "SELECT GET_LOCK(%s,10)", (LOCK,)) or 0) != 1:
        raise RuntimeError("native writer lock timeout")


async def writer_unlock(conn):
    try:
        await scalar(conn, "SELECT RELEASE_LOCK(%s)", (LOCK,))
    except Exception:
        pass


def ddl_map() -> dict[str, str]:
    result = {}
    for block in SCHEMA.split("-- TABLE:")[1:]:
        name, body = block.split("\n", 1)
        result[name.strip()] = body.strip().rstrip(";")
    return result


async def reset_schema():
    conn = await connect(**creds())
    try:
        await raw(conn, "SET FOREIGN_KEY_CHECKS=0")
        for table in DROP:
            await raw(conn, f"DROP TABLE IF EXISTS `{table}`")
        await raw(conn, "SET FOREIGN_KEY_CHECKS=1")
        await conn.commit()
    finally:
        await conn.close()


async def install_base():
    conn = await connect(**creds())
    try:
        base = [
            """CREATE TABLE users(
                guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,
                wallet DECIMAL(65,0) NOT NULL DEFAULT 0,bank DECIMAL(65,0) NOT NULL DEFAULT 0,
                money_lost DECIMAL(65,0) NOT NULL DEFAULT 0,money_earned DECIMAL(65,0) NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id,user_id)
            ) ENGINE=InnoDB""",
            """CREATE TABLE transactions(
                tx_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,guild_id BIGINT UNSIGNED NOT NULL,
                user_id BIGINT UNSIGNED NOT NULL,amount DECIMAL(65,0) NOT NULL,reason VARCHAR(191) NOT NULL,
                created_at VARCHAR(64) NOT NULL,PRIMARY KEY(tx_id),KEY idx_tx_reason(guild_id,user_id,reason)
            ) ENGINE=InnoDB""",
            """CREATE TABLE characters(
                guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,status VARCHAR(24) NOT NULL,
                home_city_key VARCHAR(40) NULL,PRIMARY KEY(guild_id,user_id)
            ) ENGINE=InnoDB""",
            """CREATE TABLE character_vehicles(
                vehicle_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,
                model_key VARCHAR(80) NOT NULL,condition_key VARCHAR(40) NOT NULL,city_key VARCHAR(40) NOT NULL,
                purchase_price DECIMAL(65,0) NOT NULL,estimated_value DECIMAL(65,0) NOT NULL,status VARCHAR(24) NOT NULL,
                acquired_at VARCHAR(64) NOT NULL,updated_at VARCHAR(64) NOT NULL,sold_at VARCHAR(64) NULL,
                PRIMARY KEY(vehicle_id),KEY idx_cv_owner(guild_id,user_id,status)
            ) ENGINE=InnoDB""",
            """CREATE TABLE vehicle_state(
                vehicle_id BIGINT UNSIGNED NOT NULL,guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,
                is_primary TINYINT UNSIGNED NOT NULL DEFAULT 0,issue_key VARCHAR(80) NULL,issue_revealed TINYINT UNSIGNED NOT NULL DEFAULT 0,
                last_service_at VARCHAR(64) NULL,updated_at VARCHAR(64) NOT NULL,PRIMARY KEY(vehicle_id)
            ) ENGINE=InnoDB""",
            """CREATE TABLE housing_properties(
                property_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,
                city_key VARCHAR(40) NOT NULL,tier_key VARCHAR(40) NOT NULL,purchase_price DECIMAL(65,0) NOT NULL,
                maintenance_paid_until VARCHAR(64) NOT NULL,maintenance_grace_until VARCHAR(64) NULL,maintenance_debt DECIMAL(65,0) NOT NULL DEFAULT 0,
                last_opportunity_cycle VARCHAR(64) NULL,status VARCHAR(24) NOT NULL,acquired_at VARCHAR(64) NOT NULL,updated_at VARCHAR(64) NOT NULL,
                sold_at VARCHAR(64) NULL,sale_price DECIMAL(65,0) NULL,PRIMARY KEY(property_id),KEY idx_hp_owner(guild_id,user_id,status,city_key)
            ) ENGINE=InnoDB""",
            """CREATE TABLE housing_state(
                guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,tier_key VARCHAR(40) NOT NULL,city_key VARCHAR(40) NOT NULL,
                acquired_at VARCHAR(64) NULL,paid_until VARCHAR(64) NULL,grace_until VARCHAR(64) NULL,updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(guild_id,user_id)
            ) ENGINE=InnoDB""",
            """CREATE TABLE housing_garage(
                guild_id BIGINT UNSIGNED NOT NULL,property_id BIGINT UNSIGNED NOT NULL,vehicle_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,
                PRIMARY KEY(guild_id,property_id,vehicle_id)
            ) ENGINE=InnoDB""",
        ]
        for stmt in base:
            await raw(conn, stmt)
        for stmt in ddl_map().values():
            await raw(conn, stmt)
        await conn.commit()
    finally:
        await conn.close()


def now_s() -> str:
    return datetime.now(timezone.utc).isoformat()


async def seed_user(conn, user_id: int, wallet: int = 1_000_000, bank: int = 0):
    await raw(conn, "INSERT INTO users(guild_id,user_id,wallet,bank) VALUES(1,%s,%s,%s)", (user_id, wallet, bank))
    await raw(conn, "INSERT INTO characters(guild_id,user_id,status,home_city_key) VALUES(1,%s,'active','budapest')", (user_id,))


async def reserve_money(conn, user_id: int, amount: int, reason: str) -> tuple[int, int]:
    row = (await rows(conn, "SELECT wallet,bank FROM users WHERE guild_id=1 AND user_id=%s FOR UPDATE", (user_id,)))[0]
    wallet, bank = int(row[0]), int(row[1])
    if wallet + bank < amount:
        raise ValueError("insufficient funds")
    wu = min(wallet, amount); bu = amount - wu
    await raw(conn, "UPDATE users SET wallet=wallet-%s,bank=bank-%s,money_lost=money_lost+%s WHERE guild_id=1 AND user_id=%s", (wu, bu, amount, user_id))
    await raw(conn, "INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(1,%s,%s,%s,%s)", (user_id, -amount, reason, now_s()))
    return wu, bu


async def refund_money(conn, user_id: int, wallet_amount: int, bank_amount: int, reason: str):
    total = wallet_amount + bank_amount
    await raw(conn, "UPDATE users SET wallet=wallet+%s,bank=bank+%s,money_lost=GREATEST(0,money_lost-%s) WHERE guild_id=1 AND user_id=%s", (wallet_amount, bank_amount, total, user_id))
    await raw(conn, "INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(1,%s,%s,%s,%s)", (user_id, total, reason, now_s()))


async def credit_money(conn, user_id: int, amount: int, reason: str):
    await raw(conn, "UPDATE users SET wallet=wallet+%s,money_earned=money_earned+%s WHERE guild_id=1 AND user_id=%s", (amount, amount, user_id))
    await raw(conn, "INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(1,%s,%s,%s,%s)", (user_id, amount, reason, now_s()))


async def seed_asset(conn, asset_type: str, source_ref: str, owner_id: int, *, rarity: str = "rare", flags: str = "{}") -> int:
    ts = now_s()
    cur = await raw(conn, """INSERT INTO asset_instances(guild_id,asset_type,source_ref,reference_key,rarity,origin_key,special_flags_json,created_at,updated_at)
                           VALUES(1,%s,%s,%s,%s,'native-gate',%s,%s,%s)""", (asset_type, source_ref, f"ref:{source_ref}", rarity, flags, ts, ts))
    aid = int(cur.lastrowid)
    await raw(conn, """INSERT INTO asset_ownership_history(instance_id,guild_id,owner_type,owner_id,acquisition_type,acquisition_ref,acquired_at,active_slot,event_key,created_at,updated_at)
                           VALUES(%s,1,'user',%s,'seed','seed',%s,1,%s,%s,%s)""", (aid, owner_id, ts, f"seed:{aid}", ts, ts))
    return aid


async def transfer_provenance(conn, aid: int, seller: int, buyer: int, transfer_ref: str, *, fail_after_cleanup: bool = False):
    event_key = f"user-transfer:auction_sale:{transfer_ref}"
    existing = await rows(conn, "SELECT owner_id FROM asset_ownership_history WHERE instance_id=%s AND event_key=%s LIMIT 1", (aid, event_key))
    if existing:
        if int(existing[0][0]) != buyer:
            raise RuntimeError("idempotency conflict")
        await raw(conn, "DELETE FROM asset_trophy_showcase WHERE guild_id=1 AND user_id=%s AND asset_instance_id=%s", (seller, aid))
        return
    active = await rows(conn, "SELECT ownership_id,owner_type,owner_id FROM asset_ownership_history WHERE instance_id=%s AND active_slot=1 LIMIT 1 FOR UPDATE", (aid,))
    if not active or str(active[0][1]) != "user" or int(active[0][2]) != seller:
        raise RuntimeError("active owner mismatch")
    await raw(conn, "DELETE FROM asset_trophy_showcase WHERE guild_id=1 AND user_id=%s AND asset_instance_id=%s", (seller, aid))
    if fail_after_cleanup:
        raise RuntimeError("injected after showcase cleanup")
    ts = now_s()
    cur = await raw(conn, "UPDATE asset_ownership_history SET released_at=%s,release_type='auction_sale',release_ref=%s,active_slot=NULL,updated_at=%s WHERE ownership_id=%s AND active_slot=1", (ts, transfer_ref, ts, int(active[0][0])))
    if cur.rowcount != 1:
        raise RuntimeError("ownership close failed")
    await raw(conn, """INSERT INTO asset_ownership_history(instance_id,guild_id,owner_type,owner_id,acquisition_type,acquisition_ref,acquired_at,active_slot,event_key,created_at,updated_at)
                           VALUES(%s,1,'user',%s,'auction_sale',%s,%s,1,%s,%s,%s)""", (aid, buyer, transfer_ref, ts, event_key, ts, ts))


async def release_provenance(conn, aid: int, owner: int, release_ref: str, *, fail_after_cleanup: bool = False):
    active = await rows(conn, "SELECT ownership_id,owner_id FROM asset_ownership_history WHERE instance_id=%s AND active_slot=1 LIMIT 1 FOR UPDATE", (aid,))
    if not active:
        return False
    if int(active[0][1]) != owner:
        raise RuntimeError("owner mismatch")
    await raw(conn, "DELETE FROM asset_trophy_showcase WHERE guild_id=1 AND user_id=%s AND asset_instance_id=%s", (owner, aid))
    if fail_after_cleanup:
        raise RuntimeError("injected after showcase cleanup")
    ts = now_s()
    cur = await raw(conn, "UPDATE asset_ownership_history SET released_at=%s,release_type='system_sale',release_ref=%s,active_slot=NULL,updated_at=%s WHERE ownership_id=%s AND active_slot=1", (ts, release_ref, ts, int(active[0][0])))
    return cur.rowcount == 1


async def create_listing(conn, aid: int, seller: int, *, start: int = 100_000, inc: int = 10_000) -> int:
    owner = await scalar(conn, "SELECT owner_id FROM asset_ownership_history WHERE instance_id=%s AND active_slot=1 FOR UPDATE", (aid,))
    if owner is None or int(owner) != seller:
        raise ValueError("not owner")
    ts = datetime.now(timezone.utc)
    cur = await raw(conn, """INSERT INTO asset_auction_listings(guild_id,asset_instance_id,seller_id,start_price,min_increment,status,active_slot,created_at,expires_at)
                           VALUES(1,%s,%s,%s,%s,'active',1,%s,%s)""", (aid, seller, start, inc, ts.isoformat(), (ts + timedelta(hours=1)).isoformat()))
    return int(cur.lastrowid)


async def place_bid_native(auction_id: int, bidder: int, amount: int, request_ref: str):
    conn = await connect(**creds())
    try:
        await writer_lock(conn); await conn.start_transaction()
        existing = await rows(conn, "SELECT bidder_id,amount,wallet_reserved,bank_reserved,status FROM asset_auction_bids WHERE auction_id=%s AND request_ref=%s LIMIT 1", (auction_id, request_ref))
        if existing:
            if int(existing[0][0]) != bidder or int(existing[0][1]) != amount:
                raise ValueError("request replay mismatch")
            await conn.commit(); return True
        listing = (await rows(conn, "SELECT seller_id,start_price,min_increment,current_bid_id,current_bid_amount,status FROM asset_auction_listings WHERE auction_id=%s FOR UPDATE", (auction_id,)))[0]
        if str(listing[5]) != "active" or int(listing[0]) == bidder:
            raise ValueError("inactive/self bid")
        minimum = int(listing[1]) if listing[4] is None else int(listing[4]) + int(listing[2])
        if amount < minimum:
            raise ValueError("bid too low")
        prev = None
        if listing[3] is not None:
            prev = (await rows(conn, "SELECT bid_id,bidder_id,amount,wallet_reserved,bank_reserved,status FROM asset_auction_bids WHERE bid_id=%s FOR UPDATE", (listing[3],)))[0]
            if str(prev[5]) != "leading": raise RuntimeError("bad leader")
        if prev is not None and int(prev[1]) == bidder:
            await refund_money(conn, bidder, int(prev[3]), int(prev[4]), f"rebid:{auction_id}:{prev[0]}")
        wu, bu = await reserve_money(conn, bidder, amount, f"escrow:{auction_id}:{request_ref}")
        if prev is not None:
            if int(prev[1]) != bidder:
                await refund_money(conn, int(prev[1]), int(prev[3]), int(prev[4]), f"outbid:{auction_id}:{prev[0]}")
            await raw(conn, "UPDATE asset_auction_bids SET status='outbid',resolved_at=%s WHERE bid_id=%s AND status='leading'", (now_s(), int(prev[0])))
        cur = await raw(conn, """INSERT INTO asset_auction_bids(auction_id,guild_id,bidder_id,amount,wallet_reserved,bank_reserved,status,request_ref,created_at)
                               VALUES(%s,1,%s,%s,%s,%s,'leading',%s,%s)""", (auction_id, bidder, amount, wu, bu, request_ref, now_s()))
        bid_id = int(cur.lastrowid)
        await raw(conn, "UPDATE asset_auction_listings SET current_bid_id=%s,current_bid_amount=%s WHERE auction_id=%s AND status='active'", (bid_id, amount, auction_id))
        await conn.commit(); return True
    except Exception:
        await conn.rollback(); raise
    finally:
        await writer_unlock(conn); await conn.close()


async def settle_native(auction_id: int, *, inject_failure: bool = False):
    conn = await connect(**creds())
    try:
        await writer_lock(conn); await conn.start_transaction()
        listing = (await rows(conn, "SELECT asset_instance_id,seller_id,status,current_bid_id,current_bid_amount,winner_id,final_price,seller_net FROM asset_auction_listings WHERE auction_id=%s FOR UPDATE", (auction_id,)))[0]
        if str(listing[2]) != "active":
            await conn.commit(); return str(listing[2])
        if listing[3] is None:
            await raw(conn, "UPDATE asset_auction_listings SET status='expired',active_slot=NULL,resolved_at=%s,settlement_ref=%s WHERE auction_id=%s AND status='active'", (now_s(), f"auction_expire:{auction_id}", auction_id))
            await conn.commit(); return "expired"
        bid = (await rows(conn, "SELECT bid_id,bidder_id,amount,status FROM asset_auction_bids WHERE bid_id=%s FOR UPDATE", (listing[3],)))[0]
        if str(bid[3]) != "leading" or int(bid[2]) != int(listing[4]): raise RuntimeError("bad winning bid")
        aid, seller, winner, amount = int(listing[0]), int(listing[1]), int(bid[1]), int(bid[2])
        asset_type, source_ref = (await rows(conn, "SELECT asset_type,source_ref FROM asset_instances WHERE asset_instance_id=%s", (aid,)))[0]
        transfer_ref = f"auction:{auction_id}:bid:{int(bid[0])}"
        if str(asset_type) == "vehicle":
            cur = await raw(conn, "UPDATE character_vehicles SET user_id=%s,purchase_price=%s,acquired_at=%s,updated_at=%s,sold_at=NULL,status='owned' WHERE vehicle_id=%s AND guild_id=1 AND user_id=%s AND status='owned'", (winner, amount, now_s(), now_s(), int(source_ref), seller))
            if cur.rowcount != 1: raise RuntimeError("vehicle source transfer failed")
            await raw(conn, "UPDATE vehicle_state SET user_id=%s,is_primary=0,updated_at=%s WHERE vehicle_id=%s", (winner, now_s(), int(source_ref)))
        elif str(asset_type) == "property":
            cur = await raw(conn, "UPDATE housing_properties SET user_id=%s,purchase_price=%s,acquired_at=%s,updated_at=%s,sold_at=NULL,sale_price=NULL,status='owned' WHERE property_id=%s AND guild_id=1 AND user_id=%s AND status='owned'", (winner, amount, now_s(), now_s(), int(source_ref), seller))
            if cur.rowcount != 1: raise RuntimeError("property source transfer failed")
        fee = amount * 500 // 10000; seller_net = amount - fee
        await credit_money(conn, seller, seller_net, f"asset_auction_sale:{auction_id}:{aid}")
        await transfer_provenance(conn, aid, seller, winner, transfer_ref)
        if inject_failure: raise RuntimeError("injected pre-commit failure")
        await raw(conn, "UPDATE asset_auction_bids SET status='won',resolved_at=%s WHERE bid_id=%s AND status='leading'", (now_s(), int(bid[0])))
        await raw(conn, "UPDATE asset_auction_listings SET status='sold',active_slot=NULL,resolved_at=%s,winner_id=%s,final_price=%s,seller_net=%s,settlement_ref=%s WHERE auction_id=%s AND status='active' AND active_slot=1", (now_s(), winner, amount, seller_net, transfer_ref, auction_id))
        await conn.commit(); return "sold"
    except Exception:
        await conn.rollback(); raise
    finally:
        await writer_unlock(conn); await conn.close()
