from typing import Any, Type, override
import httpx

from pymidil.client.transport.retry.transport import RetryTransport


class MidilAsyncClient(httpx.AsyncClient):
    """
    This class is a wrapper around httpx.AsyncClient that uses a custom transport class.
    This is done to allow passing our custom transport class to the AsyncClient constructor while still allowing
    all the default AsyncClient behavior that is changed when passing a custom transport instance.
    """

    def __init__(
        self,
        transport_class: Type[RetryTransport] = RetryTransport,
        transport_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        self._transport_kwargs = transport_kwargs
        self._transport_class = transport_class
        super().__init__(**kwargs)

    @override
    def _init_transport(  # type: ignore[override]
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> httpx.AsyncBaseTransport:
        if transport is not None:
            return super()._init_transport(transport=transport, **kwargs)

        return self._transport_class(
            wrapped=httpx.AsyncHTTPTransport(
                **kwargs,
            ),
            **(self._transport_kwargs or {}),
        )

    def _init_proxy_transport(  # type: ignore[override]
        self, proxy: httpx.Proxy, **kwargs: Any
    ) -> httpx.AsyncBaseTransport:
        return self._transport_class(
            wrapped=httpx.AsyncHTTPTransport(
                proxy=proxy,
                **kwargs,
            ),
            **(self._transport_kwargs or {}),
        )
