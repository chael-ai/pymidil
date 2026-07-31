"""
Tests for midil.auth.interfaces.authenticator
"""

import pytest
from abc import ABC
from unittest.mock import AsyncMock
from pymidil.auth.interfaces.authenticator import AuthNProvider
from pymidil.auth.interfaces.types import AuthNToken

# Mark all async tests in this module to use anyio
pytestmark = pytest.mark.anyio


class ConcreteAuthNProvider(AuthNProvider):
    """Concrete implementation for testing."""

    def __init__(self, token_value: str = "test-token") -> None:
        self.token_value: str = token_value

    async def get_token(self) -> AuthNToken:
        return AuthNToken(token=self.token_value)


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
        """Test that concrete implementations must implement get_token."""

        class IncompleteProvider(AuthNProvider):
            pass  # Missing get_token implementation

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

    async def test_default_invalidate_not_implemented(self) -> None:
        """Test that the default invalidate() raises NotImplementedError."""
        provider: ConcreteAuthNProvider = ConcreteAuthNProvider()

        with pytest.raises(NotImplementedError):
            await provider.invalidate()

    def test_provider_docstring_examples(self) -> None:
        """Test that the docstring examples are accurate."""
        provider: ConcreteAuthNProvider = ConcreteAuthNProvider()

        assert hasattr(provider, "get_token")

        import asyncio

        assert asyncio.iscoroutinefunction(provider.get_token)


class MockAuthNProvider(AuthNProvider):
    """Mock provider for additional testing scenarios."""

    def __init__(self) -> None:
        self.get_token_mock: AsyncMock = AsyncMock()

    async def get_token(self) -> AuthNToken:
        return await self.get_token_mock()


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

    async def test_mock_provider_exceptions(self) -> None:
        """Test mocking exceptions in provider methods."""
        provider: MockAuthNProvider = MockAuthNProvider()

        provider.get_token_mock.side_effect = Exception("Token fetch failed")

        with pytest.raises(Exception, match="Token fetch failed"):
            await provider.get_token()

    async def test_mock_provider_call_counts(self) -> None:
        """Test that mock providers track call counts correctly."""
        provider: MockAuthNProvider = MockAuthNProvider()

        provider.get_token_mock.return_value = AuthNToken(token="test")

        await provider.get_token()
        await provider.get_token()

        assert provider.get_token_mock.call_count == 2
