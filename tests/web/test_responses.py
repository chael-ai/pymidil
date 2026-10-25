"""JSONAPIResponse as MidilAPI's default response class."""

from typing import Optional

from fastapi.testclient import TestClient
from pydantic import BaseModel

from pymidil.jsonapi import Document, ResourceObject
from pymidil.jsonapi.document import JSONAPI_CONTENT_TYPE
from pymidil.web import MidilAPI


class Gym(BaseModel):
    name: str
    description: Optional[str] = None


def _app() -> MidilAPI:
    app = MidilAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/gyms/{gym_id}", response_model=Document[Gym])
    def gym(gym_id: str):
        return Document(
            data=ResourceObject(type="gyms", id=gym_id, attributes=Gym(name="Osu"))
        )

    @app.get("/gyms", response_model=Document[Gym])
    def gyms():
        return Document(
            data=[ResourceObject(type="gyms", id="1", attributes=Gym(name="Osu"))]
        )

    return app


def test_plain_dict_routes_work():
    r = TestClient(_app()).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["content-type"].startswith(JSONAPI_CONTENT_TYPE)


def test_document_routes_serialize_through_response_model():
    client = TestClient(_app())
    one = client.get("/gyms/g1")
    assert one.status_code == 200
    assert one.json()["data"]["attributes"]["name"] == "Osu"
    many = client.get("/gyms")
    assert many.status_code == 200
    assert many.json()["data"][0]["id"] == "1"
