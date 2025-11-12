## Logger Documentation

Think of the `midil` package as a complex machine, like a car. Just as a car has a dashboard with warning lights and gauges to tell you what's happening under the hood, the `midil` package needs a way to report its own status. This is where the `midil/logger` folder comes in. It's the "dashboard" and "event recorder" for the entire `midil` system.

Its main job is to:

- **Record events:** Keep a journal of what the `midil` machine is doing, like "started engine," "accelerating," or "low fuel."
- **Report problems:** Alert you when something goes wrong, like "engine overheating" or "tire pressure low."
- **Provide details:** Give you enough information to understand *why* something happened, including where and when.

Let's break down the key parts of this "logger" system:

### The Logger's Rulebook 

Every system needs rules, and our logger gets its rules from `midil/logger/config.py`. This file sets up the basic settings for how our logging system will behave.

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

The `LoggerConfig` (lines 10-14) defines:

- `log_level`: This is like a filter. You can set it to "INFO" to see general messages, "WARNING" for potential issues, or "ERROR" for serious problems. Messages below this level won't be shown.
- `enable_http_logging`: A switch to turn on or off sending logs over the internet to another service, which can be useful for collecting logs from many parts of a large system.
- `hostname` and `instance_id`: These are unique labels for the computer and the specific running program. They help you know exactly *where* a log message came from, especially if you have many parts of `midil` running at once.

### The Logger's Builder 

Once we have our rules, we need someone to actually build the logging tool. That's the job of `midil/logger/factory.py`. It contains the `LoggerFactory`, which is like a specialized workshop for creating our logger.

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
27             }
28         )
29         for handler in self.handlers:
30             handler.attach(self.config.log_level)
31         return logger
```

The `LoggerFactory` (lines 10-31) does two main things:

- `add_handler`: It lets us add different "handlers." A handler is simply *where* the log messages go. For example, one handler might print logs to your screen, another might save them to a file, and another might send them to a special log-collecting service.
- `build`: This is the final step where it puts everything together. It sets up the actual `loguru` logger (a popular logging tool) and makes sure that our unique `hostname` and `instance_id` are attached to every message. It also connects all the handlers we've added.

### Getting the Logger Ready 

Now that we have the rules and the builder, we need to actually start the logging system. This is handled by `midil/logger/setup.py`, which has a function called `setup_logger`. This function is like the "on" switch for our logger.

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

The `setup_logger` function (lines 23-40) does the following:

- It uses our `LoggerConfig` and `LoggerFactory`.

- It adds a `StdoutHandler` (lines 29-32). This means that by default, all logs will be printed to your console (your screen). This handler also has special features:

  - `sensitive_log_filter`: This is like a privacy guard, making sure that sensitive information doesn't accidentally show up in your logs.
  - `exception_deserializer`: This helps make sure that error messages (exceptions) are always formatted in a clear and consistent way.

- It has a placeholder for an `HttpHandler` (lines 36-38), meaning it's ready to send logs over the internet if that feature is turned on.

- Finally, it returns the fully prepared logger, ready to start recording events.

### Connecting the Logger to the Midil package

So, how does the entire `midil` package, including parts like `midilapi`, actually use this logger? The connection happens at the very beginning, when `midil` starts up.

First, `midil/settings.py` is where all the main settings for `midil` are stored. It's like the car's owner's manual, telling the car how to behave. This includes how to load our `LoggerConfig` (our logging rules), often from special files or environment variables, so you can easily change them without touching the code.

```python
1  # ... other settings ...
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

The `LoggerSettings` (lines 5-6) and `get_logger_settings` function (lines 9-14) ensure that our logging rules are properly loaded.

Then, in `midil/__init__.py`, which is the very first file loaded when `midil` starts, the `setup_logger` function is called:

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

Here, the logging rules are fetched (line 9), and then `setup_logger` is run (lines 11-14). This means that as soon as any part of `midil` (like `midilapi`) begins to operate, the logging system is already fully configured and ready to record events.

### How Midil Uses the Logger

Because the logger is set up right when `midil` starts, any part of the `midil` package can easily use it. Developers just import the `loguru` logger and use simple commands to record what's happening.

For example, if a part of `midil` (like a `midilapi` service handling user requests) wants to log something:

```python
1  from loguru import logger
2  # ... other code
3
4  def handle_new_order(order_details):
5      logger.info(f"New order received: {order_details.id}")
6      try:
7          # Process the order
8          if order_details.is_valid():
9              # save_order_to_database(order_details)
10             logger.debug(f"Order {order_details.id} processed successfully.")
11             return {"status": "success"}
12         else:
13             logger.warning(f"Invalid order details for {order_details.id}.")
14             return {"status": "failed"}
15     except Exception as e:
16         logger.error(f"Failed to process order {order_details.id}: {e}", exc_info=True)
17         raise
```

In this example, `logger.info()`, `logger.debug()`, `logger.warning()`, and `logger.error()` are used to track the order processing. All these messages will automatically include the `hostname` and `instance_id` and will be sent to the configured places (like your screen), giving you a clear, consistent record of what the `midil` machine is doing.

In short, the `midil/logger` folder is the essential monitoring system for the entire `midil` package. It provides a structured way to record events, report issues, and help developers understand how the application is running, making it easier to keep the `midil` machine in top shape.
