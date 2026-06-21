from typing import Optional, Dict, Any, List
from pydantic import BaseModel

from pymidil.jsonapi._mixins.serializers import (
    ResourceSerializerMixin,
    ErrorSerializerMixin,
    DocumentSerializerMixin,
)


class DummyAttributes(BaseModel):
    title: str
    content: str


class DummyRelationship(BaseModel):
    data: Dict[str, str]


class ResourceStub(ResourceSerializerMixin, BaseModel):
    type: str
    id: Optional[str] = None
    lid: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    links: Optional[Dict[str, str]] = None
    attributes: Optional[DummyAttributes] = None
    relationships: Optional[Dict[str, DummyRelationship]] = None


class ErrorStub(ErrorSerializerMixin, BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    detail: Optional[str] = None
    code: Optional[str] = None
    source: Optional[Dict[str, str]] = None


class DocumentStub(DocumentSerializerMixin, BaseModel):
    data: Optional[Any] = None
    meta: Optional[Dict[str, str]] = None
    jsonapi: Optional[Dict[str, str]] = None
    links: Optional[Dict[str, str]] = None
    included: Optional[List[Any]] = None


def test_resource_to_jsonapi_basic():
    resource = ResourceStub(
        type="article",
        id="1",
        attributes=DummyAttributes(title="Hello", content="World"),
        links={"self": "/articles/1"},
        meta={"custom": "meta"},
    )

    jsonapi_dict = resource.to_jsonapi()
    assert jsonapi_dict["type"] == "article"
    assert jsonapi_dict["id"] == "1"
    assert jsonapi_dict["attributes"] == {"title": "Hello", "content": "World"}
    assert jsonapi_dict["links"] == {"self": "/articles/1"}
    assert jsonapi_dict["meta"] == {"custom": "meta"}


def test_resource_to_jsonapi_sparse_fieldset():
    resource = ResourceStub(
        type="article", attributes=DummyAttributes(title="Title only", content="Hidden")
    )
    result = resource.to_jsonapi(fields=["title"])
    assert result["attributes"] == {"title": "Title only"}
    assert "content" not in result["attributes"]


def test_resource_to_jsonapi_with_relationships():
    resource = ResourceStub(
        type="article",
        attributes=DummyAttributes(title="Post", content="Body"),
        relationships={"author": DummyRelationship(data={"type": "people", "id": "9"})},
    )
    output = resource.to_jsonapi()
    assert "relationships" in output
    assert output["relationships"]["author"]["data"]["id"] == "9"


def test_error_to_jsonapi():
    error = ErrorStub(
        id="123",
        title="Invalid",
        detail="Invalid request",
        code="400",
        source={"pointer": "/data"},
    )

    result = error.to_jsonapi()
    assert result["id"] == "123"
    assert result["title"] == "Invalid"
    assert result["code"] == "400"
    assert result["source"]["pointer"] == "/data"


def test_error_to_jsonapi_partial():
    error = ErrorStub(
        title="Partial",
    )
    result = error.to_jsonapi()
    assert result == {"title": "Partial"}


def test_document_to_jsonapi_with_single_resource():
    resource = ResourceStub(
        type="article",
        id="1",
        attributes=DummyAttributes(title="Doc", content="Content"),
    )

    doc = DocumentStub(data=resource)
    result = doc.to_jsonapi()
    assert result["data"]["id"] == "1"
    assert result["data"]["attributes"]["title"] == "Doc"


def test_document_to_jsonapi_with_multiple_resources():
    r1 = ResourceStub(type="x", id="1")
    r2 = ResourceStub(type="x", id="2")

    doc = DocumentStub(data=[r1, r2])
    result = doc.to_jsonapi()
    assert isinstance(result["data"], list)
    assert result["data"][0]["id"] == "1"


def test_document_to_jsonapi_with_meta_links_jsonapi():
    doc = DocumentStub(
        meta={"info": "meta"}, links={"self": "/doc"}, jsonapi={"version": "1.1"}
    )
    result = doc.to_jsonapi()
    assert result["meta"] == {"info": "meta"}
    assert result["links"] == {"self": "/doc"}
    assert result["jsonapi"] == {"version": "1.1"}


def test_document_to_jsonapi_with_included_resources():
    included_res = ResourceStub(type="related", id="42")
    doc = DocumentStub(data=None, included=[included_res])
    result = doc.to_jsonapi()
    assert result["included"][0]["id"] == "42"
