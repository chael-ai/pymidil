from __future__ import annotations

__all__ = ["AsyncMongoCursorPaginationStrategy"]


from typing import Any, Callable, Dict, Generic, List, TypeVar

try:
    from pymongo.asynchronous.collection import AsyncCollection
except ImportError as e:
    raise ImportError(
        "MongoDB support requires the 'mongodb' extra: pip install midil[mongodb]"
    ) from e

from pymidil.web.pagination.strategies.cursor.encoders.base import (
    CursorEncoder,
)
from pymidil.web.pagination.strategies.cursor.enums import PaginationDirection
from pymidil.web.pagination.strategies.cursor.page import CursorPage
from pymidil.web.pagination.strategies.cursor.base import (
    CursorPaginationStrategy,
    ItemT,
)
from pymidil.web.pagination.integrations.mongodb.builder import (
    CursorQueryBuilder,
    SortBuilder,
    PayloadBuilder,
)
from pymidil.web.pagination.integrations.mongodb.defaults import (
    DefaultCursorQueryBuilder,
    DefaultSortBuilder,
    DefaultPayloadBuilder,
)

_DocumentType = TypeVar("_DocumentType", bound=Dict[str, Any])


class AsyncMongoCursorPaginationStrategy(
    CursorPaginationStrategy[ItemT], Generic[ItemT]
):
    """
    Cursor-based pagination strategy for Async MongoDB collections.

    Follows SOLID:
    - Single Responsibility: Orchestrates pagination flow.
    - Open/Closed: Extensible via injected builders.
    - Dependency Inversion: Depends on abstractions (builders, encoder, mapper).
    """

    def __init__(
        self,
        *,
        collection: AsyncCollection[_DocumentType],
        encoder: CursorEncoder,
        mapper: Callable[[_DocumentType | Dict[str, Any]], ItemT],
        base_query: Dict[str, Any] | None = None,
        sort_fields: List[str] | None = None,
        query_builder: CursorQueryBuilder | None = None,
        sort_builder: SortBuilder | None = None,
        payload_builder: PayloadBuilder | None = None,
    ) -> None:
        self._collection = collection
        self._encoder = encoder
        self._mapper = mapper
        self._base_query = dict(base_query) if base_query else {}
        self._sort_fields = sort_fields or ["created_at", "_id"]

        self._query_builder = query_builder or DefaultCursorQueryBuilder()
        self._sort_builder = sort_builder or DefaultSortBuilder()
        self._payload_builder = payload_builder or DefaultPayloadBuilder()

    async def paginate(
        self,
        size: int,
        cursor: str | None = None,
    ) -> CursorPage[ItemT]:
        """
        Execute cursor-based pagination.

        Returns a page with items and opaque next/prev cursors.
        """
        query = await self._build_query(cursor)
        documents = await self._fetch_documents(query, size, cursor)

        items = [self._mapper(doc) for doc in documents.processed_docs]

        next_cursor = None
        prev_cursor = None

        if documents.processed_docs:
            next_cursor = self._build_next_cursor(documents, cursor, size)
            prev_cursor = self._build_prev_cursor(documents, cursor)

        return CursorPage(
            items=items,
            size=size,
            next=next_cursor,
            prev=prev_cursor,
        )

    async def _build_query(self, cursor: str | None) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []

        if self._base_query:
            filters.append(self._base_query)

        if cursor:
            payload = self._encoder.decode(cursor)
            cursor_query = self._query_builder.build_cursor_query(
                payload, self._sort_fields
            )
            filters.append(cursor_query)

        if not filters:
            return {}
        if len(filters) == 1:
            return filters[0]
        return {"$and": filters}

    async def _fetch_documents(
        self, query: Dict[str, Any], size: int, cursor: str | None
    ) -> _FetchedDocuments:
        direction = self._determine_direction(cursor)

        raw_docs = (
            await self._collection.find(query)
            .sort(self._sort_builder.build_sort(direction, self._sort_fields))
            .limit(size + 1)
            .to_list(length=size + 1)
        )

        has_extra = len(raw_docs) > size
        processed_docs = raw_docs[:size]

        if direction == PaginationDirection.PREV:
            processed_docs.reverse()

        return _FetchedDocuments(
            processed_docs=processed_docs,
            has_extra=has_extra,
            direction=direction,
        )

    def _determine_direction(self, cursor: str | None) -> PaginationDirection:
        if not cursor:
            return PaginationDirection.NEXT
        payload = self._encoder.decode(cursor)
        return payload.direction

    def _build_next_cursor(
        self, docs: _FetchedDocuments, original_cursor: str | None, size: int
    ) -> str | None:
        if not docs.processed_docs:
            return None

        if docs.direction == PaginationDirection.NEXT:
            if docs.has_extra:
                last_doc = docs.processed_docs[-1]
                payload = self._payload_builder.build_payload(
                    last_doc, PaginationDirection.NEXT, self._sort_fields
                )
                return self._encoder.encode(payload)
            return None

        # Was PREV direction
        last_doc = docs.processed_docs[-1]
        payload = self._payload_builder.build_payload(
            last_doc, PaginationDirection.NEXT, self._sort_fields
        )
        return self._encoder.encode(payload)

    def _build_prev_cursor(
        self, docs: _FetchedDocuments, original_cursor: str | None
    ) -> str | None:
        if not docs.processed_docs or original_cursor is None:
            return None

        if docs.direction == PaginationDirection.NEXT:
            first_doc = docs.processed_docs[0]
            payload = self._payload_builder.build_payload(
                first_doc, PaginationDirection.PREV, self._sort_fields
            )
            return self._encoder.encode(payload)

        # Was PREV direction
        if docs.has_extra:
            first_doc = docs.processed_docs[0]
            payload = self._payload_builder.build_payload(
                first_doc, PaginationDirection.PREV, self._sort_fields
            )
            return self._encoder.encode(payload)
        return None


class _FetchedDocuments:
    """Internal value object for fetched results."""

    def __init__(
        self,
        processed_docs: List[_DocumentType],
        has_extra: bool,
        direction: PaginationDirection,
    ) -> None:
        self.processed_docs = processed_docs
        self.has_extra = has_extra
        self.direction = direction
