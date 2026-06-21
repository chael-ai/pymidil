from enum import StrEnum


class PaginationDirection(StrEnum):
    NEXT = "next"
    PREV = "prev"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"
