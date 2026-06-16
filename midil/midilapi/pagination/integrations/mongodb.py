from __future__ import annotations

from typing import Any, Callable, Dict, Generic, TypeVar, List

try:
    from bson import ObjectId
    from pymongo.asynchronous.collection import AsyncCollection
except ImportError as e:
    raise ImportError(
        "MongoDB support requires the 'mongodb' extra: pip install midil[mongodb]"
    ) from e

from midil.midilapi.pagination.strategies.cursor.encoders.abstract import CursorEncoder
from midil.midilapi.pagination.strategies.cursor.enums import PaginationDirection
from midil.midilapi.pagination.strategies.cursor.models import CursorPayload
from midil.midilapi.pagination.strategies.cursor.page import CursorPage
from midil.midilapi.pagination.strategies.cursor.abstract import (
    CursorPaginationStrategy,
    ItemT,
)

_DocumentType = TypeVar("_DocumentType", bound=Dict[str, Any])

_DEFAULT_SORT_FIELDS = ["created_at", "_id"]


class AsyncMongoCursorPaginationStrategy(
    CursorPaginationStrategy[ItemT],
    Generic[ItemT],
):
    def __init__(
        self,
        *,
        collection: AsyncCollection[_DocumentType],
        encoder: CursorEncoder,
        mapper: Callable[[_DocumentType], ItemT],
        base_query: Dict[str, Any] | None = None,
        sort_fields: List[str] | None = None,
    ) -> None:
        self._collection = collection
        self._encoder = encoder
        self._mapper = mapper
        self._base_query = base_query or {}
        self._sort_fields = sort_fields or _DEFAULT_SORT_FIELDS

    async def paginate(
        self,
        *,
        size: int,
        cursor: str | None = None,
    ) -> CursorPage[ItemT]:
        filters: List[Dict[str, Any]] = []
        if self._base_query:
            filters.append(dict(self._base_query))

        direction = PaginationDirection.NEXT

        if cursor:
            payload = self._encoder.decode(cursor)
            direction = payload.direction
            filters.append(self._build_cursor_query(payload))

        # Combine with $and rather than dict.update so a base_query that already
        # uses a top-level $or (e.g. a text search) is not clobbered by the
        # cursor keyset $or.
        if not filters:
            query: Dict[str, Any] = {}
        elif len(filters) == 1:
            query = filters[0]
        else:
            query = {"$and": filters}

        documents = (
            await self._collection.find(query)
            .sort(self._build_sort(direction))
            .limit(size + 1)
            .to_list(length=size + 1)
        )

        has_extra = len(documents) > size
        documents = documents[:size]

        if direction == PaginationDirection.PREV:
            documents.reverse()

        items = [self._mapper(doc) for doc in documents]

        next_cursor = None
        prev_cursor = None

        if documents:
            if direction == PaginationDirection.NEXT:
                if has_extra:
                    next_cursor = self._encoder.encode(
                        self._payload(documents[-1], PaginationDirection.NEXT)
                    )
                if cursor is not None:
                    prev_cursor = self._encoder.encode(
                        self._payload(documents[0], PaginationDirection.PREV)
                    )
            else:
                if has_extra:
                    prev_cursor = self._encoder.encode(
                        self._payload(documents[0], PaginationDirection.PREV)
                    )
                next_cursor = self._encoder.encode(
                    self._payload(documents[-1], PaginationDirection.NEXT)
                )

        return CursorPage(
            items=items,
            size=size,
            next=next_cursor,
            prev=prev_cursor,
        )

    def _payload(
        self, doc: Dict[str, Any], direction: PaginationDirection
    ) -> CursorPayload:
        # ObjectId is not JSON-serializable, so stringify it for the cursor;
        # _build_cursor_query rehydrates it via ObjectId(...). Other values
        # (strings, datetimes) are stored raw — datetimes survive the round-trip
        # via CursorPayload's tagged (de)serialization.
        values: Dict[str, Any] = {}
        for field in self._sort_fields:
            if field not in doc:
                continue
            raw = doc[field]
            values[field] = str(raw) if isinstance(raw, ObjectId) else raw
        return CursorPayload(values=values, direction=direction)

    def _build_cursor_query(self, payload: CursorPayload) -> Dict[str, Any]:
        op = "$lt" if payload.direction == PaginationDirection.NEXT else "$gt"
        fields = self._sort_fields
        values = payload.values

        def coerce(field: str) -> Any:
            raw = values[field]
            return ObjectId(raw) if field == "_id" else raw

        if len(fields) == 1:
            return {fields[0]: {op: coerce(fields[0])}}

        # Composite sort: tie-break with an $or across all prefix combinations.
        # For fields [f0, f1]: (f0 op v0) OR (f0 == v0 AND f1 op v1)
        clauses = []
        for i, field in enumerate(fields):
            clause: Dict[str, Any] = {f: coerce(f) for f in fields[:i]}
            clause[field] = {op: coerce(field)}
            clauses.append(clause)

        return {"$or": clauses}

    def _build_sort(self, direction: PaginationDirection) -> List[tuple[str, int]]:
        order = -1 if direction == PaginationDirection.NEXT else 1
        return [(field, order) for field in self._sort_fields]
