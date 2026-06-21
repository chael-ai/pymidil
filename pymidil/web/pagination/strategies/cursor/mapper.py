from starlette.datastructures import URL

from pymidil.jsonapi.document import Links, MetaType
from pymidil.web.pagination.strategies.cursor.page import CursorPage
from pymidil.web.pagination.mappers.page import PageMapper
from pymidil.web.pagination.mappers.resource import DomainT, SchemaT


class CursorPageMapper(PageMapper[DomainT, SchemaT, CursorPage[DomainT]]):
    def links(self, *, page: CursorPage[DomainT], url: URL) -> Links:
        next_link = None
        prev_link = None

        if page.next:
            next_link = str(
                url.include_query_params(
                    cursor=page.next,
                    size=page.size,
                )
            )

        if page.prev:
            prev_link = str(
                url.include_query_params(
                    cursor=page.prev,
                    size=page.size,
                )
            )

        return Links(self=str(url), next=next_link, prev=prev_link)

    def meta(self, *, page: CursorPage[DomainT]) -> MetaType:
        return {"size": page.size, **page.meta}
