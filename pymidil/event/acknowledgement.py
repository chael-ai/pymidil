"""Transport-agnostic acknowledgement (Acknowledger).

Every consumer *is* an ``Acknowledger``: the dispatch lifecycle resolves an
outcome into one of three broker-agnostic dispositions and calls them.

- ``ack``   — processed successfully; remove/commit.
- ``retry`` — make the delivery available again for re-processing.
- ``dlq``   — divert to a dead-letter destination.

Defaults are no-ops (the Null Object), which is exactly right for push transports
(e.g. webhook) and tests; pull transports like SQS override all three. Note there
is deliberately no ``nack``: it conflated "retry-or-dead-letter by config", which
this three-verb vocabulary decomposes.

These are pure transport actions — they do **not** fire lifecycle hooks; the
dispatcher owns observability so each disposition is reported exactly once.
"""

from __future__ import annotations

from abc import ABC
from typing import Optional

from pymidil.event.message import Message


class Acknowledger(ABC):
    """Three dispositions with no-op defaults; transports override what applies."""

    async def ack(self, message: Message) -> None:
        """
        Acknowledge the receipt of an event.

        This method should be implemented to acknowledge the receipt of an event,
        such as confirming that the event has been processed successfully.

        Args:
            message: The message to ack.
        """
        pass

    async def retry(self, message: Message) -> None:
        """
        Retry the receipt of an event.

        This method should be implemented to retry the receipt of an event,
        such as making the event available again for re-processing.

        Args:
            message: The message to retry.
        """
        pass

    async def dlq(self, message: Message, error: Optional[Exception] = None) -> None:
        """
        Dead-letter the receipt of an event.

        This method should be implemented to dead-letter the receipt of an event,
        such as diverting the event to a dead-letter destination.

        Args:
            message: The message to dlq.
            error: The error that occurred.
        """
        pass
