"""
Pytest configuration and fixtures for midil tests.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel


class MockAttributes(BaseModel):
    """Mock attributes for testing JSON:API resources."""

    name: str = "Test Name"
    email: str = "test@example.com"
    status: str = "active"


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_jwt_claims():
    """Mock JWT claims for testing."""
    return {
        "sub": "test-user-id",
        "email": "test@example.com",
        "name": "Test User",
        "iss": "https://idp.example.com/test",
        "aud": "test-client-id",
        "iat": int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }


@pytest.fixture
def mock_auth_headers():
    """Mock authentication headers."""
    return {
        "Authorization": "Bearer test-token",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


@pytest.fixture
def mock_sqs_message():
    """Mock SQS message for testing."""
    return {
        "Body": '{"event": "test.event", "body": {"test": "data"}}',
        "ReceiptHandle": "test-receipt-handle",
        "MessageId": "test-message-id",
        "Attributes": {},
        "MessageAttributes": {},
    }


@pytest.fixture
def mock_jsonapi_resource():
    """Mock JSON:API resource data."""
    return {
        "type": "users",
        "id": "123",
        "attributes": {
            "name": "Test User",
            "email": "test@example.com",
            "status": "active",
        },
        "relationships": {
            "posts": {
                "data": [{"type": "posts", "id": "1"}, {"type": "posts", "id": "2"}]
            }
        },
        "meta": {"created_at": "2023-01-01T00:00:00Z"},
    }


@pytest.fixture
def mock_async_client():
    """Mock httpx.AsyncClient for testing."""
    client = AsyncMock()
    client.request = AsyncMock()
    client.base_url = "https://api.example.com"
    return client


@pytest.fixture
def mock_boto3_sqs_client():
    """Mock boto3 SQS client for testing."""
    client = AsyncMock()
    client.receive_message = AsyncMock()
    client.delete_message = AsyncMock()
    return client


@pytest.fixture
def mock_jwt_token():
    """Valid JWT token for testing."""
    return "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0LXVzZXItaWQiLCJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJuYW1lIjoiVGVzdCBVc2VyIiwiaXNzIjoiaHR0cHM6Ly9jb2duaXRvLWlkcC51cy1lYXN0LTEuYW1hem9uYXdzLmNvbS91cy1lYXN0LTFfdGVzdCIsImF1ZCI6InRlc3QtY2xpZW50LWlkIiwiaWF0IjoxNjQwOTk1MjAwLCJleHAiOjE2NDA5OTg4MDB9"


@pytest.fixture
def sample_event_data():
    """Sample event data for event tests."""
    return {
        "event": "user.created",
        "body": {
            "user_id": "123",
            "email": "user@example.com",
            "timestamp": "2023-01-01T00:00:00Z",
        },
    }
