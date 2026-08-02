"""Run async coroutines from synchronous call sites (Django, Celery, …)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
from typing import Any


def run_sync(coro: Any) -> Any:
    """Drive ``coro`` to completion from sync code.

    Uses :func:`asyncio.run` when no loop is running. If already inside a
    loop (e.g. Channels / ASGI), runs the coroutine in a worker thread so
    the caller's thread is not blocked waiting on itself.

    The caller's :mod:`contextvars` context is copied into that worker thread
    so overrides set around the call (e.g. span-id capture for sync emit)
    remain visible during emission.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, coro).result()
