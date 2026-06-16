from typing import Generic, TypeVar, Any
from pydantic import BaseModel, Field
from typing import Dict, List


ItemT = TypeVar("ItemT")


class Page(BaseModel, Generic[ItemT]):
    items: List[ItemT] = Field(..., description="The items of the page")
    size: int = Field(..., ge=1, description="The requested page size")
    meta: Dict[str, Any] = Field(
        default_factory=dict, description="The meta data of the page"
    )


PageType = TypeVar("PageType", bound=Page[Any])
