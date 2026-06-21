import jwt
from typing import Optional
from jwt import PyJWKClient, InvalidTokenError, DecodeError, PyJWK
from pymidil.auth.cognito.exceptions import CognitoAuthorizationError
from pymidil.auth.exceptions import AuthorizationError
import asyncio


from loguru import logger
from pymidil.auth.interfaces.authorizer import (
    AuthZProvider,
)
from pymidil.auth.interfaces.types import AuthZTokenClaims
from pydantic import ConfigDict, Field


class CognitoTokenClaims(AuthZTokenClaims):
    email: Optional[str] = Field(
        default=None,
        alias="email",
        description="The email address of the user",
        pattern=r"^[^@]+@[^@]+\.[^@]+$",
    )
    name: Optional[str] = Field(
        default=None, alias="name", description="The name of the user"
    )
    iss: Optional[str] = Field(
        default=None, alias="iss", description="The issuer of the token"
    )
    aud: Optional[str] = Field(
        default=None, alias="aud", description="The audience of the token"
    )
    iat: Optional[int] = Field(
        default=None, alias="iat", description="The issued at time of the token"
    )

    model_config = ConfigDict(extra="allow")


class CognitoJWTAuthorizer(AuthZProvider):
    """
    Authorizes and decodes JWT tokens issued by AWS Cognito using the JWKs endpoint.
    """

    _REFRESH_INTERVAL: int = 900  # 15 minutes
    _MAX_CACHE_SIZE: int = 32

    def __init__(
        self, user_pool_id: str, region: str, audience: Optional[str] = None
    ) -> None:
        self.user_pool_id = user_pool_id
        self.region = region
        self.audience = audience
        self.jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
        self._jwk_client = PyJWKClient(
            self.jwks_url,
            cache_keys=True,
            lifespan=self._REFRESH_INTERVAL,
            max_cached_keys=self._MAX_CACHE_SIZE,
        )
        self._jwk_client_lock = asyncio.Lock()

    async def _get_signing_key(self, token: str) -> PyJWK:
        try:
            return await asyncio.to_thread(
                self._jwk_client.get_signing_key_from_jwt, token
            )
        except jwt.exceptions.PyJWKClientError:
            logger.warning("JWKS client failed to find signing key — refreshing...")
            # Retry after refreshing client
            async with self._jwk_client_lock:
                self._jwk_client = PyJWKClient(
                    self.jwks_url,
                    cache_keys=True,
                    lifespan=self._REFRESH_INTERVAL,
                    max_cached_keys=self._MAX_CACHE_SIZE,
                )
                try:
                    return await asyncio.to_thread(
                        self._jwk_client.get_signing_key_from_jwt, token
                    )
                except Exception as e2:
                    raise CognitoAuthorizationError(
                        "Failed to fetch signing key after retry"
                    ) from e2

    async def verify(self, token: str) -> AuthZTokenClaims:
        """
        Validates and decodes a JWT token using Cognito JWKs.
        Raises CognitoAuthenticationError if invalid.
        Returns the decoded claims.
        """
        try:
            signing_key = await self._get_signing_key(token)
            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience if self.audience else None,
                options={
                    "verify_exp": True,
                    "verify_aud": self.audience is not None,
                    "verify_iss": True,
                    "verify_signature": True,
                    "require": [
                        "exp",
                        "iat",
                        "sub",
                        "iss",
                        "aud",
                    ],  # essential security claims
                },
            )
            logger.debug("Successfully verified JWT token", extra={"decoded": decoded})
            claims = CognitoTokenClaims(token=token, **decoded)
            return claims

        except (InvalidTokenError, DecodeError) as e:
            logger.error(f"JWT verification failed: {str(e)}")
            raise CognitoAuthorizationError(f"JWT verification failed: {str(e)}") from e

        except AuthorizationError as e:
            logger.error(f"JWT verification failed: {str(e)}")
            raise

        except Exception as e:
            logger.error(f"An unexpected error occurred while verifying JWT: {str(e)}")
            raise
