# Examples

Runnable examples demonstrating how to use `midil`.

## Event

| File | Description |
|---|---|
| [event/event_bus.py](event/event_bus.py) | Full event bus setup with producers and consumers |
| [event/event_context.py](event/event_context.py) | Using `EventContext` to propagate event metadata |
| [event/standalone_consumer.py](event/standalone_consumer.py) | Running a consumer independently without the event bus |
| [event/standalone_producer.py](event/standalone_producer.py) | Publishing messages directly with a producer |
| [event/webhook_producer.py](event/webhook_producer.py) | Producing events via webhook delivery |

## Running an example

```bash
# Install with all extras
pip install pymidil[full]

# Copy .env.example and fill in your values
cp .env.example .env

# Run an example
python examples/event/standalone_producer.py
```
