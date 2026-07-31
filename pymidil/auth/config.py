from typing import Literal, Optional, Union
from pydantic import BaseModel, Field, SecretStr


class OAuth2ClientCredentialsConfig(BaseModel):
    type: Literal["client_credentials"] = "client_credentials"
    token_url: str = Field(..., description="OAuth2 token endpoint URL")
    client_id: str = Field(..., description="OAuth2 client ID")
    client_secret: SecretStr = Field(..., description="OAuth2 client secret")
    scope: Optional[str] = Field(
        default=None, description="Space-separated scopes to request"
    )


class StaticCredentialAuthConfig(BaseModel):
    type: Literal["static_credential"] = "static_credential"
    api_key: SecretStr = Field(..., description="Static, non-refreshable credential")
    scheme: Optional[str] = Field(
        default="Bearer",
        description="Authorization scheme prefix (e.g. 'Bearer'); set to None to send the raw key",
    )


class JWKAuthorizerConfig(BaseModel):
    type: Literal["jwk"] = "jwk"
    issuer: str = Field(
        ..., description="Expected token issuer (iss claim / OIDC issuer URL)"
    )
    jwks_url: str = Field(..., description="JWKS endpoint URL")
    audience: Optional[str] = Field(
        default=None, description="Expected audience (aud claim)"
    )
    algorithms: Optional[list[str]] = Field(
        default=None,
        description="Accepted JWS signing algorithms (defaults to ['RS256'])",
    )


AuthConfig = Union[
    OAuth2ClientCredentialsConfig, StaticCredentialAuthConfig, JWKAuthorizerConfig
]
