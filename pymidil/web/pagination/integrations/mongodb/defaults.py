from typing import List, Dict, Any
from pymidil.web.pagination.integrations.mongodb.builder import (
    CursorQueryBuilder,
    SortBuilder,
    PayloadBuilder,
)
from pymidil.web.pagination.strategies.cursor.models import CursorPayload
from pymidil.web.pagination.strategies.cursor.enums import PaginationDirection
from bson import ObjectId


class DefaultCursorQueryBuilder(CursorQueryBuilder):
    """Default MongoDB cursor query builder using keyset pagination."""

    def build_cursor_query(
        self, payload: CursorPayload, sort_fields: List[str]
    ) -> Dict[str, Any]:
        op = "$lt" if payload.direction == PaginationDirection.NEXT else "$gt"
        values = payload.values

        def coerce(field: str) -> Any:
            raw = values[field]
            return ObjectId(raw) if field == "_id" else raw

        if len(sort_fields) == 1:
            field = sort_fields[0]
            return {field: {op: coerce(field)}}

        # Composite keyset pagination
        clauses: List[Dict[str, Any]] = []
        for i, field in enumerate(sort_fields):
            clause: Dict[str, Any] = {f: coerce(f) for f in sort_fields[:i]}
            clause[field] = {op: coerce(field)}
            clauses.append(clause)

        return {"$or": clauses}


class DefaultSortBuilder(SortBuilder):
    """Default MongoDB sort specification builder."""

    def build_sort(
        self, direction: PaginationDirection, sort_fields: List[str]
    ) -> List[tuple[str, int]]:
        order = -1 if direction == PaginationDirection.NEXT else 1
        return [(field, order) for field in sort_fields]


class DefaultPayloadBuilder(PayloadBuilder):
    """Default cursor payload builder (handles ObjectId serialization)."""

    def build_payload(
        self,
        doc: Dict[str, Any],
        direction: PaginationDirection,
        sort_fields: List[str],
    ) -> CursorPayload:
        values: Dict[str, Any] = {}
        for field in sort_fields:
            if field not in doc:
                continue
            raw = doc[field]
            # ObjectId needs stringification for JSON cursor safety
            values[field] = str(raw) if isinstance(raw, ObjectId) else raw

        return CursorPayload(values=values, direction=direction)
