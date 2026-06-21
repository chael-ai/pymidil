# MIDIL — Managed Interface for Data, Integration & Logic

**Backend infrastructure, as a Python SDK.**

MIDIL gives distributed backend systems a shared foundation — auth, eventing, HTTP, and API conventions — so teams spend less time rebuilding the same plumbing across every service.

---

## Install

```bash
pip install pymidil
```

MIDIL is modular. Install only what your service needs:

| Extra | Installs | Use when you need |
|---|---|---|
| `pymidil[auth]` | httpx, pyjwt | Cognito auth, JWT verification, HTTP client |
| `pymidil[web]` | fastapi, starlette, uvicorn | REST APIs, middleware, pagination |
| `pymidil[aws]` | aioboto3 | SQS consumers, EventBridge scheduling |
| `pymidil[redis]` | redis | Redis-backed event streaming |
| `pymidil[mongodb]` | pymongo | MongoDB cursor pagination |
| `pymidil[cli]` | click, rich, cookiecutter | Project scaffolding and service launcher |
| `pymidil[full]` | everything | — |

Requires Python 3.12+.

---

## What's included

### Auth

Outbound machine-to-machine auth and inbound JWT verification, with a pluggable interface so you're not locked into any one provider.

```python
from pymidil.auth.cognito import CognitoClientCredentialsAuthenticator, CognitoJWTAuthorizer

# Outbound — get a token for service-to-service calls
auth = CognitoClientCredentialsAuthenticator(
    client_id="...",
    client_secret="...",
    cognito_domain="your-domain.auth.region.amazoncognito.com",
)
headers = await auth.get_headers()  # {"Authorization": "Bearer ..."}

# Inbound — verify tokens from incoming requests
authorizer = CognitoJWTAuthorizer(user_pool_id="...", region="us-east-1")
claims = await authorizer.verify(token)
```

### Event system

A transport-agnostic event bus. Swap between SQS, Redis, or webhooks through config — your handler code stays the same.

```python
from pymidil.event.event_bus import EventBus
from pymidil.event.subscriber.base import EventSubscriber
from pymidil.event.message import Message

class OrderPlacedHandler(EventSubscriber):
    async def handle(self, event: Message) -> None:
        ...

    async def on_error(self, event: Message, error: Exception) -> None:
        ...

bus = EventBus()
bus.subscribe(OrderPlacedHandler())

await bus.publish({"order_id": "abc-123"})
await bus.start()
```

Transport is configured through your service settings — no code change needed to switch from Redis to SQS in production.

### HTTP client

An HTTPX-based client with built-in retry, exponential backoff, and first-class auth integration.

```python
from pymidil.http_client import HttpClient

client = HttpClient(auth_client=auth, base_url="https://api.example.com")
response = await client.send_request("POST", "/orders", data={...})
```

### FastAPI extensions

Drop-in middleware and dependencies for auth and JSON:API-compliant responses.

```python
from fastapi import FastAPI, Depends
from pymidil.midilapi.middleware.auth_middleware import CognitoAuthMiddleware
from pymidil.midilapi.dependencies.jsonapi import parse_sort, parse_include

app = FastAPI()
app.add_middleware(CognitoAuthMiddleware)

@app.get("/orders")
async def list_orders(sort=Depends(parse_sort), include=Depends(parse_include)):
    ...
```

### JSON:API

Build spec-compliant API documents without boilerplate.

```python
from pymidil.jsonapi import Document, ResourceObject

doc = Document(
    data=ResourceObject(
        id="1",
        type="orders",
        attributes={"status": "placed", "total": 99.00},
    )
)
```

---

## CLI

Scaffold and run services from the terminal.

```bash
midil init        # create a new service from a template
midil launch      # start the service with uvicorn
midil version     # show the installed SDK version
```

---

## Design principles

- **Async-first.** Every component is built for `asyncio` — no sync wrappers.
- **Opt-in by default.** Nothing is installed you didn't ask for.
- **Interface-driven.** Auth providers, event subscribers, retry strategies — all are abstract base classes you can swap or extend.
- **Convention over configuration.** Sane defaults, with escape hatches where it matters.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
Built at [midil.io](https://midil.io).
