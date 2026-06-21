import pytest
from datetime import datetime, timezone, timedelta
from dateutil import parser

from pymidil.auth.interfaces.types import (
    ExpirableTokenMixin,
    AuthNToken,
    AuthNHeaders,
    AuthZTokenClaims,
)


class TestExpirableTokenMixin:
    """Tests for ExpirableTokenMixin."""

    def test_expires_at_not_implemented(self):
        """Test that expires_at raises NotImplementedError in base class."""
        token = ExpirableTokenMixin(token="test-token")

        with pytest.raises(
            NotImplementedError, match="Subclasses must implement expires_at"
        ):
            token.expires_at()

    def test_expired_property_with_none_expiry(self):
        """Test expired property when expires_at returns None."""

        class TestToken(ExpirableTokenMixin):
            def expires_at(self):
                return None

        token = TestToken(token="test-token")
        assert not token.expired

    def test_expired_property_with_future_expiry(self):
        """Test expired property when token expires in the future."""

        class TestToken(ExpirableTokenMixin):
            def expires_at(self):
                return datetime.now(timezone.utc) + timedelta(hours=1)

        token = TestToken(token="test-token")
        assert not token.expired

    def test_expired_property_with_past_expiry(self):
        """Test expired property when token has expired."""

        class TestToken(ExpirableTokenMixin):
            def expires_at(self):
                return datetime.now(timezone.utc) - timedelta(hours=1)

        token = TestToken(token="test-token")
        assert token.expired

    def test_expired_property_with_buffer(self):
        """Test expired property considers the time buffer."""

        class TestToken(ExpirableTokenMixin):
            def expires_at(self):
                # Token expires in 3 minutes, but buffer is 5 minutes
                return datetime.now(timezone.utc) + timedelta(minutes=3)

        token = TestToken(token="test-token")
        assert token.expired  # Should be considered expired due to buffer


class TestAuthNToken:
    """Tests for AuthNToken."""

    def test_authn_token_init_with_expiry(self):
        """Test AuthNToken initialization with expiry date."""
        expiry_str = "2023-12-31T23:59:59Z"
        token = AuthNToken(token="test-token", expires_at_iso=expiry_str)

        assert token.token == "test-token"
        assert token.expires_at_iso == expiry_str

    def test_authn_token_init_without_expiry(self):
        """Test AuthNToken initialization without expiry date."""
        token = AuthNToken(token="test-token")

        assert token.token == "test-token"
        assert token.expires_at_iso is None

    def test_expires_at_with_valid_iso_string(self):
        """Test expires_at method with valid ISO string."""
        expiry_str = "2023-12-31T23:59:59Z"
        token = AuthNToken(token="test-token", expires_at_iso=expiry_str)

        expected_dt = parser.parse(expiry_str)
        assert token.expires_at() == expected_dt

    def test_expires_at_with_none(self):
        """Test expires_at method when expires_at_iso is None."""
        token = AuthNToken(token="test-token")

        assert token.expires_at() is None

    def test_expires_at_with_various_iso_formats(self):
        """Test expires_at method with various ISO date formats."""
        test_cases = [
            "2023-12-31T23:59:59Z",
            "2023-12-31T23:59:59+00:00",
            "2023-12-31T23:59:59.123Z",
            "2023-12-31 23:59:59",
        ]

        for iso_string in test_cases:
            token = AuthNToken(token="test-token", expires_at_iso=iso_string)
            # Should not raise an exception
            result = token.expires_at()
            assert isinstance(result, datetime)


class TestAuthNHeaders:
    """Tests for AuthNHeaders."""

    def test_authn_headers_init_minimal(self):
        """Test AuthNHeaders initialization with minimal data."""
        headers = AuthNHeaders(**{"Authorization": "Bearer token"})

        assert headers.authorization == "Bearer token"
        assert headers.accept == "application/json"  # default
        assert headers.content_type == "application/json"  # default

    def test_authn_headers_init_full(self):
        """Test AuthNHeaders initialization with all fields."""
        headers = AuthNHeaders(
            **{
                "Authorization": "Bearer token",
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json",
            }
        )

        assert headers.authorization == "Bearer token"
        assert headers.accept == "application/vnd.api+json"
        assert headers.content_type == "application/vnd.api+json"

    def test_authn_headers_with_aliases(self):
        """Test AuthNHeaders field aliases work correctly."""
        headers = AuthNHeaders(
            **{
                "Authorization": "Bearer token",
                "Accept": "text/plain",
                "Content-Type": "text/plain",
            }
        )

        assert headers.authorization == "Bearer token"
        assert headers.accept == "text/plain"
        assert headers.content_type == "text/plain"

    def test_authn_headers_model_dump_with_aliases(self):
        """Test model_dump uses aliases correctly."""
        headers = AuthNHeaders(
            **{
                "Authorization": "Bearer token",
                "Accept": "application/xml",
                "Content-Type": "application/xml",
            }
        )

        dumped = headers.model_dump(by_alias=True)

        assert "Authorization" in dumped
        assert "Accept" in dumped
        assert "Content-Type" in dumped
        assert dumped["Authorization"] == "Bearer token"

    def test_authn_headers_extra_fields_allowed(self):
        """Test that extra fields are allowed in AuthNHeaders."""
        headers = AuthNHeaders(
            **{
                "Authorization": "Bearer token",
                "custom_header": "custom_value",
            }
        )

        # Should not raise an error due to extra="allow"
        assert headers.authorization == "Bearer token"


class TestAuthZTokenClaims:
    """Tests for AuthZTokenClaims."""

    def test_authz_token_claims_init(self):
        """Test AuthZTokenClaims initialization."""
        exp_timestamp = int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )
        claims = AuthZTokenClaims(token="test-token", sub="user-123", exp=exp_timestamp)

        assert claims.token == "test-token"
        assert claims.sub == "user-123"
        assert claims.exp == exp_timestamp

    def test_expires_at_method(self):
        """Test expires_at method converts epoch to datetime correctly."""
        exp_timestamp = 1640995200  # 2022-01-01 00:00:00 UTC
        claims = AuthZTokenClaims(token="test-token", sub="user-123", exp=exp_timestamp)

        expected_dt = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        assert claims.expires_at() == expected_dt

    def test_expired_property(self):
        """Test expired property works correctly with AuthZTokenClaims."""
        # Create a token that expires in the past
        past_timestamp = int(
            (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
        )
        claims = AuthZTokenClaims(
            token="test-token", sub="user-123", exp=past_timestamp
        )

        assert claims.expired

    def test_not_expired_property(self):
        """Test token that is not expired."""
        # Create a token that expires in the future (beyond buffer)
        future_timestamp = int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )
        claims = AuthZTokenClaims(
            token="test-token", sub="user-123", exp=future_timestamp
        )

        assert not claims.expired
