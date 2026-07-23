"""LocalStack plumbing: an aioboto3 session and one-shot queue creation.

Isolated from the event logic so the interesting modules never touch boto3
bootstrapping.
"""

from __future__ import annotations

import aioboto3
import boto3
from loguru import logger

from .settings import BRANCHES, LOYALTY_DLQ, SOURCE_QUEUE, Settings


def make_session(s: Settings) -> aioboto3.Session:
    """An aioboto3 session with LocalStack's dummy credentials."""
    return aioboto3.Session(
        aws_access_key_id="test", aws_secret_access_key="test", region_name=s.region
    )


def create_queues(s: Settings) -> dict[str, str]:
    """Create every queue the topology needs and return ``name → url``."""
    sqs = boto3.client(
        "sqs",
        endpoint_url=s.endpoint_url,
        region_name=s.region,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    names = [SOURCE_QUEUE, LOYALTY_DLQ, *(b.queue for b in BRANCHES)]
    urls = {name: sqs.create_queue(QueueName=name)["QueueUrl"] for name in names}
    logger.info("Created {} SQS queues on LocalStack", len(urls))
    return urls
