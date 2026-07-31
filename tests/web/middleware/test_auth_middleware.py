import pytest
from unittest.mock import AsyncMock, Mock, patch
from starlette.requests import Request
from starlette.responses import Response
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from typing import Callable, Awaitable

from pymidil.web.middleware.auth import (
    AuthContext,
    JWKAuthMiddleware,
)
from pymidil.auth.interfaces.types import AuthZTokenClaims
from pymidil.auth.interfaces.authorizer import AuthZProvider


class TestAuthContext:
    """Tests for AuthContext class."""

    def test_auth_context_init(self, mock_jwt_claims) -> None:
        """Test AuthContext initialization."""
        claims: AuthZTokenClaims = AuthZTokenClaims(
            token="Bearer test-token", **mock_jwt_claims
        )
        raw_headers = {
            "authorization": "Bearer token",
            "content-type": "application/json",
        }

        context = AuthContext(claims=claims, _raw_headers=raw_headers)

        assert context.claims == claims
        assert context._raw_headers == raw_headers

    def test_auth_context_to_dict(self, mock_jwt_claims) -> None:
        """Test AuthContext to_dict method."""
        claims = AuthZTokenClaims(token="Bearer test-token", **mock_jwt_claims)
        raw_headers = {"authorization": "Bearer token"}

        context = AuthContext(claims=claims, _raw_headers=raw_headers)
        result = context.to_dict()

        assert "claims" in result
        assert "raw_headers" in result
        assert result["raw_headers"] == raw_headers
        assert isinstance(result["claims"], dict)


class TestJWKAuthMiddleware:
    """Tests for JWKAuthMiddleware class."""

    @pytest.fixture
    def mock_request(self) -> Request:
        """Create a mock request."""
        request = Mock(spec=Request)
        request.headers = {"authorization": "Bearer test-token"}
        request.state = Mock()
        return request

    @pytest.fixture
    def mock_call_next(self) -> Callable[[Request], Awaitable[Response]]:
        """Create a mock call_next function."""

        async def call_next(request: Request) -> Response:
            return Response("OK")

        return call_next

    @pytest.fixture
    def auth_middleware(self) -> JWKAuthMiddleware:
        """Create JWKAuthMiddleware instance."""
        app = Starlette()
        return JWKAuthMiddleware(app)

    @pytest.fixture
    def mock_authorizer(self, mock_jwt_claims) -> AuthZProvider:
        """Create a mock authorizer."""
        authorizer = AsyncMock()
        claims = AuthZTokenClaims(token="Bearer test-token", **mock_jwt_claims)
        authorizer.verify.return_value = claims
        return authorizer

    @pytest.mark.anyio
    @patch.dict(
        "os.environ",
        {
            "MIDIL__AUTH": '{"type": "jwk", "issuer": "https://idp.example.com/test", "jwks_url": "https://idp.example.com/test/.well-known/jwks.json"}',
        },
    )
    @patch("pymidil.web.middleware.auth.JWKAuthorizer")
    async def test_dispatch_success(
        self,
        mock_authorizer_class,
        auth_middleware,
        mock_request,
        mock_call_next,
        mock_authorizer,
        mock_jwt_claims,
    ) -> None:
        """Test successful authentication in middleware dispatch."""
        # Setup mocks
        mock_authorizer_class.return_value = mock_authorizer
        claims = AuthZTokenClaims(token="Bearer test-token", **mock_jwt_claims)
        mock_authorizer.verify.return_value = claims

        # Execute
        response = await auth_middleware.dispatch(mock_request, mock_call_next)

        # Verify
        assert response.status_code == 200
        mock_authorizer.verify.assert_called_once_with("test-token")

        # Check that auth context was set on request state
        assert hasattr(mock_request.state, "auth")
        auth_context = mock_request.state.auth
        assert isinstance(auth_context, AuthContext)
        assert auth_context.claims == claims
        assert auth_context._raw_headers == dict(mock_request.headers)

    @patch.dict(
        "os.environ",
        {
            "MIDIL__AUTH": '{"type": "jwk", "issuer": "https://idp.example.com/test", "jwks_url": "https://idp.example.com/test/.well-known/jwks.json"}',
        },
    )
    @pytest.mark.anyio
    @patch("pymidil.web.middleware.auth.JWKAuthorizer")
    async def test_dispatch_authorization_error(
        self, mock_authorizer_class, auth_middleware, mock_request, mock_call_next
    ) -> None:
        """Test middleware behavior when authorization fails."""
        # Setup mock to raise exception
        mock_authorizer = AsyncMock()
        mock_authorizer.verify.side_effect = Exception("Invalid token")
        mock_authorizer_class.return_value = mock_authorizer

        # Execute and verify exception is raised
        with pytest.raises(Exception, match="Invalid token"):
            await auth_middleware.dispatch(mock_request, mock_call_next)

        mock_authorizer.verify.assert_called_once_with("test-token")

    @pytest.mark.anyio
    @patch.dict(
        "os.environ",
        {
            "MIDIL__AUTH": '{"type": "jwk", "issuer": "https://idp.example.com/test", "jwks_url": "https://idp.example.com/test/.well-known/jwks.json"}',
        },
    )
    @patch("pymidil.web.middleware.auth.JWKAuthorizer")
    async def test_dispatch_empty_environment(
        self,
        mock_authorizer_class,
        auth_middleware,
        mock_request,
        mock_call_next,
        mock_authorizer,
        mock_jwt_claims,
    ) -> None:
        """Test middleware with empty environment variables."""
        # Setup mocks
        mock_authorizer_class.return_value = mock_authorizer
        claims = AuthZTokenClaims(token="Bearer test-token", **mock_jwt_claims)
        mock_authorizer.verify.return_value = claims

        # Execute
        response = await auth_middleware.dispatch(mock_request, mock_call_next)

        # Verify
        assert response.status_code == 200
        mock_authorizer_class.assert_called_once_with(
            issuer="https://idp.example.com/test",
            jwks_url="https://idp.example.com/test/.well-known/jwks.json",
            audience=None,
            algorithms=None,
        )

    @pytest.mark.anyio
    async def test_missing_authorization_header(
        self, auth_middleware, mock_call_next
    ) -> None:
        """Test middleware behavior when authorization header is missing."""
        request = Mock(spec=Request)
        request.headers = {}  # No authorization header
        request.state = Mock()

        # The middleware should raise HTTPException with status 401 when authorization header is missing
        with pytest.raises(HTTPException) as exc_info:
            await auth_middleware.dispatch(request, mock_call_next)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Authorization header is missing"
