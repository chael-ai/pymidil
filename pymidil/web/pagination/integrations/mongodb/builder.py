from typing import Protocol, List, Dict, Any
from pymidil.web.pagination.strategies.cursor.models import CursorPayload
from pymidil.web.pagination.strategies.cursor.enums import PaginationDirection


class CursorQueryBuilder(Protocol):
    """Abstraction for building cursor-based MongoDB queries."""

    def build_cursor_query(
        self, payload: CursorPayload, sort_fields: List[str]
    ) -> Dict[str, Any]:
        ...


class SortBuilder(Protocol):
    """Abstraction for building MongoDB sort specifications."""

    def build_sort(
        self, direction: PaginationDirection, sort_fields: List[str]
    ) -> List[tuple[str, int]]:
        ...


class PayloadBuilder(Protocol):
    """Abstraction for building cursor payloads from documents."""

    def build_payload(
        self,
        doc: Dict[str, Any],
        direction: PaginationDirection,
        sort_fields: List[str],
    ) -> CursorPayload:
        ...
