from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field, SecretStr


class CognitoAuthConfig(BaseModel):
    type: Literal["cognito"] = "cognito"
    user_pool_id: str = Field(..., description="Cognito User Pool ID")
    client_id: str = Field(..., description="Cognito App Client ID")
    client_secret: Optional[SecretStr] = Field(
        None, description="Cognito App Client Secret (optional)"
    )
    region: str = Field(..., description="AWS region for Cognito")


AuthConfig = Annotated[Union[CognitoAuthConfig], Field(discriminator="type")]
