from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pymidil.jsonapi import Document, ErrorDocument
import typing
from pymidil.jsonapi.document import JSONAPI_CONTENT_TYPE
from starlette.background import BackgroundTask


class JSONAPIResponse(JSONResponse):
    """JSON response with the JSON:API media type.

    Accepts a ``Document``/``ErrorDocument`` (or any pydantic model), and also
    plain JSON content — which is what FastAPI passes when this is used as an
    app's ``default_response_class``, since it serializes route return values
    (via ``response_model``) before building the response.
    """

    def __init__(
        self,
        document: Document[typing.Any] | ErrorDocument | BaseModel | typing.Any = None,
        status_code: int = 200,
        headers: typing.Mapping[str, str] | None = None,
        media_type: str | None = JSONAPI_CONTENT_TYPE,
        background: BackgroundTask | None = None,
        content: typing.Any = None,
    ):
        payload = document if document is not None else content
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json", exclude_none=True)
        super().__init__(
            content=payload,
            media_type=media_type,
            status_code=status_code,
            headers=headers,
            background=background,
        )
