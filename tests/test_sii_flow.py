import asyncio
from pathlib import Path

import httpx
import pytest

from src.sii import SiiClient, SiiException


FIXTURES = Path(__file__).parent / "fixtures" / "sii"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def confirmation_redirect() -> httpx.Response:
    return httpx.Response(
        302, headers={"Location": "/cvc_cgi/dte/of_confirma_folio"}
    )


def make_client(handler) -> SiiClient:
    client = object.__new__(SiiClient)
    client.pfx_base64 = ""
    client.pfx_password = ""
    client.environment = "maullin"
    client.base_url = "https://maullin.sii.cl"
    client.logs = []
    client.unused_folios = None
    client.max_authorized = None
    client.last_range_start = None
    client.last_range_end = None
    client.availability_status = "unknown"
    client.final_submission_started = False
    client.cert_file = None
    client.key_file = None

    async def no_warmup(_client):
        return None

    client.warmup = no_warmup
    client._create_client = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    return client


def run_request(client: SiiClient, amount: int = 50) -> str:
    return asyncio.run(
        client.request_folios(
            rut_sender="11111111-1",
            rut_company="76123456-0",
            document_type=33,
            amount=amount,
        )
    )


def run_availability(client: SiiClient) -> dict:
    return asyncio.run(
        client.check_availability(
            rut_sender="11111111-1",
            rut_company="76123456-0",
            document_type=33,
        )
    )


def test_excess_amount_is_rejected_before_final_generation_post():
    final_posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/of_solicita_folios"):
            return confirmation_redirect()
        if request.method == "POST" and request.url.path.endswith("/of_genera_folio"):
            final_posts.append(str(request.url))
        return httpx.Response(200, text=fixture("confirmation_over_limit.html"))

    client = make_client(handler)

    with pytest.raises(SiiException) as exc_info:
        run_request(client)

    assert exc_info.value.code == "SII_FOLIO_AMOUNT_EXCEEDS_MAX_AUTHORIZED"
    assert client.max_authorized == 12
    assert client.unused_folios == 4
    assert final_posts == []


def test_unknown_form_is_not_submitted_as_fallback():
    submitted_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            submitted_paths.append(request.url.path)
        return httpx.Response(200, text=fixture("unknown_form.html"))

    client = make_client(handler)

    with pytest.raises(SiiException) as exc_info:
        run_request(client)

    assert exc_info.value.code == "SII_FOLIO_FORM_CHANGED"
    assert submitted_paths == []


def test_late_limit_rejection_uses_specific_error_code():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/of_solicita_folios"):
            return confirmation_redirect()
        if request.method == "POST":
            return httpx.Response(200, text=fixture("limit_rejection.html"))
        return httpx.Response(200, text=fixture("confirmation_unknown_limit.html"))

    client = make_client(handler)

    with pytest.raises(SiiException) as exc_info:
        run_request(client)

    assert exc_info.value.code == "SII_FOLIO_AMOUNT_EXCEEDS_MAX_AUTHORIZED"


def test_success_receipt_without_caf_is_reported_as_unknown_outcome(monkeypatch):
    async def no_delay(_seconds):
        return None

    monkeypatch.setattr("src.sii.asyncio.sleep", no_delay)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/of_solicita_folios"):
            return confirmation_redirect()
        if request.method == "POST":
            receipt_with_navigation_form = fixture("success_receipt.html") + """
            <form method="post" action="/cvc_cgi/dte/navigation_only">
              <input name="IGNORED" value="1">
            </form>
            """
            return httpx.Response(200, text=receipt_with_navigation_form)
        return httpx.Response(200, text=fixture("confirmation_unknown_limit.html"))

    client = make_client(handler)

    with pytest.raises(SiiException) as exc_info:
        run_request(client, amount=1)

    assert exc_info.value.code == "SII_FOLIO_OUTCOME_UNKNOWN"
    assert client.last_range_start == 25
    assert client.last_range_end == 25


@pytest.mark.parametrize(
    "confirmation_fixture,amount",
    [
        ("confirmation_over_limit.html", 10),
        ("confirmation_unknown_limit.html", 1),
    ],
)
def test_allowed_or_unknown_limit_continues_to_caf(confirmation_fixture, amount):
    caf = "<AUTORIZACION><CAF><DA><TD>33</TD><RNG><D>25</D><H>36</H></RNG></DA></CAF></AUTORIZACION>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/of_solicita_folios"):
            return confirmation_redirect()
        if request.method == "POST":
            return httpx.Response(200, text=caf)
        return httpx.Response(200, text=fixture(confirmation_fixture))

    client = make_client(handler)

    assert run_request(client, amount=amount) == caf
    assert client.last_range_start == 25
    assert client.last_range_end == 36


def test_trace_and_business_rejection_do_not_expose_identity_data():
    sensitive_html = """
    <html><body>
      <h1>Transaccion Rechazada</h1>
      <p>Contribuyente PERSONA DEMO, RUT 76123456-0.</p>
    </body></html>
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sensitive_html)

    client = make_client(handler)

    with pytest.raises(SiiException) as exc_info:
        run_request(client)

    exposed = " ".join(client.logs) + " " + exc_info.value.message
    assert exc_info.value.code == "SII_FOLIO_REQUEST_REJECTED"
    assert "76123456-0" not in exposed
    assert "11111111-1" not in exposed
    assert "PERSONA DEMO" not in exposed


def test_unknown_page_without_forms_is_redacted_and_reported_as_changed():
    sensitive_html = "<html><body>SESSION-SECRET PERSONA DEMO</body></html>"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sensitive_html)

    client = make_client(handler)

    with pytest.raises(SiiException) as exc_info:
        run_request(client)

    exposed = " ".join(client.logs) + " " + exc_info.value.message
    assert exc_info.value.code == "SII_FOLIO_FORM_CHANGED"
    assert "SESSION-SECRET" not in exposed
    assert "PERSONA DEMO" not in exposed


def test_availability_status_is_derived_from_values_accumulated_across_steps():
    first_step = """
    <html><body>
      <input name="MAX_AUTOR" value="12">
      <form method="post" action="/cvc_cgi/dte/of_solicita_folios_dcto">
        <input name="RUT_EMP" value="">
      </form>
    </body></html>
    """
    quantity_step = """
    <html><body>
      <form method="post" action="/cvc_cgi/dte/of_confirma_folio">
        <input name="CANT_DOCTOS" value="">
      </form>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=quantity_step)
        return httpx.Response(200, text=first_step)

    client = make_client(handler)

    info = run_availability(client)

    assert info["max_authorized"] == 12
    assert info["unused_folios"] is None
    assert info["availability_status"] == "partial"


def test_later_zero_placeholder_does_not_overwrite_a_known_positive_maximum():
    client = make_client(lambda _request: httpx.Response(200, text=""))

    client._update_folio_info(
        '<input name="MAX_AUTOR" value="11">'
        '<input name="FOLIOS_DISP" value="5">'
    )
    client._update_folio_info(
        fixture("availability_zero_followed_by_unrelated_number.html")
    )

    assert client.max_authorized == 11
    assert client.unused_folios == 5
    assert client.availability_status == "known"


def test_trace_does_not_expose_query_parameters_from_sii_urls():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/of_solicita_folios"):
            return httpx.Response(
                302,
                headers={
                    "Location": "/cvc_cgi/dte/of_confirma_folio?SESSION_SECRET=abc123"
                },
            )
        return httpx.Response(200, text=fixture("confirmation_over_limit.html"))

    client = make_client(handler)

    with pytest.raises(SiiException):
        run_request(client)

    assert "SESSION_SECRET" not in " ".join(client.logs)
    assert "abc123" not in " ".join(client.logs)


def test_final_generation_is_never_retried_when_response_is_ambiguous(monkeypatch):
    async def no_delay(_seconds):
        return None

    monkeypatch.setattr("src.sii.asyncio.sleep", no_delay)
    final_posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal final_posts
        if request.url.path.endswith("/of_solicita_folios"):
            return confirmation_redirect()
        if request.method == "POST" and request.url.path.endswith(
            "/of_genera_folio"
        ):
            final_posts += 1
        return httpx.Response(200, text=fixture("confirmation_unknown_limit.html"))

    client = make_client(handler)

    with pytest.raises(SiiException) as exc_info:
        run_request(client, amount=1)

    assert exc_info.value.code == "SII_FOLIO_OUTCOME_UNKNOWN"
    assert final_posts == 1
