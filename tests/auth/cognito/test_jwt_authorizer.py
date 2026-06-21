import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple
from unittest.mock import AsyncMock, Mock, patch

import jwt
import pytest

from pymidil.auth.cognito.exceptions import CognitoAuthorizationError
from pymidil.auth.cognito.jwt_authorizer import (
    CognitoJWTAuthorizer,
    CognitoTokenClaims,
)
from pymidil.auth.interfaces.types import AuthZTokenClaims

# Mark all async tests in this module to use anyio
pytestmark = pytest.mark.anyio


class TestCognitoTokenClaims:
    """Tests for CognitoTokenClaims model."""

    def test_cognito_token_claims_inheritance(self) -> None:
        """Test that CognitoTokenClaims inherits from AuthZTokenClaims."""
        assert issubclass(CognitoTokenClaims, AuthZTokenClaims)

    def test_cognito_token_claims_init_minimal(self) -> None:
        """Test CognitoTokenClaims with minimal required fields."""
        exp_timestamp: int = int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )
        claims: CognitoTokenClaims = CognitoTokenClaims(
            token="test-token", sub="user-123", exp=exp_timestamp
        )

        assert claims.token == "test-token"
        assert claims.sub == "user-123"
        assert claims.exp == exp_timestamp
        assert claims.email is None
        assert claims.name is None

    def test_cognito_token_claims_init_full(self) -> None:
        """Test CognitoTokenClaims with all fields."""
        exp_timestamp: int = int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )
        iat_timestamp: int = int(
            (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
        )

        claims: CognitoTokenClaims = CognitoTokenClaims(
            token="test-token",
            sub="user-123",
            exp=exp_timestamp,
            email="test@example.com",
            name="Test User",
            iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test",
            aud="test-client-id",
            iat=iat_timestamp,
        )

        assert claims.email == "test@example.com"
        assert claims.name == "Test User"
        assert (
            claims.iss == "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test"
        )
        assert claims.aud == "test-client-id"
        assert claims.iat == iat_timestamp

    def test_cognito_token_claims_field_aliases(self) -> None:
        """Test that field aliases work correctly."""
        exp_timestamp: int = int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )

        # Test with alias names
        claims_data: Dict[str, Any] = {
            "token": "test-token",
            "sub": "user-123",
            "exp": exp_timestamp,
            "email": "alias@example.com",
            "name": "Alias User",
            "iss": "https://cognito-test.com",
            "aud": "test-audience",
            "iat": exp_timestamp - 300,
        }

        claims: CognitoTokenClaims = CognitoTokenClaims(**claims_data)
        assert claims.email == "alias@example.com"
        assert claims.name == "Alias User"

    def test_cognito_token_claims_email_validation(self) -> None:
        """Test email validation in CognitoTokenClaims."""
        exp_timestamp: int = int(
            (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        )

        # Valid email
        claims: CognitoTokenClaims = CognitoTokenClaims(
            token="test-token",
            sub="user-123",
            exp=exp_timestamp,
            email="valid@example.com",
        )
        assert claims.email == "valid@example.com"

        # Invalid email should raise validation error
        with pytest.raises(ValueError):
            CognitoTokenClaims(
                token="test-token",
                sub="user-123",
                exp=exp_timestamp,
                email="invalid-email",
            )


@pytest.fixture
def valid_token_payload() -> Dict[str, Any]:
    """Valid token payload for testing."""
    now: datetime = datetime.now(tz=timezone.utc)
    return {
        "sub": "user123",
        "email": "user@example.com",
        "name": "Test User",
        "iss": "https://cognito-idp.us-west-2.amazonaws.com/test-pool",
        "aud": "test-client-id",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }


@pytest.fixture
def mock_cognito_claims() -> Dict[str, Any]:
    """Mock Cognito claims data for testing."""
    now: datetime = datetime.now(tz=timezone.utc)
    return {
        "sub": "user123",
        "email": "user@example.com",
        "name": "Test User",
        "iss": "https://cognito-idp.us-west-2.amazonaws.com/test-pool",
        "aud": "test-client-id",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }


class TestCognitoJWTAuthorizer:
    """Tests for CognitoJWTAuthorizer."""

    @pytest.fixture
    def authorizer(self) -> CognitoJWTAuthorizer:
        """Create a CognitoJWTAuthorizer instance for testing."""
        return CognitoJWTAuthorizer(
            user_pool_id="us-east-1_TestPool",
            region="us-east-1",
            audience="test-client-id",
        )

    @pytest.fixture
    def authorizer_no_audience(self) -> CognitoJWTAuthorizer:
        """Create a CognitoJWTAuthorizer instance without audience for testing."""
        return CognitoJWTAuthorizer(
            user_pool_id="us-east-1_TestPool", region="us-east-1"
        )

    @pytest.fixture
    def mock_jwk_client(self) -> Tuple[Mock, Mock]:
        """Create a mock PyJWKClient."""
        client: Mock = Mock()
        signing_key: Mock = Mock()
        signing_key.key = "mock-key"
        client.get_signing_key_from_jwt.return_value = signing_key
        return client, signing_key

    def test_authorizer_init(self, authorizer: CognitoJWTAuthorizer) -> None:
        """Test CognitoJWTAuthorizer initialization."""
        assert authorizer.user_pool_id == "us-east-1_TestPool"
        assert authorizer.region == "us-east-1"
        assert authorizer.audience == "test-client-id"
        assert (
            authorizer.jwks_url
            == "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool/.well-known/jwks.json"
        )

    def test_authorizer_init_without_audience(
        self, authorizer_no_audience: CognitoJWTAuthorizer
    ) -> None:
        """Test CognitoJWTAuthorizer initialization without audience."""
        assert authorizer_no_audience.audience is None

    @patch("pymidil.auth.cognito.jwt_authorizer.PyJWKClient")
    def test_jwk_client_initialization(self, mock_jwk_client_class: Mock) -> None:
        """Test that PyJWKClient is initialized correctly."""
        # Create authorizer after mock is applied
        authorizer: CognitoJWTAuthorizer = CognitoJWTAuthorizer(
            user_pool_id="us-east-1_TestPool",
            region="us-east-1",
            audience="test-client-id",
        )

        mock_jwk_client_class.assert_called_once_with(
            authorizer.jwks_url,
            cache_keys=True,
            lifespan=900,  # 15 minutes
            max_cached_keys=32,
        )

    @patch("pymidil.auth.cognito.jwt_authorizer.asyncio.to_thread")
    async def test_get_signing_key_success(
        self,
        mock_to_thread: Mock,
        authorizer: CognitoJWTAuthorizer,
        mock_jwk_client: Tuple[Mock, Mock],
    ) -> None:
        """Test successful signing key retrieval."""
        client, signing_key = mock_jwk_client
        authorizer._jwk_client = client
        mock_to_thread.return_value = signing_key

        result = await authorizer._get_signing_key("test-token")

        assert result == signing_key
        mock_to_thread.assert_called_once_with(
            client.get_signing_key_from_jwt, "test-token"
        )

    @patch("pymidil.auth.cognito.jwt_authorizer.asyncio.to_thread")
    @patch("pymidil.auth.cognito.jwt_authorizer.PyJWKClient")
    async def test_get_signing_key_with_retry(
        self, mock_jwk_client_class: Mock, mock_to_thread: Mock
    ) -> None:
        """Test signing key retrieval with retry logic."""
        signing_key: Mock = Mock()
        signing_key.key = "retry-key"
        mock_to_thread.side_effect = [
            jwt.exceptions.PyJWKClientError("Key not found"),
            signing_key,
        ]

        # Create a new authorizer after mocking
        authorizer: CognitoJWTAuthorizer = CognitoJWTAuthorizer(
            user_pool_id="us-east-1_TestPool",
            region="us-east-1",
            audience="test-client-id",
        )

        result = await authorizer._get_signing_key("test-token")

        assert result == signing_key
        assert mock_to_thread.call_count == 2
        assert mock_jwk_client_class.call_count == 2  # initial + retry

    @patch("pymidil.auth.cognito.jwt_authorizer.asyncio.to_thread")
    async def test_get_signing_key_retry_failure(
        self, mock_to_thread: Mock, authorizer: CognitoJWTAuthorizer
    ) -> None:
        """Test signing key retrieval failure even after retry."""
        mock_to_thread.side_effect = [
            jwt.exceptions.PyJWKClientError("Key not found"),
            Exception("Still failing"),
        ]

        with pytest.raises(
            CognitoAuthorizationError, match="Failed to fetch signing key after retry"
        ):
            await authorizer._get_signing_key("test-token")

    @patch("pymidil.auth.cognito.jwt_authorizer.jwt.decode")
    @patch.object(CognitoJWTAuthorizer, "_get_signing_key")
    async def test_verify_success(
        self,
        mock_get_signing_key: Mock,
        mock_jwt_decode: Mock,
        authorizer: CognitoJWTAuthorizer,
        mock_cognito_claims: Dict[str, Any],
    ) -> None:
        """Test successful token verification."""
        # Setup mocks
        signing_key: Mock = Mock()
        signing_key.key = "test-key"
        mock_get_signing_key.return_value = signing_key
        mock_jwt_decode.return_value = mock_cognito_claims

        result = await authorizer.verify("valid-token")

        assert isinstance(result, CognitoTokenClaims)
        assert result.sub == mock_cognito_claims["sub"]
        assert result.email == mock_cognito_claims["email"]

        mock_jwt_decode.assert_called_once_with(
            "valid-token",
            "test-key",
            algorithms=["RS256"],
            audience="test-client-id",
            options={
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_signature": True,
                "require": ["exp", "iat", "sub", "iss", "aud"],
            },
        )

    @patch("pymidil.auth.cognito.jwt_authorizer.jwt.decode")
    @patch.object(CognitoJWTAuthorizer, "_get_signing_key")
    async def test_verify_without_audience(
        self,
        mock_get_signing_key: Mock,
        mock_jwt_decode: Mock,
        authorizer_no_audience: CognitoJWTAuthorizer,
        mock_cognito_claims: Dict[str, Any],
    ) -> None:
        """Test token verification without audience validation."""
        # Setup mocks
        signing_key: Mock = Mock()
        signing_key.key = "test-key"
        mock_get_signing_key.return_value = signing_key
        mock_jwt_decode.return_value = mock_cognito_claims

        result = await authorizer_no_audience.verify("valid-token")

        assert isinstance(result, CognitoTokenClaims)

        # Verify jwt.decode was called with audience=None and verify_aud=False
        mock_jwt_decode.assert_called_once_with(
            "valid-token",
            "test-key",
            algorithms=["RS256"],
            audience=None,
            options={
                "verify_exp": True,
                "verify_aud": False,
                "verify_iss": True,
                "verify_signature": True,
                "require": ["exp", "iat", "sub", "iss", "aud"],
            },
        )

    @patch.object(CognitoJWTAuthorizer, "_get_signing_key")
    async def test_verify_invalid_token_error(
        self, mock_get_signing_key: Mock, authorizer: CognitoJWTAuthorizer
    ) -> None:
        """Test verification with invalid token."""
        signing_key: Mock = Mock()
        signing_key.key = "test-key"
        mock_get_signing_key.return_value = signing_key

        with patch("pymidil.auth.cognito.jwt_authorizer.jwt.decode") as mock_decode:
            mock_decode.side_effect = jwt.InvalidTokenError("Token is invalid")

            with pytest.raises(
                CognitoAuthorizationError,
                match="JWT verification failed: Token is invalid",
            ):
                await authorizer.verify("invalid-token")

    @patch.object(CognitoJWTAuthorizer, "_get_signing_key")
    async def test_verify_decode_error(
        self, mock_get_signing_key: Mock, authorizer: CognitoJWTAuthorizer
    ) -> None:
        """Test verification with decode error."""
        signing_key: Mock = Mock()
        signing_key.key = "test-key"
        mock_get_signing_key.return_value = signing_key

        with patch("pymidil.auth.cognito.jwt_authorizer.jwt.decode") as mock_decode:
            mock_decode.side_effect = jwt.DecodeError("Cannot decode token")

            with pytest.raises(
                CognitoAuthorizationError,
                match="JWT verification failed: Cannot decode token",
            ):
                await authorizer.verify("malformed-token")

    @patch.object(CognitoJWTAuthorizer, "_get_signing_key")
    async def test_verify_authorization_error_passthrough(
        self, mock_get_signing_key: Mock, authorizer: CognitoJWTAuthorizer
    ) -> None:
        """Test that AuthorizationError is passed through."""
        mock_get_signing_key.side_effect = CognitoAuthorizationError(
            "Custom auth error"
        )

        with pytest.raises(CognitoAuthorizationError, match="Custom auth error"):
            await authorizer.verify("test-token")

    @patch.object(CognitoJWTAuthorizer, "_get_signing_key")
    async def test_verify_unexpected_error(
        self, mock_get_signing_key: Mock, authorizer: CognitoJWTAuthorizer
    ) -> None:
        """Test verification with unexpected error."""
        mock_get_signing_key.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(RuntimeError, match="Unexpected error"):
            await authorizer.verify("test-token")

    @patch("pymidil.auth.cognito.jwt_authorizer.jwt.decode")
    @patch.object(CognitoJWTAuthorizer, "_get_signing_key")
    async def test_verify_creates_cognito_claims(
        self,
        mock_get_signing_key: Mock,
        mock_jwt_decode: Mock,
        authorizer: CognitoJWTAuthorizer,
        mock_cognito_claims: Dict[str, Any],
    ) -> None:
        """Test that verify returns CognitoTokenClaims, not generic AuthZTokenClaims."""
        signing_key: Mock = Mock()
        signing_key.key = "test-key"
        mock_get_signing_key.return_value = signing_key
        mock_jwt_decode.return_value = mock_cognito_claims

        result = await authorizer.verify("valid-token")

        assert isinstance(result, CognitoTokenClaims)
        assert isinstance(
            result, AuthZTokenClaims
        )  # Should also be instance of parent class
        assert hasattr(result, "email")  # Cognito-specific field
        assert hasattr(result, "name")  # Cognito-specific field

    def test_constants(self) -> None:
        """Test class constants are set correctly."""
        assert CognitoJWTAuthorizer._REFRESH_INTERVAL == 900  # 15 minutes
        assert CognitoJWTAuthorizer._MAX_CACHE_SIZE == 32

    async def test_concurrent_access_with_lock(
        self, authorizer: CognitoJWTAuthorizer
    ) -> None:
        """Test that concurrent access to _get_signing_key uses locking correctly."""
        # This test verifies the lock exists and is properly set up
        assert hasattr(authorizer, "_jwk_client_lock")
        import asyncio

        assert isinstance(authorizer._jwk_client_lock, asyncio.Lock)


@pytest.mark.asyncio
@patch("pymidil.auth.cognito.jwt_authorizer.jwt.decode")
@patch("pymidil.auth.cognito.jwt_authorizer.CognitoJWTAuthorizer._get_signing_key")
async def test_verify_valid_token(
    mock_get_key: Mock, mock_decode: Mock, valid_token_payload: Dict[str, Any]
) -> None:
    token: str = "valid.token.here"
    mock_get_key.return_value.key = "public_key"
    mock_decode.return_value = valid_token_payload

    authorizer: CognitoJWTAuthorizer = CognitoJWTAuthorizer(
        "test-pool", "us-west-2", audience="test-client-id"
    )
    claims: AuthZTokenClaims = await authorizer.verify(token)

    assert isinstance(claims, CognitoTokenClaims)
    assert claims.email == "user@example.com"
    assert claims.iss == valid_token_payload["iss"]
    assert claims.aud == valid_token_payload["aud"]


@pytest.mark.asyncio
@patch("pymidil.auth.cognito.jwt_authorizer.jwt.decode")
@patch("pymidil.auth.cognito.jwt_authorizer.CognitoJWTAuthorizer._get_signing_key")
async def test_token_expired(
    mock_get_key: Mock, mock_decode: Mock, valid_token_payload: Dict[str, Any]
) -> None:
    expired_payload: Dict[str, Any] = valid_token_payload.copy()
    expired_payload["exp"] = int(
        (datetime.now(tz=timezone.utc) - timedelta(seconds=1)).timestamp()
    )
    mock_get_key.return_value.key = "public_key"
    mock_decode.side_effect = jwt.ExpiredSignatureError("Token has expired")

    authorizer: CognitoJWTAuthorizer = CognitoJWTAuthorizer(
        "test-pool", "us-west-2", audience="test-client-id"
    )
    with pytest.raises(CognitoAuthorizationError) as exc_info:
        await authorizer.verify("expired.token")

    assert "expired" in str(exc_info.value).lower()


@pytest.mark.asyncio
@patch("pymidil.auth.cognito.jwt_authorizer.jwt.decode")
@patch("pymidil.auth.cognito.jwt_authorizer.CognitoJWTAuthorizer._get_signing_key")
async def test_issuer_mismatch(
    mock_get_key: Mock, mock_decode: Mock, valid_token_payload: Dict[str, Any]
) -> None:
    invalid_payload: Dict[str, Any] = valid_token_payload.copy()
    invalid_payload["iss"] = "https://invalid-issuer.com"
    mock_get_key.return_value.key = "public_key"
    mock_decode.side_effect = jwt.InvalidIssuerError("Invalid issuer")

    authorizer: CognitoJWTAuthorizer = CognitoJWTAuthorizer(
        "test-pool", "us-west-2", audience="test-client-id"
    )
    with pytest.raises(CognitoAuthorizationError) as exc_info:
        await authorizer.verify("bad.token")

    assert "issuer" in str(exc_info.value).lower()


@pytest.mark.asyncio
@patch("pymidil.auth.cognito.jwt_authorizer.jwt.decode")
@patch("pymidil.auth.cognito.jwt_authorizer.CognitoJWTAuthorizer._get_signing_key")
async def test_audience_mismatch(
    mock_get_key: Mock, mock_decode: Mock, valid_token_payload: Dict[str, Any]
) -> None:
    mock_get_key.return_value.key = "public_key"
    mock_decode.side_effect = jwt.InvalidAudienceError("Invalid audience")

    authorizer: CognitoJWTAuthorizer = CognitoJWTAuthorizer(
        "test-pool", "us-west-2", audience="expected-client-id"
    )
    with pytest.raises(CognitoAuthorizationError) as exc_info:
        await authorizer.verify("token.with.wrong.aud")

    assert "audience" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_concurrent_signing_key_fetch() -> None:
    from pymidil.auth.cognito.jwt_authorizer import CognitoJWTAuthorizer

    authorizer: CognitoJWTAuthorizer = CognitoJWTAuthorizer(
        "test-pool", "us-west-2", audience="test-client-id"
    )

    with patch.object(
        authorizer, "_get_signing_key", new_callable=AsyncMock
    ) as mock_get_key, patch(
        "pymidil.auth.cognito.jwt_authorizer.jwt.decode"
    ) as mock_decode:
        now: datetime = datetime.now(tz=timezone.utc)
        token_payload: Dict[str, Any] = {
            "sub": "abc",
            "email": "test@c.com",
            "name": "test",
            "iss": "https://cognito-idp.us-west-2.amazonaws.com/test-pool",
            "aud": "test-client-id",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        }
        mock_get_key.return_value.key = "mock-public-key"
        mock_decode.return_value = token_payload

        token: str = "simultaneous.jwt.token"
        results = await asyncio.gather(*[authorizer.verify(token) for _ in range(10)])

        assert all(isinstance(r, CognitoTokenClaims) for r in results)
        assert mock_get_key.call_count == 10  # Ensures it handles concurrent requests
