from abc import ABC, abstractmethod
from typing import Generic, List, Optional, TypeVar

from starlette.datastructures import URL

from pymidil.jsonapi.document import Document, Links, MetaType, ResourceObject
from pymidil.web.pagination.mappers.resource import (
    DomainT,
    ResourceMapper,
    SchemaT,
)
from pymidil.web.pagination.models import Page
from pydantic import BaseModel
from typing import Mapping, Any

PageT = TypeVar("PageT", bound=Page)


class PageMapper(ABC, Generic[DomainT, SchemaT, PageT]):
    def __init__(self, *, mapper: ResourceMapper[DomainT, SchemaT]) -> None:
        self._mapper = mapper

    @abstractmethod
    def links(self, *, page: PageT, url: URL) -> Links:
        ...

    def meta(self, *, page: PageT) -> MetaType:
        return None

    def included(
        self, *, page: PageT
    ) -> Optional[List[ResourceObject[BaseModel | Mapping[str, Any]]]]:
        return None

    def map(self, *, page: PageT, url: URL) -> Document[SchemaT]:
        return Document(
            data=[self._mapper.map(item) for item in page.items],
            links=self.links(page=page, url=url),
            meta=self.meta(page=page),
            included=self.included(page=page),
        )


class DocumentMapper(ABC, Generic[DomainT, SchemaT]):
    """Create a JSON API document for a single domain object."""

    def __init__(
        self,
        mapper: ResourceMapper[DomainT, SchemaT],
    ):
        self._mapper = mapper

    @abstractmethod
    def links(self, obj: DomainT, url: URL) -> Links:
        ...

    def meta(self, obj: DomainT) -> MetaType:
        ...

    def included(
        self, obj: DomainT
    ) -> Optional[List[ResourceObject[BaseModel | Mapping[str, Any]]]]:
        return None

    def map(self, obj: DomainT, url: URL) -> Document[SchemaT]:
        return Document(
            data=self._mapper.map(obj),
            meta=self.meta(obj),
            links=self.links(obj, url),
            included=self.included(obj),
        )
