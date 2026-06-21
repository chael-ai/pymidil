from pymidil.event.producer.sqs import SQSProducer, SQSProducerEventConfig
from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn
from pydantic import BaseModel, Field
from pymidil.settings import get_settings


# Create config explicitly
# config = SQSProducerEventConfig(queue_url="https://sqs.us-east-1.amazonaws.com/616782207790/example-queue")
# producer = SQSProducer(config)

# Alternative: Create config from environment variables
producer_config = get_settings().get_producer("booking")

if not isinstance(producer_config, SQSProducerEventConfig):
    raise TypeError(
        "event_settings.event.producer must be an instance of SQSProducerEventConfig"
    )

producer = SQSProducer(producer_config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # If your producer needs to start/stop, do it here
    yield
    await producer.close()


app = FastAPI(lifespan=lifespan)


class Event(BaseModel):
    message: str = Field(..., description="Message to publish")


@app.post("/produce")
async def produce_event(event: Event):
    await producer.publish(event.model_dump())
    return {"status": "event published"}


if __name__ == "__main__":
    uvicorn.run(
        "pymidil.event._examples.standalone_producer:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
    )
