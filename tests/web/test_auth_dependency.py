"""authorize_request: audience enforcement and authorizer reuse."""

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends
from fastapi.testclient import TestClient
from jwt import PyJWK

from pymidil.auth.config import CognitoAuthConfig
from pymidil.web import MidilAPI
from pymidil.web.dependencies.auth import authorize_request, get_cognito_authorizer

POOL, REGION, CLIENT = "us-east-1_test", "us-east-1", "app-client-id"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(aud: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "user-1",
            "iss": f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}",
            "aud": aud,
            "iat": now,
            "exp": now + 300,
        },
        KEY,
        algorithm="RS256",
        headers={"kid": "k1"},
    )


@pytest.fixture
def client():
    get_cognito_authorizer.cache_clear()
    settings = MagicMock()
    settings.get_auth.return_value = CognitoAuthConfig(
        user_pool_id=POOL, client_id=CLIENT, region=REGION
    )
    signing_key = PyJWK.from_dict(
        {
            **jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True),
            "alg": "RS256",
            "kid": "k1",
        }
    )
    app = MidilAPI()

    @app.get("/me")
    async def me(claims=Depends(authorize_request)):
        return {"sub": claims.sub}

    with patch(
        "pymidil.web.dependencies.auth.get_settings", return_value=settings
    ), patch(
        "jwt.PyJWKClient.get_signing_key_from_jwt", return_value=signing_key
    ) as jwks:
        # MidilAPI maps errors via its catch-all handler, which Starlette re-raises
        # after responding; assert on the response like a real client would.
        yield TestClient(app, raise_server_exceptions=False), jwks
    get_cognito_authorizer.cache_clear()


def test_accepts_tokens_for_the_configured_client(client):
    http, _ = client
    r = http.get("/me", headers={"Authorization": f"Bearer {_token(CLIENT)}"})
    assert r.status_code == 200
    assert r.json() == {"sub": "user-1"}


def test_rejects_tokens_issued_to_other_app_clients(client):
    http, _ = client
    r = http.get(
        "/me", headers={"Authorization": f"Bearer {_token('some-other-client')}"}
    )
    assert r.status_code == 401


def test_reuses_one_authorizer_across_requests(client):
    http, _ = client
    for _ in range(3):
        http.get("/me", headers={"Authorization": f"Bearer {_token(CLIENT)}"})
    assert get_cognito_authorizer.cache_info().currsize == 1
    assert get_cognito_authorizer.cache_info().hits == 2
