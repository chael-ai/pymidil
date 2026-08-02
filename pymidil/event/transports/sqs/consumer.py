"""SQS consumer — adapts the SQS wire into an ``Event`` + ``SQSDelivery``.

Everything SQS-shaped is quarantined in this package: the ``{"StringValue": …}``
attribute envelope, ``ApproximateReceiveCount``, receipt handles,
region-from-ARN. The rest of pymidil sees only a transport-neutral
:class:`Event` and a :class:`~pymidil.event.core.Delivery`.

The split inside: :class:`SQSDelivery` *reads* (identity, attempt count, trace
carrier) and owns the settle-once latch it inherits; :class:`SQSSettlement`
*writes* (the physical broker calls). Terminal failures go where the config
DECLARES — ``dlq_url`` or an explicit ``no_dlq`` choice — never to a silent
fallback.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Literal, Mapping, Optional

import aioboto3
from botocore.exceptions import ClientError
from loguru import logger
from pydantic import Field, model_validator

from pymidil.event.transports.sqs.producer import (
    build_sqs_message_attributes,
    region_from_arn,
)
from pymidil.event.consumer.strategies.pull import (
    PullEventConsumer,
    PullEventConsumerConfig,
)
from pymidil.event.control import ControlSource, ControlState
from pymidil.event.core import Delivery, Event, Settlement
from pymidil.event.retry import TransportCapabilities
from pymidil.event.wire import wire_to_event
from pymidil.utils.backoff import ExponentialBackoff
from pymidil.utils.time import utcnow

_DEFAULT_REGION = "us-east-1"


def _unwrap(value: Any) -> Optional[str]:
    """Peel an SQS attribute value (``{"StringValue": …}``) to a plain string."""
    if isinstance(value, dict):
        value = (
            value.get("StringValue") or value.get("stringValue") or value.get("Value")
        )
    return None if value is None else str(value)


class SQSConsumerEventConfig(PullEventConsumerConfig):
    type: Literal["sqs"] = "sqs"
    queue_url: str = Field(..., description="URL of the queue")
    dlq_url: Optional[str] = Field(
        default=None, description="URL of the dead-letter queue"
    )
    no_dlq: Optional[Literal["requeue", "drop"]] = Field(
        default=None,
        description=(
            "Explicit fate for terminal failures when no dlq_url is set: "
            "'requeue' (the queue's own RedrivePolicy owns dead-lettering) or "
            "'drop' (failed messages are deleted — explicit data loss)."
        ),
    )
    visibility_timeout: int = Field(
        default=30, description="Visibility timeout (s)", ge=0
    )
    max_number_of_messages: int = Field(default=10, ge=1, le=10)
    wait_time_seconds: int = Field(default=20, ge=0, le=20)
    aws_region: Optional[str] = Field(default=None)
    endpoint_url: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def _terminal_destination_declared(self) -> "SQSConsumerEventConfig":
        if self.dlq_url and self.no_dlq:
            raise ValueError(
                "dlq_url and no_dlq are mutually exclusive — pick one owner "
                "of terminal failures."
            )
        if not self.dlq_url and not self.no_dlq:
            raise ValueError(
                "SQS consumer has no dead-letter destination. Terminal "
                "failures (non-retryable errors, or retries exhausted after "
                f"max_attempts={self.retry.max_attempts}) need a declared "
                "fate: set dlq_url, or no_dlq='requeue' (your queue's "
                "RedrivePolicy owns dead-lettering), or no_dlq='drop' "
                "(failed messages are deleted — explicit data loss)."
            )
        if self.no_dlq == "requeue" and self.retry.max_attempts is not None:
            # A budget the fate cannot honor is a promise with no physical
            # effect: exhaustion would 'terminate' into... another retry.
            raise ValueError(
                "no_dlq='requeue' declares that the queue's own RedrivePolicy "
                f"owns termination — a finite retry.max_attempts="
                f"{self.retry.max_attempts} can terminate nothing on this "
                "consumer. Set retry.max_attempts=None (unbounded here; the "
                "broker bounds it), or choose dlq_url/no_dlq='drop' so the "
                "budget has a real terminal destination."
            )
        return self

    @property
    def terminal_action(self) -> Literal["dlq", "requeue", "drop"]:
        return "dlq" if self.dlq_url else self.no_dlq  # type: ignore[return-value]

    @property
    def region(self) -> str:
        return self.aws_region or region_from_arn(self.queue_url) or _DEFAULT_REGION

    @property
    def dlq_region(self) -> str:
        return self.aws_region or region_from_arn(self.dlq_url) or self.region


class SQSSettlement(Settlement):
    """Physical SQS settlement for one receipt handle. Declares the fate the
    config declared (``dlq_url`` XOR ``no_dlq``)."""

    def __init__(
        self,
        *,
        session: Any,
        config: SQSConsumerEventConfig,
        message_id: str,
        receipt_handle: str,
        raw_attributes: Mapping[str, Any],
    ) -> None:
        self._session = session
        self._config = config
        self._message_id = message_id
        self._receipt_handle = receipt_handle
        self._raw = dict(raw_attributes)

    @property
    def terminal_action(self) -> Literal["dlq", "requeue", "drop"]:
        return self._config.terminal_action

    def _client(self, region: str):
        return self._session.client(
            "sqs", region_name=region, endpoint_url=self._config.endpoint_url
        )

    async def ack(self) -> None:
        try:
            async with self._client(self._config.region) as sqs:
                await sqs.delete_message(
                    QueueUrl=self._config.queue_url,
                    ReceiptHandle=self._receipt_handle,
                )
            logger.debug(f"Acknowledged message {self._message_id}")
        except ClientError as e:
            logger.error(f"Error acknowledging message {self._message_id}: {e}")

    async def retry(self, delay: float) -> None:
        try:
            async with self._client(self._config.region) as sqs:
                await sqs.change_message_visibility(
                    QueueUrl=self._config.queue_url,
                    ReceiptHandle=self._receipt_handle,
                    VisibilityTimeout=max(0, round(delay)),
                )
            logger.debug(f"Requeued message {self._message_id} with delay={delay:.1f}s")
        except ClientError as e:
            logger.error(f"Error retrying message {self._message_id}: {e}")

    async def dlq(
        self,
        event: Event,
        carrier: Mapping[str, str],
        error: Optional[Exception] = None,
    ) -> None:
        if not self._config.dlq_url:
            # Unreachable by contract: the config validator guarantees a
            # dlq_url whenever terminal_action == "dlq". Loud if violated.
            raise RuntimeError(
                f"SQSSettlement.dlq called without a dlq_url for "
                f"{self._message_id} — config validation should have made "
                f"this impossible"
            )
        try:
            params: Dict[str, Any] = {
                "QueueUrl": self._config.dlq_url,
                "MessageBody": json.dumps(event.data),
            }
            # Preserve the trace carrier so a later replay links back.
            attributes = build_sqs_message_attributes(dict(carrier))
            if attributes:
                params["MessageAttributes"] = attributes
            if self._config.dlq_url.endswith(".fifo"):
                params.update(
                    {
                        "MessageGroupId": _unwrap(self._raw.get("MessageGroupId"))
                        or "default",
                        "MessageDeduplicationId": _unwrap(
                            self._raw.get("MessageDeduplicationId")
                        )
                        or self._message_id,
                    }
                )
            async with self._client(self._config.dlq_region) as sqs:
                await sqs.send_message(**params)
            logger.debug(f"Sent message {self._message_id} to DLQ")
        except ClientError as e:
            # Divert failed → do NOT remove from source; the message
            # redelivers after its visibility timeout.
            logger.error(f"Error dead-lettering message {self._message_id}: {e}")
            return
        await self.ack()  # remove from source only after a successful divert


class SQSDelivery(Delivery):
    """One SQS delivery attempt — READS the wire (identity, attempt count,
    trace carrier); every write goes through the composed
    :class:`SQSSettlement` (which also declares the terminal fate), via the
    base latch."""

    def __init__(
        self,
        event: Event,
        *,
        settlement: Settlement,
        message_id: str,
        system_attributes: Mapping[str, Any],
        wire_attributes: Mapping[str, Any],
    ) -> None:
        super().__init__(event, settlement)
        self._message_id = message_id
        self._system = dict(system_attributes)
        self._wire = dict(wire_attributes)

    @property
    def transport_id(self) -> str:
        return self._message_id

    @property
    def retry_count(self) -> int:
        # Broker-owned counter (system namespace) — unspoofable by producers.
        return int(_unwrap(self._system.get("ApproximateReceiveCount")) or 1)

    def carrier(self) -> Mapping[str, str]:
        """W3C trace context + wire attributes — producer namespace ONLY, so a
        DLQ divert forwards event identity and trace, never broker counters
        (a stale ApproximateReceiveCount in the carrier would poison the
        replayed message's attempt counting downstream)."""
        flat: Dict[str, str] = {}
        for key, value in self._wire.items():
            text = _unwrap(value)
            if text is not None:
                flat[str(key)] = text
        return flat


class SQSConsumer(PullEventConsumer):
    def __init__(
        self,
        config: SQSConsumerEventConfig,
        *,
        session: Optional[Any] = None,
        control: Optional[ControlSource] = None,
    ):
        super().__init__(config, control=control)
        self._config: SQSConsumerEventConfig = config
        self.session = session or aioboto3.Session()

    @property
    def capabilities(self) -> TransportCapabilities:
        # ApproximateReceiveCount is a real per-redelivery counter (of
        # *receives* — a ceiling on deliveries, not handler runs).
        return TransportCapabilities(counts_attempts=True)

    def _to_event(
        self,
        message: Dict[str, Any],
        wire: Dict[str, Any],
        system: Dict[str, Any],
    ) -> Event:
        try:
            data = json.loads(message["Body"])
        except json.JSONDecodeError:
            data = message["Body"]

        # SentTimestamp is broker-owned (system namespace) — a producer's
        # message attributes can never shadow it.
        sent = system.get("SentTimestamp")
        occurred = datetime.fromtimestamp(int(sent) / 1000) if sent else utcnow()

        # Flatten the producer's attribute bag to plain strings, then
        # reconstruct the event through the one wire contract (with the
        # transport's own id/time as fallbacks for foreign producers).
        flat = {
            str(key): text
            for key, value in wire.items()
            if (text := _unwrap(value)) is not None
        }
        return wire_to_event(
            flat,
            data=data,
            fallback_id=message["MessageId"],
            fallback_time=occurred,
        )

    async def _process_message(self, message: Dict[str, Any]) -> None:
        try:
            # System attributes (broker-owned: ApproximateReceiveCount,
            # SentTimestamp, …) and message attributes (producer-owned: the
            # wire contract + trace carrier) are DIFFERENT namespaces — never
            # merged, so a producer cannot shadow broker counters.
            system = message.get("Attributes", {})
            wire = message.get("MessageAttributes", {})
            settlement = SQSSettlement(
                session=self.session,
                config=self._config,
                message_id=message["MessageId"],
                receipt_handle=message["ReceiptHandle"],
                raw_attributes=wire,
            )
            delivery = SQSDelivery(
                self._to_event(message, wire, system),
                settlement=settlement,
                message_id=message["MessageId"],
                system_attributes=system,
                wire_attributes=wire,
            )
        except Exception as e:
            # Malformed at the wire — cannot even build a delivery. Leave it
            # unsettled: it redelivers after the visibility timeout, where the
            # queue's own redrive (or an operator) owns the poison case.
            # Raising here would abort the TaskGroup and cancel healthy
            # sibling dispatches mid-handler.
            logger.error(
                f"Malformed SQS message {message.get('MessageId')} left for "
                f"redelivery: {e}"
            )
            return
        try:
            await self.dispatch(delivery)
        except Exception as e:
            # Dispatcher-level failure (not a handler outcome — those settle
            # inside dispatch). The outcome is UNKNOWN, so the only honest
            # disposition is none at all: leave the message for redelivery.
            # Hard-dead-lettering here would ignore the declared terminal
            # fate and physically divert without any hook firing.
            logger.exception(
                f"Dispatch failed for message {delivery.transport_id}; "
                f"leaving unsettled for redelivery: {e}"
            )

    async def _poll_loop(self) -> None:
        # Polling infrastructure must SURVIVE broker outages: a poll error is
        # backed off and retried for as long as the consumer runs — a finite
        # strike count here would permanently kill consumption over a
        # transient outage longer than a few polls.
        poll_backoff = ExponentialBackoff(base_delay=1.0, max_delay=30.0)
        consecutive_errors = 0
        async with self.session.client(
            "sqs",
            region_name=self._config.region,
            endpoint_url=self._config.endpoint_url,
        ) as sqs:  # type: ignore[attr-defined]
            while self._running:
                control = await self._control_gate()
                if control is None:
                    continue
                throttled = control.state is ControlState.THROTTLED

                logger.debug(f"Polling SQS from queue: {self._config.queue_url}")
                try:
                    response = await sqs.receive_message(
                        QueueUrl=self._config.queue_url,
                        MaxNumberOfMessages=(
                            1 if throttled else self._config.max_number_of_messages
                        ),
                        VisibilityTimeout=self._config.visibility_timeout,
                        WaitTimeSeconds=self._config.wait_time_seconds,
                        AttributeNames=["All"],
                        MessageAttributeNames=["All"],
                    )
                    consecutive_errors = 0
                    messages = response.get("Messages", [])
                    if messages:
                        logger.debug(
                            f"Found {len(messages)} message(s), dispatching..."
                        )
                        async with asyncio.TaskGroup() as tg:
                            for msg in messages:
                                tg.create_task(self._process_message(msg))
                        await self._throttle_pace(control)
                    else:
                        await asyncio.sleep(self._config.poll_interval)
                except ClientError as e:
                    consecutive_errors += 1
                    delay = poll_backoff.next_delay(consecutive_errors)
                    logger.warning(
                        f"Error polling SQS ({consecutive_errors} consecutive): "
                        f"{e} — retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
