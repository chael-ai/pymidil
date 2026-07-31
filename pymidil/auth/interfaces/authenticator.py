from abc import ABC, abstractmethod
from pymidil.auth.interfaces.types import AuthNToken


class AuthNProvider(ABC):
    """
    Abstract base class for authentication clients that acquire and manage access tokens.

    Usecase:
    - For acquiring and managing access tokens.
    - Your services making outbound authenticated requests (to APIs, etc.) implement AccessTokenProvider.

    Implementations of this class should provide methods to:
      - Acquire a new access token from an authentication provider (e.g., OAuth2, Cognito, etc.).
      - Return authentication headers suitable for making authorized HTTP requests.

    This interface is intended to be used by services or middleware that need to authenticate
    outgoing requests or validate incoming tokens.



    Example usage:

        class MyAuthClient(AccessTokenProvider):
            async def get_access_token(self) -> AccessToken:
                # Implementation to fetch and return an AccessToken
                ...

            async def invalidate(self) -> AuthHeaders:
                # Invalidate credential
                ...

    """

    @abstractmethod
    async def get_token(self) -> AuthNToken:
        pass

    async def invalidate(self) -> None:
        """Called when the current token should no longer be trusted."""
        raise NotImplementedError("Token invalidation not implemented for this client")
