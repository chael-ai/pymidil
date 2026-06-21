from starlette.datastructures import URL

from pymidil.jsonapi.document import Links, MetaType
from pymidil.web.pagination.mappers.page import PageMapper
from pymidil.web.pagination.mappers.resource import DomainT, SchemaT
from pymidil.web.pagination.strategies.offset.models import OffsetPage


class OffsetPageMapper(PageMapper[DomainT, SchemaT, OffsetPage[DomainT]]):
    def links(self, *, page: OffsetPage[DomainT], url: URL) -> Links:
        base = url.remove_query_params(["offset", "size"])
        next_offset = page.offset + page.size
        prev_offset = max(page.offset - page.size, 0)

        return Links(
            self=str(url),
            next=(
                str(base.include_query_params(offset=next_offset, size=page.size))
                if next_offset < page.total
                else None
            ),
            prev=(
                str(base.include_query_params(offset=prev_offset, size=page.size))
                if page.offset > 0
                else None
            ),
        )

    def meta(self, *, page: OffsetPage[DomainT]) -> MetaType:
        return {
            "total": page.total,
            "size": page.size,
            "offset": page.offset,
        }
