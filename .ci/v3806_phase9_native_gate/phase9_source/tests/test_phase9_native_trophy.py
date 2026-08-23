from native_support import *

@pytest.mark.asyncio
async def test_11_trophy_fk_unique_and_concurrent_replacement():
    conn=await connect(**creds())
    try:
        aids=[await seed_asset(conn,'collectible',f't{i}',10) for i in range(1,7)]; await conn.commit()
        with pytest.raises(IntegrityError):
            await raw(conn,"INSERT INTO asset_trophy_showcase(guild_id,user_id,slot_index,asset_instance_id,created_at,updated_at) VALUES(1,10,1,999999,%s,%s)",(now_s(),now_s())); await conn.commit()
        await conn.rollback()
    finally: await conn.close()
    async def replace(selection):
        conn=await connect(**creds())
        try:
            await writer_lock(conn); await conn.start_transaction(); await raw(conn,"DELETE FROM asset_trophy_showcase WHERE guild_id=1 AND user_id=10")
            for slot,aid in enumerate(selection,1): await raw(conn,"INSERT INTO asset_trophy_showcase(guild_id,user_id,slot_index,asset_instance_id,created_at,updated_at) VALUES(1,10,%s,%s,%s,%s)",(slot,aid,now_s(),now_s()))
            await conn.commit(); return tuple(selection)
        finally: await writer_unlock(conn); await conn.close()
    a=tuple(aids[:3]); b=tuple(aids[3:6]); await asyncio.gather(replace(a),replace(b))
    conn=await connect(**creds())
    try:
        final=tuple(int(r[0]) for r in await rows(conn,"SELECT asset_instance_id FROM asset_trophy_showcase WHERE guild_id=1 AND user_id=10 ORDER BY slot_index")); assert final in (a,b)
        with pytest.raises(IntegrityError):
            await raw(conn,"INSERT INTO asset_trophy_showcase(guild_id,user_id,slot_index,asset_instance_id,created_at,updated_at) VALUES(1,10,6,%s,%s,%s)",(final[0],now_s(),now_s())); await conn.commit()
        await conn.rollback()
    finally: await conn.close()


@pytest.mark.asyncio
async def test_12_trophy_cleanup_atomic_transfer_system_sale_and_no_resurrection():
    conn=await connect(**creds())
    try:
        aid=await seed_asset(conn,'collectible','cleanup',10); await raw(conn,"INSERT INTO asset_trophy_showcase(guild_id,user_id,slot_index,asset_instance_id,created_at,updated_at) VALUES(1,10,1,%s,%s,%s)",(aid,now_s(),now_s())); await conn.commit()
    finally: await conn.close()
    conn=await connect(**creds())
    try:
        await conn.start_transaction()
        with pytest.raises(RuntimeError): await transfer_provenance(conn,aid,10,20,'xfer-fail',fail_after_cleanup=True)
        await conn.rollback()
        assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_trophy_showcase WHERE asset_instance_id=%s",(aid,)))==1
    finally: await conn.close()
    conn=await connect(**creds())
    try:
        await conn.start_transaction(); await transfer_provenance(conn,aid,10,20,'xfer-ok'); await conn.commit()
        assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_trophy_showcase WHERE asset_instance_id=%s",(aid,)))==0
        await raw(conn,"INSERT INTO asset_trophy_showcase(guild_id,user_id,slot_index,asset_instance_id,created_at,updated_at) VALUES(1,20,1,%s,%s,%s)",(aid,now_s(),now_s())); await conn.commit()
        await conn.start_transaction()
        with pytest.raises(RuntimeError): await release_provenance(conn,aid,20,'sale-fail',fail_after_cleanup=True)
        await conn.rollback(); assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_trophy_showcase WHERE asset_instance_id=%s",(aid,)))==1
        await conn.start_transaction(); assert await release_provenance(conn,aid,20,'sale-ok'); await conn.commit(); assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_trophy_showcase WHERE asset_instance_id=%s",(aid,)))==0
        ts=now_s(); await raw(conn,"INSERT INTO asset_ownership_history(instance_id,guild_id,owner_type,owner_id,acquisition_type,acquired_at,active_slot,event_key,created_at,updated_at) VALUES(%s,1,'user',20,'reacquire',%s,1,'reacquire:1',%s,%s)",(aid,ts,ts,ts)); await conn.commit()
        assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_trophy_showcase WHERE asset_instance_id=%s",(aid,)))==0
    finally: await conn.close()
