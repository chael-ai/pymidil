import aioboto3
import json
from typing import Any, Dict
from loguru import logger
from datetime import datetime


class AWSEventBridgeScheduler:
    def __init__(self, region: str = "us-east-1"):
        self.region = region

    async def put_event(
        self,
        detail_type: str,
        source: str,
        detail: Dict[str, Any],
        event_bus_name: str = "default",
    ) -> Dict[str, Any]:
        try:
            async with aioboto3.client("events", region_name=self.region) as client:  # type: ignore[attr-defined]
                response: Dict[str, Any] = await client.put_events(
                    Entries=[
                        {
                            "Source": source,
                            "DetailType": detail_type,
                            "Detail": json.dumps(detail),
                            "EventBusName": event_bus_name,
                        }
                    ]
                )
                logger.info("EventBridge event emitted", extra={"response": response})

                return response
        except Exception as e:
            logger.error(f"Failed to put EventBridge event: {e}")
            raise

    async def schedule_event(
        self,
        schedule_name: str,
        endpoint: str,
        execution_time: datetime,
        data: Dict[str, Any],
        role_arn: str,
    ) -> None:
        try:
            async with aioboto3.client("scheduler", region_name=self.region) as client:  # type: ignore[attr-defined]
                await client.create_schedule(
                    Name=schedule_name,
                    ScheduleExpression=f"at({execution_time.isoformat()})",
                    FlexibleTimeWindow={"Mode": "OFF"},
                    Target={
                        "Arn": endpoint,
                        "RoleArn": role_arn,
                        "Input": json.dumps(data),
                    },
                )
                logger.info(
                    f"Scheduled event '{schedule_name}' at {execution_time.isoformat()}"
                )
        except Exception as e:
            logger.error(f"Failed to schedule event '{schedule_name}': {e}")
            raise
