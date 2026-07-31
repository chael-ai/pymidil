from __future__ import annotations

import asyncio
from typing import Any

import httpx
import jwt
from jwt import (
    DecodeError,
    InvalidTokenError,
    PyJWK,
    PyJWKClient,
    PyJWKClientError,
)
from loguru import logger

from pymidil.auth.exceptions import AuthorizationError
from pymidil.auth.interfaces.authorizer import AuthZProvider
from pymidil.auth.interfaces.types import AuthZTokenClaims


class JWKAuthorizer(AuthZProvider):
    """
    Generic JWT authorizer backed by a JSON Web Key Set (JWKS).

    This implementation is compatible with any OAuth2 / OpenID Connect
    identity provider that exposes a JWKS endpoint.

    Examples:
        - Amazon Cognito
        - Auth0
        - Okta
        - Keycloak
        - Microsoft Entra ID
        - Google Identity

    The authorizer is responsible for:

    - Fetching signing keys from the JWKS endpoint
    - Caching keys
    - Verifying JWT signatures
    - Validating issuer
    - Validating audience (optional)
    - Validating expiration and standard JWT claims
    """

    DEFAULT_CACHE_LIFETIME = 900
    DEFAULT_MAX_CACHED_KEYS = 32
    DEFAULT_REQUIRED_CLAIMS = [
        "sub",
        "iss",
        "exp",
        "iat",
    ]

    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        audience: str | None = None,
        algorithms: list[str] | None = None,
        cache_lifetime: int = DEFAULT_CACHE_LIFETIME,
        max_cached_keys: int = DEFAULT_MAX_CACHED_KEYS,
        required_claims: list[str] = DEFAULT_REQUIRED_CLAIMS,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.jwks_url = jwks_url
        self.audience = audience
        self.algorithms = algorithms or ["RS256"]

        self.required_claims = required_claims

        if audience is not None:
            self.required_claims.append("aud")

        self._client = PyJWKClient(
            jwks_url,
            cache_keys=True,
            lifespan=cache_lifetime,
            max_cached_keys=max_cached_keys,
        )

        self._refresh_lock = asyncio.Lock()

    async def _refresh_client(self) -> None:
        """
        Re-create the underlying PyJWKClient.

        This is used when key rotation has occurred and the requested
        signing key cannot be found.
        """

        async with self._refresh_lock:
            self._client = PyJWKClient(
                self.jwks_url,
                cache_keys=True,
                lifespan=self.DEFAULT_CACHE_LIFETIME,
                max_cached_keys=self.DEFAULT_MAX_CACHED_KEYS,
            )

    async def _get_signing_key(self, token: str) -> PyJWK:
        """
        Retrieve the signing key corresponding to the JWT's `kid`.
        """

        try:
            return await asyncio.to_thread(
                self._client.get_signing_key_from_jwt,
                token,
            )

        except PyJWKClientError:
            logger.warning("Signing key not found in JWKS cache. Refreshing...")

            await self._refresh_client()

            try:
                return await asyncio.to_thread(
                    self._client.get_signing_key_from_jwt,
                    token,
                )

            except Exception as exc:
                raise AuthorizationError("Unable to retrieve signing key.") from exc

    async def verify(self, token: str) -> AuthZTokenClaims:
        """
        Verify a JWT and return its decoded claims.

        Raises:
            AuthorizationError
                If the token is invalid or cannot be verified.
        """

        try:
            signing_key = await self._get_signing_key(token)

            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=self.algorithms,
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": self.audience is not None,
                    "require": self.required_claims,
                },
            )

            logger.debug(
                "JWT successfully verified.",
                extra={
                    "issuer": self.issuer,
                    "subject": payload.get("sub"),
                },
            )

            return AuthZTokenClaims(
                token=token,
                **payload,
            )

        except (InvalidTokenError, DecodeError) as exc:
            logger.warning("JWT verification failed: {}", exc)

            raise AuthorizationError(f"JWT verification failed: {exc}") from exc

        except AuthorizationError:
            raise

        except Exception as exc:
            logger.exception("Unexpected authorization failure.")

            raise AuthorizationError("Unexpected error while verifying JWT.") from exc

    @classmethod
    async def from_oidc_discovery(
        cls,
        *,
        issuer: str,
        audience: str | None = None,
        algorithms: list[str] | None = None,
    ) -> "JWKAuthorizer":
        """
        Create a JWKAuthorizer using OpenID Connect discovery.

        Example:
            authorizer = await JWKAuthorizer.from_oidc_discovery(
                issuer="https://dev-abc123.us.auth0.com/",
                audience="api://backend",
            )
        """

        issuer = issuer.rstrip("/")

        discovery_url = f"{issuer}/.well-known/openid-configuration"

        async with httpx.AsyncClient() as client:
            response = await client.get(discovery_url)
            response.raise_for_status()

            config: dict[str, Any] = response.json()

        return cls(
            issuer=config["issuer"],
            jwks_url=config["jwks_uri"],
            audience=audience,
            algorithms=algorithms,
        )
