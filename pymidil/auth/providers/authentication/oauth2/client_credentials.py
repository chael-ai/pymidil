import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from pymidil.auth.interfaces.authenticator import AuthNProvider
from pymidil.auth.interfaces.types import AuthNToken
from pymidil.auth.exceptions import AuthenticationError


_DEFAULT_REFRESH_BUFFER = 30


class OAuth2ClientCredentialsProvider(AuthNProvider):
    """
    OAuth2 Client Credentials grant provider.

    This provider implements the OAuth2 Client Credentials flow (RFC 6749)
    and is compatible with common providers including:
        - AWS Cognito
        - Auth0
        - Azure AD
        - Keycloak
        - Okta

    It manages access tokens on behalf of the client and handles expiration
    and optional scope settings.
    """

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: Optional[str] = None,
        refresh_buffer: int = _DEFAULT_REFRESH_BUFFER,
    ):
        """
        Initialize the OAuth2ClientCredentialsProvider.

        Args:
            token_url (str):
                The OAuth2 token endpoint URL.
            client_id (str):
                The OAuth2 client ID for authentication.
            client_secret (str):
                The OAuth2 client secret for authentication.
            scope (Optional[str], optional):
                (Space-separated) Scopes to request from the provider.
            refresh_buffer (int, optional):
                Seconds before token expiry to refresh early.
                Defaults to 30 seconds.
        """

        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.refresh_buffer = refresh_buffer

        self._token: AuthNToken | None = None
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            auth=httpx.BasicAuth(
                self.client_id,
                self.client_secret,
            )
        )

    async def get_token(self) -> AuthNToken:
        """
        Return a valid cached token if available, otherwise fetch a new one.

        Uses a lock to prevent concurrent token refreshes.

        Returns:
            AuthNToken: The access token object.
        """
        # Fast path
        if self._token and not self._token.expired:
            return self._token

        async with self._lock:
            # Another coroutine may have refreshed it
            if self._token and not self._token.expired:
                return self._token

            self._token = await self._fetch_token()
            return self._token

    async def invalidate(self) -> None:
        """
        Invalidates the cached token, forcing the next call to get_token() to fetch a new token.
        """
        async with self._lock:
            self._token = None

    async def _fetch_token(self) -> AuthNToken:
        """
        Fetch a new OAuth2 access token from the provider.

        Constructs and sends a POST request to the token URL using the client credentials.
        Will refresh slightly before the provider's expiry to avoid using expired tokens.

        Returns:
            AuthNToken: The newly obtained access token.

        Raises:
            AuthenticationError: If the token request fails.
        """
        data = {
            "grant_type": "client_credentials",
        }

        if self.scope:
            data["scope"] = self.scope

        response = await self._client.post(self.token_url, data=data)

        if response.status_code != 200:
            raise AuthenticationError(
                f"Failed to obtain access token "
                f"({response.status_code}): {response.text}"
            )

        payload = response.json()

        expires_at = None
        expires_in = payload.get("expires_in")

        if expires_in is not None:
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=expires_in - self.refresh_buffer)
            ).isoformat()

        return AuthNToken(
            token=payload["access_token"],
            token_type=payload.get(
                "token_type",
                "Bearer",
            ),
            expires_at_iso=expires_at,
        )
