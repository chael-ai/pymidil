from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer
from pymidil.auth.cognito.jwt_authorizer import CognitoJWTAuthorizer
from pymidil.settings import get_settings
from pymidil.auth.interfaces.types import AuthZTokenClaims
from loguru import logger


security = HTTPBearer(auto_error=True)


async def authorize_request(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthZTokenClaims:
    token = credentials.credentials
    cognito_settings = get_settings().get_auth("cognito")
    authorizer = CognitoJWTAuthorizer(
        user_pool_id=cognito_settings.user_pool_id,
        region=cognito_settings.region,
    )
    claims = await authorizer.verify(token)
    logger.info(f"Authenticated request for user {claims.sub}")
    return claims
