from abc import ABC, abstractmethod

from pymidil.web.pagination.strategies.cursor.models import (
    CursorPayload,
)


class CursorEncoder(ABC):
    @abstractmethod
    def encode(
        self,
        payload: CursorPayload,
    ) -> str:
        ...

    @abstractmethod
    def decode(
        self,
        cursor: str,
    ) -> CursorPayload:
        ...
