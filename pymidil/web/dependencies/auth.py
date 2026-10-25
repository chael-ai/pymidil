from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer
from pymidil.auth.cognito.jwt_authorizer import CognitoJWTAuthorizer
from pymidil.settings import get_settings
from pymidil.auth.interfaces.types import AuthZTokenClaims
from loguru import logger


security = HTTPBearer(auto_error=True)


@lru_cache(maxsize=8)
def get_cognito_authorizer(
    user_pool_id: str, region: str, client_id: str
) -> CognitoJWTAuthorizer:
    """One authorizer per pool/app client, so the JWKS cache survives across requests.

    Tokens must be ID tokens issued to ``client_id`` (their ``aud``): tokens from
    other app clients in the same pool are rejected.
    """
    return CognitoJWTAuthorizer(
        user_pool_id=user_pool_id, region=region, audience=client_id
    )


async def authorize_request(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthZTokenClaims:
    token = credentials.credentials
    cognito_settings = get_settings().get_auth("cognito")
    authorizer = get_cognito_authorizer(
        cognito_settings.user_pool_id,
        cognito_settings.region,
        cognito_settings.client_id,
    )
    claims = await authorizer.verify(token)
    logger.info(f"Authenticated request for user {claims.sub}")
    return claims
