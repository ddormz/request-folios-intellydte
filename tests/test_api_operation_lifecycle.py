import asyncio
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

import src.main as main_module
from src.config import settings
from src.coordinator import FolioBusy


client = TestClient(main_module.app)
AUTH_HEADERS = {"Authorization": f"Bearer {settings.API_BEARER_TOKEN}"}
REQUEST_BODY = {
    "pfx_base64": "ignored-by-fake",
    "pfx_password": "ignored-by-fake",
    "rut_sender": "11111111-1",
    "rut_company": "76123456-0",
    "document_type": 33,
    "amount": 1,
    "environment": "maullin",
}


class AlwaysBusyCoordinator:
    @asynccontextmanager
    async def slot(self, _environment, _company):
        raise FolioBusy("busy")
        yield


class DelayedCoordinator:
    @asynccontextmanager
    async def slot(self, _environment, _company):
        await asyncio.sleep(0.07)
        yield


def test_busy_is_returned_before_creating_an_sii_session(monkeypatch):
    constructions = 0

    class MustNotBeConstructed:
        def __init__(self, **_kwargs):
            nonlocal constructions
            constructions += 1

    monkeypatch.setattr(main_module, "folio_coordinator", AlwaysBusyCoordinator())
    monkeypatch.setattr(main_module, "SiiClient", MustNotBeConstructed)

    response = client.post(
        "/api/v1/folios/request", json=REQUEST_BODY, headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "SII_FOLIO_BUSY"
    assert constructions == 0


def test_client_is_cleaned_after_operation_timeout(monkeypatch):
    instances = []

    class SlowClient:
        def __init__(self, **_kwargs):
            self.logs = []
            self.unused_folios = None
            self.max_authorized = None
            self.last_range_start = None
            self.last_range_end = None
            self.availability_status = "unknown"
            self.final_submission_started = False
            self.cleaned = False
            instances.append(self)

        async def request_folios(self, **_kwargs):
            await asyncio.sleep(1)

        def cleanup(self):
            self.cleaned = True

    monkeypatch.setattr(main_module, "SiiClient", SlowClient)
    monkeypatch.setattr(settings, "SII_OPERATION_TIMEOUT", 0.01, raising=False)

    response = client.post(
        "/api/v1/folios/request", json=REQUEST_BODY, headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "SII_FOLIO_UNEXPECTED_ERROR"
    assert instances[0].cleaned is True


def test_timeout_after_final_submission_has_unknown_outcome(monkeypatch):
    class SlowFinalClient:
        def __init__(self, **_kwargs):
            self.logs = []
            self.unused_folios = 4
            self.max_authorized = 12
            self.last_range_start = 25
            self.last_range_end = 25
            self.availability_status = "known"
            self.final_submission_started = False

        async def request_folios(self, **_kwargs):
            self.final_submission_started = True
            await asyncio.sleep(1)

        def cleanup(self):
            pass

    monkeypatch.setattr(main_module, "SiiClient", SlowFinalClient)
    monkeypatch.setattr(settings, "SII_OPERATION_TIMEOUT", 0.01, raising=False)

    response = client.post(
        "/api/v1/folios/request", json=REQUEST_BODY, headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "SII_FOLIO_OUTCOME_UNKNOWN"
    assert response.json()["last_range_start"] == 25


def test_operation_deadline_includes_time_spent_waiting_for_capacity(monkeypatch):
    class SlightlySlowClient:
        def __init__(self, **_kwargs):
            self.logs = []
            self.unused_folios = None
            self.max_authorized = None
            self.last_range_start = None
            self.last_range_end = None
            self.availability_status = "unknown"
            self.final_submission_started = False

        async def request_folios(self, **_kwargs):
            await asyncio.sleep(0.07)
            return "<AUTORIZACION/>"

        def cleanup(self):
            pass

    monkeypatch.setattr(main_module, "folio_coordinator", DelayedCoordinator())
    monkeypatch.setattr(main_module, "SiiClient", SlightlySlowClient)
    monkeypatch.setattr(settings, "SII_OPERATION_TIMEOUT", 0.1, raising=False)

    response = client.post(
        "/api/v1/folios/request", json=REQUEST_BODY, headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error_code"] == "SII_FOLIO_UNEXPECTED_ERROR"
