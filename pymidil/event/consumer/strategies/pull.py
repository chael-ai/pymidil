from pymidil.event.consumer.strategies.base import EventConsumer
from pymidil.event.exceptions import (
    ConsumerCrashError,
    ConsumerStopError,
)
from loguru import logger
import asyncio
from typing import Any
from pydantic import Field
from pymidil.event.consumer.strategies.base import BaseConsumerConfig
from abc import abstractmethod


class PullEventConsumerConfig(BaseConsumerConfig):
    poll_interval: float = Field(
        default=0.1, description="Interval between polls if no messages", ge=0.0
    )


class PullEventConsumer(EventConsumer):
    def __init__(self, config: PullEventConsumerConfig):
        super().__init__(config)
        self._running: bool = False
        self._loop_task: asyncio.Task[Any] | None = None

    @abstractmethod
    async def _poll_loop(self) -> None:
        ...

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
