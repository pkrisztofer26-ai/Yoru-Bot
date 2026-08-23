from native_support import *

@pytest.mark.asyncio
async def test_01_schema_innodb_indexes_fks():
    conn = await connect(**creds())
    try:
        engines = await rows(conn, "SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (%s,%s,%s,%s,%s)", W19_TABLES)
        assert {r[0] for r in engines} == set(W19_TABLES)
        assert all(str(r[1]).lower() == "innodb" for r in engines)
        idx = {r[0] for r in await rows(conn, "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('asset_instances','asset_ownership_history','asset_auction_listings','asset_auction_bids','asset_trophy_showcase')")}
        assert {"uq_asset_source","uq_asset_active_owner","uq_asset_auction_active","uq_asset_auction_bid_request","uq_asset_trophy_user_instance"} <= idx
        fks = {r[0] for r in await rows(conn, "SELECT CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE()")}
        assert {"fk_asset_ownership_instance","fk_asset_auction_instance","fk_asset_auction_bid_listing","fk_asset_trophy_instance"} <= fks
    finally: await conn.close()


@pytest.mark.asyncio
async def test_02_provenance_source_and_active_owner_concurrency():
    async def worker(owner: int):
        conn = await connect(**creds())
        try:
            await writer_lock(conn); await conn.start_transaction(); ts=now_s()
            await raw(conn, "INSERT IGNORE INTO asset_instances(guild_id,asset_type,source_ref,reference_key,rarity,origin_key,special_flags_json,created_at,updated_at) VALUES(1,'collectible','same','same','rare','event','{}',%s,%s)", (ts,ts))
            aid=int(await scalar(conn,"SELECT asset_instance_id FROM asset_instances WHERE guild_id=1 AND asset_type='collectible' AND source_ref='same'"))
            try:
                await raw(conn, "INSERT INTO asset_ownership_history(instance_id,guild_id,owner_type,owner_id,acquisition_type,acquired_at,active_slot,event_key,created_at,updated_at) VALUES(%s,1,'user',%s,'mint',%s,1,%s,%s,%s)", (aid,owner,ts,f"mint:{owner}",ts,ts))
                await conn.commit(); return True
            except IntegrityError:
                await conn.rollback(); return False
        finally:
            await writer_unlock(conn); await conn.close()
    result=await asyncio.gather(worker(10),worker(20))
    assert sum(bool(x) for x in result)==1
    conn=await connect(**creds())
    try:
        assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_instances"))==1
        assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_ownership_history WHERE active_slot=1"))==1
    finally: await conn.close()


@pytest.mark.asyncio
async def test_03_unique_trait_persistence_and_replay():
    conn=await connect(**creds())
    try:
        ts=now_s(); seed="vehicle:42:dealer"; digest=hashlib.sha256(seed.encode()).hexdigest(); rarity="limited" if int(digest[:2],16)%5==0 else "rare"; flags=json.dumps({"trait_seed":digest[:16],"edition":"w19"},sort_keys=True)
        await raw(conn,"INSERT INTO asset_instances(guild_id,asset_type,source_ref,reference_key,rarity,origin_key,special_flags_json,created_at,updated_at) VALUES(1,'vehicle','42','model:x',%s,'dealer',%s,%s,%s)",(rarity,flags,ts,ts)); await conn.commit()
        first=await rows(conn,"SELECT asset_instance_id,rarity,special_flags_json FROM asset_instances WHERE source_ref='42'")
        await raw(conn,"INSERT IGNORE INTO asset_instances(guild_id,asset_type,source_ref,reference_key,rarity,origin_key,special_flags_json,created_at,updated_at) VALUES(1,'vehicle','42','model:x','standard','dealer','{}',%s,%s)",(ts,ts)); await conn.commit()
    finally: await conn.close()
    conn=await connect(**creds())
    try:
        second=await rows(conn,"SELECT asset_instance_id,rarity,special_flags_json FROM asset_instances WHERE source_ref='42'")
        assert first==second and str(second[0][1])==rarity and json.loads(second[0][2])["trait_seed"]==digest[:16]
    finally: await conn.close()


@pytest.mark.asyncio
async def test_04_collectible_event_mint_idempotent_replay():
    async def mint():
        conn=await connect(**creds())
        try:
            await writer_lock(conn); await conn.start_transaction(); ts=now_s(); source='world-event:alpha:reward:1'
            await raw(conn,"INSERT IGNORE INTO asset_instances(guild_id,asset_type,source_ref,reference_key,rarity,origin_key,special_flags_json,created_at,updated_at) VALUES(1,'collectible',%s,'relic:alpha','limited','world-event','{}',%s,%s)",(source,ts,ts))
            aid=int(await scalar(conn,"SELECT asset_instance_id FROM asset_instances WHERE guild_id=1 AND asset_type='collectible' AND source_ref=%s",(source,)))
            await raw(conn,"INSERT IGNORE INTO asset_ownership_history(instance_id,guild_id,owner_type,owner_id,acquisition_type,acquisition_ref,acquired_at,active_slot,event_key,created_at,updated_at) VALUES(%s,1,'user',10,'event_reward',%s,%s,1,%s,%s,%s)",(aid,source,ts,f"collectible:{source}",ts,ts)); await conn.commit()
        finally:
            await writer_unlock(conn); await conn.close()
    await asyncio.gather(*(mint() for _ in range(8)))
    conn=await connect(**creds())
    try:
        assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_instances"))==1
        assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_ownership_history"))==1
    finally: await conn.close()


def test_13_source_projection_contract():
    assert FP["source_release"] == "3.80.6"
    assert len(FP["source_files"]) >= 8
    assert len(FP["service_methods"]) >= 15
    assert FP["phase9_schema_sha256"] == hashlib.sha256(SCHEMA.encode()).hexdigest()
    assert all(token in SCHEMA for token in W19_TABLES)
    assert all(token in SCHEMA for token in ("uq_asset_source","uq_asset_active_owner","uq_asset_auction_active","uq_asset_auction_bid_request","uq_asset_trophy_user_instance","ENGINE=InnoDB"))
    keys="\n".join(FP["service_methods"].keys())
    for token in ("transfer_user_ownership_tx","release_source_tx","set_trophy_showcase","place_bid","_settle_tx","transfer_auction_ownership_tx","sell_vehicle","sell_property","reserve_wallet_and_bank_tx","refund_wallet_and_bank_tx","credit_wallet_tx"):
        assert token in keys
