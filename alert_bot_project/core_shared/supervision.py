"""Fail visibly when a required service loop exits; always join owned tasks."""

import asyncio
import logging
from collections.abc import Callable, Coroutine, Mapping
from typing import Any


def run_service(main: Callable[[], Coroutine[Any, Any, None]], logger: logging.Logger) -> None:
    """Log through configured redacting sinks; do not print a raw traceback."""
    try:
        asyncio.run(main())
    except Exception:
        logger.exception("Service stopped after initialization or critical loop failure")
        raise SystemExit(1) from None


async def supervise(factories: Mapping[str, Callable[[], Coroutine[Any, Any, None]]], shutdown: asyncio.Event) -> None:
    """Own critical loops until shutdown, propagating failure for process restart.

    Factories avoid creating unawaited coroutines if startup fails. A normal
    return or independent cancellation before shutdown is also a failure.
    This detects termination, not lack of progress in a still-running loop.
    """
    if not factories:
        raise ValueError("At least one critical loop is required")
    tasks: dict[str, asyncio.Task[None]] = {}
    stopped = asyncio.create_task(shutdown.wait(), name="service-shutdown")
    try:
        if shutdown.is_set():
            return
        for name, factory in factories.items():
            tasks[name] = asyncio.create_task(factory(), name=name)
        done, _ = await asyncio.wait([stopped, *tasks.values()], return_when=asyncio.FIRST_COMPLETED)
        for name, task in tasks.items():
            if task not in done:
                continue
            if not task.cancelled() and (error := task.exception()) is not None:
                raise RuntimeError(f"Critical loop failed: {name}") from error
            if not shutdown.is_set():
                raise RuntimeError(f"Critical loop stopped unexpectedly: {name}")
    finally:
        shutdown.set()
        stopped.cancel()
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(stopped, *tasks.values(), return_exceptions=True)
