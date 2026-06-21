import httpx
import contextvars
import hashlib
import json

from pymidil.client.transport.factory import MidilAsyncClient
from pymidil.client.transport.retry.transport import RetryTransport

from typing import Any


_http_client_var: contextvars.ContextVar[
    httpx.AsyncClient | None
] = contextvars.ContextVar("_http_client_var", default=None)

_client_params_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_client_params_var", default=None
)


def _get_http_client_context(timeout: int = 60, **kwargs: Any) -> httpx.AsyncClient:
    params: dict[str, Any] = {"timeout": timeout}
    for key, value in kwargs.items():
        if hasattr(value, "__str__") and "URL" in str(type(value)):
            params[key] = str(value)
        else:
            params[key] = value

    params_hash = hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest()

    cached_params = _client_params_var.get()
    client = _http_client_var.get()

    if client is not None and cached_params == params_hash:
        return client

    client = MidilAsyncClient(
        transport_class=RetryTransport,
        timeout=timeout,
        **kwargs,
    )

    _http_client_var.set(client)
    _client_params_var.set(params_hash)

    return client


def get_http_async_client(timeout: int = 60, **kwargs: Any) -> httpx.AsyncClient:
    return _get_http_client_context(timeout, **kwargs)
