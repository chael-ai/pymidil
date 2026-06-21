from pymidil.event.context import event_context, get_current_event
from loguru import logger
import asyncio


async def handle_request():
    async with event_context("http_request") as ctx:
        logger.info("Started request:{}", ctx)
        await do_subtask()


async def do_subtask():
    async with event_context("subtask") as ctx:
        logger.info("In subtask with event:{}", ctx)


async def do_subtask_with_parent():
    async with event_context("subtask_with_parent"):
        grandparent = get_current_event()
        logger.info("In subtask with grandparent:{}", grandparent)


if __name__ == "__main__":
    asyncio.run(handle_request())


# Possible output:
# Started request: <EventContext id=abc123 type=http_request parent=None>
# In subtask with event: <EventContext id=def456 type=subtask parent=abc123>
