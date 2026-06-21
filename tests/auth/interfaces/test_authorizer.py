import pytest
from abc import ABC
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

from pymidil.auth.interfaces.types import AuthZTokenClaims
from pymidil.auth.interfaces.authorizer import AuthZProvider
from typing import Dict, Any

pytestmark = pytest.mark.anyio


class ConcreteAuthZProvider(AuthZProvider):
    """Concrete implementation for testing."""

    def __init__(
        self,
        should_fail: bool = False,
        claims_data: Dict[str, Any] | None = None,
    ):
        self.should_fail = should_fail
        self.claims_data = claims_data or {
            "token": "test-token",
            "sub": "test-user",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }

    async def verify(self, token: str) -> AuthZTokenClaims:
        if self.should_fail:
            raise ValueError("Token verification failed")

        return AuthZTokenClaims(**self.claims_data)


class TestAuthZTokenClaims:
    """Tests for AuthZTokenClaims class."""

    def test_authz_token_claims_inheritance(self):
        """Test that AuthZTokenClaims inherits from ExpirableTokenMixin."""
        exp_timestamp = int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )
        claims = AuthZTokenClaims(token="test-token", sub="user-123", exp=exp_timestamp)

        # Should have all properties from ExpirableTokenMixin
        assert hasattr(claims, "token")
        assert hasattr(claims, "expired")
        assert hasattr(claims, "expires_at")

    def test_expires_at_implementation(self):
        """Test that expires_at is properly implemented."""
        exp_timestamp = 1640995200  # 2022-01-01 00:00:00 UTC
        claims = AuthZTokenClaims(token="test-token", sub="user-123", exp=exp_timestamp)

        expected_dt = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        assert claims.expires_at() == expected_dt

    def test_claims_with_current_timestamp(self):
        """Test claims with current timestamp."""
        now = datetime.now(timezone.utc)
        future_time = now + timedelta(minutes=30)
        exp_timestamp = int(future_time.timestamp())

        claims = AuthZTokenClaims(
            token="current-token", sub="current-user", exp=exp_timestamp
        )

        assert claims.sub == "current-user"
        assert claims.exp == exp_timestamp
        assert not claims.expired  # Should not be expired

        # Verify expires_at returns correct datetime
        expires_dt = claims.expires_at()
        assert abs((expires_dt - future_time).total_seconds()) < 1  # Within 1 second

    def test_claims_with_past_timestamp(self):
        """Test claims with past timestamp (expired token)."""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        exp_timestamp = int(past_time.timestamp())

        claims = AuthZTokenClaims(
            token="expired-token", sub="expired-user", exp=exp_timestamp
        )

        assert claims.expired  # Should be expired

    def test_claims_edge_case_zero_timestamp(self):
        """Test claims with zero timestamp (epoch)."""
        claims = AuthZTokenClaims(token="epoch-token", sub="epoch-user", exp=0)

        expected_dt = datetime.fromtimestamp(0, tz=timezone.utc)
        assert claims.expires_at() == expected_dt
        assert claims.expired  # Should definitely be expired


class TestAuthZProvider:
    """Tests for AuthZProvider abstract base class."""

    def test_is_abstract_base_class(self):
        """Test that AuthZProvider is an abstract base class."""
        assert issubclass(AuthZProvider, ABC)

    def test_cannot_instantiate_directly(self):
        """Test that AuthZProvider cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            AuthZProvider()  # type: ignore

    def test_abstract_methods_required(self):
        """Test that concrete implementations must implement abstract methods."""

        class IncompleteProvider(AuthZProvider):
            # Missing verify implementation
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteProvider()  # type: ignore

    async def test_concrete_implementation_verify_success(self):
        """Test successful token verification."""
        provider = ConcreteAuthZProvider()

        claims = await provider.verify("valid-token")

        assert isinstance(claims, AuthZTokenClaims)
        assert claims.sub == "test-user"
        assert claims.token == "test-token"

    async def test_concrete_implementation_verify_failure(self):
        """Test failed token verification."""
        provider = ConcreteAuthZProvider(should_fail=True)

        with pytest.raises(ValueError, match="Token verification failed"):
            await provider.verify("invalid-token")

    async def test_provider_with_custom_claims(self):
        """Test provider with custom claims data."""
        custom_claims = {
            "token": "custom-token",
            "sub": "custom-user-123",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=2)).timestamp()),
        }
        provider = ConcreteAuthZProvider(claims_data=custom_claims)

        claims = await provider.verify("some-token")

        assert claims.sub == "custom-user-123"
        assert claims.token == "custom-token"
        assert not claims.expired

    def test_provider_docstring_content(self):
        """Test that the docstring accurately describes the class purpose."""
        provider = ConcreteAuthZProvider()

        # Should have verify method as described in docstring
        assert hasattr(provider, "verify")

        # Method should be async as mentioned in docstring
        import asyncio

        assert asyncio.iscoroutinefunction(provider.verify)


class MockAuthZProvider(AuthZProvider):
    """Mock provider for testing scenarios."""

    def __init__(self):
        self.verify_mock = AsyncMock()

    async def verify(self, token: str) -> AuthZTokenClaims:
        return await self.verify_mock(token)


class TestAuthZProviderMocking:
    """Tests for mocking AuthZProvider implementations."""

    async def test_mock_provider_verify_success(self):
        """Test mocking successful verification."""
        provider = MockAuthZProvider()
        expected_claims = AuthZTokenClaims(
            token="mocked-token",
            sub="mocked-user",
            exp=int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        )
        provider.verify_mock.return_value = expected_claims

        result = await provider.verify("test-token")

        assert result == expected_claims
        provider.verify_mock.assert_called_once_with("test-token")

    async def test_mock_provider_verify_with_different_tokens(self):
        """Test mock provider with different input tokens."""
        provider = MockAuthZProvider()

        # Setup different return values for different tokens
        def side_effect(token):
            if token == "valid-token":
                return AuthZTokenClaims(
                    token=token,
                    sub="valid-user",
                    exp=int(
                        (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
                    ),
                )
            else:
                raise ValueError("Invalid token")

        provider.verify_mock.side_effect = side_effect

        # Test valid token
        claims = await provider.verify("valid-token")
        assert claims.sub == "valid-user"

        # Test invalid token
        with pytest.raises(ValueError, match="Invalid token"):
            await provider.verify("invalid-token")

    async def test_mock_provider_call_tracking(self):
        """Test that mock provider tracks calls correctly."""
        provider = MockAuthZProvider()
        mock_claims = AuthZTokenClaims(
            token="test",
            sub="test",
            exp=int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        )
        provider.verify_mock.return_value = mock_claims

        # Make multiple calls
        await provider.verify("token1")
        await provider.verify("token2")
        await provider.verify("token3")

        # Verify call count and arguments
        assert provider.verify_mock.call_count == 3
        provider.verify_mock.assert_any_call("token1")
        provider.verify_mock.assert_any_call("token2")
        provider.verify_mock.assert_any_call("token3")

    async def test_mock_provider_exception_handling(self):
        """Test mock provider exception scenarios."""
        provider = MockAuthZProvider()

        # Test different exception types
        test_cases = [
            (ValueError("Invalid token format"), ValueError),
            (RuntimeError("Service unavailable"), RuntimeError),
            (Exception("Generic error"), Exception),
        ]

        for exception, expected_type in test_cases:
            provider.verify_mock.side_effect = exception

            with pytest.raises(expected_type):
                await provider.verify("test-token")
