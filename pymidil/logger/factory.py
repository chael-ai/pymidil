from pymidil.logger.config import LoggerConfig
from pymidil.logger.handlers.base import LogHandler
from loguru import logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loguru import Logger


class LoggerFactory:
    """Factory to setup loguru logger with multiple handlers."""

    def __init__(self, config: LoggerConfig) -> None:
        self.config = config
        self.handlers: list[LogHandler] = []

    def add_handler(self, handler: LogHandler) -> None:
        self.handlers.append(handler)

    def build(self) -> "Logger":
        logger.remove()
        logger.configure(
            extra={
                "hostname": self.config.hostname,
                "instance": self.config.instance_id,
            }
        )
        for handler in self.handlers:
            handler.attach(self.config.log_level)
        return logger
