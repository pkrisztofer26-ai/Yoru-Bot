from __future__ import annotations

import asyncio
import inspect

import w10_heist_canonical_runner as canonical


gate = canonical.gate
_original_install_support_stubs = gate.install_support_stubs


class _NullDependency:
    """Neutral dependency for constructor-only legacy/service wiring in W10.2."""

    def __getattr__(self, name: str):
        async def _async(*args, **kwargs):
            return None

        return _async


def _install_constructor_compat() -> None:
    _original_install_support_stubs()

    from app.services.heist import HeistService

    original_init = HeistService.__init__
    signature = inspect.signature(original_init)
    parameters = signature.parameters

    def compat_init(self, *args, **kwargs):
        # Ignore only constructor kwargs that the frozen v3.72 service does not
        # accept. This adapts the test harness, not Heist settlement behavior.
        accepted_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in parameters and key != "self"
        }
        positional_names = [
            name
            for name, parameter in parameters.items()
            if name != "self"
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ][: len(args)]
        for name, parameter in parameters.items():
            if name == "self" or name in positional_names or name in accepted_kwargs:
                continue
            if parameter.kind not in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                continue
            if parameter.default is inspect.Parameter.empty:
                accepted_kwargs[name] = _NullDependency()
        return original_init(self, *args, **accepted_kwargs)

    HeistService.__init__ = compat_init


gate.install_support_stubs = _install_constructor_compat


async def _assert_success_state(db, backend, gid, lobby_id, run_id, users):
    wallets = {uid: (await db.get_balance(gid, uid))[0] for uid in users}
    expected = {users[0]: 700_000, users[1]: 500_000}
    if wallets != expected:
        raise AssertionError(f"Heist payout mismatch: {wallets!r} != {expected!r}")

    txs = await gate.backend_rows(
        backend,
        "SELECT user_id,amount,reason FROM transactions WHERE guild_id=? AND reason LIKE ? ORDER BY user_id",
        (gid, f"heist_payout:{lobby_id}:%"),
    )
    if len(txs) != 2 or sum(int(row[1]) for row in txs) != 1_000_000:
        raise AssertionError(f"Heist transaction ledger mismatch: {txs!r}")

    run_row = await gate.backend_row(
        backend,
        "SELECT status,success,total_reward,phase FROM heist_runs WHERE guild_id=? AND run_id=?",
        (gid, run_id),
    )
    lobby_row = await gate.backend_row(
        backend,
        "SELECT status,phase FROM heist_lobbies WHERE guild_id=? AND lobby_id=?",
        (gid, lobby_id),
    )
    vehicle_count = await gate.backend_row(
        backend,
        "SELECT COUNT(*) FROM heist_vehicle_choices WHERE guild_id=? AND lobby_id=?",
        (gid, lobby_id),
    )
    earned = await gate.backend_rows(
        backend,
        "SELECT user_id,value FROM user_statistics WHERE guild_id=? AND stat_name='economy.earned' ORDER BY user_id",
        (gid,),
    )
    peaks = await gate.backend_rows(
        backend,
        "SELECT user_id,value FROM user_statistics WHERE guild_id=? AND stat_name='economy.wallet_peak' ORDER BY user_id",
        (gid,),
    )

    if run_row is None or run_row[0] != "success" or int(run_row[1]) != 1 or int(run_row[2]) != 1_000_000 or int(run_row[3]) != 3:
        raise AssertionError(f"Heist run finalize mismatch: {run_row!r}")
    if lobby_row != ("finished", 3):
        raise AssertionError(f"Heist lobby finalize mismatch: {lobby_row!r}")
    if vehicle_count != (0,):
        raise AssertionError(f"Heist vehicle choices were not cleared: {vehicle_count!r}")
    if {int(uid): int(value) for uid, value in earned} != {users[0]: 600_000, users[1]: 400_000}:
        raise AssertionError(f"Heist earned stats mismatch: {earned!r}")
    if {int(uid): int(value) for uid, value in peaks} != expected:
        raise AssertionError(f"Heist wallet peak mismatch: {peaks!r}")

    return {
        "wallets": wallets,
        "transaction_rows": len(txs),
        "ledger_payout_total": sum(int(row[1]) for row in txs),
        "run_status": run_row[0],
        "lobby_status": lobby_row[0],
        "vehicle_choices_after": 0,
    }


async def _success_contract(service, db, backend, gid, lobby_id, run_id, users):
    run = await gate.seed_case(db, backend, gid, lobby_id, run_id, users)
    phase_results = list(run["phase_results"])
    result = await service._resolve_run(gid, lobby_id, run, phase_results)
    if not bool(result.get("success")) or int(result.get("total_reward", -1)) != 1_000_000:
        raise AssertionError(f"Unexpected Heist success result: {result!r}")
    state = await _assert_success_state(db, backend, gid, lobby_id, run_id, users)
    state["result_total_reward"] = int(result["total_reward"])
    return state


async def _exactly_once_contract(service, db, backend, gid, lobby_id, run_id, users):
    run = await gate.seed_case(db, backend, gid, lobby_id, run_id, users)
    phase_results = list(run["phase_results"])
    outcomes = await asyncio.gather(
        service._resolve_run(gid, lobby_id, dict(run), list(phase_results)),
        service._resolve_run(gid, lobby_id, dict(run), list(phase_results)),
        return_exceptions=True,
    )
    successes = [item for item in outcomes if isinstance(item, dict)]
    failures = [item for item in outcomes if isinstance(item, BaseException)]
    if len(successes) != 1 or len(failures) != 1 or not isinstance(failures[0], ValueError):
        raise AssertionError(f"Heist concurrent resolve outcome mismatch: {outcomes!r}")
    state = await _assert_success_state(db, backend, gid, lobby_id, run_id, users)
    state.update(
        {
            "parallel_calls": 2,
            "authoritative_resolves": 1,
            "rejected_replays": 1,
            "replay_error": str(failures[0]),
        }
    )
    return state


async def _rollback_contract(service, heist_module, db, backend, gid, lobby_id, run_id, users):
    run = await gate.seed_case(db, backend, gid, lobby_id, run_id, users)
    original_connect = backend.connect
    trip = {"done": False}

    def faulty_connect(*args, **kwargs):
        return gate.FaultConnectContext(original_connect, trip, *args, **kwargs)

    backend.connect = faulty_connect
    try:
        try:
            await service._resolve_run(gid, lobby_id, run, list(run["phase_results"]))
            raise AssertionError("Injected Heist failure did not abort settlement")
        except RuntimeError as exc:
            if "W10 injected failure" not in str(exc):
                raise
    finally:
        backend.connect = original_connect

    if not trip["done"]:
        raise AssertionError("Injected Heist wallet failure was never reached")

    wallets = {uid: (await db.get_balance(gid, uid))[0] for uid in users}
    if wallets != {users[0]: 100_000, users[1]: 100_000}:
        raise AssertionError(f"Heist rollback left partial wallet writes: {wallets!r}")

    run_row = await gate.backend_row(
        backend,
        "SELECT status,phase,success,total_reward FROM heist_runs WHERE guild_id=? AND run_id=?",
        (gid, run_id),
    )
    lobby_row = await gate.backend_row(
        backend,
        "SELECT status,phase FROM heist_lobbies WHERE guild_id=? AND lobby_id=?",
        (gid, lobby_id),
    )
    tx_count = await gate.backend_row(
        backend,
        "SELECT COUNT(*) FROM transactions WHERE guild_id=? AND reason LIKE ?",
        (gid, f"heist_payout:{lobby_id}:%"),
    )
    vehicle_count = await gate.backend_row(
        backend,
        "SELECT COUNT(*) FROM heist_vehicle_choices WHERE guild_id=? AND lobby_id=?",
        (gid, lobby_id),
    )
    stat_count = await gate.backend_row(
        backend,
        "SELECT COUNT(*) FROM user_statistics WHERE guild_id=? AND stat_name IN ('economy.earned','economy.wallet_peak')",
        (gid,),
    )

    if run_row is None or run_row[0] != "running" or int(run_row[1]) != 2 or run_row[2] is not None or int(run_row[3]) != 0:
        raise AssertionError(f"Heist run claim/finalize was not rolled back: {run_row!r}")
    if lobby_row != ("running", 2):
        raise AssertionError(f"Heist lobby changed despite rollback: {lobby_row!r}")
    if tx_count != (0,) or vehicle_count != (2,) or stat_count != (0,):
        raise AssertionError(
            f"Heist rollback side effects mismatch: tx={tx_count}, vehicles={vehicle_count}, stats={stat_count}"
        )

    return {
        "injected_after_first_wallet_update": True,
        "wallets_after": wallets,
        "run_status_after": run_row[0],
        "lobby_status_after": lobby_row[0],
        "transaction_rows_after": 0,
        "vehicle_choices_after": 2,
        "authoritative_stats_after": 0,
    }


# Replace only stale W10.2 harness contracts. The frozen RC3 HeistService and its
# authoritative transaction implementation remain untouched.
gate.assert_success_state = _assert_success_state
gate.success_contract = _success_contract
gate.exactly_once_contract = _exactly_once_contract
gate.rollback_contract = _rollback_contract


if __name__ == "__main__":
    raise SystemExit(gate.main())
