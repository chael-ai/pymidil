from typing import Any, Dict, TYPE_CHECKING, Optional
import httpx

from pymidil.client.transport.context import (
    get_http_async_client,
)
from pymidil.auth.interfaces.types import AuthNHeaders
from typing import Union, Mapping

if TYPE_CHECKING:
    from pymidil.auth.interfaces.authenticator import AuthNProvider


class HttpClient:
    def __init__(
        self,
        base_url: Union[str, httpx.URL],
        headers: Optional[Mapping[str, Any]] = None,
        auth_client: Optional["AuthNProvider"] = None,
    ) -> None:
        self.base_url = httpx.URL(base_url)
        self._base_headers: Dict[str, Any] = dict(headers or {})
        self._auth_client = auth_client
        self._client = get_http_async_client(base_url=self.base_url)

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client."""
        print("Getting client", self._client.base_url)
        print("Getting client base url", self._client.headers)
        return self._client

    @client.setter
    def client(self, value: httpx.AsyncClient) -> None:
        """Set the HTTP client and update its base_url."""
        self._client = value
        # Update the client's base_url to match our base_url
        self._client.base_url = self.base_url

    async def get_headers(self) -> Dict[str, Any]:
        """
        Resolve effective headers (base + auth).
        Auth headers override base headers if keys overlap.
        """
        if self._auth_client is None:
            return dict(self._base_headers)
        auth_headers: AuthNHeaders = await self._auth_client.get_headers()
        return {**self._base_headers, **auth_headers.model_dump(by_alias=True)}

    async def update_headers(self, value: Union[AuthNHeaders, Dict[str, Any]]) -> None:
        """
        Update base headers (does not override auth headers which are refreshed dynamically).
        """
        if isinstance(value, AuthNHeaders):
            self._base_headers.update(value.model_dump(by_alias=True))
        else:
            self._base_headers.update(value)

    async def send_request(
        self,
        method: str,
        url: Union[str, httpx.URL],
        json: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Send a single HTTP request with retries and auth headers.
        """
        headers = await self.get_headers()

        response: httpx.Response = await self.client.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    async def send_paginated_request(
        self,
        method: str,
        url: str,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        raise NotImplementedError("Paginated requests are not implemented")
