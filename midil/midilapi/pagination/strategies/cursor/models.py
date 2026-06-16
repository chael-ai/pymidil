from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from midil.midilapi.pagination.strategies.cursor.enums import (
    PaginationDirection,
    SortDirection,
)

# Sentinel key used to tag datetime values inside ``values`` so they survive the
# JSON round-trip the cursor encoder performs. Without this, a datetime sort key
# would serialize to an ISO string and come back as a plain ``str`` (because
# ``values`` is typed ``dict[str, Any]`` and Pydantic cannot coerce it back),
# breaking keyset comparisons against datetime-typed columns.
_DATETIME_TAG = "$dt"


class CursorPayload(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    version: int = 1

    values: dict[str, Any]

    direction: PaginationDirection = PaginationDirection.NEXT

    sort: SortDirection = SortDirection.DESC

    expires_at: datetime | None = None

    @field_validator("values", mode="before")
    @classmethod
    def _decode_values(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {
            key: (
                datetime.fromisoformat(item[_DATETIME_TAG])
                if isinstance(item, dict) and set(item) == {_DATETIME_TAG}
                else item
            )
            for key, item in value.items()
        }

    @field_serializer("values", when_used="json")
    def _encode_values(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (
                {_DATETIME_TAG: item.isoformat()}
                if isinstance(item, datetime)
                else item
            )
            for key, item in value.items()
        }
