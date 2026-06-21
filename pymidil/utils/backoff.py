import abc
import random


class BackoffStrategy(abc.ABC):
    """Abstract base for backoff strategies"""

    @abc.abstractmethod
    def next_delay(self, attempt: int) -> float:
        raise NotImplementedError


class ExponentialBackoff(BackoffStrategy):
    """Exponential backoff without jitter"""

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0) -> None:
        self.base_delay = base_delay
        self.max_delay = max_delay

    def next_delay(self, attempt: int) -> float:
        return min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)


class ExponentialBackoffWithJitter(BackoffStrategy):
    def __init__(
        self, base: float = 1.0, cap: float = 60.0, jitter: float = 0.2
    ) -> None:
        self.base = base
        self.cap = cap
        self.jitter = jitter

    def next_delay(self, attempt: int) -> float:
        delay = min(self.cap, self.base * (2 ** (attempt - 1)))
        jitter_amt = (random.random() * 2 - 1) * self.jitter * delay
        return max(0.0, delay + jitter_amt)
