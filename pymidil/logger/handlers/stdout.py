import sys
from typing import Optional, Callable, TYPE_CHECKING

from loguru import logger

from pymidil.logger.config import LogLevelType
from pymidil.logger.handlers.base import LogHandler, LogPatcher

if TYPE_CHECKING:
    from loguru import Record


class StdoutHandler(LogHandler):
    """Stdout log handler with optional debug extras."""

    def __init__(
        self,
        filter_fn: Optional[Callable[["Record"], bool]] = None,
        patcher: Optional[LogPatcher] = None,
    ) -> None:
        self._filter_fn = filter_fn
        self._patcher = patcher

    def attach(self, level: LogLevelType) -> None:
        log_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        )
        if level.upper() == "DEBUG":
            log_format += " | {extra}"

        logger.add(
            sys.stdout,
            level=level.upper(),
            format=log_format,
            enqueue=True,
            diagnose=False,
            filter=self._filter_fn,
        )
        if self._patcher:
            logger.configure(patcher=self._patcher)
