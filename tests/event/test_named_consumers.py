import pytest
from pymidil.settings import MidilSettings, EventSettingsError
from pymidil.event.config import EventConfig, EventConsumerType
from pymidil.event.consumer.sqs import SQSConsumerEventConfig
from pymidil.event.consumer.webhook import WebhookConsumerEventConfig


def _settings_with_consumers(**consumers) -> MidilSettings:
    return MidilSettings(event=EventConfig(consumers=consumers))


class TestNamedConsumers:
    """Test named consumer configuration functionality."""

    def test_get_consumer_by_name(self):
        """Test getting a specific consumer by name."""
        settings = _settings_with_consumers(
            booking_queue=SQSConsumerEventConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/booking-queue"
            ),
            payment_webhook=WebhookConsumerEventConfig(endpoint="/webhook/payments"),
        )

        booking_consumer = settings.get_consumer("booking_queue")
        assert booking_consumer.type == "sqs"
        assert (
            booking_consumer.queue_url
            == "https://sqs.us-east-1.amazonaws.com/123456789/booking-queue"
        )

        payment_consumer = settings.get_consumer("payment_webhook")
        assert payment_consumer.type == "webhook"
        assert payment_consumer.endpoint == "/webhook/payments"

    def test_get_consumer_by_name_not_found(self):
        """Test error when consumer name is not found."""
        settings = _settings_with_consumers(
            booking_queue=SQSConsumerEventConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/booking-queue"
            ),
        )

        with pytest.raises(
            EventSettingsError, match="Consumer 'nonexistent' not found"
        ):
            settings.get_consumer("nonexistent")

    def test_get_consumers_by_type_sqs(self):
        """Test getting consumers by type (SQS)."""
        settings = _settings_with_consumers(
            booking_queue=SQSConsumerEventConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/booking-queue"
            ),
            payment_webhook=WebhookConsumerEventConfig(endpoint="/webhook/payments"),
            notification_queue=SQSConsumerEventConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/notification-queue"
            ),
        )

        sqs_consumers = settings.get_consumers_by_type(EventConsumerType.SQS)

        assert len(sqs_consumers) == 2
        assert "booking_queue" in sqs_consumers
        assert "notification_queue" in sqs_consumers
        assert "payment_webhook" not in sqs_consumers
        assert all(consumer.type == "sqs" for consumer in sqs_consumers.values())

    def test_get_consumers_by_type_webhook(self):
        """Test getting consumers by type (Webhook)."""
        settings = _settings_with_consumers(
            booking_queue=SQSConsumerEventConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/booking-queue"
            ),
            payment_webhook=WebhookConsumerEventConfig(endpoint="/webhook/payments"),
            notification_webhook=WebhookConsumerEventConfig(
                endpoint="/webhook/notifications"
            ),
        )

        webhook_consumers = settings.get_consumers_by_type(EventConsumerType.WEBHOOK)

        assert len(webhook_consumers) == 2
        assert "payment_webhook" in webhook_consumers
        assert "notification_webhook" in webhook_consumers
        assert "booking_queue" not in webhook_consumers
        assert all(
            consumer.type == "webhook" for consumer in webhook_consumers.values()
        )

    def test_get_consumers_by_type_none_found(self):
        """Test error when no consumers of specified type are found."""
        settings = _settings_with_consumers(
            booking_queue=SQSConsumerEventConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/booking-queue"
            ),
        )

        with pytest.raises(
            EventSettingsError,
            match="No consumer configurations with type 'EventConsumerType.WEBHOOK'",
        ):
            settings.get_consumers_by_type(EventConsumerType.WEBHOOK)
