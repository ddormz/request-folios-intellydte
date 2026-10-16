"""Run with python -m scripts.verify_sii_simulation while Postman's local simulation runs."""
import asyncio

import httpx

from src.sii import SiiClient


async def main():
    client = object.__new__(SiiClient)
    client.environment = "palena"
    client.base_url = "http://127.0.0.1:4900"
    client.logs = []
    client.max_authorized = client.unused_folios = None
    client.last_range_start = client.last_range_end = None
    client.availability_status = "unknown"
    client.final_submission_started = client.post_authorization_download_started = False
    client.cert_file = client.key_file = None
    client._create_client = lambda: httpx.AsyncClient(
        headers={"x-mock-slug": "sii"}, follow_redirects=True, timeout=5,
    )

    async def no_warmup(_http):
        pass

    client.warmup = no_warmup
    availability = await client.check_availability("11111111-1", "76123456-0", 33)
    assert availability["max_authorized"] == 13
    assert availability["unused_folios"] == 10
    xml = await client.request_folios("11111111-1", "76123456-0", 33, 1)
    assert "<AUTORIZACION>" in xml
    async with client._create_client() as transport:
        response = await transport.get(f"{client.base_url}/verification")
        counts = response.json()
    assert counts == {"refresh": 2, "confirmation": 1, "generation": 1, "rejected": 0}, counts
    print("PASS: availability and CAF request over local HTTP; Latin-1 payloads, no NEW, one generation.")


if __name__ == "__main__":
    asyncio.run(main())
