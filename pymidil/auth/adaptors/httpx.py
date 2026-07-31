import httpx
from typing import TYPE_CHECKING
from copy import deepcopy


if TYPE_CHECKING:
    from pymidil.auth.interfaces.authenticator import AuthNProvider


class BearerAuth(httpx.Auth):
    """
    HTTPX authentication handler for bearer tokens.

    Works with:
    - OAuth2 access tokens
    - JWT tokens
    - Static bearer credentials
    """

    def __init__(
        self,
        provider: AuthNProvider,
        retry_on_401: bool = True,
    ):
        self.provider = provider
        self.retry_on_401 = retry_on_401

    async def async_auth_flow(
        self,
        request: httpx.Request,
    ):
        token = await self.provider.get_token()

        request.headers["Authorization"] = f"{token.token_type} {token.token}"

        response = yield request

        if response.status_code == 401 and self.retry_on_401:
            await self.provider.invalidate()

            token = await self.provider.get_token()

            retry_request = deepcopy(request)

            retry_request.headers["Authorization"] = f"{token.token_type} {token.token}"

            yield retry_request


class HeaderAuth(httpx.Auth):
    """
    Injects credentials into a HTTP header.
    """

    def __init__(
        self,
        provider: AuthNProvider,
        header_name: str,
        prefix: str | None = None,
    ):
        self.provider = provider
        self.header_name = header_name
        self.prefix = prefix

    async def async_auth_flow(
        self,
        request: httpx.Request,
    ):
        token = await self.provider.get_token()

        value = token.token

        if self.prefix:
            value = f"{self.prefix} {value}"

        request.headers[self.header_name] = value

        yield request
