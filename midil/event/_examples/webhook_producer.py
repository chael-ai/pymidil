from fastapi import FastAPI
import uvicorn
from midil.event.consumer.webhook import WebhookConsumer, WebhookConsumerEventConfig
from midil.event.message import Message
from midil.event.subscriber.base import FunctionSubscriber
from contextlib import asynccontextmanager


# Example handler function
async def handle_event(event: Message):
    print(f"Received event: {event.id}, body: {event.body}")


# Configure the webhook consumer
config = WebhookConsumerEventConfig(endpoint="/event/{tenant_id}/{workflow_id}/webhook")
consumer = WebhookConsumer(config)
consumer.subscribe(FunctionSubscriber(handle_event))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await consumer.start()
    yield
    await consumer.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(consumer.entrypoint, tags=["webhook"])

if __name__ == "__main__":
    uvicorn.run(
        "midil.event._examples.webhook_producer:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
