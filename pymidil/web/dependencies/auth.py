from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer
from pymidil.auth.providers.authorization.jwk import JWKAuthorizer
from pymidil.settings import get_settings
from pymidil.auth.interfaces.types import AuthZTokenClaims
from loguru import logger


security = HTTPBearer(auto_error=True)


async def authorize_request(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthZTokenClaims:
    token = credentials.credentials
    jwk_settings = get_settings().get_auth("jwk")
    authorizer = JWKAuthorizer(
        issuer=jwk_settings.issuer,
        jwks_url=jwk_settings.jwks_url,
        audience=jwk_settings.audience,
        algorithms=jwk_settings.algorithms,
    )
    claims = await authorizer.verify(token)
    logger.info(f"Authenticated request for user {claims.sub}")
    return claims
