from http import HTTPStatus
from typing import Protocol, Any, Dict, Optional, Tuple, Type, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from loguru import logger

from pymidil.exceptions import MidilError, AuthorizationError, AuthenticationError
from pymidil.jsonapi.document import ErrorObject, ErrorDocument, ErrorSource
from pymidil.web.responses import JSONAPIResponse


class ExceptionHandler(Protocol):
    """Structural interface for all exception handlers."""

    async def handle(self, request: Request, exc: Exception) -> JSONAPIResponse:
        ...


class ErrorSourceBuilder:
    """Converts Pydantic validation error locations to JSON:API ErrorSource."""

    @staticmethod
    def build(loc: Tuple[Any, ...]) -> ErrorSource:
        if not loc:
            return ErrorSource()

        first = loc[0]
        if first == "body":
            pointer = "".join(f"/{ErrorSourceBuilder._escape(str(p))}" for p in loc[1:])
            return ErrorSource(pointer=pointer or "/")
        elif first == "query":
            param = loc[1] if len(loc) > 1 else None
            return ErrorSource(parameter=str(param) if param else None)
        elif first == "header":
            header = loc[1] if len(loc) > 1 else None
            return ErrorSource(header=str(header) if header else None)
        else:
            pointer = "".join(f"/{ErrorSourceBuilder._escape(str(p))}" for p in loc)
            return ErrorSource(pointer=pointer)

    @staticmethod
    def _escape(part: str) -> str:
        return part.replace("~", "~0").replace("/", "~1")


def _status_phrase(code: int) -> str:
    try:
        return HTTPStatus(code).phrase
    except ValueError:
        return "Error"


def _request_meta(request: Request) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "method": request.method,
        "path": request.url.path,
    }
    request_id = request.headers.get("x-request-id") or request.headers.get(
        "x-correlation-id"
    )
    if request_id:
        meta["request_id"] = request_id
    return meta


class HTTPExceptionHandler:
    """Maps Starlette HTTPException to a JSON:API error response."""

    async def handle(self, request: Request, exc: Exception) -> JSONAPIResponse:
        exc = cast(HTTPException, exc)
        title = (
            exc.detail
            if isinstance(exc.detail, str)
            else _status_phrase(exc.status_code)
        )
        error = ErrorObject(
            status=str(exc.status_code),
            title=title,
            detail=str(exc.detail),
            meta=_request_meta(request),
        )
        return JSONAPIResponse(
            status_code=exc.status_code,
            document=ErrorDocument(errors=[error]),
        )


class ValidationExceptionHandler:
    """Maps FastAPI RequestValidationError to JSON:API validation errors."""

    _DEFAULT_ERROR_TITLE = "Validation Error"
    _DEFAULT_ERROR_DETAIL = "Invalid input"

    def __init__(self, source_builder: ErrorSourceBuilder):
        self._source_builder = source_builder

    async def handle(self, request: Request, exc: Exception) -> JSONAPIResponse:
        exc = cast(RequestValidationError, exc)
        meta = _request_meta(request)
        errors = [
            ErrorObject(
                status=str(status.HTTP_422_UNPROCESSABLE_ENTITY),
                title=self._DEFAULT_ERROR_TITLE,
                detail=err.get("msg", self._DEFAULT_ERROR_DETAIL),
                source=self._source_builder.build(err.get("loc", ())),
                code=err.get("type"),
                meta=meta,
            )
            for err in exc.errors()
        ]
        return JSONAPIResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            document=ErrorDocument(errors=errors),
        )


class StatusCodeHandler:
    """
    Maps any exception type to a fixed HTTP status code.

    Used for built-in domain exception mappings and user-defined mappings via
    MidilAPI.map_exception().
    """

    def __init__(self, status_code: int, title: Optional[str] = None):
        self._status_code = status_code
        self._title = title or _status_phrase(status_code)

    async def handle(self, request: Request, exc: Exception) -> JSONAPIResponse:
        detail = str(exc) or self._title
        error = ErrorObject(
            status=str(self._status_code),
            title=self._title,
            detail=detail,
            meta=_request_meta(request),
        )
        return JSONAPIResponse(
            status_code=self._status_code,
            document=ErrorDocument(errors=[error]),
        )


class UnhandledExceptionHandler:
    """Catches any unhandled exception and returns a 500 response."""

    _DEFAULT_ERROR_TITLE = "Internal Server Error"
    _DEFAULT_ERROR_DETAIL = "An unexpected error occurred. Please try again later."

    async def handle(self, request: Request, exc: Exception) -> JSONAPIResponse:
        logger.error(
            f"Unhandled exception on {request.method} {request.url.path}",
            exc_info=exc,
        )
        error = ErrorObject(
            status=str(status.HTTP_500_INTERNAL_SERVER_ERROR),
            title=self._DEFAULT_ERROR_TITLE,
            detail=self._DEFAULT_ERROR_DETAIL,
            meta=_request_meta(request),
        )
        return JSONAPIResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            document=ErrorDocument(errors=[error]),
        )


class JSONAPIExceptionDispatcher:
    """
    Single callable registered with FastAPI that dispatches exceptions to the
    most specific registered handler using MRO resolution.

    Built-in mappings (registered in order of increasing specificity):
        Exception               → 500 UnhandledExceptionHandler  (catch-all, logs)
        MidilError              → 500 StatusCodeHandler
        AuthenticationError     → 401 StatusCodeHandler
        AuthorizationError      → 401 StatusCodeHandler
        RequestValidationError  → 422 ValidationExceptionHandler
        HTTPException           → passthrough status code

    More specific handlers win over less specific ones. Registering a handler
    for a subclass overrides the parent-class handler for that subclass only.
    """

    def __init__(self) -> None:
        self._handlers: Dict[Type[Exception], ExceptionHandler] = {}
        self._source_builder = ErrorSourceBuilder()
        self._generic = UnhandledExceptionHandler()

        # Register from least to most specific so MRO resolution is predictable
        self.register(Exception, self._generic)
        self.register(MidilError, StatusCodeHandler(500, "Internal Error"))
        self.register(
            AuthenticationError, StatusCodeHandler(401, "Authentication Failed")
        )
        self.register(AuthorizationError, StatusCodeHandler(401, "Unauthorized"))
        self.register(
            RequestValidationError, ValidationExceptionHandler(self._source_builder)
        )
        self.register(HTTPException, HTTPExceptionHandler())

    def register(self, exc_type: Type[Exception], handler: ExceptionHandler) -> None:
        """Register a handler for an exception type (and its subclasses)."""
        self._handlers[exc_type] = handler

    def map(
        self,
        exc_type: Type[Exception],
        *,
        status_code: int,
        title: Optional[str] = None,
    ) -> None:
        """Shortcut for mapping an exception type to an HTTP status code."""
        self.register(exc_type, StatusCodeHandler(status_code, title))

    def resolve(self, exc: Exception) -> ExceptionHandler:
        """Return the most specific registered handler for this exception."""
        for cls in type(exc).__mro__:
            handler = self._handlers.get(cls)
            if handler is not None:
                return handler
        return self._generic

    async def __call__(self, request: Request, exc: Exception) -> JSONAPIResponse:
        return await self.resolve(exc).handle(request, exc)


def register_jsonapi_exception_handlers(
    app: FastAPI,
    dispatcher: Optional[JSONAPIExceptionDispatcher] = None,
) -> JSONAPIExceptionDispatcher:
    """
    Wire up JSON:API exception handling on any FastAPI app.

    Creates a fresh dispatcher if one is not provided. Returns the dispatcher
    so callers can register additional handlers after the fact.

    Example:
        app = FastAPI()
        dispatcher = register_jsonapi_exception_handlers(app)
        dispatcher.map(PaymentError, status_code=402)
    """
    if dispatcher is None:
        dispatcher = JSONAPIExceptionDispatcher()
    app.add_exception_handler(HTTPException, dispatcher)
    app.add_exception_handler(RequestValidationError, dispatcher)
    app.add_exception_handler(Exception, dispatcher)
    return dispatcher
