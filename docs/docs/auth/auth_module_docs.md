---
slug: /auth
title: Authentication (Auth)
description: Centralized authentication and authorization integration for Midil services. Includes support for AWS Cognito, JWT verification, and pluggable authentication providers.
---

# Authentication (Auth)

## Overview
The `auth` module provides a unified authentication and authorization framework for all Midil services. It enables seamless integration with **AWS Cognito** for both **client credentials authentication** (for outbound requests) and **JWT-based authorization** (for inbound requests). This ensures that only verified users and services interact securely across the Midil ecosystem.

The module is designed for developers and service integrators who want to easily enable authentication without deep technical understanding of the underlying security mechanisms.

---

## How It Fits Into Midil
Authentication sits at the heart of Midil’s security layer. Every inbound request is verified through JWT tokens, while outbound service-to-service calls use secure client credentials to fetch access tokens. The `auth` module standardizes this process, making it simple and consistent across all microservices.

**Inbound flow:**
- Verifies incoming JWTs using AWS Cognito public keys.
- Ensures tokens are valid, signed, and scoped correctly.

**Outbound flow:**
- Generates and caches access tokens using Cognito’s client credentials grant flow.
- Automatically attaches tokens to outgoing HTTP requests.

---

## Key Components

| File / Submodule | Purpose |
|------------------|----------|
| `cognito/` | Handles Cognito authentication and JWT validation. |
| `interfaces/` | Defines abstract interfaces for authentication and authorization providers. |
| `config.py` | Stores configuration models for auth settings (client ID, secret, token URL, etc.). |
| `exceptions.py` | Custom errors raised during authentication or authorization failures. |
| `middlewares/` | FastAPI middleware for easy JWT verification in HTTP APIs. |
| `utils.py` | Helper utilities for token parsing and validation. |

---

## Quick Start

### Installation
Make sure the Midil SDK is installed in your project:

```bash
pip install midil-kit[auth]
```

### Example 1: Outbound Authentication (Client Credentials)
Authenticate your service when calling another Midil service.

```python
from midil.auth.cognito import CognitoClientCredentialsAuthenticator

auth_client = CognitoClientCredentialsAuthenticator(
    client_id="COGNITO_CLIENT_ID",              # *(inferred — verify)*
    client_secret="<REDACTED>",
    token_url="https://<your-domain>.auth.<region>.amazoncognito.com/oauth2/token",
)

token = await auth_client.get_token()
headers = await auth_client.get_headers()
# Use headers in your outbound HTTP request
```

### Example 2: Inbound Authentication (JWT Middleware)
Secure your FastAPI application with Cognito JWT verification.

```python
from fastapi import FastAPI
from midil.auth.cognito import CognitoJWTAuthorizer
from midil.midilapi.fastapi.middleware.auth_middleware import CognitoAuthMiddleware

app = FastAPI()

# Add the JWT verification middleware
app.add_middleware(CognitoAuthMiddleware, authorizer=CognitoJWTAuthorizer(...))
```

---

## Configuration
The `auth` module uses environment variables or configuration files to securely store credentials.

| Key | Description |
|-----|--------------|
| `COGNITO_CLIENT_ID` | The Cognito app client ID used for authentication. |
| `COGNITO_CLIENT_SECRET` | Secret key for the Cognito app client. |
| `COGNITO_DOMAIN` | Base domain for your Cognito user pool. |
| `COGNITO_REGION` | AWS region where your user pool is hosted. |
| `COGNITO_USER_POOL_ID` | Identifier for your user pool. |

> **Tip:** Use environment variables or a secrets manager—never store credentials directly in code or repositories.

---

## Error Handling
Common exceptions include:

- `AuthenticationError` – Raised when authentication fails (e.g., invalid credentials).
- `AuthorizationError` – Raised when a user lacks permission to access a resource.
- `CognitoAuthenticationError` – AWS Cognito token generation failed.
- `CognitoAuthorizationError` – Token verification failed (invalid signature or audience).

You can handle these errors gracefully in FastAPI:

```python
from midil.auth.exceptions import AuthenticationError
from fastapi import HTTPException

try:
    await auth_client.get_token()
except AuthenticationError:
    raise HTTPException(status_code=401, detail="Unauthorized")
```

---

## Security & Best Practices
- Always use HTTPS for token exchange.
- Use AWS Secrets Manager or similar for storing sensitive values.
- Validate token audience (`aud`) and issuer (`iss`).
- Rotate credentials regularly.
- Ensure system clocks are synchronized (for token expiry accuracy).

---

## Integrations & References
- **AWS Cognito Documentation:** [https://docs.aws.amazon.com/cognito](https://docs.aws.amazon.com/cognito)
- **FastAPI Middleware:** [https://fastapi.tiangolo.com/tutorial/middleware/](https://fastapi.tiangolo.com/tutorial/middleware/)
- **JWT Introduction:** [https://jwt.io/introduction](https://jwt.io/introduction)

---

## Troubleshooting
| Issue | Cause | Solution |
|--------|--------|-----------|
| 401 Unauthorized | Invalid token or expired credentials | Regenerate tokens or verify Cognito setup |
| 403 Forbidden | Token lacks required permissions | Check scopes or user group mappings |
| InvalidSignatureError | Wrong JWKS endpoint or mismatched keys | Ensure correct Cognito region and pool ID |

---

## Maintainers
**Midil Labs Security & Platform Team**  
Contact: [security@midil.io](mailto:security@midil.io)

---

## Appendix: Key Classes
| Class | Description |
|--------|--------------|
| `CognitoClientCredentialsAuthenticator` | Fetches access tokens for outbound API calls. |
| `CognitoJWTAuthorizer` | Validates incoming JWTs using Cognito’s public keys. |
| `AuthConfig` | Central configuration for authentication parameters. |
| `AuthenticationError`, `AuthorizationError` | Standard error classes used across the module. |

---
*Last updated: October 2025*

