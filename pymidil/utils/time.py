from datetime import datetime, timezone


def utcnow() -> datetime:
    """
    Get the current time in UTC.
    """
    return datetime.now(timezone.utc)
