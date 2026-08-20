from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class TaskSupervisor:
    """Own long-lived/background asyncio tasks and shut them down deterministically.

    Discord.py owns gateway-dispatch tasks itself, but Yoru also starts detached
    timers, audit deliveries and background workers.  Those tasks must have a
    strong reference, named ownership scope and a single shutdown path so they
    cannot silently disappear or survive a Cog/service reload.
    """

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("vaultbot.runtime")
        self._tasks: set[asyncio.Task[Any]] = set()
        self._scopes: dict[str, set[asyncio.Task[Any]]] = defaultdict(set)
        self._closing = False

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    def scope_count(self, scope: str) -> int:
        return len(self._scopes.get(str(scope), ()))

    def snapshot(self) -> dict[str, int]:
        return {
            scope: len(tasks)
            for scope, tasks in sorted(self._scopes.items())
            if tasks
        }

    def create(
        self,
        coro: Coroutine[Any, Any, T] | Awaitable[T],
        *,
        name: str | None = None,
        scope: str = "global",
    ) -> asyncio.Task[T]:
        if self._closing:
            if isinstance(coro, Coroutine):
                coro.close()
            raise RuntimeError("A TaskSupervisor már leállítás alatt van; új task nem indítható.")
        task = asyncio.create_task(coro, name=name)
        return self.track(task, scope=scope)

    def track(self, task: asyncio.Task[T], *, scope: str = "global") -> asyncio.Task[T]:
        if self._closing:
            task.cancel()
            return task

        scope = str(scope or "global")
        self._tasks.add(task)
        self._scopes[scope].add(task)

        def _done(done: asyncio.Task[Any]) -> None:
            self._tasks.discard(done)
            scoped = self._scopes.get(scope)
            if scoped is not None:
                scoped.discard(done)
                if not scoped:
                    self._scopes.pop(scope, None)

            if done.cancelled():
                return
            try:
                exc = done.exception()
            except asyncio.CancelledError:
                return
            except Exception:
                self._logger.exception("Nem sikerült lekérni a background task állapotát: %s", done.get_name())
                return
            if exc is not None:
                self._logger.error(
                    "Background task hibával állt le: name=%s scope=%s",
                    done.get_name(),
                    scope,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

        task.add_done_callback(_done)
        return task

    async def cancel_scope(self, scope: str, *, timeout: float = 10.0) -> None:
        tasks = list(self._scopes.get(str(scope), ()))
        if not tasks:
            return
        for task in tasks:
            if not task.done():
                task.cancel()
        await self._wait(tasks, timeout=timeout, reason=f"scope:{scope}")

    async def shutdown(self, *, timeout: float = 15.0) -> None:
        if self._closing:
            return
        self._closing = True
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        await self._wait(tasks, timeout=timeout, reason="shutdown")
        self._tasks.clear()
        self._scopes.clear()

    async def _wait(self, tasks: list[asyncio.Task[Any]], *, timeout: float, reason: str) -> None:
        if not tasks:
            return
        done, pending = await asyncio.wait(tasks, timeout=max(0.0, float(timeout)))
        # Force exception retrieval for finished tasks. The regular callback also
        # observes them, but doing it here makes shutdown deterministic.
        for task in done:
            if task.cancelled():
                continue
            try:
                task.exception()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if pending:
            names = ", ".join(sorted(task.get_name() for task in pending)[:12])
            self._logger.warning(
                "Background task shutdown timeout (%s): %s task még fut%s%s",
                reason,
                len(pending),
                ": " if names else "",
                names,
            )

# Test/standalone fallback. Production VaultBot always provides a TaskSupervisor;
# this set only keeps tasks alive for services/cogs instantiated without it.
_FALLBACK_TASKS: set[asyncio.Task[Any]] = set()


def spawn_background(
    coro: Coroutine[Any, Any, T] | Awaitable[T],
    *,
    owner: Any | None = None,
    supervisor: TaskSupervisor | None = None,
    name: str | None = None,
    scope: str = "global",
) -> asyncio.Task[T]:
    """Create a strongly-owned background task.

    ``owner`` may be a VaultBot/Cog-related object exposing ``background_tasks``.
    The explicit ``supervisor`` parameter is useful for services that are bound
    to the process runtime without importing Discord types.
    """
    runtime = supervisor or getattr(owner, "background_tasks", None)
    if isinstance(runtime, TaskSupervisor):
        return runtime.create(coro, name=name, scope=scope)

    task = asyncio.create_task(coro, name=name)
    _FALLBACK_TASKS.add(task)

    def _done(done: asyncio.Task[Any]) -> None:
        _FALLBACK_TASKS.discard(done)
        if done.cancelled():
            return
        try:
            done.exception()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    task.add_done_callback(_done)
    return task

async def cancel_discord_loop(loop: Any) -> None:
    """Cancel a ``discord.ext.tasks.Loop`` and await its underlying Task.

    ``Loop.cancel()`` is synchronous and only requests cancellation. Awaiting the
    retained task prevents extension reload/shutdown from leaving an old Cog
    callback alive for another event-loop turn or an in-flight DB await.
    """
    task = None
    try:
        task = loop.get_task()
    except Exception:
        task = None
    try:
        loop.cancel()
    except Exception:
        return
    if task is None or task is asyncio.current_task() or task.done():
        return
    await asyncio.gather(task, return_exceptions=True)

