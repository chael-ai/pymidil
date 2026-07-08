"""Unit tests for consumer control enforcement (data-plane side)."""

import pytest

from pymidil.event.control import (
    Control,
    ControlState,
    HttpControlSource,
    NullControlSource,
)

pytestmark = pytest.mark.anyio


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, *, payload=None, raises=None):
        self._payload = payload
        self._raises = raises

    async def get(self, url):
        if self._raises is not None:
            raise self._raises
        return _FakeResp(self._payload)


def test_should_pull_by_state():
    assert ControlState.RUNNING.should_pull is True
    assert ControlState.THROTTLED.should_pull is True  # still pulls, capped
    assert ControlState.PAUSED.should_pull is False
    assert ControlState.DRAINING.should_pull is False


async def test_null_source_is_always_running():
    assert (await NullControlSource().get()) == Control(ControlState.RUNNING)


async def test_http_source_parses_state_and_rate():
    src = HttpControlSource("http://obs", "loyalty-svc", ttl=0.0)
    src._client = _FakeClient(
        payload={"data": {"state": "throttled", "throttle_per_sec": 25}}
    )
    got = await src.get()
    assert got.state is ControlState.THROTTLED
    assert got.throttle_per_sec == 25


async def test_http_source_fails_open_on_error():
    # a control-plane hiccup must never wedge the consumer — keep last-known (running)
    src = HttpControlSource("http://obs", "x", ttl=0.0)
    src._client = _FakeClient(raises=RuntimeError("connection refused"))
    assert (await src.get()).state is ControlState.RUNNING
