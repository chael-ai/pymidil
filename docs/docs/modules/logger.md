# Logger Documentation 



## Overview

This documentation provides a comprehensive overview of the `midil/logger` module, detailing its structure, functionality, and its integral role within the broader `midil` package. The `midil/logger` module establishes a centralized and configurable logging infrastructure, crucial for monitoring, debugging, and maintaining the operational integrity of the entire `midil` application.

### Logger Configuration 

The `midil/logger/config.py` file defines the fundamental configuration parameters that govern the behavior of the logging system. These settings are critical for tailoring log generation and content.

```python
1  from typing import Literal
2  from midil.logger.utils import resolve_hostname
3  from midil.utils.models import SnakeCaseModel
4  from pydantic import Field
5  import uuid
6
7  LogLevelType = Literal["ERROR", "WARNING", "INFO", "DEBUG", "CRITICAL"]
8
9
10 class LoggerConfig(SnakeCaseModel):
11     log_level: LogLevelType = Field(default="INFO")
12     enable_http_logging: bool = Field(default=False)
13     hostname: str = Field(default=resolve_hostname())
14     instance_id: str = Field(default=str(uuid.uuid4()))
```

The `LoggerConfig` class (lines 10-14) specifies the following attributes:

- `log_level`: Determines the minimum severity threshold for log messages to be processed (e.g., "INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL").
- `enable_http_logging`: A boolean flag that controls whether logs are transmitted via HTTP, typically for integration with external log aggregation services.
- `hostname` and `instance_id`: Automatically generated unique identifiers for the host machine and the specific application instance. These identifiers are essential for contextualizing log entries in distributed or microservice architectures.

### Logger Factory 

The `midil/logger/factory.py` module encapsulates the `LoggerFactory` class, which is responsible for the programmatic construction and management of the `loguru` logger instance based on the `LoggerConfig`.

```python
1  from midil.logger.config import LoggerConfig
2  from midil.logger.handlers.abstracts import LogHandler
3  from loguru import logger
4  from typing import TYPE_CHECKING
5
6  if TYPE_CHECKING:
7      from loguru import Logger
8
9
10 class LoggerFactory:
11     """Factory to setup loguru logger with multiple handlers."""
12
13     def __init__(self, config: LoggerConfig) -> None:
14         self.config = config
15         self.handlers: list[LogHandler] = []
16
17     def add_handler(self, handler: LogHandler) -> None:
18         self.handlers.append(handler)
19
20     def build(self) -> "Logger":
21         logger.remove()
22         logger.configure(
23             extra={
24                 "hostname": self.config.hostname,
25                 "instance": self.config.instance_id,
26             }
27         )
28         for handler in self.handlers:
29             handler.attach(self.config.log_level)
30         return logger
```

The `LoggerFactory` (lines 10-30) provides the following core functionalities:

- `add_handler`: Facilitates the registration of various `LogHandler` implementations. These handlers define the destination and processing logic for log messages (e.g., console output, file storage, network transmission).
- `build`: This method orchestrates the final configuration of the underlying `loguru` logger. It injects global `extra` parameters, such as `hostname` and `instance_id`, into every log record (lines 23-26). Subsequently, it attaches all registered handlers, ensuring they process messages that meet or exceed the configured `log_level`.

### Logger Initialization 

The `midil/logger/setup.py` module contains the `setup_logger` function, which serves as the primary entry point for initializing and activating the logging system within the `midil` application.

```python
1  import loguru
2
3  from midil.logger.config import LogLevelType
4  from midil.logger.sensitive import sensitive_log_filter
5  from midil.logger.config import LoggerConfig
6  from midil.logger.factory import LoggerFactory
7  from midil.logger.handlers.stdout_handler import StdoutHandler
8
9  from typing import TYPE_CHECKING
10
11 if TYPE_CHECKING:
12     from loguru import Logger
13
14
15 def exception_deserializer(record: "loguru.Record") -> None:
16     """Normalize exception values for loguru serialization."""
17     exception: loguru.RecordException | None = record.get("exception")
18     if exception:
19         fixed = Exception(str(exception.value))
20         record["exception"] = exception._replace(value=fixed)
21
22
23 def setup_logger(level: LogLevelType, enable_http_logging: bool) -> "Logger":
24     """Setup application logger with configured handlers."""
25     config = LoggerConfig(log_level=level, enable_http_logging=enable_http_logging)
26     factory = LoggerFactory(config)
27
28     factory.add_handler(
29         StdoutHandler(
30             filter_fn=sensitive_log_filter.create_filter(),
31             patcher=exception_deserializer,
32         )
33     )
34
35     # Future: conditionally add HTTP handler
36     if config.enable_http_logging:
37         # factory.add_handler(HttpHandler(...))
38         pass
39
40     return factory.build()
```

The `setup_logger` function (lines 23-40) executes the following critical steps:

- It instantiates `LoggerConfig` and `LoggerFactory` based on the provided logging level and HTTP logging enablement.
- It adds a `StdoutHandler` (lines 29-32) to direct log messages to standard output. This handler is augmented with a `sensitive_log_filter` to prevent the logging of sensitive data and an `exception_deserializer` (lines 15-20) to ensure consistent exception formatting.
- A conditional block (lines 36-38) indicates a planned extension for an `HttpHandler`, enabling remote log forwarding.
- Finally, it invokes `factory.build()` to return the fully configured `loguru` logger instance, ready for application use.

### System-Wide Integration

The `midil/logger` module is integrated at the root of the `midil` package, ensuring a consistent logging approach across all its components. This integration is managed through `midil/__init__.py` and the application's central settings defined in `midil/settings.py`.

`midil/settings.py` is responsible for defining how `LoggerConfig` is loaded, typically from environment variables or a `.env` file. This mechanism provides a flexible and externalizable way to manage logging configurations without modifying source code.

```python
1  # ... other imports and classes ...
2  from midil.logger.config import LoggerConfig
3  # ...
4
5  class LoggerSettings(_BaseSettings):
6      logger: LoggerConfig = Field(default=LoggerConfig())
7  # ...
8
9  def get_logger_settings() -> LoggerConfig:
10     """Get logger settings, raising an error if not configured."""
11     settings = get_settings()
12     if settings.logger is None:
13         return LoggerConfig()
14     return settings.logger
```

The `LoggerSettings` class (lines 5-6) and the `get_logger_settings` function (lines 9-14) facilitate the retrieval of logger configurations.

The actual initialization of the logger for the entire `midil` package occurs within `midil/__init__.py`:

```python
1  from midil.cli.main import cli
2  from midil.version import __service_version__, __version__
3  from midil.logger.setup import setup_logger
4  from midil.settings import LoggerSettings
5
6
7  __all__ = ["cli", "__service_version__", "__version__"]
8
9  logger_settings = LoggerSettings().logger
10 print(logger_settings)
11 setup_logger(
12     level=logger_settings.log_level,
13     enable_http_logging=logger_settings.enable_http_logging,
14 )
```

In this entry point, `logger_settings` are retrieved (line 9), and the `setup_logger` function is invoked (lines 11-14) with these configurations. This ensures that the logging system is fully configured and operational upon the initial import of the `midil` package, making it immediately available to all sub-modules, including `midilapi`.

### Operational Role within the `midil` Package

Given the package-level initialization, any module or component within the `midil` package can directly utilize the pre-configured `loguru` logger instance. This provides a consistent and standardized mechanism for logging events, facilitating debugging, and enabling comprehensive monitoring across the entire application.

Example of logger usage within a `midil` module (e.g., a `midilapi` service, a CLI command, or an event handler):

```python
1  from loguru import logger
2  # ... other module-specific imports
3
4  def process_data_operation(data_id):
5      logger.info(f"Initiating data processing for ID: {data_id}")
6      try:
7          # Complex data processing logic
8          if data_id % 2 == 0:
9              logger.debug(f"Data ID {data_id} is even, performing specific task.")
10             # perform_even_task(data_id)
11         else:
12             logger.debug(f"Data ID {data_id} is odd, performing alternative task.")
13             # perform_odd_task(data_id)
14         logger.info(f"Data processing completed for ID: {data_id}.")
15         return {"status": "success", "processed_id": data_id}
16     except ValueError as ve:
17         logger.warning(f"Validation error for data ID {data_id}: {ve}")
18         return {"status": "failed", "error": str(ve)}
19     except Exception as e:
20         logger.error(f"Critical error during processing for ID {data_id}: {e}", exc_info=True)
21         raise
```

In this example, `logger.info()`, `logger.debug()`, `logger.warning()`, and `logger.error()` are employed to track the various stages and potential issues during a data processing operation. All generated log messages automatically include the configured `hostname` and `instance_id` and are directed to the specified handlers, providing a clear, consistent, and traceable record of the `midil` application's activities.

In conclusion, the `midil/logger` module establishes a robust, flexible, and centrally managed logging infrastructure. This system is seamlessly integrated throughout the `midil` package, enabling comprehensive observability, efficient debugging, and reliable monitoring of the application's behavior.

