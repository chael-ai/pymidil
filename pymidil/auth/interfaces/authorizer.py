from abc import ABC, abstractmethod
from pymidil.auth.interfaces.types import AuthZTokenClaims


class AuthZProvider(ABC):
    """
    Abstract base class for authentication authorizers that validate and decode tokens.

    Usecase: For decoding and verifying incoming tokens.

    Implementations of this class should provide methods to:
    - Validate and decode a token from an authentication provider (e.g., OAuth2, Cognito, etc.).
    - Return the claims (payload) of a valid token.

    Your services doing inbound auth (like API gateways or middlewares) use TokenVerifier.
    """

    @abstractmethod
    async def verify(self, token: str) -> AuthZTokenClaims:
        pass
