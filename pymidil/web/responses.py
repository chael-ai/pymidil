from fastapi.responses import JSONResponse
from pymidil.jsonapi import Document, ErrorDocument
import typing
from pymidil.jsonapi.document import JSONAPI_CONTENT_TYPE
from starlette.background import BackgroundTask


class JSONAPIResponse(JSONResponse):
    def __init__(
        self,
        document: Document[typing.Any] | ErrorDocument,
        status_code: int = 200,
        headers: typing.Mapping[str, str] | None = None,
        media_type: str | None = JSONAPI_CONTENT_TYPE,
        background: BackgroundTask | None = None,
    ):
        super().__init__(
            content=document.model_dump(exclude_none=True),
            media_type=media_type,
            status_code=status_code,
            headers=headers,
            background=background,
        )
