"""Tests for cursor pagination: payload round-trip, HMAC encoder, and the
generic AsyncMongoCursorPaginationStrategy (forward/backward navigation,
$and merge with a base query, and storage-type-agnostic keyset comparison)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from midil.midilapi.pagination.strategies.cursor.config import HMACCursorConfig
from midil.midilapi.pagination.strategies.cursor.encoders.hmac import HMACCursorEncoder
from midil.midilapi.pagination.strategies.cursor.enums import PaginationDirection
from midil.midilapi.pagination.strategies.cursor.exceptions import (
    ExpiredCursorError,
    InvalidCursorError,
)
from midil.midilapi.pagination.strategies.cursor.models import CursorPayload

pytest.importorskip("bson", reason="cursor strategy needs the mongodb extra")

from midil.midilapi.pagination import (  # noqa: E402
    AsyncMongoCursorPaginationStrategy,
)


@pytest.fixture
def encoder() -> HMACCursorEncoder:
    return HMACCursorEncoder(config=HMACCursorConfig(secret_key="test-secret"))


# --------------------------------------------------------------------------- #
# CursorPayload round-trip through the encoder
# --------------------------------------------------------------------------- #


class TestPayloadRoundTrip:
    def test_naive_datetime_round_trips_as_datetime(self, encoder):
        dt = datetime(2026, 6, 15, 12, 30, 45, 123456)
        token = encoder.encode(CursorPayload(values={"created_at": dt, "id": "a"}))
        back = encoder.decode(token)
        assert back.values["created_at"] == dt
        assert isinstance(back.values["created_at"], datetime)
        assert back.values["id"] == "a"

    def test_aware_datetime_round_trips(self, encoder):
        dt = datetime(2026, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
        back = encoder.decode(encoder.encode(CursorPayload(values={"t": dt})))
        assert back.values["t"] == dt

    def test_iso_string_value_stays_a_string(self, encoder):
        """Staff stores created_at as an ISO string; it must NOT be coerced
        to datetime, or the keyset comparison would change types."""
        iso = "2026-06-15T12:30:45.123456Z"
        back = encoder.decode(encoder.encode(CursorPayload(values={"created_at": iso})))
        assert back.values["created_at"] == iso
        assert isinstance(back.values["created_at"], str)

    def test_direction_and_sort_preserved(self, encoder):
        back = encoder.decode(
            encoder.encode(
                CursorPayload(values={"id": "x"}, direction=PaginationDirection.PREV)
            )
        )
        assert back.direction == PaginationDirection.PREV


# --------------------------------------------------------------------------- #
# HMAC encoder security / robustness
# --------------------------------------------------------------------------- #


class TestEncoderSecurity:
    def test_tampered_payload_rejected(self, encoder):
        token = encoder.encode(CursorPayload(values={"id": "x"}))
        payload_b64, signature = token.split(".", 1)
        forged = payload_b64[:-2] + ("AA" if not payload_b64.endswith("AA") else "BB")
        with pytest.raises(InvalidCursorError):
            encoder.decode(f"{forged}.{signature}")

    def test_multi_dot_cursor_rejected(self, encoder):
        """A cursor with extra dots must not be silently truncated to two
        parts (the split(\".\", 1) fix keeps the whole signature segment)."""
        token = encoder.encode(CursorPayload(values={"id": "x"}))
        with pytest.raises(InvalidCursorError):
            encoder.decode(token + ".extra.parts")

    def test_single_segment_cursor_rejected(self, encoder):
        with pytest.raises(InvalidCursorError):
            encoder.decode("no-dot-here")

    def test_expired_cursor_rejected(self):
        enc = HMACCursorEncoder(
            config=HMACCursorConfig(secret_key="k", expires_in_seconds=900)
        )
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        token = enc.encode(CursorPayload(values={"id": "x"}, expires_at=past))
        with pytest.raises(ExpiredCursorError):
            enc.decode(token)


# --------------------------------------------------------------------------- #
# Fake async Mongo collection (minimal query/sort/limit semantics)
# --------------------------------------------------------------------------- #


def _match_field(value: Any, cond: Any) -> bool:
    if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
        if "$regex" in cond:
            flags = re.I if "i" in cond.get("$options", "") else 0
            return (
                value is not None
                and re.search(cond["$regex"], value, flags) is not None
            )
        for op, operand in cond.items():
            if op == "$lt" and not (value is not None and value < operand):
                return False
            if op == "$gt" and not (value is not None and value > operand):
                return False
            if op not in ("$lt", "$gt"):
                raise NotImplementedError(op)
        return True
    return value == cond


def _match(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for key, cond in query.items():
        if key == "$and":
            if not all(_match(doc, sub) for sub in cond):
                return False
        elif key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
        elif not _match_field(doc.get(key), cond):
            return False
    return True


class _FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs
        self._sort: List[tuple[str, int]] = []
        self._limit: int | None = None

    def sort(self, spec: List[tuple[str, int]]) -> "_FakeCursor":
        self._sort = spec
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._limit = n
        return self

    async def to_list(self, length: int | None = None) -> List[Dict[str, Any]]:
        docs = list(self._docs)
        for field, order in reversed(self._sort):  # stable, least- to most-significant
            docs.sort(key=lambda d: d[field], reverse=(order == -1))
        if self._limit is not None:
            docs = docs[: self._limit]
        return docs


class _FakeCollection:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs
        self.last_query: Dict[str, Any] | None = None

    def find(self, query: Dict[str, Any]) -> _FakeCursor:
        self.last_query = query
        return _FakeCursor([d for d in self._docs if _match(d, query)])


# --------------------------------------------------------------------------- #
# AsyncMongoCursorPaginationStrategy (staff-like: ISO-string created_at + str id)
# --------------------------------------------------------------------------- #


def _staff_docs() -> List[Dict[str, Any]]:
    docs = [
        {"id": f"id{i}", "created_at": f"2026-06-1{i}T00:00:00Z", "partner_id": "p1"}
        for i in range(5)
    ]
    docs.append(
        {"id": "other", "created_at": "2026-06-19T00:00:00Z", "partner_id": "p2"}
    )
    return docs


class TestMongoCursorStrategy:
    pytestmark = pytest.mark.asyncio

    def _strategy(self, coll, encoder, base_query=None):
        return AsyncMongoCursorPaginationStrategy(
            collection=coll,
            encoder=encoder,
            mapper=lambda d: d["id"],
            base_query=base_query or {"partner_id": "p1"},
            sort_fields=["created_at", "id"],
        )

    async def test_forward_pagination_full_walk(self, encoder):
        coll = _FakeCollection(_staff_docs())
        strat = self._strategy(coll, encoder)

        page1 = await strat.paginate(size=2)
        assert page1.items == ["id4", "id3"]  # DESC by created_at
        assert page1.prev is None
        assert page1.next is not None

        page2 = await strat.paginate(size=2, cursor=page1.next)
        assert page2.items == ["id2", "id1"]
        assert page2.prev is not None and page2.next is not None

        page3 = await strat.paginate(size=2, cursor=page2.next)
        assert page3.items == ["id0"]
        assert page3.next is None  # reached the end

    async def test_prev_cursor_navigates_back(self, encoder):
        coll = _FakeCollection(_staff_docs())
        strat = self._strategy(coll, encoder)

        page1 = await strat.paginate(size=2)
        page2 = await strat.paginate(size=2, cursor=page1.next)
        back = await strat.paginate(size=2, cursor=page2.prev)

        assert back.items == page1.items  # prev returns to the original page
        assert back.prev is None  # back at the very start

    async def test_base_query_filters_other_partner(self, encoder):
        coll = _FakeCollection(_staff_docs())
        strat = self._strategy(coll, encoder)
        # Walk everything; "other" (partner p2) must never appear.
        seen: List[str] = []
        cursor = None
        while True:
            page = await strat.paginate(size=2, cursor=cursor)
            seen.extend(page.items)
            if not page.next:
                break
            cursor = page.next
        assert "other" not in seen
        assert sorted(seen) == ["id0", "id1", "id2", "id3", "id4"]

    async def test_search_or_not_clobbered_by_cursor_or(self, encoder):
        """A base_query with its own top-level $or (text search) must survive
        being combined with the cursor keyset $or."""
        coll = _FakeCollection(_staff_docs())
        base = {
            "partner_id": "p1",
            "$or": [{"id": "id4"}, {"id": "id3"}, {"id": "id2"}],
        }
        strat = self._strategy(coll, encoder, base_query=base)

        page1 = await strat.paginate(size=1)
        assert page1.items == ["id4"]
        page2 = await strat.paginate(size=1, cursor=page1.next)
        assert page2.items == ["id3"]  # search filter still applied after cursor
        page3 = await strat.paginate(size=1, cursor=page2.next)
        assert page3.items == ["id2"]
        assert page3.next is None  # id1/id0 excluded by the search $or
