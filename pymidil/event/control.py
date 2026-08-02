"""Consumer control enforcement (data-plane side).

A consumer polls its *desired* control state from the Midil Observatory and
honours it: ``paused``/``draining`` stop pulling, ``throttled`` caps the pull
rate, ``running`` consumes normally. The state is cached for a short TTL so
enforcement never hammers the control plane, and any lookup error *fails open*
(keep consuming) — a control-plane hiccup must not wedge the data plane.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    import httpx
from loguru import logger


class ControlState(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    THROTTLED = "throttled"
    DRAINING = "draining"

    @property
    def should_pull(self) -> bool:
        """Whether the consumer should pull messages at all (throttled still does)."""
        return self in (ControlState.RUNNING, ControlState.THROTTLED)


@dataclass(frozen=True)
class Control:
    state: ControlState = ControlState.RUNNING
    throttle_per_sec: Optional[float] = None


class ControlSource(Protocol):
    async def get(self) -> Control:
        ...


class NullControlSource:
    """Always running — the default when no control plane is wired."""

    async def get(self) -> Control:
        return Control(ControlState.RUNNING)


class HttpControlSource:
    """Polls ``GET {base_url}/v1/consumers/{consumer}/control``, cached for ``ttl`` s.

    ``httpx`` is imported lazily so the module loads without the optional http
    dependency. Lookup errors fail open to the last-known state (running).
    """

    def __init__(
        self,
        base_url: str,
        consumer: str,
        *,
        api_key: Optional[str] = None,
        ttl: float = 5.0,
        timeout: float = 3.0,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/v1/consumers/{consumer}/control"
        self._ttl = ttl
        self._timeout = timeout
        # Control polling is a data-plane surface — same Observatory API key the
        # telemetry sink uses; unset only in open/dev deployments.
        self._headers = {"X-Api-Key": api_key} if api_key else {}
        self._cached = Control(ControlState.RUNNING)
        self._fetched_at = 0.0
        self._client: Optional["httpx.AsyncClient"] = None

    async def get(self) -> Control:
        now = time.monotonic()
        if self._client is not None and (now - self._fetched_at) < self._ttl:
            return self._cached
        try:
            import httpx

            if self._client is None:
                self._client = httpx.AsyncClient(
                    timeout=self._timeout, headers=self._headers
                )
            resp = await self._client.get(self._url)
            resp.raise_for_status()
            data = resp.json()["data"]
            self._cached = Control(
                state=ControlState(data["state"]),
                throttle_per_sec=data.get("throttle_per_sec"),
            )
        except Exception as e:  # fail open — never let control lookups stop consumption
            logger.error(f"Error fetching control state from {self._url}: {e}")
            pass
        self._fetched_at = now
        return self._cached

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
