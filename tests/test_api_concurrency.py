import asyncio

import httpx

import src.main as main_module
from src.config import settings
from src.coordinator import FolioCoordinator


AUTH_HEADERS = {"Authorization": f"Bearer {settings.API_BEARER_TOKEN}"}
BASE_REQUEST = {
    "pfx_base64": "ignored-by-fake",
    "pfx_password": "ignored-by-fake",
    "rut_sender": "11111111-1",
    "document_type": 33,
    "amount": 1,
    "environment": "maullin",
}


class ConcurrentSiiClient:
    active = 0
    peak = 0
    constructions = 0

    @classmethod
    def reset(cls):
        cls.active = 0
        cls.peak = 0
        cls.constructions = 0

    def __init__(self, **_kwargs):
        type(self).constructions += 1
        self.logs = []
        self.unused_folios = 4
        self.max_authorized = 12
        self.last_range_start = 25
        self.last_range_end = 25
        self.availability_status = "known"
        self.final_submission_started = False

    async def request_folios(self, **_kwargs):
        type(self).active += 1
        type(self).peak = max(type(self).peak, type(self).active)
        try:
            await asyncio.sleep(0.03)
            return "<AUTORIZACION/>"
        finally:
            type(self).active -= 1

    def cleanup(self):
        pass


def test_real_app_handles_ten_companies_with_four_active_operations(monkeypatch):
    ConcurrentSiiClient.reset()
    monkeypatch.setattr(main_module, "SiiClient", ConcurrentSiiClient)
    monkeypatch.setattr(
        main_module,
        "folio_coordinator",
        FolioCoordinator(max_concurrent=4, queue_timeout=1),
    )

    async def scenario():
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as api:
            requests = []
            for company in range(10):
                body = dict(BASE_REQUEST)
                body["rut_company"] = f"7612345{company}-{company}"
                requests.append(
                    api.post(
                        "/api/v1/folios/request",
                        json=body,
                        headers=AUTH_HEADERS,
                    )
                )
            return await asyncio.gather(*requests)

    responses = asyncio.run(scenario())

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["success"] is True for response in responses)
    assert ConcurrentSiiClient.constructions == 10
    assert ConcurrentSiiClient.peak == 4


def test_real_app_serializes_requests_for_the_same_company(monkeypatch):
    ConcurrentSiiClient.reset()
    monkeypatch.setattr(main_module, "SiiClient", ConcurrentSiiClient)
    monkeypatch.setattr(
        main_module,
        "folio_coordinator",
        FolioCoordinator(max_concurrent=4, queue_timeout=1),
    )

    async def scenario():
        body = dict(BASE_REQUEST)
        body["rut_company"] = "76123456-0"
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as api:
            return await asyncio.gather(
                *(
                    api.post(
                        "/api/v1/folios/request",
                        json=body,
                        headers=AUTH_HEADERS,
                    )
                    for _ in range(5)
                )
            )

    responses = asyncio.run(scenario())

    assert all(response.json()["success"] is True for response in responses)
    assert ConcurrentSiiClient.peak == 1
