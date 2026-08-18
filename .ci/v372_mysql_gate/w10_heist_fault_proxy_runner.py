from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

import w10_heist_constructor_compat_runner as runner


class FaultConnection:
    """Fault-injection proxy that preserves normal connection attributes.

    The previous proxy delegated reads through __getattr__ but did not delegate
    assignments such as ``conn.row_factory = aiosqlite.Row``. That changed the
    behavior of the real Heist get_lobby/lobby_members reads before the injected
    wallet failure was even reached. This proxy forwards both reads and writes
    while keeping only the fault-control fields local.
    """

    def __init__(self, inner: Any, trip: dict[str, bool]) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_trip", trip)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_inner", "_trip"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._inner, name, value)

    async def execute(self, sql: str, parameters=()):
        cur = await self._inner.execute(sql, parameters)
        normalized = " ".join(str(sql).split()).lower()
        if not self._trip["done"] and normalized.startswith("update users set wallet=?"):
            self._trip["done"] = True
            raise RuntimeError("W10 injected failure after first Heist wallet UPDATE")
        return cur


class FaultConnectContext(AbstractAsyncContextManager[Any]):
    def __init__(self, original_factory: Any, trip: dict[str, bool], *args: Any, **kwargs: Any) -> None:
        self._ctx = original_factory(*args, **kwargs)
        self._trip = trip

    async def __aenter__(self) -> Any:
        inner = await self._ctx.__aenter__()
        return FaultConnection(inner, self._trip)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return await self._ctx.__aexit__(exc_type, exc, tb)


# Replace only the W10 fault-injection transport. The frozen v3.72 HeistService,
# Database/db_backend code and all contract assertions remain unchanged.
runner.gate.FaultConnectContext = FaultConnectContext


if __name__ == "__main__":
    raise SystemExit(runner.main())
