from typing import Any, Dict, List, Optional
from pydantic import model_serializer


class ResourceSerializerMixin:
    @model_serializer(mode="plain")
    def to_jsonapi(self, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        result["type"] = getattr(self, "type", None)

        self._add_core_fields(result)
        self._add_links(result)
        self._add_attributes(result, fields)
        self._add_relationships(result, fields)

        return {k: v for k, v in result.items() if v is not None}

    def _add_core_fields(self, result: Dict[str, Any]) -> None:
        for field in ("id", "lid", "meta"):
            value = getattr(self, field, None)
            if value is not None:
                result[field] = value

    def _add_links(self, result: Dict[str, Any]) -> None:
        links = getattr(self, "links", None)
        if links:
            result["links"] = (
                links.model_dump(exclude_none=True)
                if hasattr(links, "model_dump")
                else dict(links)
            )

    def _add_attributes(
        self, result: Dict[str, Any], fields: Optional[List[str]]
    ) -> None:
        attributes = getattr(self, "attributes", None)
        if attributes:
            if fields and hasattr(attributes, "model_dump"):
                result["attributes"] = attributes.model_dump(
                    include=set(fields), exclude_none=True
                )
            elif hasattr(attributes, "model_dump"):
                result["attributes"] = attributes.model_dump(exclude_none=True)
            else:
                raise ValueError("Attributes is not a BaseModel")

    def _add_relationships(
        self, result: Dict[str, Any], fields: Optional[List[str]]
    ) -> None:
        relationships = getattr(self, "relationships", None)
        if relationships:
            pruned = {}
            for key, rel in relationships.items():
                if fields and key not in fields:
                    continue
                pruned[key] = (
                    rel.model_dump(exclude_none=True)
                    if hasattr(rel, "model_dump")
                    else rel
                )
            if pruned:
                result["relationships"] = pruned


class ErrorSerializerMixin:
    @model_serializer(mode="plain")
    def to_jsonapi(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        for field in [
            "id",
            "links",
            "status",
            "code",
            "title",
            "detail",
            "source",
            "meta",
        ]:
            val = getattr(self, field, None)
            if val is not None:
                result[field] = val

        return result


class DocumentSerializerMixin:
    @model_serializer(mode="plain")
    def to_jsonapi(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        self._add_data(result)
        self._add_meta_jsonapi_links(result)
        self._add_included(result)
        return result

    def _add_data(self, result: Dict[str, Any]) -> None:
        data = getattr(self, "data", None)
        if data:
            result["data"] = (
                [d.to_jsonapi() for d in data]
                if isinstance(data, list)
                else data.to_jsonapi()
            )

    def _add_meta_jsonapi_links(self, result: Dict[str, Any]) -> None:
        for field in ["meta", "jsonapi", "links"]:
            val = getattr(self, field, None)
            if val:
                result[field] = (
                    val.model_dump(exclude_none=True)
                    if hasattr(val, "model_dump")
                    else val
                )

    def _add_included(self, result: Dict[str, Any]) -> None:
        included = getattr(self, "included", None)
        if included:
            result["included"] = [i.to_jsonapi() for i in included]
