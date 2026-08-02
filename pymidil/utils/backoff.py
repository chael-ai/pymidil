import abc
import random


class BackoffStrategy(abc.ABC):
    """Abstract base for backoff strategies"""

    @abc.abstractmethod
    def next_delay(self, attempt: int) -> float:
        raise NotImplementedError


# 2**_MAX_EXPONENT already dwarfs any real cap; clamping the exponent keeps
# base * 2**n inside float range for arbitrarily large attempt counts
# (unbounded-retry consumers reach attempt numbers where 2**(attempt-1)
# overflows float conversion).
_MAX_EXPONENT = 63


class ExponentialBackoff(BackoffStrategy):
    """Exponential backoff without jitter"""

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0) -> None:
        self.base_delay = base_delay
        self.max_delay = max_delay

    def next_delay(self, attempt: int) -> float:
        exponent = min(max(attempt - 1, 0), _MAX_EXPONENT)
        return min(self.base_delay * (2**exponent), self.max_delay)


class ExponentialBackoffWithJitter(BackoffStrategy):
    def __init__(
        self, base: float = 1.0, cap: float = 60.0, jitter: float = 0.2
    ) -> None:
        self.base = base
        self.cap = cap
        self.jitter = jitter

    def next_delay(self, attempt: int) -> float:
        exponent = min(max(attempt - 1, 0), _MAX_EXPONENT)
        delay = min(self.cap, self.base * (2**exponent))
        jitter_amt = (random.random() * 2 - 1) * self.jitter * delay
        # Jitter must stay inside the promised curve: never above the cap,
        # never negative.
        return max(0.0, min(delay + jitter_amt, self.cap))
