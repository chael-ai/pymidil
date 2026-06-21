from typing import Dict, Any, Callable, Awaitable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from pymidil.auth.interfaces.authorizer import AuthZProvider
from pymidil.auth.interfaces.types import AuthZTokenClaims
from pymidil.auth.cognito.jwt_authorizer import CognitoJWTAuthorizer
from starlette.exceptions import HTTPException
from starlette.responses import Response
from pymidil.auth.exceptions import AuthorizationError
from pymidil.settings import get_settings


class AuthContext:
    """
    Holds decoded token claims and raw authentication headers from a request.

    Attributes:
        claims (AuthZTokenClaims): The decoded JWT claims.
        _raw_headers (Dict[str, Any]): Raw HTTP headers related to authentication.

    Usage:
        ```python
        context = AuthContext(claims=claims, _raw_headers=request.headers)
        user_id = context.claims.sub
        ```
    """

    def __init__(
        self,
        claims: AuthZTokenClaims,
        _raw_headers: Dict[str, Any],
    ) -> None:
        """
        Initialize the authentication context.

        Args:
            claims (AuthZTokenClaims): The decoded token claims.
            _raw_headers (Dict[str, Any]): Raw HTTP headers from the request.
        """
        self.claims = claims
        self._raw_headers = _raw_headers

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claims": self.claims.model_dump(),
            "raw_headers": self._raw_headers,
        }


class BaseAuthMiddleware(BaseHTTPMiddleware):
    """
    Base middleware for extracting authentication headers from the request and storing
    authentication context in the request state.

    Subclass this middleware and implement the `authorizer` method to provide a concrete
    AuthZProvider (e.g., CognitoJWTAuthorizer).

    Example:

    ```python
    from fastapi import FastAPI, Depends
    from pymidil.auth.interfaces.authorizer import AuthZProvider
    from pymidil.auth.interfaces.types import AuthZTokenClaims
    from pymidil.web.fastapi.middleware.auth_middleware import (
        AuthContext,
        BaseAuthMiddleware,
    )

    app = FastAPI()

    class MyAuthMiddleware(BaseAuthMiddleware):
        async def authorizer(self, request: Request) -> AuthZProvider:
            # implement your authorizer here
            return AuthZProvider(...)


    def get_auth(request: Request) -> AuthContext:
        return request.state.auth

    @app.get("/me")
    def me(auth: AuthContext = Depends(get_auth)):
        return auth.to_dict()

    # Add as middleware
    app.add_middleware(MyAuthMiddleware)
    ```

    After authentication, the request's state will have an `auth` attribute containing
    an AuthContext instance with the decoded claims and raw headers.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            if "authorization" not in request.headers:
                raise HTTPException(
                    status_code=401, detail="Authorization header is missing"
                )
            token = self._resolve_bearer_token(request.headers["authorization"])

            authorizer = await self.authorizer(request)
            claims = await authorizer.verify(token)

            request.state.auth = AuthContext(
                claims=claims,
                _raw_headers=dict(request.headers),
            )
            response = await call_next(request)
            return response

        except AuthorizationError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e

    async def authorizer(self, request: Request) -> AuthZProvider:
        """
        Returns an authorization provider for the given request.

        Args:
            request (Request): The incoming HTTP request.

        Returns:
            AuthZProvider: An instance capable of verifying JWT tokens.

        Raises:
            NotImplementedError: If the method is not overridden.

        Usage:
            ```python
            authorizer = await middleware.authorizer(request)
            claims = await authorizer.verify(token)
            ```
        """
        raise NotImplementedError("Authorizer not implemented")

    def _resolve_bearer_token(self, token: str) -> str:
        """
        Resolves the bearer token from the Authorization header.

        Args:
            token (str): The Authorization header value.

        Returns:
            str: The stripped token without "Bearer " prefix.
        """
        if token.startswith("Bearer "):
            return token.replace("Bearer ", "")
        return token


class CognitoAuthMiddleware(BaseAuthMiddleware):
    """
    Middleware to extract cognitoauth headers from request and store them in the request state.

    Example:
    ```python
    from fastapi import FastAPI, Depends
    from pymidil.auth.cognito.jwt_authorizer import CognitoJWTAuthorizer
    from pymidil.auth.interfaces.authorizer import AuthZProvider
    from pymidil.auth.interfaces.types import AuthZTokenClaims
    from pymidil.web.fastapi.middleware.auth_middleware import (
        CognitoAuthMiddleware,
    )
    app = FastAPI()

        def get_auth(request: Request) -> AuthContext:
            return request.state.auth

        @app.get("/me")
        def me(auth: AuthContext = Depends(get_auth)):
            return auth.to_dict()

        # as middleware
        app.add_middleware(CognitoAuthMiddleware)

    """

    async def authorizer(self, request: Request) -> AuthZProvider:
        cognito_settings = get_settings().get_auth("cognito")
        return CognitoJWTAuthorizer(
            user_pool_id=cognito_settings.user_pool_id, region=cognito_settings.region
        )
