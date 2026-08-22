import re
import unicodedata
from typing import Optional

from bs4 import BeautifulSoup


def _normalized_text(html_body: str) -> str:
    soup = BeautifulSoup(html_body, "lxml")
    for element in soup(["script", "style"]):
        element.decompose()
    text = " ".join(soup.get_text(" ").split()).lower()
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def _parse_integer(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def _input_integer(soup: BeautifulSoup, name: str) -> Optional[int]:
    field = soup.find(attrs={"name": re.compile(rf"^{re.escape(name)}$", re.IGNORECASE)})
    if field is None:
        return None
    return _parse_integer(field.get("value"))


def is_rejected_sii_page(html_body: str) -> bool:
    """Detects business rejections returned by the SII folio portal."""
    text = _normalized_text(html_body)
    rejection_markers = (
        "transaccion rechazada",
        "mesa de ayuda",
        "no ha sido posible completar su solicitud",
        "cantidad de documentos a timbrar debe ser menor o igual al maximo autorizado",
    )
    return any(marker in text for marker in rejection_markers)


def is_limit_exceeded_page(html_body: str) -> bool:
    text = _normalized_text(html_body)
    return (
        "cantidad de documentos a timbrar debe ser menor o igual al maximo autorizado"
        in text
    )


def is_success_receipt(html_body: str) -> bool:
    text = _normalized_text(html_body)
    return "ha autorizado" in text and "numeracion desde" in text


def parse_folio_info(html_body: str) -> dict:
    """Extracts availability and confirmed ranges without trusting preview ranges."""
    soup = BeautifulSoup(html_body, "lxml")
    text = _normalized_text(html_body)

    unused_folios = _input_integer(soup, "FOLIOS_DISP")
    max_authorized = _input_integer(soup, "MAX_AUTOR")
    requested_amount = _input_integer(soup, "CANT_DOCTOS")

    if unused_folios is None:
        match = re.search(r"(?:tiene\s+)?([0-9][0-9.]*)\s+folios\s+sin\s+utilizar", text)
        if match:
            unused_folios = _parse_integer(match.group(1))

    if max_authorized is None:
        patterns = (
            r"autorizado\s+solicitar\s+hasta\s+([0-9][0-9.]*)\s+folios",
            r"rango\s+maximo\s+autorizado[^0-9]*([0-9][0-9.]*)",
            r"maximo\s+autorizado[^0-9]*([0-9][0-9.]*)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                max_authorized = _parse_integer(match.group(1))
                break

    last_range_start = None
    last_range_end = None
    caf_range = re.search(
        r"<RNG\b[^>]*>[\s\S]*?<D\b[^>]*>\s*([0-9][0-9.]*)\s*</D>"
        r"[\s\S]*?<H\b[^>]*>\s*([0-9][0-9.]*)\s*</H>[\s\S]*?</RNG>",
        html_body,
        re.IGNORECASE,
    )
    if caf_range:
        last_range_start = _parse_integer(caf_range.group(1))
        last_range_end = _parse_integer(caf_range.group(2))
    else:
        success_range = re.search(
            r"ha\s+autorizado[\s\S]*?numeracion\s+desde\s+([0-9][0-9.]*)\s+hasta\s+([0-9][0-9.]*)",
            text,
        )
        if success_range:
            last_range_start = _parse_integer(success_range.group(1))
            last_range_end = _parse_integer(success_range.group(2))

    if max_authorized is None:
        availability_status = "unknown"
    elif unused_folios is None:
        availability_status = "partial"
    else:
        availability_status = "known"

    return {
        "unused_folios": unused_folios,
        "max_authorized": max_authorized,
        "requested_amount": requested_amount,
        "last_range_start": last_range_start,
        "last_range_end": last_range_end,
        "availability_status": availability_status,
    }
