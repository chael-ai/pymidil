"""
Tests for midil.auth.interfaces.authenticator
"""

import pytest
from abc import ABC
from unittest.mock import AsyncMock
from pymidil.auth.interfaces.authenticator import AuthNProvider
from pymidil.auth.interfaces.types import AuthNToken, AuthNHeaders

# Mark all async tests in this module to use anyio
pytestmark = pytest.mark.anyio


class ConcreteAuthNProvider(AuthNProvider):
    """Concrete implementation for testing."""

    def __init__(
        self, token_value: str = "test-token", header_value: str = "Bearer test-token"
    ) -> None:
        self.token_value: str = token_value
        self.header_value: str = header_value

    async def get_token(self) -> AuthNToken:
        return AuthNToken(token=self.token_value)

    async def get_headers(self) -> AuthNHeaders:
        return AuthNHeaders(**{"Authorization": self.header_value})


class TestAuthNProvider:
    """Tests for AuthNProvider abstract base class."""

    def test_is_abstract_base_class(self) -> None:
        """Test that AuthNProvider is an abstract base class."""
        assert issubclass(AuthNProvider, ABC)

    def test_cannot_instantiate_directly(self) -> None:
        """Test that AuthNProvider cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            AuthNProvider()  # type: ignore

    def test_abstract_methods_required(self) -> None:
        """Test that concrete implementations must implement abstract methods."""

        class IncompleteProvider(AuthNProvider):
            async def get_token(self) -> AuthNToken:
                return AuthNToken(token="test")

            # Missing get_headers implementation

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteProvider()  # type: ignore

    async def test_concrete_implementation_get_token(self) -> None:
        """Test concrete implementation of get_token method."""
        provider: ConcreteAuthNProvider = ConcreteAuthNProvider(
            token_value="my-test-token"
        )

        token: AuthNToken = await provider.get_token()

        assert isinstance(token, AuthNToken)
        assert token.token == "my-test-token"

    async def test_concrete_implementation_get_headers(self) -> None:
        """Test concrete implementation of get_headers method."""
        provider: ConcreteAuthNProvider = ConcreteAuthNProvider(
            header_value="Bearer my-auth-token"
        )

        headers: AuthNHeaders = await provider.get_headers()

        assert isinstance(headers, AuthNHeaders)
        assert headers.authorization == "Bearer my-auth-token"

    async def test_provider_with_different_configurations(self) -> None:
        """Test provider with different token and header configurations."""
        # Test with OAuth token
        oauth_provider: ConcreteAuthNProvider = ConcreteAuthNProvider(
            token_value="oauth-token-123", header_value="Bearer oauth-token-123"
        )

        token: AuthNToken = await oauth_provider.get_token()
        headers: AuthNHeaders = await oauth_provider.get_headers()

        assert token.token == "oauth-token-123"
        assert headers.authorization == "Bearer oauth-token-123"

        # Test with API key
        api_key_provider: ConcreteAuthNProvider = ConcreteAuthNProvider(
            token_value="api-key-456", header_value="X-API-Key api-key-456"
        )

        token = await api_key_provider.get_token()
        headers = await api_key_provider.get_headers()

        assert token.token == "api-key-456"
        assert headers.authorization == "X-API-Key api-key-456"

    def test_provider_docstring_examples(self) -> None:
        """Test that the docstring examples are accurate."""
        # The docstring mentions these methods should be implemented
        provider: ConcreteAuthNProvider = ConcreteAuthNProvider()

        # These methods should exist and be async
        assert hasattr(provider, "get_token")
        assert hasattr(provider, "get_headers")

        import asyncio

        assert asyncio.iscoroutinefunction(provider.get_token)
        assert asyncio.iscoroutinefunction(provider.get_headers)


class MockAuthNProvider(AuthNProvider):
    """Mock provider for additional testing scenarios."""

    def __init__(self) -> None:
        self.get_token_mock: AsyncMock = AsyncMock()
        self.get_headers_mock: AsyncMock = AsyncMock()

    async def get_token(self) -> AuthNToken:
        return await self.get_token_mock()

    async def get_headers(self) -> AuthNHeaders:
        return await self.get_headers_mock()


class TestAuthNProviderMocking:
    """Tests for mocking AuthNProvider implementations."""

    async def test_mock_provider_get_token(self) -> None:
        """Test mocking get_token method."""
        provider: MockAuthNProvider = MockAuthNProvider()
        expected_token: AuthNToken = AuthNToken(token="mocked-token")
        provider.get_token_mock.return_value = expected_token

        result: AuthNToken = await provider.get_token()

        assert result == expected_token
        provider.get_token_mock.assert_called_once()

    async def test_mock_provider_get_headers(self) -> None:
        """Test mocking get_headers method."""
        provider: MockAuthNProvider = MockAuthNProvider()
        expected_headers: AuthNHeaders = AuthNHeaders(
            **{"Authorization": "Bearer mocked-header"}
        )
        provider.get_headers_mock.return_value = expected_headers

        result: AuthNHeaders = await provider.get_headers()

        assert result == expected_headers
        provider.get_headers_mock.assert_called_once()

    async def test_mock_provider_exceptions(self) -> None:
        """Test mocking exceptions in provider methods."""
        provider: MockAuthNProvider = MockAuthNProvider()

        # Test get_token exception
        provider.get_token_mock.side_effect = Exception("Token fetch failed")

        with pytest.raises(Exception, match="Token fetch failed"):
            await provider.get_token()

        # Test get_headers exception
        provider.get_headers_mock.side_effect = ValueError("Invalid credentials")

        with pytest.raises(ValueError, match="Invalid credentials"):
            await provider.get_headers()

    async def test_mock_provider_call_counts(self) -> None:
        """Test that mock providers track call counts correctly."""
        provider: MockAuthNProvider = MockAuthNProvider()

        # Setup mocks
        provider.get_token_mock.return_value = AuthNToken(token="test")
        provider.get_headers_mock.return_value = AuthNHeaders(
            **{"Authorization": "test"}
        )

        # Call methods multiple times
        await provider.get_token()
        await provider.get_token()
        await provider.get_headers()

        # Verify call counts
        assert provider.get_token_mock.call_count == 2
        assert provider.get_headers_mock.call_count == 1
