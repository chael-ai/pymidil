# tests/test_jsonapi_models.py
import pytest
from pydantic import ValidationError, HttpUrl
from pymidil.jsonapi.document import (
    JSONAPIObject,
    ErrorSource,
    ErrorLinks,
    ErrorObject,
    LinkObject,
    Links,
    RelationshipObject,
    ResourceIdentifierObject,
    ResourceObject,
    Document,
    ErrorDocument,
    Header,
    PostDocument,
    PatchDocument,
    PatchMultiDocument,
    PostMultiDocument,
    _ResourceBase,
    JSONAPI_CONTENT_TYPE,
)
from pydantic import BaseModel


class UserAttributes(BaseModel):
    name: str
    email: str


def test_jsonapi_object_defaults():
    obj = JSONAPIObject()
    assert obj.version == "1.1"
    assert obj.ext is None
    assert obj.profile is None


def test_error_source_valid_and_invalid():
    valid = ErrorSource(pointer="/data/attributes/name")
    assert valid.pointer == "/data/attributes/name"

    with pytest.raises(ValidationError):
        ErrorSource(pointer="invalid pointer")  # regex fail


def test_error_links():
    links = ErrorLinks(
        about=HttpUrl("https://example.com/details"),
        type=HttpUrl("https://example.com/type"),
    )
    assert isinstance(links.about, HttpUrl)


def test_error_object_minimal():
    err = ErrorObject(status="400")
    assert err.status == "400"
    assert err.meta is None


def test_link_object_and_links_container():
    link_obj = LinkObject(href="https://example.com")
    assert link_obj.href == "https://example.com"

    links = Links(self=link_obj)
    assert isinstance(links.self, LinkObject)


def test_relationship_object_with_resource_identifier():
    rel = RelationshipObject(data=ResourceIdentifierObject(id="123", type="users"))
    assert rel.data.id == "123"  # type: ignore


def test_resource_object_and_document_serialization():
    user_res = ResourceObject[UserAttributes](
        id="1",
        type="users",
        attributes=UserAttributes(name="John", email="john@example.com"),
    )
    doc = Document[UserAttributes](data=user_res)
    dumped = doc.model_dump()
    assert dumped["data"]["type"] == "users"
    assert dumped["data"]["id"] == "1"


def test_error_document_with_multiple_errors():
    err_doc = ErrorDocument(
        errors=[
            ErrorObject(status="400", title="Invalid"),
            ErrorObject(status="404", title="Not Found"),
        ]
    )
    assert len(err_doc.errors) == 2
    assert err_doc.jsonapi.version == "1.1"  # type: ignore


def test_header_defaults_and_custom():
    h = Header()
    assert h.accept == JSONAPI_CONTENT_TYPE
    assert h.version == "1.1"

    h2 = Header(version="2.0")  # alias
    assert h2.version == "2.0"


def test_post_and_patch_documents():
    user_attrs = UserAttributes(name="Jane", email="jane@example.com")

    post_doc = PostDocument[UserAttributes](
        data=_ResourceBase[UserAttributes](
            type="users",
            attributes=user_attrs,
        )
    )
    assert post_doc.data.attributes.name == "Jane"  # type: ignore

    patch_doc = PatchDocument[UserAttributes](
        data=ResourceObject[UserAttributes](id="1", type="users", attributes=user_attrs)
    )
    assert patch_doc.data.id == "1"


def test_multi_documents():
    attrs = UserAttributes(name="John", email="john@example.com")
    res1 = ResourceObject[UserAttributes](id="1", type="users", attributes=attrs)
    res2 = ResourceObject[UserAttributes](id="2", type="users", attributes=attrs)

    patch_multi = PatchMultiDocument[UserAttributes](data=[res1, res2])
    assert len(patch_multi.data) == 2

    post_multi = PostMultiDocument[UserAttributes](data=[res1, res2])
    assert len(post_multi.data) == 2


def test_forbid_extra_fields():
    with pytest.raises(ValidationError):
        ResourceIdentifierObject(id="123", type="users", extra_field="oops")  # type: ignore


def test_allow_extra_fields():
    obj = JSONAPIObject(extra_field="ok")  # type: ignore
    assert obj.extra_field == "ok"  # type: ignore
