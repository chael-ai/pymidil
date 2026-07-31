from pydantic import BaseModel, PrivateAttr, Field, ConfigDict
from typing import Optional, Any
from datetime import datetime, timezone, timedelta
from dateutil.parser import isoparse


class ExpirableTokenMixin(BaseModel):
    _time_buffer: timedelta = PrivateAttr(default_factory=lambda: timedelta(minutes=5))
    token: str
    refresh_token: Optional[str] = None

    def expires_at(self) -> Optional[datetime]:
        raise NotImplementedError("Subclasses must implement expires_at()")

    @property
    def expired(self) -> bool:
        dt = self.expires_at()
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt is not None and datetime.now(timezone.utc) >= (dt - self._time_buffer)

    @property
    def should_refresh(self) -> bool:
        return self.expired and self.refresh_token is not None


class AuthNToken(ExpirableTokenMixin):
    token_type: str = "Bearer"
    expires_at_iso: Optional[str] = None

    def expires_at(self) -> Optional[datetime]:
        return isoparse(self.expires_at_iso) if self.expires_at_iso else None


class AuthZTokenClaims(ExpirableTokenMixin):
    """
    Standard JWT authorization claims.

    This model represents claims defined by JWT/OIDC standards.
    Provider-specific claims are allowed through `extra="allow"`.

    Examples of additional claims:
        Cognito:
            email
            cognito:groups

        Auth0:
            permissions
            scope

        Keycloak:
            realm_access
            resource_access

        Azure:
            roles
    """

    token: str = Field(description="Original encoded JWT token")
    sub: str = Field(description="Unique identifier of the token subject")
    iss: str = Field(description="Issuer of the JWT")
    aud: str | list[str] = Field(description="Token audience")
    iat: int = Field(description="Issued-at timestamp")
    exp: int = Field(description="Expiration timestamp")
    nbf: int | None = Field(default=None, description="Not-before timestamp")
    jti: str | None = Field(default=None, description="Unique token identifier")

    model_config = ConfigDict(extra="allow")

    def get_claim(
        self,
        name: str,
        default: Any = None,
    ) -> Any:
        """
        Retrieve custom provider claims safely.
        """
        return getattr(self, name, default)

    def expires_at(self) -> datetime:
        return datetime.fromtimestamp(self.exp, tz=timezone.utc)
