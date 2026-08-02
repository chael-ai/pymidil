"""Retry policy — the consumer-level contract for bounded, paced redelivery.

One policy, one owner: the dispatcher decides (whether to retry, with what
delay, and when the budget is spent), the transport enacts (visibility
timeout, requeue). Handlers never see any of this — they drive the outcome by
what they return or raise.

The policy is pure data (:class:`RetryConfig`), so it rides the declarative
``MIDIL__EVENT`` config and the programmatic config object identically — there
is no separate mutator API.

A policy is a promise about physical behavior, so it is validated against
what the transport can physically do (:class:`TransportCapabilities`) at
construction — a bounded budget on a transport that cannot count attempts
would silently never trigger, which is exactly the silent fallback this
module exists to kill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from pymidil.utils.backoff import (
    BackoffStrategy,
    ExponentialBackoff,
    ExponentialBackoffWithJitter,
)


class RetryConfig(BaseModel):
    """Bounded transport redelivery. The broker redelivers; this caps and paces it."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: Optional[int] = Field(
        default=5,
        ge=1,
        description=(
            "Total delivery attempts before a retryable failure becomes "
            "terminal (routed to the consumer's declared terminal fate). "
            "None = unbounded — an explicit choice, e.g. for consumers that "
            "legitimately wait on out-of-order events."
        ),
    )
    backoff_base_delay: float = Field(default=5, ge=0)
    backoff_max_delay: float = Field(default=300, ge=0)
    jitter: bool = Field(
        default=True,
        description="Jitter the delay curve to prevent synchronized redelivery herds",
    )

    def build_backoff(self) -> BackoffStrategy:
        """The delay curve this policy promises — decided here, enacted by the
        transport (``delivery.retry(delay)``)."""
        if self.jitter:
            return ExponentialBackoffWithJitter(
                base=self.backoff_base_delay, cap=self.backoff_max_delay
            )
        return ExponentialBackoff(
            base_delay=self.backoff_base_delay, max_delay=self.backoff_max_delay
        )


@dataclass(frozen=True)
class TransportCapabilities:
    """What a consumer's transport can PHYSICALLY do — computed from live
    config at construction, never aspirational. Policies validate against it,
    so a promise the transport cannot keep refuses loudly at wiring time.

    Grows a field per capability the moment a policy needs to check it.
    """

    counts_attempts: bool = (
        False  # Delivery.retry_count is a real per-redelivery counter
    )


class RetryPolicyError(ValueError):
    """A retry policy the consumer's transport cannot physically honor."""


def validate_policy(
    retry: RetryConfig, capabilities: TransportCapabilities, consumer_name: str
) -> None:
    """Refuse, at construction, any policy the transport cannot keep."""
    if retry.max_attempts is not None and not capabilities.counts_attempts:
        raise RetryPolicyError(
            f"Consumer '{consumer_name}' sets retry.max_attempts="
            f"{retry.max_attempts}, but its transport cannot count delivery "
            f"attempts (retry_count is always 1) — the budget would silently "
            f"never trigger. Set retry.max_attempts=None explicitly, or use a "
            f"transport that tracks attempts."
        )
