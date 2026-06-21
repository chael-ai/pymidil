import pytest
from unittest.mock import MagicMock, patch

from pymidil.event import DispatchHook, MessageProtocol
from pymidil.event.event_bus import EventBus
from pymidil.event.config import EventConfig
from pymidil.event.consumer.webhook import WebhookConsumerEventConfig
from pymidil.event.exceptions import ConsumerError


pytestmark = pytest.mark.anyio


def _bus_with_consumers(**consumers) -> EventBus:
    config = EventConfig(consumers=consumers)
    with patch(
        "pymidil.event.event_bus.EventBusFactory.create_consumer"
    ) as mock_create:
        mock_create.side_effect = lambda cfg: MagicMock(add_hook=MagicMock())
        return EventBus(config=config)


class TestDispatchHookDefaults:
    async def test_on_receive_is_noop(self):
        hook = DispatchHook()
        message = MagicMock(spec=MessageProtocol, id="msg-1")
        await hook.on_receive(message, "orders")

    async def test_on_complete_is_noop(self):
        hook = DispatchHook()
        message = MagicMock(spec=MessageProtocol, id="msg-1")
        await hook.on_complete(message, "orders", duration_ms=12.5)

    async def test_on_failure_is_noop(self):
        hook = DispatchHook()
        message = MagicMock(spec=MessageProtocol, id="msg-1")
        await hook.on_failure(message, "orders", error=ValueError("boom"))

    async def test_on_retry_is_noop(self):
        hook = DispatchHook()
        message = MagicMock(spec=MessageProtocol, id="msg-1")
        await hook.on_retry(message, "orders", errors=[])


class TestDispatchHookExtension:
    async def test_custom_hook_receives_correct_args(self):
        received = []

        class RecordingHook(DispatchHook):
            async def on_receive(self, message, consumer_name):
                received.append(("on_receive", message.id, consumer_name))

            async def on_complete(self, message, consumer_name, duration_ms):
                received.append(("on_complete", message.id, consumer_name, duration_ms))

            async def on_failure(self, message, consumer_name, error):
                received.append(("on_failure", message.id, consumer_name, str(error)))

            async def on_retry(self, message, consumer_name, errors):
                received.append(("on_retry", message.id, consumer_name))

        hook = RecordingHook()
        message = MagicMock(spec=MessageProtocol, id="msg-42")

        await hook.on_receive(message, "orders")
        await hook.on_complete(message, "orders", duration_ms=5.0)
        await hook.on_failure(message, "orders", error=RuntimeError("fail"))
        await hook.on_retry(message, "orders", errors=[])

        assert received == [
            ("on_receive", "msg-42", "orders"),
            ("on_complete", "msg-42", "orders", 5.0),
            ("on_failure", "msg-42", "orders", "fail"),
            ("on_retry", "msg-42", "orders"),
        ]


class TestEventBusAddDispatchHook:
    def test_add_hook_to_all_consumers(self):
        bus = _bus_with_consumers(
            orders=WebhookConsumerEventConfig(endpoint="/orders"),
            payments=WebhookConsumerEventConfig(endpoint="/payments"),
        )
        hook = DispatchHook()
        bus.add_dispatch_hook(hook)

        for consumer in bus.consumers.values():
            consumer.add_hook.assert_called_once_with(hook)

    def test_add_hook_to_specific_consumer(self):
        bus = _bus_with_consumers(
            orders=WebhookConsumerEventConfig(endpoint="/orders"),
            payments=WebhookConsumerEventConfig(endpoint="/payments"),
        )
        hook = DispatchHook()
        bus.add_dispatch_hook(hook, target="orders")

        bus.consumers["orders"].add_hook.assert_called_once_with(hook)
        bus.consumers["payments"].add_hook.assert_not_called()

    def test_add_hook_unknown_target_raises(self):
        bus = _bus_with_consumers(
            orders=WebhookConsumerEventConfig(endpoint="/orders"),
        )
        with pytest.raises(ConsumerError, match="Consumer 'unknown' not found"):
            bus.add_dispatch_hook(DispatchHook(), target="unknown")

    def test_multiple_hooks_on_same_consumer(self):
        bus = _bus_with_consumers(
            orders=WebhookConsumerEventConfig(endpoint="/orders"),
        )
        hook_a = DispatchHook()
        hook_b = DispatchHook()

        bus.add_dispatch_hook(hook_a)
        bus.add_dispatch_hook(hook_b)

        assert bus.consumers["orders"].add_hook.call_count == 2
