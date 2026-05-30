"""Task supervision for long-running async services.

The :class:`TaskSupervisor` runs background coroutines and keeps them alive:
if a supervised task crashes with an unexpected exception it is restarted with
exponential backoff (bounded by an optional max-restart budget). This is the
backbone that keeps websocket streams, the event-bus worker, schedulers and the
trading loop running unattended for weeks.

It also coordinates **graceful shutdown**: installing OS signal handlers
(SIGINT/SIGTERM) that trigger an orderly stop of every supervised task.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

from quantbot.core.logging import get_logger
from quantbot.core.utils import utcnow

_log = get_logger(__name__)

#: A factory returning the coroutine to (re)run for a supervised service.
TaskFactory = Callable[[], Awaitable[None]]


class TaskState(str, Enum):
    """Lifecycle state of a supervised task."""

    PENDING = "pending"
    RUNNING = "running"
    RESTARTING = "restarting"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class SupervisedTask:
    """Bookkeeping for one supervised service."""

    name: str
    factory: TaskFactory
    restart: bool = True
    max_restarts: int | None = None
    base_delay: float = 1.0
    max_delay: float = 30.0
    factor: float = 2.0
    critical: bool = False
    """If True, exhausting the restart budget triggers a supervisor shutdown."""

    state: TaskState = TaskState.PENDING
    restarts: int = 0
    last_error: str | None = None
    started_at: object | None = None
    _task: asyncio.Task[None] | None = field(default=None, repr=False)


class TaskSupervisor:
    """Supervise and auto-restart a set of long-running async tasks."""

    def __init__(self, *, install_signal_handlers: bool = False) -> None:
        self._tasks: dict[str, SupervisedTask] = {}
        self._shutdown = asyncio.Event()
        self._install_signals = install_signal_handlers
        self._running = False
        self._on_critical_failure: Callable[[str], Awaitable[None]] | None = None

    # ------------------------------------------------------------------ register

    def add(
        self,
        name: str,
        factory: TaskFactory,
        *,
        restart: bool = True,
        max_restarts: int | None = None,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        factor: float = 2.0,
        critical: bool = False,
    ) -> SupervisedTask:
        """Register a service to be supervised.

        Args:
            name: Unique service name.
            factory: Zero-arg callable returning the coroutine to run; called
                afresh on every (re)start so the service can reinitialise.
            restart: Whether to restart on unexpected failure.
            max_restarts: Maximum restarts before marking the task FAILED
                (``None`` = unlimited).
            base_delay/max_delay/factor: Backoff parameters between restarts.
            critical: If the restart budget is exhausted, shut the whole
                supervisor down (used for indispensable services).
        """
        if name in self._tasks:
            raise ValueError(f"Task {name!r} already registered")
        sup = SupervisedTask(
            name=name,
            factory=factory,
            restart=restart,
            max_restarts=max_restarts,
            base_delay=base_delay,
            max_delay=max_delay,
            factor=factor,
            critical=critical,
        )
        self._tasks[name] = sup
        if self._running:
            self._launch(sup)
        return sup

    def on_critical_failure(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Register a coroutine invoked when a critical task fails permanently."""
        self._on_critical_failure = callback

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Launch all registered tasks and (optionally) install signal handlers."""
        if self._running:
            return
        self._running = True
        self._shutdown.clear()
        if self._install_signals:
            self._setup_signal_handlers()
        for sup in self._tasks.values():
            self._launch(sup)
        _log.info("supervisor_started", tasks=list(self._tasks))

    def _launch(self, sup: SupervisedTask) -> None:
        sup.state = TaskState.PENDING
        sup._task = asyncio.create_task(self._supervise(sup), name=f"sup:{sup.name}")

    async def _supervise(self, sup: SupervisedTask) -> None:
        """Run *sup*'s coroutine, restarting on failure with backoff."""
        while not self._shutdown.is_set():
            sup.state = TaskState.RUNNING
            sup.started_at = utcnow()
            try:
                await sup.factory()
                # Clean completion → do not restart.
                sup.state = TaskState.STOPPED
                _log.info("task_completed", task=sup.name)
                return
            except asyncio.CancelledError:
                sup.state = TaskState.STOPPED
                _log.debug("task_cancelled", task=sup.name)
                raise
            except Exception as exc:  # noqa: BLE001 - supervisor catches everything
                sup.last_error = str(exc)
                _log.error(
                    "task_crashed",
                    task=sup.name,
                    error=str(exc),
                    restarts=sup.restarts,
                    exc_info=True,
                )
                if not sup.restart or self._shutdown.is_set():
                    sup.state = TaskState.FAILED
                    return
                if sup.max_restarts is not None and sup.restarts >= sup.max_restarts:
                    sup.state = TaskState.FAILED
                    _log.critical("task_restart_exhausted", task=sup.name)
                    await self._handle_permanent_failure(sup)
                    return

                sup.restarts += 1
                delay = min(sup.base_delay * (sup.factor ** (sup.restarts - 1)), sup.max_delay)
                sup.state = TaskState.RESTARTING
                _log.warning("task_restarting", task=sup.name, delay=round(delay, 2))
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=delay)
                    return  # shutdown requested during backoff
                except TimeoutError:
                    continue

    async def _handle_permanent_failure(self, sup: SupervisedTask) -> None:
        if sup.critical:
            _log.critical("critical_task_failed_triggering_shutdown", task=sup.name)
            if self._on_critical_failure is not None:
                with contextlib.suppress(Exception):
                    await self._on_critical_failure(sup.name)
            self.request_shutdown()

    async def stop(self, *, timeout: float = 30.0) -> None:
        """Signal shutdown and await all tasks to finish (cancelling if needed)."""
        if not self._running:
            return
        _log.info("supervisor_stopping")
        self.request_shutdown()
        tasks = [s._task for s in self._tasks.values() if s._task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            for task in pending:  # pragma: no cover - only on hung tasks
                _log.warning("task_did_not_stop", task=task.get_name())
        self._running = False
        _log.info("supervisor_stopped")

    def request_shutdown(self) -> None:
        """Idempotently signal all tasks to wind down."""
        self._shutdown.set()

    async def wait(self) -> None:
        """Block until a shutdown is requested (e.g. via signal)."""
        await self._shutdown.wait()

    async def run_forever(self) -> None:
        """Start, wait for shutdown, then stop — the typical service entrypoint."""
        await self.start()
        try:
            await self.wait()
        finally:
            await self.stop()

    # ------------------------------------------------------------------ signals

    def _setup_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._on_signal, sig)
            except (NotImplementedError, RuntimeError):  # pragma: no cover - Windows
                _log.debug("signal_handler_unavailable", signal=sig)

    def _on_signal(self, sig: signal.Signals) -> None:
        _log.info("signal_received", signal=getattr(sig, "name", str(sig)))
        self.request_shutdown()

    # ------------------------------------------------------------------ introspection

    def status(self) -> dict[str, dict[str, object]]:
        """Return a snapshot of every task's state for health endpoints."""
        return {
            name: {
                "state": sup.state.value,
                "restarts": sup.restarts,
                "last_error": sup.last_error,
                "critical": sup.critical,
            }
            for name, sup in self._tasks.items()
        }

    @property
    def healthy(self) -> bool:
        """True if no supervised task is in a FAILED state."""
        return all(s.state is not TaskState.FAILED for s in self._tasks.values())

    async def __aenter__(self) -> TaskSupervisor:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()


__all__ = ["SupervisedTask", "TaskState", "TaskSupervisor", "TaskFactory"]
