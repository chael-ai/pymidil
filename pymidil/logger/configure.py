import loguru

from pymidil.logger.config import LogLevelType
from pymidil.logger.sensitive import sensitive_log_filter
from pymidil.logger.config import LoggerConfig
from pymidil.logger.factory import LoggerFactory
from pymidil.logger.handlers.stdout import StdoutHandler

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loguru import Logger


def exception_deserializer(record: "loguru.Record") -> None:
    """Normalize exception values for loguru serialization."""
    exception: loguru.RecordException | None = record.get("exception")
    if exception:
        fixed = Exception(str(exception.value))
        record["exception"] = exception._replace(value=fixed)


def setup_logger(level: LogLevelType, enable_http_logging: bool) -> "Logger":
    """Setup application logger with configured handlers."""
    config = LoggerConfig(log_level=level, enable_http_logging=enable_http_logging)
    factory = LoggerFactory(config)

    factory.add_handler(
        StdoutHandler(
            filter_fn=sensitive_log_filter.create_filter(),
            patcher=exception_deserializer,
        )
    )

    # Future: conditionally add HTTP handler
    if config.enable_http_logging:
        # factory.add_handler(HttpHandler(...))
        pass

    return factory.build()
