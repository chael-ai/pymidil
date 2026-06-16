"""Tests for offset pagination after aligning the page-size vocabulary on
`size` (the `limit` field/param was removed)."""

from __future__ import annotations

import pytest
from starlette.datastructures import URL

from midil.midilapi.pagination import OffsetPage, OffsetPageMapper


def test_offset_page_uses_size_not_limit():
    page = OffsetPage[int](items=[1, 2, 3], size=3, offset=6, total=20)
    assert page.size == 3
    assert page.offset == 6
    assert page.total == 20
    assert not hasattr(page, "limit")


def test_offset_page_rejects_size_below_one():
    with pytest.raises(ValueError):
        OffsetPage[int](items=[], size=0, offset=0, total=0)


class _IntMapper:
    """Minimal ResourceMapper stand-in; OffsetPageMapper only needs .map()."""

    def map(self, item):  # pragma: no cover - trivial
        return item


class TestOffsetPageMapperLinks:
    def _mapper(self):
        return OffsetPageMapper(mapper=_IntMapper())

    def test_meta_reports_size(self):
        page = OffsetPage[int](items=[1, 2], size=2, offset=0, total=10)
        meta = self._mapper().meta(page=page)
        assert meta == {"total": 10, "size": 2, "offset": 0}
        assert "limit" not in meta

    def test_links_use_size_query_param(self):
        page = OffsetPage[int](items=[1, 2], size=2, offset=2, total=10)
        url = URL("http://x/items?offset=2&size=2")
        links = self._mapper().links(page=page, url=url)
        assert "size=2" in links.next
        assert "offset=4" in links.next  # offset + size
        assert "limit" not in links.next
        assert "size=2" in links.prev
        assert "offset=0" in links.prev  # max(offset - size, 0)

    def test_no_next_on_last_page(self):
        page = OffsetPage[int](items=[1, 2], size=2, offset=8, total=10)
        links = self._mapper().links(
            page=page, url=URL("http://x/items?offset=8&size=2")
        )
        assert links.next is None  # offset + size == total

    def test_no_prev_on_first_page(self):
        page = OffsetPage[int](items=[1, 2], size=2, offset=0, total=10)
        links = self._mapper().links(
            page=page, url=URL("http://x/items?offset=0&size=2")
        )
        assert links.prev is None
