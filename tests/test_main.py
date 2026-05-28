import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.config import settings
from src.sii import extract_login_reference, extract_support_id, is_blocked_sii_page

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


def test_extract_login_reference_from_raw_zeus_query():
    url = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoCertificado.html?https://palena.sii.cl/cvc_cgi/dte/of_solicita_folios"
    html = '<input type="hidden" name="referencia" id="referencia" value="">'

    assert extract_login_reference(url, html) == "https://palena.sii.cl/cvc_cgi/dte/of_solicita_folios"


def test_extract_login_reference_from_hidden_value():
    url = "https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoCertificado.html"
    html = '<input type="hidden" name="referencia" value="https%3A%2F%2Fmaullin.sii.cl%2Fcvc_cgi%2Fdte%2Fof_solicita_folios">'

    assert extract_login_reference(url, html) == "https://maullin.sii.cl/cvc_cgi/dte/of_solicita_folios"


def test_detects_transaccion_rechazada_and_extracts_id():
    html = """
    <html><body>
      <h1>Transaccion Rechazada</h1>
      <p>Para mas informacion favor comunicarse con Mesa de Ayuda indicando el ID: 2319082957939332096</p>
    </body></html>
    """

    assert is_blocked_sii_page(html) is True
    assert extract_support_id(html) == "2319082957939332096"
