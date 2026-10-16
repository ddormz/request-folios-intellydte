from urllib.parse import parse_qs

import httpx
import pytest

from src.sii import SiiClient


@pytest.fixture
def client():
    instance = object.__new__(SiiClient)
    instance.cert_file = instance.key_file = None
    return instance


@pytest.mark.parametrize("charset_source", ["header", "meta", "utf8"])
def test_form_serialization_preserves_page_charset(client, charset_source):
    headers = {"Content-Type": "text/html; charset=ISO-8859-1"} if charset_source == "header" else {}
    html = '<meta charset="ISO-8859-1">' if charset_source == "meta" else "<html></html>"
    response = httpx.Response(200, headers=headers, content=html.encode("ascii"))
    body = client._encode_form_data({"ACEPTAR": "Solicitar Numeración"}, response)
    expected = b"ACEPTAR=Solicitar+Numeraci%C3%B3n" if charset_source == "utf8" else b"ACEPTAR=Solicitar+Numeraci%F3n"
    assert body == expected


def test_form_omits_non_successful_controls_and_chooses_forward_button(client):
    form = client._parse_html_forms('''
      <form method="post">
        <input name="RUT_EMP" readonly value="76123456">
        <input name="EMPTY" value="">
        <input name="DISABLED" disabled value="private">
        <input name="NEW" type="button" value="Volver">
        <input name="RESET" type="reset" value="Limpiar">
        <input name="NO" type="checkbox" value="no">
        <input name="YES" type="checkbox" checked>
        <input name="RADIO" type="radio" value="a">
        <input name="RADIO" type="radio" value="b" checked>
        <input name="CANCEL" type="submit" value="Cancelar">
        <input name="ACEPTAR" type="submit" value="Solicitar Numeración">
        <textarea name="NOTE">Texto</textarea>
        <select name="COD_DOCTO">
          <option selected value="-1">NINGUNO</option>
          <option selected value="33">FACTURA</option>
        </select>
      </form>
    ''')[0]
    assert form["inputs"] == {
        "RUT_EMP": "76123456", "EMPTY": "", "YES": "on", "RADIO": "b",
        "ACEPTAR": "Solicitar Numeración", "NOTE": "Texto", "COD_DOCTO": "33",
    }
    response = httpx.Response(200, headers={"Content-Type": "text/html; charset=ISO-8859-1"})
    body = client._encode_form_data(form["inputs"], response)
    assert parse_qs(body.decode(), encoding="latin-1")["ACEPTAR"] == ["Solicitar Numeración"]


def test_legacy_meta_http_equiv_charset(client):
    response = httpx.Response(200, content=b'''
      <meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">
    ''')
    assert client._encode_form_data({"NOMUSU": "Muñoz"}, response) == b"NOMUSU=Mu%F1oz"


def test_scripted_document_selection_has_no_submitter(client):
    html = '<form><input name="COD_DOCTO" value="33"><button name="ACEPTAR">Continuar</button></form>'
    assert client._parse_html_forms(html)[0]["inputs"] == {"COD_DOCTO": "33", "ACEPTAR": ""}
    assert client._parse_html_forms(html, include_submit=False)[0]["inputs"] == {"COD_DOCTO": "33"}
