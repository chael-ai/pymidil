# MidilAPI Documentation

## 1. Introduction

MidilAPI is a powerful and opinionated Python API framework built on top of FastAPI, designed to accelerate the development of web services that adhere to the [JSON:API specification](https://jsonapi.org/). It provides a structured approach to API development, integrating robust authentication, standardized query parameter parsing, and streamlined project scaffolding.

__Key Features:__

- __JSON:API Compliance__: Ensures consistent data exchange and API interactions by enforcing JSON:API standards.
- __FastAPI Foundation__: Leverages FastAPI's high performance, automatic OpenAPI documentation, and intuitive dependency injection system.
- __Integrated Authentication__: Provides out-of-the-box support for JWT-based authentication, with specific integration for AWS Cognito.
- __Standardized Query Parameters__: Simplifies the handling of common API patterns like sorting and including related resources, following JSON:API conventions.
- __CLI Scaffolding__: Enables rapid project setup and consistent project structures through the `midil` command-line interface.

## 2. Getting Started

To begin using MidilAPI, you'll typically start by scaffolding a new service using the `midil` CLI.

### 2.1. Prerequisites

- Python 3.8+
- `midil-kit` installed (usually via `pip install midil-kit`)

### 2.2. Creating a New MidilAPI Service

Use the `midil init service` command to create a new project:

```bash
midil init service my-awesome-api
```

This command will:

- Create a new directory `services/my-awesome-api`.
- Populate it with a basic FastAPI application structure, including `main.py`, `pyproject.toml`, and a `README.md`.
- Configure the project to use MidilAPI's features.

## 3. MidilAPI Module File Structure

The `midilapi` module itself, as part of the `midil-kit`, has a well-defined internal structure. This structure organizes its core components, dependencies, and middleware.

```javascript
midilapi/
├── __init__.py                 # MidilAPI application class (MidilAPI)
├── config.py                   # Configuration models (ServerConfig, MidilApiConfig)
├── exceptions.py               # Custom exceptions and handlers
├── responses.py                # JSONAPIResponse class
├── utils.py                    # Utility functions
├── dependencies/
│   ├── __init__.py
│   ├── auth.py                 # Authentication dependencies (authorize_request)
│   └── jsonapi.py              # JSON:API query parameter dependencies (parse_sort, parse_include)
└── middleware/
    ├── __init__.py
    └── auth_middleware.py      # Authentication middleware (BaseAuthMiddleware, CognitoAuthMiddleware)
```

__Explanation of Key Directories/Files within `midilapi/`:__

- __`__init__.py`__: This is the entry point for the `midilapi` module. It defines the `MidilAPI` class, which extends FastAPI to provide JSON:API specific enhancements, and exports key utilities like `register_jsonapi_exception_handlers` and `JSONAPIResponse`.

- __`config.py`__: Contains Pydantic models (`ServerConfig`, `MidilApiConfig`) for defining and validating configuration settings related to the API server, such as host and port.

- __`exceptions.py`__: Houses custom exception classes and functions for registering JSON:API compliant exception handlers, ensuring consistent error responses.

- __`responses.py`__: Defines the `JSONAPIResponse` class, which is a custom FastAPI response class to ensure all API responses adhere to the JSON:API specification.

- __`utils.py`__: A module for general utility functions that support the `midilapi` framework.

- __`dependencies/`__: This sub-directory contains FastAPI dependency functions that can be injected into your API routes.

  - `auth.py`: Provides `authorize_request`, a dependency for authenticating requests using JWT tokens and integrating with AWS Cognito.
  - `jsonapi.py`: Offers `parse_sort` and `parse_include` dependencies for parsing JSON:API standard query parameters for sorting and including related resources.

- __`middleware/`__: This sub-directory contains Starlette/FastAPI middleware classes for global request processing.
  - `auth_middleware.py`: Defines `BaseAuthMiddleware` and `CognitoAuthMiddleware` for handling authentication across all incoming requests, storing authentication context in the request state.

Understanding this internal structure is crucial for developers who wish to extend, customize, or deeply integrate with the `midilapi` framework.

## 4. Core Components and Features

### 4.1. The `MidilAPI` Application Class

The heart of your MidilAPI service is the `MidilAPI` class, which extends FastAPI.

__Location__: `midilapi/__init__.py`

```python
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from typing import Any, Dict
from midil.midilapi.exceptions import register_jsonapi_exception_handlers
from midil.midilapi.responses import JSONAPIResponse
from midil.midilapi.utils import _update_openapi_jsonapi_media_types


class MidilAPI(FastAPI):
    """
    FastAPI subclass that globally sets JSON:API media types in OpenAPI schema.
    """
    def openapi(self) -> Dict[str, Any]:
        # ... (implementation details) ...
        pass

# Exported utilities
__all__ = ["MidilAPI", "register_jsonapi_exception_handlers", "JSONAPIResponse"]
```

__Key Responsibilities__:

- __JSON:API OpenAPI Integration__: Automatically modifies the generated OpenAPI schema to include JSON:API media types (`application/vnd.api+json`), ensuring your API documentation reflects JSON:API standards.
- __Standardized Responses__: Provides `JSONAPIResponse` for consistent JSON:API formatted responses.
- __Exception Handling__: Integrates `register_jsonapi_exception_handlers` to convert common HTTP exceptions into JSON:API error objects.

__Basic Usage__:

```python
from midil.midilapi import MidilAPI, register_jsonapi_exception_handlers

app = MidilAPI(
    title="My Awesome API",
    version="1.0.0",
    description="A sample API built with MidilAPI."
)

# Register JSON:API compliant exception handlers
register_jsonapi_exception_handlers(app)

@app.get("/health", response_model=JSONAPIResponse)
async def health_check():
    return {"data": {"type": "status", "id": "1", "attributes": {"status": "ok"}}}
```

### 4.2. Configuration

MidilAPI uses Pydantic models for type-safe and validated configuration.

__Location__: `midilapi/config.py`

```python
from midil.utils.models import SnakeCaseModel
from pydantic import Field


class ServerConfig(SnakeCaseModel):
    host: str = Field(
        default="0.0.0.0", description="Host on which the application will run."
    )
    port: int = Field(
        default=8000, description="Port on which the application will run."
    )


class MidilApiConfig(SnakeCaseModel, extra="allow"):
    server: ServerConfig = Field(
        default=ServerConfig(), description="Server configuration."
    )
```

These configurations define how your MidilAPI application runs, including network settings. They are typically loaded at application startup, often managed by the `midil` CLI's `launch` command.

## 5. Authentication

MidilAPI provides robust authentication capabilities, with built-in support for JWT-based authentication and AWS Cognito.

### 5.1. Authentication Dependency (`authorize_request`)

The `authorize_request` dependency simplifies securing your API endpoints.

__Location__: `midilapi/dependencies/auth.py`

```python
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from midil.auth.cognito.jwt_authorizer import CognitoJWTAuthorizer
from midil.settings import get_auth_settings
from midil.auth.interfaces.models import AuthZTokenClaims
from loguru import logger

security = HTTPBearer(auto_error=True)

async def authorize_request(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthZTokenClaims:
    """
    Authenticates a request using a JWT token from the Authorization header.
    Verifies the token against AWS Cognito and returns decoded claims.
    """
    token = credentials.credentials
    cognito_settings = get_auth_settings("cognito")
    authorizer = CognitoJWTAuthorizer(
        user_pool_id=cognito_settings.user_pool_id,
        region=cognito_settings.region,
    )
    claims = await authorizer.verify(token)
    logger.info(f"Authenticated request for user {claims.sub}")
    return claims
```

__Usage__:

To protect an endpoint, simply add `authorize_request` as a dependency:

```python
from midil.midilapi import MidilAPI
from midil.midilapi.dependencies.auth import authorize_request
from midil.auth.interfaces.models import AuthZTokenClaims
from midil.midilapi.responses import JSONAPIResponse

app = MidilAPI()

@app.get("/me", response_model=JSONAPIResponse)
async def get_current_user(claims: AuthZTokenClaims = Depends(authorize_request)):
    """
    Returns information about the authenticated user.
    Requires a valid JWT in the Authorization header.
    """
    return {
        "data": {
            "type": "users",
            "id": claims.sub,
            "attributes": {
                "email": claims.email,
                "username": claims.username,
                # ... other claims
            }
        }
    }
```

### 5.2. Authentication Middleware (`CognitoAuthMiddleware`)

For global authentication handling, MidilAPI provides middleware.

__Location__: `midilapi/middleware/auth_middleware.py`

```python
# ... (imports and AuthContext class) ...

class BaseAuthMiddleware(BaseHTTPMiddleware):
    # ... (base implementation) ...
    async def authorizer(self, request: Request) -> AuthZProvider:
        raise NotImplementedError("Authorizer not implemented")

class CognitoAuthMiddleware(BaseAuthMiddleware):
    """
    Middleware to extract cognitoauth headers from request and store them in the request state.
    """
    async def authorizer(self, request: Request) -> AuthZProvider:
        cognito_settings = get_auth_settings("cognito")
        return CognitoJWTAuthorizer(
            user_pool_id=cognito_settings.user_pool_id, region=cognito_settings.region
        )
```

__Usage__:

Add `CognitoAuthMiddleware` to your `MidilAPI` application:

```python
from midil.midilapi import MidilAPI
from midil.midilapi.middleware.auth_middleware import CognitoAuthMiddleware
from starlette.requests import Request
from midil.midilapi.responses import JSONAPIResponse
from fastapi import Depends

app = MidilAPI()
app.add_middleware(CognitoAuthMiddleware)

# Helper to get auth context from request state
def get_auth_context(request: Request):
    return request.state.auth

@app.get("/protected-resource", response_model=JSONAPIResponse)
async def protected_resource(auth_context = Depends(get_auth_context)):
    """
    An endpoint protected by the CognitoAuthMiddleware.
    Accesses authenticated user claims from request.state.auth.
    """
    user_id = auth_context.claims.sub
    return {
        "data": {
            "type": "resources",
            "id": "some-id",
            "attributes": {"message": f"Hello, user {user_id}!"}
        }
    }
```

## 6. JSON:API Query Parameters

MidilAPI simplifies parsing common JSON:API query parameters like `sort` and `include`.

__Location__: `midilapi/dependencies/jsonapi.py`

```python
from typing import List, Optional
from fastapi import Query, Depends
from midil.jsonapi.query import Sort, SortField, Include


def parse_sort(sort: Optional[List[str]] = Query(None, alias="sort")) -> Optional[Sort]:
    """
    Parses the 'sort' query parameter into a `Sort` object.
    e.g., ?sort=-created_at,name
    """
    if sort:
        return Sort(fields=[SortField.from_raw(s) for s in sort])
    return None


def parse_include(
    include: Optional[List[str]] = Query(None, alias="include")
) -> Optional[Include]:
    """
    Parses the 'include' query parameter into an `Include` object.
    e.g., ?include=author,comments.author
    """
    if include:
        return Include(relationships=include)
    return None
```

__Usage__:

Integrate these functions as dependencies in your endpoint definitions:

```python
from midil.midilapi import MidilAPI
from midil.midilapi.dependencies.jsonapi import parse_sort, parse_include
from midil.jsonapi.query import Sort, Include
from midil.midilapi.responses import JSONAPIResponse
from fastapi import Depends

app = MidilAPI()

@app.get("/articles", response_model=JSONAPIResponse)
async def list_articles(
    sort: Optional[Sort] = Depends(parse_sort),
    include: Optional[Include] = Depends(parse_include)
):
    """
    Retrieves a list of articles, supporting JSON:API sorting and eager loading of relationships.
    Example: GET /articles?sort=-createdAt,title&include=author,comments.author
    """
    # In a real application, you would use 'sort' and 'include' to modify your database query
    response_data = {
        "type": "articles",
        "id": "1",
        "attributes": {"title": "Sample Article"},
        "relationships": {}
    }

    if sort:
        print(f"Sorting by: {sort.fields}")
        # Apply sorting logic here
    if include:
        print(f"Including relationships: {include.relationships}")
        # Apply eager loading logic here, e.g., fetch author and comments
        if "author" in include.relationships:
            response_data["relationships"]["author"] = {
                "data": {"type": "users", "id": "101"}
            }

    return {"data": response_data}
```

## 7. CLI Integration and Scaffolding

The `midil` CLI provides a `FastAPIServiceScaffolder` to quickly set up new MidilAPI projects.

__Location__: `cli/core/scaffolds/fastapi.py`

```python
from pathlib import Path
from typing import Dict, Any
from cookiecutter.main import cookiecutter
from rich.console import Console
from midil.cli.core.scaffolds.base import ProjectScaffolder

class FastAPIServiceScaffolder(ProjectScaffolder):
    """
    Concrete scaffolder using Cookiecutter for FastAPI services.
    """
    # ... (implementation details) ...

    def scaffold(self, name: str) -> None:
        # ... (cookiecutter invocation) ...
        pass
```

This scaffolder uses `cookiecutter` with the `cookiecutter-midil-project` template to generate a ready-to-use MidilAPI service, ensuring consistency and adherence to project best practices.
