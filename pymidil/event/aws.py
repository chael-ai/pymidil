from urllib.parse import urlparse
from loguru import logger


def get_region_from_sqs_queue_url(queue_url: str) -> str:
    try:
        host = urlparse(queue_url).netloc  # e.g. "sqs.us-east-1.amazonaws.com"
        parts = host.split(".")
        if len(parts) < 3 or parts[0] != "sqs":
            raise ValueError("Invalid SQS host format")
        return parts[1]
    except Exception as e:
        logger.error(f"Could not extract region from queue url: {e}")
        raise ValueError(f"Invalid SQS queue url: {queue_url}") from e
