from pymidil.utils.base_models import SnakeCaseModel
from pydantic import Field
from pymidil.web.pagination.strategies.cursor.config import CursorConfig
from typing import Optional


class ServerConfig(SnakeCaseModel):
    host: str = Field(
        default="0.0.0.0", description="Host on which the application will run."
    )
    port: int = Field(
        default=8000, description="Port on which the application will run."
    )


class PaginationConfig(SnakeCaseModel, extra="forbid"):
    cursor: Optional[CursorConfig] = Field(
        default=None, description="Cursor pagination configuration."
    )


class MidilApiConfig(SnakeCaseModel, extra="allow"):
    server: ServerConfig = Field(
        default=ServerConfig(), description="Server configuration."
    )
    pagination: PaginationConfig = Field(
        default=PaginationConfig(), description="Pagination configuration."
    )
