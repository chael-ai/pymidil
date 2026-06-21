import pytest
from typing import Optional, Any, List, Dict
from pydantic import BaseModel, ValidationError

from pymidil.jsonapi._mixins.validators import (
    ResourceValidatorMixin,
    ErrorSourceValidatorMixin,
)


class ResourceModel(BaseModel, ResourceValidatorMixin):
    type: Optional[str] = None
    id: Optional[str] = None
    lid: Optional[str] = None


def test_resource_valid_with_type_and_id():
    m = ResourceModel(type="user", id="1")
    assert m.type == "user"


def test_resource_valid_with_type_and_lid():
    m = ResourceModel(type="post", lid="local-1")
    assert m.lid == "local-1"


def test_resource_invalid_missing_type():
    with pytest.raises(ValidationError) as exc:
        ResourceModel(id="1")
    assert "The 'type' field is required" in str(exc.value)


def test_resource_invalid_missing_id_and_lid():
    with pytest.raises(ValidationError) as exc:
        ResourceModel(type="user")
    assert "At least one of 'id' or 'lid'" in str(exc.value)


class ErrorSourceModel(BaseModel, ErrorSourceValidatorMixin):
    pointer: Optional[str] = None


def test_error_source_valid_pointer():
    model = ErrorSourceModel(pointer="/data/attributes/name")
    assert model.pointer.startswith("/")  # type: ignore


def test_error_source_valid_none():
    model = ErrorSourceModel(pointer=None)
    assert model.pointer is None


def test_error_source_invalid_pointer_format():
    with pytest.raises(ValidationError) as exc:
        ErrorSourceModel(pointer="invalid-pointer")
    assert "must be a string starting with '/'" in str(exc.value)


class JSONAPIErrorModel(BaseModel):
    title: Optional[str] = None
    detail: Optional[str] = None


def test_error_valid_with_title_only():
    model = JSONAPIErrorModel(title="Something went wrong")
    assert model.title is not None


def test_error_valid_with_detail_only():
    model = JSONAPIErrorModel(detail="A detailed explanation")
    assert model.detail is not None


class DocumentModel(BaseModel):
    data: Optional[Any] = None
    errors: Optional[List[Any]] = None
    meta: Optional[Dict[str, Any]] = None


def test_document_valid_with_data_only():
    model = DocumentModel(data={"type": "user", "id": "1"})
    assert model.data is not None


def test_document_valid_with_errors_only():
    model = DocumentModel(errors=[{"title": "Error occurred"}])
    assert isinstance(model.errors, list)


def test_document_valid_with_meta_only():
    model = DocumentModel(meta={"count": 1})
    assert model.meta["count"] == 1  # type: ignore
