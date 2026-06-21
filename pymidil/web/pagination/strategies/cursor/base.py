from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pymidil.web.pagination.strategies.cursor.page import (
    CursorPage,
)

ItemT = TypeVar("ItemT")


class CursorPaginationStrategy(
    ABC,
    Generic[ItemT],
):
    @abstractmethod
    async def paginate(
        self,
        size: int,
        cursor: str | None = None,
    ) -> CursorPage[ItemT]:
        ...
