from typing import List, Optional
from fastapi import Query
from pymidil.jsonapi.query import Sort, SortField, Include


def parse_sort(sort: Optional[List[str]] = Query(None, alias="sort")) -> Optional[Sort]:
    """
    Parses the 'sort' query parameter into a `Sort` object.

    Args:
        sort (Optional[List[str]]): List of sort fields from the query string,
            e.g., ["-created_at", "name"].

    Returns:
        Optional[Sort]: A `Sort` object if sort fields are provided; otherwise, `None`.

    Example:
        ```python
        parse_sort(["-created_at", "name"])
        # => Sort(fields=[
        #     SortField(field="created_at", direction=SortDirection.DESC),
        #     SortField(field="name", direction=SortDirection.ASC)
        # ])
        ```

    Usage:
        ```python
        @app.get("/items/")
        def list_items(sort: Optional[Sort] = Depends(parse_sort)):
            ...
        ```
    """
    if sort:
        return Sort(fields=[SortField.from_raw(s) for s in sort])
    return None


def parse_include(
    include: Optional[List[str]] = Query(None, alias="include")
) -> Optional[Include]:
    """
    Parses the 'include' query parameter into an `Include` object.

    Args:
        include (Optional[List[str]]): List of relationship paths to include,
            e.g., ["author", "comments.author"].

    Returns:
        Optional[Include]: An `Include` object if relationships are provided;
        otherwise, `None`.

    Example:
        ```python
        parse_include(["author", "comments.author"])
        # => Include(relationships=["author", "comments.author"])
        ```

    Usage:
        ```python
        @app.get("/items/")
        def list_items(include: Optional[Include] = Depends(parse_include)):
            ...
        ```
    """
    if include:
        return Include(relationships=include)
    return None
