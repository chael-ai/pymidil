from typing import Any, Optional, Type
from fastapi import FastAPI
from pymidil.web.handlers import (
    ExceptionHandler,
    JSONAPIExceptionDispatcher,
    StatusCodeHandler,
    register_jsonapi_exception_handlers,
)
from pymidil.web.responses import JSONAPIResponse
from pymidil.exceptions import CursorError, InvalidCursorError, ExpiredCursorError


class MidilAPI(FastAPI):
    """
    FastAPI subclass with midil conventions pre-wired.

    Differences from plain FastAPI:
    - Default response class is JSONAPIResponse (sets JSON:API content-type)
    - JSON:API exception handlers registered automatically, including built-in
      domain mappings (AuthorizationError → 401, AuthenticationError → 401)

    Custom mappings:
        app = MidilAPI()
        app.map_exception(PaymentError, status_code=402, title="Payment Required")
        app.register_exception_handler(DatabaseError, my_db_handler)
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("default_response_class", JSONAPIResponse)
        super().__init__(**kwargs)
        self._dispatcher = register_jsonapi_exception_handlers(self)

    def map_exception(
        self,
        exc_type: Type[Exception],
        *,
        status_code: int,
        title: Optional[str] = None,
    ) -> None:
        """Map an exception type to a fixed HTTP status code."""
        self._dispatcher.register(exc_type, StatusCodeHandler(status_code, title))

    def register_exception_handler(
        self,
        exc_type: Type[Exception],
        handler: ExceptionHandler,
    ) -> None:
        """Register a custom handler for an exception type."""
        self._dispatcher.register(exc_type, handler)


__all__ = [
    "MidilAPI",
    "JSONAPIExceptionDispatcher",
    "register_jsonapi_exception_handlers",
    "JSONAPIResponse",
    "CursorError",
    "InvalidCursorError",
    "ExpiredCursorError",
]
