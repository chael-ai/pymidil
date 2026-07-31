from pymidil.auth.interfaces.authenticator import AuthNProvider
from pymidil.auth.interfaces.types import AuthNToken


class StaticCredentialProvider(AuthNProvider):
    """
    Provides a non-refreshable credential.

    Examples:
    - API keys
    - Static bearer tokens
    - Service tokens
    """

    def __init__(
        self,
        credential: str,
    ):
        """
        Initialize the StaticCredentialProvider.

        Args:
            credential (str): The non-refreshable credential value (e.g., API key, static bearer token, or service token).
        """
        self.credential = credential

    async def get_token(self) -> AuthNToken:
        return AuthNToken(
            token=self.credential,
            expires_at_iso=None,
        )

    async def invalidate(self) -> None:
        pass
