from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol

from pymidil.logger.config import LogLevelType

if TYPE_CHECKING:
    from loguru import Record


class LogHandler(ABC):
    """Abstract base for log handlers."""

    @abstractmethod
    def attach(self, level: LogLevelType) -> None:
        ...


class LogPatcher(Protocol):
    """Protocol for patching log records."""

    def __call__(self, record: "Record") -> None:
        ...
