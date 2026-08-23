from native_support import *

@pytest.mark.asyncio
async def test_05_active_listing_uniqueness_under_concurrency():
    conn=await connect(**creds())
    try: aid=await seed_asset(conn,'collectible','r1',10); await conn.commit()
    finally: await conn.close()
    async def worker():
        conn=await connect(**creds())
        try:
            await writer_lock(conn); await conn.start_transaction()
            try:
                await create_listing(conn,aid,10); await conn.commit(); return True
            except IntegrityError:
                await conn.rollback(); return False
        finally:
            await writer_unlock(conn); await conn.close()
    result=await asyncio.gather(*(worker() for _ in range(6)))
    assert sum(bool(x) for x in result)==1
    conn=await connect(**creds())
    try: assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_auction_listings WHERE active_slot=1"))==1
    finally: await conn.close()


@pytest.mark.asyncio
async def test_06_bid_request_idempotency_outbid_refund_conservation():
    conn=await connect(**creds())
    try:
        await seed_user(conn,10,1000000); await seed_user(conn,20,1000000); await seed_user(conn,30,1000000)
        aid=await seed_asset(conn,'collectible','r2',10); auction=await create_listing(conn,aid,10); await conn.commit()
    finally: await conn.close()
    assert await place_bid_native(auction,20,120000,'req-1')
    assert await place_bid_native(auction,20,120000,'req-1')
    results=await asyncio.gather(place_bid_native(auction,20,150000,'req-2'),place_bid_native(auction,30,160000,'req-3'),return_exceptions=True)
    assert any(x is True for x in results)
    conn=await connect(**creds())
    try:
        lead=(await rows(conn,"SELECT bidder_id,amount,wallet_reserved,bank_reserved FROM asset_auction_bids WHERE auction_id=%s AND status='leading'",(auction,)))[0]
        assert int(lead[1])==160000
        balances={int(r[0]):int(r[1])+int(r[2]) for r in await rows(conn,"SELECT user_id,wallet,bank FROM users WHERE user_id IN (20,30)")}
        assert balances[int(lead[0])]==840000
        other=20 if int(lead[0])==30 else 30
        assert balances[other]==1000000
        assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_auction_bids WHERE auction_id=%s AND request_ref='req-1'",(auction,)))==1
    finally: await conn.close()


@pytest.mark.asyncio
async def test_07_exactly_once_settlement_and_restart_recovery():
    conn=await connect(**creds())
    try:
        await seed_user(conn,10,100000); await seed_user(conn,20,1000000)
        aid=await seed_asset(conn,'collectible','r3',10); auction=await create_listing(conn,aid,10); await conn.commit()
    finally: await conn.close()
    await place_bid_native(auction,20,200000,'win')
    result=await asyncio.gather(*(settle_native(auction) for _ in range(5)))
    assert result.count('sold')==5
    conn=await connect(**creds())
    try:
        assert int(await scalar(conn,"SELECT wallet FROM users WHERE user_id=10"))==290000
        assert int(await scalar(conn,"SELECT COUNT(*) FROM transactions WHERE user_id=10 AND reason=%s",(f"asset_auction_sale:{auction}:{aid}",)))==1
        assert int(await scalar(conn,"SELECT owner_id FROM asset_ownership_history WHERE instance_id=%s AND active_slot=1",(aid,)))==20
        assert int(await scalar(conn,"SELECT COUNT(*) FROM asset_ownership_history WHERE instance_id=%s",(aid,)))==2
        assert str(await scalar(conn,"SELECT status FROM asset_auction_listings WHERE auction_id=%s",(auction,)))=='sold'
    finally: await conn.close()
    assert await settle_native(auction)=='sold'


@pytest.mark.asyncio
async def test_08_vehicle_source_payout_provenance_atomic_rollback_then_commit():
    conn=await connect(**creds())
    try:
        await seed_user(conn,10,100000); await seed_user(conn,20,1000000); ts=now_s()
        cur=await raw(conn,"INSERT INTO character_vehicles(guild_id,user_id,model_key,condition_key,city_key,purchase_price,estimated_value,status,acquired_at,updated_at) VALUES(1,10,'m','good','budapest',50000,100000,'owned',%s,%s)",(ts,ts)); vid=int(cur.lastrowid)
        await raw(conn,"INSERT INTO vehicle_state(vehicle_id,guild_id,user_id,is_primary,updated_at) VALUES(%s,1,10,1,%s)",(vid,ts))
        aid=await seed_asset(conn,'vehicle',str(vid),10); auction=await create_listing(conn,aid,10,start=200000); await conn.commit()
    finally: await conn.close()
    await place_bid_native(auction,20,200000,'vehicle-win')
    with pytest.raises(RuntimeError): await settle_native(auction,inject_failure=True)
    conn=await connect(**creds())
    try:
        assert int(await scalar(conn,"SELECT user_id FROM character_vehicles WHERE vehicle_id=%s",(vid,)))==10
        assert int(await scalar(conn,"SELECT owner_id FROM asset_ownership_history WHERE instance_id=%s AND active_slot=1",(aid,)))==10
        assert int(await scalar(conn,"SELECT wallet FROM users WHERE user_id=10"))==100000
        assert str(await scalar(conn,"SELECT status FROM asset_auction_listings WHERE auction_id=%s",(auction,)))=='active'
    finally: await conn.close()
    assert await settle_native(auction)=='sold'


@pytest.mark.asyncio
async def test_09_property_source_payout_provenance_atomic_rollback_then_commit():
    conn=await connect(**creds())
    try:
        await seed_user(conn,10,100000); await seed_user(conn,20,1000000); ts=now_s(); future=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
        cur=await raw(conn,"INSERT INTO housing_properties(guild_id,user_id,city_key,tier_key,purchase_price,maintenance_paid_until,status,acquired_at,updated_at) VALUES(1,10,'budapest','villa',500000,%s,'owned',%s,%s)",(future,ts,ts)); pid=int(cur.lastrowid)
        await raw(conn,"INSERT INTO housing_state(guild_id,user_id,tier_key,city_key,updated_at) VALUES(1,10,'villa','budapest',%s)",(ts,))
        aid=await seed_asset(conn,'property',str(pid),10); auction=await create_listing(conn,aid,10,start=300000); await conn.commit()
    finally: await conn.close()
    await place_bid_native(auction,20,300000,'property-win')
    with pytest.raises(RuntimeError): await settle_native(auction,inject_failure=True)
    conn=await connect(**creds())
    try:
        assert int(await scalar(conn,"SELECT user_id FROM housing_properties WHERE property_id=%s",(pid,)))==10
        assert int(await scalar(conn,"SELECT owner_id FROM asset_ownership_history WHERE instance_id=%s AND active_slot=1",(aid,)))==10
        assert int(await scalar(conn,"SELECT wallet FROM users WHERE user_id=10"))==100000
    finally: await conn.close()
    assert await settle_native(auction)=='sold'


@pytest.mark.asyncio
async def test_10_lifecycle_vs_auction_interlock_race():
    conn=await connect(**creds())
    try:
        await seed_user(conn,10,0); ts=now_s(); cur=await raw(conn,"INSERT INTO character_vehicles(guild_id,user_id,model_key,condition_key,city_key,purchase_price,estimated_value,status,acquired_at,updated_at) VALUES(1,10,'m','good','budapest',1,1,'owned',%s,%s)",(ts,ts)); vid=int(cur.lastrowid); aid=await seed_asset(conn,'vehicle',str(vid),10); await conn.commit()
    finally: await conn.close()
    async def auction_worker():
        conn=await connect(**creds())
        try:
            await writer_lock(conn); await conn.start_transaction()
            if str(await scalar(conn,"SELECT status FROM character_vehicles WHERE vehicle_id=%s FOR UPDATE",(vid,)))!='owned': await conn.rollback(); return False
            try: await create_listing(conn,aid,10); await conn.commit(); return True
            except IntegrityError: await conn.rollback(); return False
        finally: await writer_unlock(conn); await conn.close()
    async def sale_worker():
        conn=await connect(**creds())
        try:
            await writer_lock(conn); await conn.start_transaction()
            active=int(await scalar(conn,"SELECT COUNT(*) FROM asset_auction_listings WHERE asset_instance_id=%s AND status='active' AND active_slot=1",(aid,)) or 0)
            if active: await conn.rollback(); return False
            cur=await raw(conn,"UPDATE character_vehicles SET status='sold',sold_at=%s,updated_at=%s WHERE vehicle_id=%s AND user_id=10 AND status='owned'",(now_s(),now_s(),vid))
            if cur.rowcount!=1: await conn.rollback(); return False
            await release_provenance(conn,aid,10,'system-sale-race'); await conn.commit(); return True
        finally: await writer_unlock(conn); await conn.close()
    result=await asyncio.gather(auction_worker(),sale_worker())
    assert sum(bool(x) for x in result)==1
    conn=await connect(**creds())
    try:
        listing=int(await scalar(conn,"SELECT COUNT(*) FROM asset_auction_listings WHERE active_slot=1") or 0)
        owner=int(await scalar(conn,"SELECT COUNT(*) FROM asset_ownership_history WHERE instance_id=%s AND active_slot=1",(aid,)) or 0)
        status=str(await scalar(conn,"SELECT status FROM character_vehicles WHERE vehicle_id=%s",(vid,)))
        assert (listing==1 and owner==1 and status=='owned') or (listing==0 and owner==0 and status=='sold')
    finally: await conn.close()
