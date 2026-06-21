"""
Tests for midil.auth.cognito.authenticator
"""

import pytest
import httpx
import base64
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timezone, timedelta

from pymidil.auth.cognito.authenticator import (
    CognitoClientCredentialsAuthenticator,
)
from pymidil.auth.interfaces.types import AuthNToken, AuthNHeaders
from pymidil.auth.cognito.exceptions import CognitoAuthenticationError
from pymidil.auth.interfaces.authenticator import AuthNProvider


class TestCognitoClientCredentialsAuthenticator:
    """Tests for CognitoClientCredentialsAuthenticator."""

    @pytest.fixture
    def auth_client(self):
        """Create a CognitoClientCredentialsAuthenticator instance for testing."""
        return CognitoClientCredentialsAuthenticator(
            client_id="test-client-id",
            client_secret="test-client-secret",
            token_url="https://cognito.amazonaws.com/oauth2/token",
            scope="read write",
        )

    @pytest.fixture
    def auth_client_no_scope(self):
        """Create a CognitoClientCredentialsAuthenticator instance without scope."""
        return CognitoClientCredentialsAuthenticator(
            client_id="test-client-id",
            client_secret="test-client-secret",
            token_url="https://cognito.amazonaws.com/oauth2/token",
        )

    @pytest.fixture
    def mock_token_response(self):
        """Mock successful token response."""
        return {
            "access_token": "test-access-token-123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read write",
        }

    def test_init(self, auth_client):
        """Test CognitoClientCredentialsAuthenticator initialization."""
        assert auth_client.client_id == "test-client-id"
        assert auth_client.client_secret == "test-client-secret"
        assert auth_client.token_url == "https://cognito.amazonaws.com/oauth2/token"
        assert auth_client.scope == "read write"
        assert auth_client._cached_token is None

    def test_init_without_scope(self, auth_client_no_scope):
        """Test initialization without scope."""
        assert auth_client_no_scope.scope is None

    @pytest.mark.asyncio
    async def test_get_token_success_first_time(self, auth_client, mock_token_response):
        """Test successful token retrieval on first call."""
        with patch.object(
            auth_client, "_fetch_token", return_value=mock_token_response
        ) as mock_fetch:
            token = await auth_client.get_token()

            assert isinstance(token, AuthNToken)
            assert token.token == "test-access-token-123"
            mock_fetch.assert_called_once()

            # Token should be cached
            assert auth_client._cached_token == token

    @pytest.mark.asyncio
    async def test_get_token_uses_cached_token(self, auth_client, mock_token_response):
        """Test that cached token is used when not expired."""
        # Set up a cached token that's not expired
        cached_token = AuthNToken(
            token="cached-token",
            expires_at_iso=(
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        )
        auth_client._cached_token = cached_token

        with patch.object(auth_client, "_fetch_token") as mock_fetch:
            token = await auth_client.get_token()

            assert token == cached_token
            mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_token_refreshes_expired_cached_token(
        self, auth_client, mock_token_response
    ):
        """Test that expired cached token is refreshed."""
        # Set up an expired cached token
        expired_token = AuthNToken(
            token="expired-token",
            expires_at_iso=(
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat(),
        )
        auth_client._cached_token = expired_token

        with patch.object(
            auth_client, "_fetch_token", return_value=mock_token_response
        ) as mock_fetch:
            token = await auth_client.get_token()

            assert isinstance(token, AuthNToken)
            assert token.token == "test-access-token-123"
            assert token != expired_token
            mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_token_concurrent_access(self, auth_client, mock_token_response):
        """Test that concurrent access is handled with locking."""
        import asyncio

        call_count = 0

        async def mock_fetch_with_delay():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Simulate network delay
            return mock_token_response

        with patch.object(
            auth_client, "_fetch_token", side_effect=mock_fetch_with_delay
        ):
            # Make concurrent calls
            tasks = [auth_client.get_token() for _ in range(3)]
            tokens = await asyncio.gather(*tasks)

            # All should return the same token
            assert all(token.token == "test-access-token-123" for token in tokens)
            # _fetch_token should only be called once due to locking
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_get_headers_success(self, auth_client, mock_token_response):
        """Test successful header generation."""
        with patch.object(
            auth_client, "_fetch_token", return_value=mock_token_response
        ):
            headers = await auth_client.get_headers()

            assert isinstance(headers, AuthNHeaders)
            assert headers.authorization == "Bearer test-access-token-123"
            assert headers.content_type == "application/x-www-form-urlencoded"

    @pytest.mark.asyncio
    async def test_get_headers_uses_cached_token(self, auth_client):
        """Test that get_headers uses cached token."""
        # Set up a cached token
        cached_token = AuthNToken(
            token="cached-header-token",
            expires_at_iso=(
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        )
        auth_client._cached_token = cached_token

        with patch.object(auth_client, "_fetch_token") as mock_fetch:
            headers = await auth_client.get_headers()

            assert headers.authorization == "Bearer cached-header-token"
            mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_token_success(self, auth_client, mock_token_response):
        """Test successful token fetching."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        auth_client.client = mock_client

        result = await auth_client._fetch_token()

        assert result == mock_token_response

        # Verify the request was made correctly
        expected_credentials = f"{auth_client.client_id}:{auth_client.client_secret}"
        expected_auth = base64.b64encode(expected_credentials.encode()).decode()

        mock_client.post.assert_called_once_with(
            auth_client.token_url,
            data={"grant_type": "client_credentials", "scope": "read write"},
            headers={
                "Authorization": f"Basic {expected_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    @pytest.mark.asyncio
    async def test_fetch_token_without_scope(
        self, auth_client_no_scope, mock_token_response
    ):
        """Test token fetching without scope."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        auth_client_no_scope.client = mock_client

        result = await auth_client_no_scope._fetch_token()

        assert result == mock_token_response

        # Verify request data doesn't include scope
        call_args = mock_client.post.call_args
        assert call_args[1]["data"] == {"grant_type": "client_credentials"}

    @pytest.mark.asyncio
    async def test_fetch_token_http_error(self, auth_client):
        """Test token fetching with HTTP error."""
        # Setup mock error response
        error_response = {
            "error": "invalid_client",
            "error_description": "Invalid client credentials",
        }
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = error_response

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        auth_client.client = mock_client

        with pytest.raises(
            CognitoAuthenticationError, match="Cognito token fetch failed"
        ):
            await auth_client._fetch_token()

    @pytest.mark.asyncio
    async def test_fetch_token_different_error_codes(self, auth_client):
        """Test token fetching with different HTTP error codes."""
        error_codes = [400, 401, 403, 500, 502]

        for status_code in error_codes:
            mock_response = Mock()
            mock_response.status_code = status_code
            mock_response.json.return_value = {"error": f"error_{status_code}"}

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            auth_client.client = mock_client

            with pytest.raises(CognitoAuthenticationError):
                await auth_client._fetch_token()

    @pytest.mark.asyncio
    async def test_fetch_token_network_error(self, auth_client):
        """Test token fetching with network error."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection failed")
        auth_client.client = mock_client

        with pytest.raises(httpx.ConnectError):
            await auth_client._fetch_token()

    def test_basic_auth_encoding(self, auth_client):
        """Test that basic auth encoding works correctly."""
        credentials = f"{auth_client.client_id}:{auth_client.client_secret}"
        expected_encoding = base64.b64encode(credentials.encode()).decode()

        # This is the same logic used in _fetch_token
        actual_encoding = base64.b64encode(
            "test-client-id:test-client-secret".encode()
        ).decode()

        assert actual_encoding == expected_encoding

    @pytest.mark.asyncio
    async def test_token_creation_with_expires_in(
        self, auth_client, mock_token_response
    ):
        """Test that AuthNToken is created correctly with expires_in field."""
        before_call = datetime.now(timezone.utc)

        with patch.object(
            auth_client, "_fetch_token", return_value=mock_token_response
        ):
            token = await auth_client.get_token()

            assert token.token == "test-access-token-123"
            assert token.expires_at_iso is not None

            # Parse the expires_at_iso and verify it's approximately 3600 seconds from now
            expires_at = datetime.fromisoformat(
                token.expires_at_iso.replace("Z", "+00:00")
            )
            expected_expires = before_call + timedelta(seconds=3600)

            # Allow for a small margin of error (up to 5 seconds) due to test execution time
            time_diff = abs((expires_at - expected_expires).total_seconds())
            assert (
                time_diff < 5
            ), f"Expected expiration around {expected_expires}, got {expires_at}"

    @pytest.mark.asyncio
    async def test_token_creation_without_expires_in(self, auth_client):
        """Test token creation when response doesn't include expires_in."""
        response_without_expires = {
            "access_token": "test-access-token-no-expiry",
            "token_type": "Bearer",
        }

        with patch.object(
            auth_client, "_fetch_token", return_value=response_without_expires
        ):
            token = await auth_client.get_token()

            assert token.token == "test-access-token-no-expiry"
            assert token.expires_at_iso is None

    @pytest.mark.asyncio
    async def test_inheritance_from_authn_provider(self, auth_client):
        """Test that the class properly implements AuthNProvider interface."""

        assert isinstance(auth_client, AuthNProvider)

        # Should have required methods
        assert hasattr(auth_client, "get_token")
        assert hasattr(auth_client, "get_headers")

        # Methods should be async
        import asyncio

        assert asyncio.iscoroutinefunction(auth_client.get_token)
        assert asyncio.iscoroutinefunction(auth_client.get_headers)

    @pytest.mark.asyncio
    async def test_lock_is_asyncio_lock(self, auth_client):
        """Test that the lock is properly initialized as asyncio.Lock."""
        import asyncio

        assert isinstance(auth_client._lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_fetch_token_request_structure(self, auth_client):
        """Test the exact structure of the token request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "test-token"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        auth_client.client = mock_client

        await auth_client._fetch_token()

        # Get the actual call arguments
        call_args = mock_client.post.call_args

        # Verify URL
        assert call_args[0][0] == "https://cognito.amazonaws.com/oauth2/token"

        # Verify data
        expected_data = {"grant_type": "client_credentials", "scope": "read write"}
        assert call_args[1]["data"] == expected_data

        # Verify headers
        expected_credentials = "test-client-id:test-client-secret"
        expected_auth = base64.b64encode(expected_credentials.encode()).decode()
        expected_headers = {
            "Authorization": f"Basic {expected_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        assert call_args[1]["headers"] == expected_headers
