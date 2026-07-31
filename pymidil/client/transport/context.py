import httpx
import contextvars
import hashlib
import json

from pymidil.client.transport.factory import RetryableAsyncClient, RetryConfig

from typing import Any, Optional


_http_client_var: contextvars.ContextVar[
    httpx.AsyncClient | None
] = contextvars.ContextVar("_http_client_var", default=None)

_client_params_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_client_params_var", default=None
)


def _get_http_client_context(
    timeout: int = 60,
    retry_config: Optional[RetryConfig] = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    params: dict[str, Any] = {"timeout": timeout, "retry_config": retry_config}
    for key, value in kwargs.items():
        if hasattr(value, "__str__") and "URL" in str(type(value)):
            params[key] = str(value)
        else:
            params[key] = value

    # default=repr: retry_config may hold strategy/observer objects, which
    # aren't natively JSON-serializable; repr() is good enough for a cache key
    # (worst case: a fresh strategy instance misses the cache instead of
    # crashing get_http_async_client() outright).
    params_hash = hashlib.md5(
        json.dumps(params, sort_keys=True, default=repr).encode()
    ).hexdigest()

    cached_params = _client_params_var.get()
    client = _http_client_var.get()

    if client is not None and cached_params == params_hash:
        return client

    client = RetryableAsyncClient(
        timeout=timeout,
        retry_config=retry_config,
        **kwargs,
    )

    _http_client_var.set(client)
    _client_params_var.set(params_hash)

    return client


def get_http_async_client(
    timeout: int = 60,
    retry_config: Optional[RetryConfig] = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    return _get_http_client_context(timeout, retry_config, **kwargs)
