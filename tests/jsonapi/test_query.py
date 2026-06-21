import pytest
from pydantic import ValidationError

from pymidil.jsonapi.query import (
    PaginationParams,
    Sort,
    SortField,
    SortDirection,
    Include,
    QueryParams,
    Constants,
)


def test_pagination_defaults():
    params = PaginationParams()
    assert params.number == Constants.DEFAULT_PAGE_NUMBER
    assert params.size == Constants.DEFAULT_PAGE_SIZE


def test_pagination_valid_input():
    params = PaginationParams(number=2, size=50)
    assert params.number == 2
    assert params.size == 50


def test_pagination_invalid_page_number():
    with pytest.raises(ValidationError):
        PaginationParams(number=0)


def test_pagination_invalid_page_size():
    with pytest.raises(ValidationError):
        PaginationParams(size=Constants.MAX_PAGE_SIZE + 1)


def test_sort_field_from_raw():
    sort_field = SortField.from_raw("name")
    assert sort_field.field == "name"
    assert sort_field.direction == SortDirection.ASC

    sort_field = SortField.from_raw("-created_at")
    assert sort_field.field == "created_at"
    assert sort_field.direction == SortDirection.DESC


def test_sort_from_string():
    sort = Sort.from_string("name,-created_at,author.name")
    assert len(sort.fields) == 3
    assert sort.fields[0].field == "name"
    assert sort.fields[0].direction == SortDirection.ASC
    assert sort.fields[1].field == "created_at"
    assert sort.fields[1].direction == SortDirection.DESC
    assert sort.fields[2].field == "author.name"
    assert sort.fields[2].direction == SortDirection.ASC


def test_sort_from_empty_string():
    sort = Sort.from_string("")
    assert sort.fields == []


def test_include_valid_depth():
    include = Include(
        relationships=["author", "author.profile", "author.profile.avatar"]
    )
    assert include.relationships == [
        "author",
        "author.profile",
        "author.profile.avatar",
    ]


def test_include_exceeds_depth():
    with pytest.raises(ValidationError) as exc:
        Include(relationships=["author.profile.avatar.thumbnail"])
    assert "exceeds maximum depth" in str(exc.value)


def test_query_params_all_fields():
    qp = QueryParams(
        page=PaginationParams(number=2, size=10),
        sort=Sort.from_string("-created_at"),
        include=Include(relationships=["author.profile"]),
    )
    assert getattr(qp.page, "number") == 2
    assert getattr(qp.sort, "fields")[0].field == "created_at"
    assert getattr(qp.include, "relationships")[0] == "author.profile"


def test_query_params_partial():
    qp = QueryParams(sort=Sort.from_string("title"))
    assert getattr(getattr(qp, "sort"), "fields")[0].field == "title"
    assert qp.page is None
    assert qp.include is None
