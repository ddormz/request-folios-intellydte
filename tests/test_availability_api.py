from fastapi.testclient import TestClient
import pytest

import src.main as main_module
from src.config import settings


client = TestClient(main_module.app)
AUTH_HEADERS = {"Authorization": f"Bearer {settings.API_BEARER_TOKEN}"}
REQUEST_BODY = {
    "pfx_base64": "ignored-by-fake",
    "pfx_password": "ignored-by-fake",
    "rut_sender": "11111111-1",
    "rut_company": "76123456-0",
    "document_type": 33,
    "environment": "maullin",
}


class FakeAvailabilityClient:
    response = {}

    def __init__(self, **_kwargs):
        self.logs = []
        self.unused_folios = self.response.get("unused_folios")
        self.max_authorized = self.response.get("max_authorized")
        self.last_range_start = None
        self.last_range_end = None
        self.availability_status = self.response.get("availability_status", "unknown")

    async def check_availability(self, **_kwargs):
        return dict(self.response)

    def cleanup(self):
        pass


def test_unknown_availability_is_an_explicit_operational_error(monkeypatch):
    FakeAvailabilityClient.response = {
        "unused_folios": None,
        "max_authorized": None,
        "last_range_start": None,
        "last_range_end": None,
        "availability_status": "unknown",
    }
    monkeypatch.setattr(main_module, "SiiClient", FakeAvailabilityClient)

    response = client.post(
        "/api/v1/folios/check-availability",
        json=REQUEST_BODY,
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "SII_FOLIO_AVAILABILITY_UNAVAILABLE"
    assert response.json()["availability_status"] == "unknown"


@pytest.mark.parametrize("document_type", [39, 41])
def test_boleta_quantity_form_without_maximum_is_not_an_error(monkeypatch, document_type):
    FakeAvailabilityClient.response = {
        "unused_folios": None, "max_authorized": None, "availability_status": "unknown",
    }
    monkeypatch.setattr(main_module, "SiiClient", FakeAvailabilityClient)
    response = client.post("/api/v1/folios/check-availability",
        json={**REQUEST_BODY, "document_type": document_type}, headers=AUTH_HEADERS)
    assert response.json()["success"] is True
    assert response.json()["max_authorized"] is None
    assert response.json()["error_code"] is None


def test_partial_availability_succeeds_when_maximum_is_known(monkeypatch):
    FakeAvailabilityClient.response = {
        "unused_folios": None,
        "max_authorized": 12,
        "last_range_start": None,
        "last_range_end": None,
        "availability_status": "partial",
    }
    monkeypatch.setattr(main_module, "SiiClient", FakeAvailabilityClient)

    response = client.post(
        "/api/v1/folios/check-availability",
        json=REQUEST_BODY,
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["max_authorized"] == 12
    assert response.json()["availability_status"] == "partial"
