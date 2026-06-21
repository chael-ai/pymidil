from pydantic import BaseModel, PrivateAttr, Field, ConfigDict
from typing import Optional
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
    expires_at_iso: Optional[str] = None

    def expires_at(self) -> Optional[datetime]:
        return isoparse(self.expires_at_iso) if self.expires_at_iso else None


class AuthNHeaders(BaseModel):
    authorization: str = Field(..., alias="Authorization")
    accept: str = Field(default="application/json", alias="Accept")
    content_type: str = Field(default="application/json", alias="Content-Type")

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
    )


class AuthZTokenClaims(ExpirableTokenMixin):
    sub: str
    exp: int  # epoch

    def expires_at(self) -> datetime:
        return datetime.fromtimestamp(self.exp, tz=timezone.utc)
