from __future__ import annotations  # noqa: F401

from typing import (
    Any,
    Mapping,
    List,
    Optional,
    TypeVar,
    Union,
    TypeAlias,
    Generic,
    Annotated,
)
from pydantic import BaseModel, Field

from pymidil.jsonapi._mixins.serializers import (
    DocumentSerializerMixin,
    ErrorSerializerMixin,
    ResourceSerializerMixin,
)
from pymidil.jsonapi._mixins.validators import (
    ErrorSourceValidatorMixin,
)
from pymidil.jsonapi.config import (
    ForbidExtraFieldsModel,
    AllowExtraFieldsModel,
)
from typing_extensions import Doc
from pydantic import HttpUrl

# Type Aliases
MetaType: TypeAlias = Annotated[
    Optional[Mapping[str, Any]],
    Doc("A meta object containing non-standard information about the resource."),
]
LinkType: TypeAlias = Annotated[
    Optional[Union[str, "LinkObject"]],
    Doc("A link object that contains further details about this link."),
]
RelationshipType: TypeAlias = Annotated[
    Union[
        "ResourceIdentifierObject",
        List["ResourceIdentifierObject"],
        None,
    ],
    Doc("Resource linkage (to-one or to-many)."),
]
ErrorList: TypeAlias = Annotated[
    List["ErrorObject"],
    Doc("A list of error objects."),
]

LidStr = Annotated[
    str,
    Field(pattern=r"^[a-zA-Z0-9_-]+$"),
    Doc(
        "Optional client-generated ID (local ID) for correlation, not for persistence."
    ),
]

IDStr = Annotated[
    str,
    Field(pattern=r"^[a-zA-Z0-9_-]+$"),
    Doc("The resource identifier."),
]

TypeStr = Annotated[
    str,
    Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$"),
    Doc("The resource type."),
]

AttributesT = TypeVar("AttributesT", bound=Union[BaseModel, Mapping[str, Any]])

# Constants
JSONAPI_CONTENT_TYPE = "application/vnd.midil+json"
JSONAPI_ACCEPT = "application/vnd.midil+json"
JSONAPI_VERSION = "1.1"


# DRY helpers for common fields
class _MetaMixin(BaseModel):
    """Mixin for including a 'meta' member as per JSON:API specification.
    https://jsonapi.org/format/#document-meta
    """

    meta: MetaType = None


class _LinksMixin(BaseModel):
    """Mixin for including a 'links' member as per JSON:API specification.
    https://jsonapi.org/format/#document-links
    """

    links: Annotated[
        Optional["Links"],
        Doc("A links object that contains further details about this link."),
    ] = None


class _RelationshipsMixin(BaseModel):
    """Mixin for including a 'relationships' member as per JSON:API specification.
    https://jsonapi.org/format/#document-relationships
    """

    relationships: Annotated[
        Optional[Mapping[str, "RelationshipObject"]],
        Doc("A dictionary of relationship objects keyed by their names."),
    ] = None


class JSONAPIObject(AllowExtraFieldsModel, _MetaMixin):
    """
    Represents the 'jsonapi' object describing the server's implementation.

    Fields:
        version: The version of the JSON:API specification implemented.
        ext: An array of URIs for supported extensions.
        profile: An array of URIs for supported profiles.
        meta: Non-standard meta-information.

    https://jsonapi.org/format/#document-jsonapi-object
    """

    version: Annotated[
        str,
        Doc("The version of the JSON:API specification implemented."),
    ] = JSONAPI_VERSION
    ext: Annotated[
        Optional[List[str]],
        Doc("An array of URIs for supported extensions."),
    ] = None
    profile: Annotated[
        Optional[List[str]],
        Doc("An array of URIs for supported profiles."),
    ] = None


class ErrorSource(ForbidExtraFieldsModel, ErrorSourceValidatorMixin):
    """
    Represents the 'source' object in a JSON:API error.

    Fields:
        pointer: A JSON Pointer to the associated entity in the request document.
        parameter: A string indicating which URI query parameter caused the error.
        header: A string indicating which header caused the error.

    https://jsonapi.org/format/#:~:text=source,-:%20an%20object%20containing
    """

    pointer: Annotated[
        Optional[str],
        Field(pattern=r"^(/([^/~]|~0|~1)*)*$"),
        Doc(
            "A JSON Pointer [RFC6901] to the associated entity in the request document."
        ),
    ] = None
    parameter: Annotated[
        Optional[str],
        Doc("A string indicating which URI query parameter caused the error."),
    ] = None
    header: Annotated[
        Optional[str], Doc("A string indicating which HTTP header caused the error.")
    ] = None


class ErrorLinks(ForbidExtraFieldsModel):
    """
    A links object that contains further details about this error.
    """

    about: Annotated[
        Optional[HttpUrl], Doc("A link that leads to further details about this error.")
    ] = None
    type: Annotated[
        Optional[HttpUrl],
        Doc("A link to the type or classification of the error."),
    ] = None


class ErrorObject(AllowExtraFieldsModel, ErrorSerializerMixin, _MetaMixin):
    """
    Represents an error object as per JSON:API specification.

    Fields:
        id: A unique identifier for this particular occurrence of the problem.
        links: Links relevant to the error.
        status: The HTTP status code applicable to this problem, as a string.
        code: An application-specific error code.
        title: A short, human-readable summary of the problem.
        detail: A human-readable explanation specific to this occurrence of the problem.
        source: An object containing references to the source of the error.
        meta: Non-standard meta-information.

    https://jsonapi.org/format/#error-objects
    """

    id: Annotated[
        Optional[str],
        Doc("A unique identifier for this particular occurrence of the problem."),
    ] = None
    status: Annotated[
        str,
        Field(pattern=r"^[1-5][0-9]{2}$"),
        Doc("The HTTP status code applicable to this problem, as a string."),
    ]
    code: Annotated[
        Optional[str],
        Doc("An application-specific error code."),
    ] = None
    title: Annotated[
        Optional[str],
        Doc("A short, human-readable summary of the problem."),
    ] = None
    detail: Annotated[
        Optional[str],
        Doc("A human-readable explanation specific to this occurrence of the problem."),
    ] = None
    source: Annotated[
        Optional[ErrorSource],
        Doc("An object containing references to the source of the error."),
    ] = None
    links: Annotated[
        Optional[ErrorLinks],
        Doc("Links related to the error."),
    ] = None


class LinkObject(ForbidExtraFieldsModel, _MetaMixin):
    """
    Represents a link object as per JSON:API specification.

    Fields:
        href: The link's URL.
        rel: The link relation type.
        describedby: A link to further documentation.
        title: A human-readable title for the link.
        type: The media type of the link's target.
        hreflang: The language(s) of the linked resource.
        meta: Non-standard meta-information.

    https://jsonapi.org/format/#auto-id--link-objects
    """

    href: str
    rel: Optional[str] = None
    describedby: Optional[str] = None
    title: Optional[str] = None
    type: Optional[str] = None
    hreflang: Optional[Union[str, List[str]]] = None


class Links(ForbidExtraFieldsModel):
    """
    Represents a set of links as per JSON:API specification.

    Fields:
        self: The link that generated the current response document.
        related: A related resource link.
        first: The first page of data.
        last: The last page of data.
        prev: The previous page of data.
        next: The next page of data.

    https://jsonapi.org/format/#document-links
    """

    self: Annotated[
        Optional[LinkType],
        Doc("The link that generated the current response document."),
    ] = None
    related: Annotated[
        Optional[LinkType],
        Doc("A related resource link."),
    ] = None
    first: Annotated[
        Optional[LinkType],
        Doc("The first page of data."),
    ] = None
    last: Annotated[
        Optional[LinkType],
        Doc("The last page of data."),
    ] = None
    prev: Annotated[
        Optional[LinkType],
        Doc("The previous page of data."),
    ] = None
    next: Annotated[
        Optional[LinkType],
        Doc("The next page of data."),
    ] = None


class RelationshipObject(ForbidExtraFieldsModel, _LinksMixin, _MetaMixin):
    """
    Represents a relationship object as per JSON:API specification.

    Fields:
        data: Optional[Resource linkage (to-one or to-many)].
        links: Links related to the relationship.
        meta: Non-standard meta-information.

    https://jsonapi.org/format/#document-resource-object-relationships
    """

    data: Annotated[
        Optional[RelationshipType],
        Doc("Resource linkage (to-one or to-many)."),
    ] = None


class ResourceIdentifierObject(ForbidExtraFieldsModel, _MetaMixin):
    """
    Represents a resource identifier object as per JSON:API specification.

    Fields:
        type: The resource type.
        id: The resource identifier.
        meta: Non-standard meta-information.

    https://jsonapi.org/format/#document-resource-identifier-objects
    """

    id: IDStr
    type: TypeStr


class _ResourceBase(
    ForbidExtraFieldsModel,
    ResourceSerializerMixin,
    _LinksMixin,
    _MetaMixin,
    _RelationshipsMixin,
    Generic[AttributesT],
):
    """
    Base class for resource objects, parameterized by attributes.

    Fields:
        type: The resource type.
        attributes: The resource's attributes.
        links: Links related to the resource.
        meta: Non-standard meta-information.
        relationships: Relationships to other resources.
    """

    type: TypeStr
    attributes: Annotated[
        Optional[AttributesT],
        Doc("The resource's attributes."),
    ] = None


class ResourceObject(
    _ResourceBase[AttributesT],
    Generic[AttributesT],
):
    """
    Represents a full resource object as per JSON:API specification.

    https://jsonapi.org/format/#document-resource-objects

    Inherits:
        type, id, attributes, links, meta, relationships.

    Example:
        ```python

        class UserAttributes(BaseModel):
            name: str
            email: str

        user = ResourceObject(
            type="users",
            id="1",
            attributes=UserAttributes(name="John Doe", email="john.doe@example.com"),
        )
        user_dict = user.model_dump(mode="json")
        ```
    """

    id: IDStr


class Document(
    ForbidExtraFieldsModel,
    DocumentSerializerMixin,
    Generic[AttributesT],
):
    """
    Represents a top-level JSON:API document.
    https://jsonapi.org/format/#document-structure

    Fields:
        data: The primary data (resource object(s) or null).
        meta: Non-standard meta-information.
        jsonapi: Information about the JSON:API implementation.
        links: Links related to the primary data.
        included: Included related resource objects.

    Example:
        ```python
        class UserAttributes(BaseModel):
            name: str
            email: str

        UserDocument : TypeAlias = Document[UserAttributes]

        user = UserDocument(
            data=UserResource(
                type="users",
                id="1",
                attributes=UserAttributes(name="John Doe", email="john.doe@example.com"),
            ),
        )
        user_dict = user.model_dump()
        ```
    """

    data: Annotated[
        Union[ResourceObject[AttributesT], List[ResourceObject[AttributesT]]],
        Doc("The primary data (resource object(s) or null)."),
    ]
    meta: Annotated[
        Optional[MetaType],
        Doc("Non-standard meta-information."),
    ] = None
    jsonapi: Annotated[
        Optional[JSONAPIObject],
        Doc("Information about the JSON:API implementation."),
    ] = JSONAPIObject()
    links: Annotated[
        Optional[Links],
        Doc("Links related to the primary data."),
    ] = None
    included: Annotated[
        Optional[List[ResourceObject[BaseModel | Mapping[str, Any]]]],
        Doc("Included related resource objects."),
    ] = None


class ErrorDocument(ForbidExtraFieldsModel):
    """
    Represents a top-level JSON:API error document.

    https://jsonapi.org/format/#errors

    Fields:
        errors: A list of error objects.
        meta: Non-standard meta-information.
        jsonapi: Information about the JSON:API implementation.
        links: Links related to the error(s).

    Example:
        ```python
        error = ErrorDocument(
            errors=[
                ErrorObject(
                    id="1",
                    status="400",
                    code="invalid_request",
                    title="Invalid Request",
                    detail="The request is invalid.",
                    source=ErrorSource(
                        pointer="/data/attributes/name",
                        parameter="name",
                        header="X-Custom-Header",
                    ),
                    #... more fields as needed
                ),
            ],
        )
        error_dict = error.model_dump()
    """

    errors: Annotated[
        List[ErrorObject],
        Doc("A list of error objects."),
    ]
    meta: Annotated[
        Optional[MetaType],
        Doc("Non-standard meta-information."),
    ] = None
    jsonapi: Annotated[
        Optional[JSONAPIObject],
        Doc("Information about the JSON:API implementation."),
    ] = JSONAPIObject()
    links: Annotated[
        Optional[Links],
        Doc("Links related to the error(s)."),
    ] = None


class Header(AllowExtraFieldsModel):
    """
    Represents HTTP headers for JSON:API requests and responses.

    Fields:
        version: The JSON:API version (as 'jsonapi-version' header).
        accept: The Accept header value.
        content_type: The Content-Type header value.
    """

    version: Annotated[
        str,
        Doc("The JSON:API version (as 'jsonapi-version' header)."),
    ] = JSONAPI_VERSION
    accept: Annotated[
        str,
        Doc("The Accept header value."),
    ] = JSONAPI_ACCEPT


class PostDocument(
    ForbidExtraFieldsModel,
    DocumentSerializerMixin,
    Generic[AttributesT],
):
    """
    Represents a resource object for POST requests (resource creation).

    https://jsonapi.org/format/#crud-creating

    Inherits:
        type, attributes, links, meta, relationships, lid.

    Example:
        ```python
        class UserAttributes(BaseModel):
            name: str
            email: str

        user = PostResource(
            type="users",
            attributes=UserAttributes(name="John Doe", email="john.doe@example.com"),
        )
        user_dict = user.model_dump(mode="json")
    """

    data: Annotated[
        _ResourceBase[AttributesT],
        Doc("The resource object."),
    ]
    meta: Annotated[
        Optional[MetaType],
        Doc("Non-standard meta-information."),
    ] = None
    jsonapi: Annotated[
        Optional[JSONAPIObject],
        Doc("Information about the JSON:API implementation."),
    ] = JSONAPIObject()
    links: Annotated[
        Optional[Links],
        Doc("Links related to the primary data."),
    ] = None


class PatchDocument(
    ForbidExtraFieldsModel,
    DocumentSerializerMixin,
    Generic[AttributesT],
):
    """
    Represents a resource object for PATCH requests (resource update).

    https://jsonapi.org/format/#crud-updating

    Inherits:
        type, id, attributes, links, meta, relationships, lid.

    Example:
        ```python
        class UserAttributes(BaseModel):
            name: str
            email: str

        user = PatchDocument(
            type="users",
            id="1",
            attributes=UserAttributes(name="John Doe", email="john.doe@example.com"),
        )
        user_dict = user.model_dump(mode="json")
    """

    data: Annotated[
        ResourceObject[AttributesT],
        Doc("The resource object."),
    ]
    meta: Annotated[
        Optional[MetaType],
        Doc("Non-standard meta-information."),
    ] = None
    jsonapi: Annotated[
        Optional[JSONAPIObject],
        Doc("Information about the JSON:API implementation."),
    ] = JSONAPIObject()
    links: Annotated[
        Optional[Links],
        Doc("Links related to the primary data."),
    ] = None


class PatchMultiDocument(
    ForbidExtraFieldsModel,
    DocumentSerializerMixin,
    Generic[AttributesT],
):
    """
    Represents a list of resource objects for PATCH requests (resource update).
    """

    data: Annotated[
        List[ResourceObject[AttributesT]],
        Doc("The list of resource objects."),
    ]
    meta: Annotated[
        Optional[MetaType],
        Doc("Non-standard meta-information."),
    ] = None
    jsonapi: Annotated[
        Optional[JSONAPIObject],
        Doc("Information about the JSON:API implementation."),
    ] = JSONAPIObject()
    links: Annotated[
        Optional[Links],
        Doc("Links related to the primary data."),
    ] = None


class PostMultiDocument(
    ForbidExtraFieldsModel,
    DocumentSerializerMixin,
    Generic[AttributesT],
):
    """
    Represents a list of resource objects for POST requests (resource creation).
    """

    data: Annotated[
        List[ResourceObject[AttributesT]],
        Doc("The list of resource objects."),
    ]
    meta: Annotated[
        Optional[MetaType],
        Doc("Non-standard meta-information."),
    ] = None
    jsonapi: Annotated[
        Optional[JSONAPIObject],
        Doc("Information about the JSON:API implementation."),
    ] = JSONAPIObject()
    links: Annotated[
        Optional[Links],
        Doc("Links related to the primary data."),
    ] = None
