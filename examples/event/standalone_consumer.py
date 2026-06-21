from pymidil.event.consumer.sqs import SQSConsumer, SQSConsumerEventConfig
from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn
from typing import Dict, Any
from pymidil.event.subscriber.base import FunctionSubscriber
from loguru import logger
from pymidil.settings import get_settings


# Load config from environment variables or .env file (recommended for production):
#
# Named Consumer Configuration:
#   MIDIL__EVENT__CONSUMERS__BOOKING__TYPE=sqs
#   MIDIL__EVENT__CONSUMERS__BOOKING__QUEUE_URL=https://sqs.us-east-1.amazonaws.com/616782207790/booking-events-dev-v1
#   MIDIL__EVENT__CONSUMERS__BOOKING__DLQ_URL=...
#   MIDIL__EVENT__CONSUMERS__BOOKING__VISIBILITY_TIMEOUT=30
#   MIDIL__EVENT__CONSUMERS__BOOKING__MAX_NUMBER_OF_MESSAGES=10
#   MIDIL__EVENT__CONSUMERS__BOOKING__WAIT_TIME_SECONDS=20
#   MIDIL__EVENT__CONSUMERS__BOOKING__POLL_INTERVAL=0.1
#   MIDIL__EVENT__CONSUMERS__BOOKING__MAX_CONCURRENT_MESSAGES=10
# Then use: consumer_config = get_settings().get_consumer("main_queue")


# Alternative: Create config explicitly
# sqs_config = SQSConsumerEventConfig(
#     queue_url="https://sqs.us-east-1.amazonaws.com/616782207790/booking-events-dev-v1",
#     dlq_url=None,
#     visibility_timeout=30,
#     max_number_of_messages=10,
#     wait_time_seconds=20,
#     poll_interval=0.1,
#     max_concurrent_messages=10,
# )


# Get the consumer configuration by name
consumer_config = get_settings().get_consumer("booking")

# Ensure the config is of the correct type (SQSConsumerEventConfig)
if not isinstance(consumer_config, SQSConsumerEventConfig):
    raise TypeError("Consumer 'booking' must be an instance of SQSConsumerEventConfig")

consumer = SQSConsumer(consumer_config)


def handle_event(event: Dict[str, Any]):
    logger.info(f"Event {event} handled successfully")


consumer.subscribe(FunctionSubscriber(handle_event))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await consumer.start()
    yield
    await consumer.stop()


app = FastAPI(lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(
        "pymidil.event._examples.standalone_consumer:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
