from pymidil.event.consumer.strategies.base import EventConsumer
from pymidil.event.control import (
    Control,
    ControlSource,
    ControlState,
    NullControlSource,
)
from pymidil.event.exceptions import (
    ConsumerCrashError,
    ConsumerStopError,
)
from loguru import logger
import asyncio
from typing import Any, Optional
from pydantic import Field
from pymidil.event.consumer.strategies.base import BaseConsumerConfig
from abc import abstractmethod


class PullEventConsumerConfig(BaseConsumerConfig):
    poll_interval: float = Field(
        default=0.1, description="Interval between polls if no messages", ge=0.0
    )


class PullEventConsumer(EventConsumer):
    """Base for transports that actively pull (SQS, Kafka, …).

    Owns the poll-task lifecycle (start/stop/crash detection) and the
    control-plane gate: every pull transport honours the operator's desired
    state — pause / throttle / drain — by bracketing its cycle with
    :meth:`_control_gate` and :meth:`_throttle_pace`, so enforcement is
    inherited rather than re-implemented per broker::

        while self._running:
            control = await self._control_gate()
            if control is None:          # paused/draining — already napped
                continue
            batch = await pull(...)      # transport-specific
            ...dispatch...
            await self._throttle_pace(control)
    """

    def __init__(
        self,
        config: PullEventConsumerConfig,
        *,
        control: Optional[ControlSource] = None,
    ):
        super().__init__(config)
        self._config: PullEventConsumerConfig = config
        self._running: bool = False
        self._loop_task: asyncio.Task[Any] | None = None
        # Defaults to always-running so consumers without a control plane are
        # unaffected; wire an HttpControlSource to enforce console actions.
        self._control: ControlSource = control or NullControlSource()

    @abstractmethod
    async def _poll_loop(self) -> None:
        ...

    async def _control_gate(self) -> Optional[Control]:
        """Gate one pull cycle on the operator's control state.

        Returns the current :class:`Control` when the consumer should pull
        (running or throttled), or ``None`` when paused/draining — in which
        case this method has already napped and the loop should ``continue``.
        """
        control = await self._control.get()
        if control.state.should_pull:
            return control
        logger.debug(f"{self.name} is {control.state.value}; not pulling this cycle")
        await asyncio.sleep(max(self._config.poll_interval, 1.0))
        return None

    async def _throttle_pace(self, control: Control) -> None:
        """After a processed batch, pace a throttled consumer to roughly
        ``throttle_per_sec`` messages/sec. No-op unless throttled."""
        if control.state is not ControlState.THROTTLED:
            return
        rate = control.throttle_per_sec or 1.0
        await asyncio.sleep(1.0 / rate if rate > 0 else 1.0)

    async def start(self) -> None:
        if self._running:
            logger.warning(f"Consumer {self.__class__.__name__} already running")
            return

        logger.info(f"Starting consumer {self.__class__.__name__}")
        self._running = True
        self._loop_task = asyncio.create_task(self._poll_loop())
        self._loop_task.add_done_callback(self._handle_task_exception)

    def _handle_task_exception(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            logger.info(f"Consumer {self.__class__.__name__} task was cancelled")
            return
        exc = task.exception()
        if exc:
            logger.error(
                f"Consumer {self.__class__.__name__} terminated with crash: {exc}"
            )
            raise ConsumerCrashError(f"Consumer crashed: {exc}")

    async def stop(self) -> None:
        if not self._running:
            logger.warning(f"Consumer {self.__class__.__name__} already stopped")
            return

        logger.info(f"Stopping consumer {self.__class__.__name__}")
        self._running = False

        try:
            await self._close()
        except Exception as e:
            logger.error(f"Error closing consumer {self.__class__.__name__}: {e}")
            raise ConsumerStopError(f"Failed to close consumer: {e}")

        finally:
            await self._reset_state()

    async def _reset_state(self) -> None:
        self._subscribers.clear()
        if self._loop_task:
            if not self._loop_task.done():
                self._loop_task.cancel()
                try:
                    await self._loop_task
                except asyncio.CancelledError:
                    logger.debug(
                        f"Task cancellation completed for {self.__class__.__name__}"
                    )
                except Exception as e:
                    logger.debug(f"Task already failed with: {e}, skipping re-raise")
            self._loop_task = None

    async def _close(self) -> None:
        """
        Close the consumer and release any resources.
        Override this method in subclasses if cleanup is needed.
        """
        pass
