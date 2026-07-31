from typing import Any, Dict, Mapping, Optional, TYPE_CHECKING, Union

import httpx

from pymidil.client.exceptions import HTTPRequestError, HTTPStatusError
from pymidil.client.transport.context import get_http_async_client
from pymidil.client.transport.factory import RetryConfig

if TYPE_CHECKING:
    from pymidil.auth.interfaces.authenticator import AuthNProvider


class AsyncHTTPClient:
    """Async HTTP client that layers auth-header injection and domain
    exceptions on top of a pooled, retrying ``httpx.AsyncClient``.

    The underlying ``httpx.AsyncClient`` comes from
    :func:`get_http_async_client`, which caches/shares one instance per
    ``(timeout, base_url, ...)`` — so another ``AsyncHTTPClient`` built with
    the same ``base_url`` may hold a reference to that exact same object.
    Because of that sharing, this class has no ``aclose()`` or context-manager
    support: it never owns the client exclusively, so closing it here would
    risk breaking another holder still using it (``RuntimeError: Cannot send
    a request, as the client has been closed.``).

    If you need full control over the underlying transport (custom certs,
    a proxy, a mock transport for tests) beyond what ``retry_config`` tunes,
    use ``httpx.AsyncClient`` directly instead of this class — there's no way
    to hand it a pre-built client.
    """

    def __init__(
        self,
        base_url: Union[str, httpx.URL],
        headers: Optional[Mapping[str, str]] = None,
        auth_provider: Optional["AuthNProvider"] = None,
        retry_config: Optional[RetryConfig] = None,
    ) -> None:
        self.base_url = httpx.URL(base_url)
        self._base_headers: Dict[str, str] = dict(headers or {})
        self._auth_provider = auth_provider
        self._client = get_http_async_client(
            base_url=self.base_url, retry_config=retry_config
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """The underlying httpx.AsyncClient."""
        return self._client

    async def resolve_headers(self) -> Dict[str, str]:
        """
        Resolve effective headers (base + auth).
        Auth headers override base headers if keys overlap.
        """
        if self._auth_provider is None:
            return dict(self._base_headers)
        token = await self._auth_provider.get_token()
        return {
            **self._base_headers,
            "Authorization": f"{token.token_type} {token.token}",
        }

    async def update_headers(self, value: Mapping[str, str]) -> None:
        """
        Update base headers (does not override auth headers which are resolved dynamically).
        """
        self._base_headers.update(value)

    async def send_request(
        self,
        method: str,
        url: Union[str, httpx.URL],
        json: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Send a single HTTP request with retries (via the transport) and auth headers.

        Returns the raw ``httpx.Response`` — callers decide how (or whether)
        to parse the body, so a 204 No Content or non-JSON response doesn't
        blow up here.

        Raises:
            HTTPStatusError: the server responded with a non-2xx status.
            HTTPRequestError: the request failed at the transport level
                (connection, timeout, DNS, etc.).
        """
        headers = await self.resolve_headers()

        try:
            response = await self._client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=json,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPStatusError(
                f"{method.upper()} {url} returned {exc.response.status_code}",
                status_code=exc.response.status_code,
                response=exc.response,
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPRequestError(f"{method.upper()} {url} failed: {exc}") from exc

        return response

    async def send_paginated_request(
        self,
        method: str,
        url: Union[str, httpx.URL],
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        raise NotImplementedError("Paginated requests are not implemented")
