import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.config import settings

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "folio-bridge-py"}


def test_unauthorized_probe_auth():
    response = client.post("/api/v1/folios/probe-auth", json={
        "pfx_base64": "invalid",
        "pfx_password": "test",
        "environment": "maullin"
    })
    # Missing Auth header
    assert response.status_code == 401


def test_invalid_token_probe_auth():
    response = client.post(
        "/api/v1/folios/probe-auth",
        json={
            "pfx_base64": "invalid",
            "pfx_password": "test",
            "environment": "maullin",
        },
        headers={"Authorization": "Bearer bad-token"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API Bearer Token"}


def test_valid_token_invalid_pfx_probe_auth():
    # If token is correct, but PFX is invalid, SiiClient will fail with SII_PFX_DECRYPTION_FAILED
    # and return success=False.
    response = client.post(
        "/api/v1/folios/probe-auth",
        json={
            "pfx_base64": "aW52YWxpZA==",  # Base64 for "invalid"
            "pfx_password": "test",
            "environment": "maullin",
        },
        headers={"Authorization": f"Bearer {settings.API_BEARER_TOKEN}"},
    )
    assert response.status_code == 200
    json_resp = response.json()
    assert json_resp["success"] is False
    assert "SII_PFX_DECRYPTION_FAILED" in json_resp["message"]
