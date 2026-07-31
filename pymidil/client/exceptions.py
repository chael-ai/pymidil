import httpx

from pymidil.exceptions import MidilError

__all__ = ["BaseClientError", "HTTPRequestError", "HTTPStatusError"]


class BaseClientError(MidilError):
    """Base exception for all pymidil.client errors."""

    ...


class HTTPRequestError(BaseClientError):
    """Raised when a request fails at the transport level (connection, timeout, DNS, etc.)."""

    ...


class HTTPStatusError(BaseClientError):
    """Raised when the server returns a non-2xx response."""

    def __init__(
        self, message: str, *, status_code: int, response: httpx.Response
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response
