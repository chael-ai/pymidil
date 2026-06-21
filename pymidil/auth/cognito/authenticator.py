import base64
from typing import Optional, Any
from datetime import datetime, timezone, timedelta
from pymidil.auth.interfaces.authenticator import AuthNProvider

from pymidil.auth.interfaces.types import AuthNToken, AuthNHeaders
import asyncio
from pymidil.auth.cognito.exceptions import CognitoAuthenticationError
from pymidil.client.transport.context import get_http_async_client


class CognitoClientCredentialsAuthenticator(AuthNProvider):
    """Implements the client credentials flow for cognito"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
        scope: Optional[str] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.token_url = token_url
        self._cached_token: Optional[AuthNToken] = None
        self._lock = asyncio.Lock()
        self.client = get_http_async_client()

    async def get_token(self) -> AuthNToken:
        async with self._lock:
            if self._cached_token and not self._cached_token.expired:
                return self._cached_token

            token = await self._fetch_token()

            # Calculate expiration time from expires_in seconds
            expires_in_seconds = token.get("expires_in")
            expires_at_iso = None
            if expires_in_seconds:
                expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=expires_in_seconds
                )
                expires_at_iso = expires_at.isoformat()

            self._cached_token = AuthNToken(
                token=token["access_token"], expires_at_iso=expires_at_iso
            )
            return self._cached_token

    async def get_headers(self) -> AuthNHeaders:
        token = await self.get_token()
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        return AuthNHeaders(**headers)

    async def _fetch_token(self) -> Any:
        credentials = f"{self.client_id}:{self.client_secret}"
        basic_auth = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {basic_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "client_credentials",
        }
        if self.scope:
            data["scope"] = self.scope

        response = await self.client.post(self.token_url, data=data, headers=headers)
        if response.status_code != 200:
            raise CognitoAuthenticationError(f"Cognito token fetch failed: {response}")
        return response.json()
