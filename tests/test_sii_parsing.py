from pathlib import Path

from src.sii import is_rejected_sii_page, parse_folio_info


FIXTURES = Path(__file__).parent / "fixtures" / "sii"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_reads_max_authorized_from_readonly_input():
    info = parse_folio_info(fixture("availability_partial.html"))

    assert info["max_authorized"] == 12
    assert info["unused_folios"] is None
    assert info["availability_status"] == "partial"


def test_ignores_zero_placeholder_when_page_exposes_a_positive_maximum():
    info = parse_folio_info(fixture("availability_placeholder_zero.html"))

    assert info["max_authorized"] == 12
    assert info["availability_status"] == "partial"


def test_zero_placeholder_alone_does_not_become_a_known_maximum():
    info = parse_folio_info('<input name="MAX_AUTOR" value="0">')

    assert info["max_authorized"] is None
    assert info["availability_status"] == "unknown"


def test_reads_confirmation_values_without_treating_preview_as_authorized_range():
    info = parse_folio_info(fixture("confirmation_over_limit.html"))

    assert info["max_authorized"] == 12
    assert info["unused_folios"] == 4
    assert info["requested_amount"] == 50
    assert info["last_range_start"] is None
    assert info["last_range_end"] is None
    assert info["availability_status"] == "known"


def test_detects_real_sii_limit_rejection():
    assert is_rejected_sii_page(fixture("limit_rejection.html")) is True


def test_reads_authorized_range_only_from_success_receipt():
    info = parse_folio_info(fixture("success_receipt.html"))

    assert info["last_range_start"] == 25
    assert info["last_range_end"] == 25


def test_reads_authorized_range_from_caf_xml():
    caf = """
    <AUTORIZACION>
      <CAF><DA><RNG><D>25</D><H>36</H></RNG></DA></CAF>
    </AUTORIZACION>
    """

    info = parse_folio_info(caf)

    assert info["last_range_start"] == 25
    assert info["last_range_end"] == 36
