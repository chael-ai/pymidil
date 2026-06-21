from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, Mapping, TypeVar

from pydantic import BaseModel

from pymidil.jsonapi.document import (
    Links,
    MetaType,
    RelationshipObject,
    ResourceObject,
    TypeStr,
)

DomainT = TypeVar(
    "DomainT",
    bound=BaseModel,
)

SchemaT = TypeVar(
    "SchemaT",
    bound=BaseModel | Mapping[str, Any],
)


class ResourceMapper(
    ABC,
    Generic[DomainT, SchemaT],
):
    @abstractmethod
    def type(self) -> TypeStr:
        ...

    @abstractmethod
    def id(
        self,
        obj: DomainT,
    ) -> str:
        ...

    @abstractmethod
    def attributes(
        self,
        obj: DomainT,
    ) -> SchemaT:
        ...

    def relationships(
        self,
        obj: DomainT,
    ) -> Mapping[str, RelationshipObject,] | None:
        return None

    def meta(
        self,
        obj: DomainT,
    ) -> MetaType:
        return None

    def links(
        self,
        obj: DomainT,
    ) -> Links | None:
        return None

    def map(
        self,
        obj: DomainT,
    ) -> ResourceObject[SchemaT]:
        return ResourceObject(
            type=self.type(),
            id=self.id(obj),
            attributes=self.attributes(
                obj,
            ),
            relationships=self.relationships(
                obj,
            ),
            meta=self.meta(obj),
            links=self.links(obj),
        )
