from typing import Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI

import uvicorn

from pymidil.event.event_bus import EventBus
from pymidil.utils.retry import AsyncRetry

bus = EventBus()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # start the event bus
    await bus.start()
    yield
    # stop the event bus
    await bus.stop()


app = FastAPI(lifespan=lifespan)


## subscribe to the event bus
retry = AsyncRetry()


@bus.subscriber(
    target="checkin",
    # middlewares=[LoggingMiddleware()],
)
async def handle_checkin_event(event: Dict[str, Any]):
    print("Function subscriber : I got it", event)


if __name__ == "__main__":
    uvicorn.run(
        "pymidil.event._examples.event_bus:app", host="0.0.0.0", port=8000, reload=True
    )
