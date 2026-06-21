from typing import Annotated, Literal, Union
from pymidil.utils.base_models import SnakeCaseModel
from pydantic import Field


_DEFAULT_EXPIRES_IN_SECONDS = 900


class HMACCursorConfig(SnakeCaseModel):
    algorithm: Literal["hmac"] = "hmac"
    secret_key: str = Field(..., description="Secret key for cursor pagination.")
    expires_in_seconds: int = Field(
        default=_DEFAULT_EXPIRES_IN_SECONDS,
        description="Expiration time for cursor in seconds.",
    )


CursorConfig = Annotated[
    Union[HMACCursorConfig],
    Field(discriminator="algorithm"),
]
