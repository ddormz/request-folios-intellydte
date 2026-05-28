import asyncio
import base64
import os
import random
import re
import ssl
import tempfile
import urllib.parse
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

# SII Constants matching Node client
FOLIO_BASE_URL = {
    "maullin": "https://maullin.sii.cl",
    "palena": "https://palena.sii.cl",
}
FOLIO_PATH = "/cvc_cgi/dte/of_solicita_folios"
CERT_AUTH_URL = "https://herculesr.sii.cl/cgi_AUT2000/CAutInicio.cgi"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Form field candidate names
DOCUMENT_TYPE_FIELD_CANDIDATES = [
    "COD_DOCTO", "cod_docto", "TIPO_DOCTO", "tipo_docto", "TIPO_DOC", "tipo_doc", "tipoDte", "tipoDocumento", "TpoDoc", "TD"
]
QUANTITY_FIELD_CANDIDATES = [
    "CANT_DOCTOS", "cant_doctos", "CANTIDAD", "cantidad", "NRO_DOCTOS", "nro_doctos", "NRO_FOLIOS", "nro_folios", "CANT_DOCS", "CANT", "cant"
]
RUT_EMP_FIELD_CANDIDATES = ["RUT_EMP", "RUT_EMPRESA", "RUTEM", "RUT_EMPRESA_SEL"]
DV_EMP_FIELD_CANDIDATES = ["DV_EMP", "DV_EMPRESA", "DVEM", "DV_EMPRESA_SEL"]

# Form action paths
MAULLIN_COMPANY_FORM_PATH = "/cvc_cgi/dte/of_solicita_folios_dcto"
MAULLIN_DOCUMENT_TYPE_FORM_PATH = "/cvc_cgi/dte/of_solicita_folios_cant"
MAULLIN_GENERATE_FOLIOS_FORM_PATH = "/cvc_cgi/dte/of_genera_folios"

MAULLIN_CONFIRM_FOLIOS_FORM_PATHS = [
    "/cvc_cgi/dte/of_confirma_folio",
    "/cvc_cgi/dte/of_confirma_folios",
]
MAULLIN_DOWNLOAD_FOLIOS_FORM_PATHS = [
    "/cvc_cgi/dte/of_genera_folio",
    "/cvc_cgi/dte/of_genera_folios",
    "/cvc_cgi/dte/of_descarga_caf",
    "/cvc_cgi/dte/of_descarga_folio",
    "/cvc_cgi/dte/of_descarga_folios",
]


class SiiException(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def clean_rut(rut: str) -> Tuple[str, str]:
    """Cleans a RUT and splits it into body and check digit (DV)."""
    cleaned = re.sub(r"[^0-9kK]", "", rut)
    if len(cleaned) < 2:
        raise ValueError(f"Invalid RUT format: {rut}")
    body = cleaned[:-1]
    dv = cleaned[-1].upper()
    return body, dv


def extract_caf_xml(html_body: str) -> Optional[str]:
    """Extracts the AUTORIZACION XML string from an HTML body."""
    # Decode HTML entities if any
    decoded = urllib.parse.unquote(html_body)
    # Match the AUTORIZACION XML block
    match = re.search(
        r"(?:<\?xml[^>]*>\s*)?<AUTORIZACION\b[\s\S]*?<\/AUTORIZACION>",
        decoded,
        re.IGNORECASE,
    )
    if match:
        return match.group(0).strip()
    return None


def is_blocked_sii_page(html_body: str) -> bool:
    """Checks if the page is a WAF block or rejection page."""
    # Look for Imperva or classic WAF block signatures
    if "requested URL was rejected" in html_body or "Support ID" in html_body:
        return True
    lowered = html_body.lower()
    if "transaccion rechazada" in lowered or "mesa de ayuda" in lowered:
        return True
    if "imperva" in html_body.lower() or "incapsula" in html_body.lower():
        return True
    return False


def extract_support_id(html_body: str) -> Optional[str]:
    """Extracts Imperva Support ID if present."""
    match = re.search(r"Support ID:\s*([0-9a-zA-Z\-]+)", html_body, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    match = re.search(r"(?:ID|supportId)\s*[:=]\s*([0-9]{6,})", html_body, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return None


def extract_login_reference(current_url: str, html_body: str, fallback: Optional[str] = None) -> str:
    """Extracts the AUT2000 reference from Zeus query string, hidden inputs, or inline JS."""
    parsed_url = urllib.parse.urlparse(str(current_url))
    raw_query = parsed_url.query or ""

    if raw_query.startswith("http"):
        return urllib.parse.unquote(raw_query)

    query_params = urllib.parse.parse_qs(raw_query)
    reference = query_params.get("referencia", [""])[0].strip()
    if reference:
        return urllib.parse.unquote(reference)

    patterns = [
        r'name=["\']referencia["\']\s+[^>]*value=["\']([^"\']+)["\']',
        r'value=["\']([^"\']+)["\']\s+[^>]*name=["\']referencia["\']',
        r'referencia\s*=\s*["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_body, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return urllib.parse.unquote(candidate)

    if fallback:
        return fallback

    raise SiiException(
        "SII_FOLIO_PORTAL_AUTH_LOOP",
        "Could not extract 'referencia' parameter from login page.",
    )


def classify_certificate_auth_failure(html_body: str) -> str:
    """Classifies certificate authentication error based on HTML content."""
    text = html_body.lower()
    if any(
        x in text
        for x in [
            "expirad",
            "vencid",
            "revocad",
            "caducad",
            "no vigente",
            "no autorizad",
            "invalido",
            "inválido",
            "rechazad",
            "denegad",
            "rut distint",
            "distinto rut",
            "contribuyente",
        ]
    ):
        return "SII_FOLIO_CERTIFICATE_AUTH_FAILED"
    return "SII_FOLIO_PORTAL_AUTH_LOOP"


def is_certificate_auth_page(url: str, html_body: str) -> bool:
    """Checks if the current page is the certificate authentication page."""
    url_str = str(url)
    if "cgi_AUT2000/CAutInicio.cgi" in url_str:
        return True
    
    text_lower = html_body.lower()
    # Check if we have the specific form tag action for CAutInicio
    if "cautinicio.cgi" in text_lower:
        return True
        
    # Check if it has the specific digital certificate authentication keywords
    has_auth_kw = any(x in text_lower for x in ["ingresocertificado", "certificado digital", "autenticacion", "autenticación"])
    
    # Must have the reference input element and authentication keywords
    has_ref_input = ('name="referencia"' in html_body or 
                     'name=\'referencia\'' in html_body or 
                     'type="hidden" name="referencia"' in text_lower or
                     'type=\'hidden\' name=\'referencia\'' in text_lower)
                     
    if has_auth_kw and has_ref_input:
        return True
        
    return False


class SiiClient:
    def __init__(
        self,
        pfx_base64: str,
        pfx_password: str,
        environment: str = "maullin",
    ):
        self.pfx_base64 = pfx_base64
        self.pfx_password = pfx_password
        self.environment = environment
        self.base_url = FOLIO_BASE_URL.get(environment, FOLIO_BASE_URL["maullin"])
        self.logs = []

        # PFX Cert and Key extraction in memory, writing to NamedTemporaryFiles for ssl context
        self.cert_file = None
        self.key_file = None
        self._extract_credentials()

    def log(self, msg: str):
        print(msg)
        self.logs.append(msg)

    def _extract_credentials(self):
        try:
            pfx_data = base64.b64decode(self.pfx_base64)
            # cryptography PKCS12 load
            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                pfx_data, self.pfx_password.encode("utf-8")
            )
            if not private_key or not certificate:
                raise ValueError("Could not extract private key or certificate from PFX")

            pem_key = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
            pem_cert = certificate.public_bytes(serialization.Encoding.PEM)

            # Write to temporary files
            # delete=False is used because Windows has file-sharing locks that prevent reading open temp files
            self.cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".crt")
            self.key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".key")

            self.cert_file.write(pem_cert)
            self.key_file.write(pem_key)

            self.cert_file.close()
            self.key_file.close()

            self.cert_path = self.cert_file.name
            self.key_path = self.key_file.name

        except Exception as e:
            self.cleanup()
            raise SiiException(
                "SII_PFX_DECRYPTION_FAILED",
                f"Failed to decrypt or parse digital certificate: {str(e)}",
            )

    def cleanup(self):
        """Cleans up temporary certificate files."""
        if self.cert_file and os.path.exists(self.cert_file.name):
            try:
                os.unlink(self.cert_file.name)
            except Exception:
                pass
        if self.key_file and os.path.exists(self.key_file.name):
            try:
                os.unlink(self.key_file.name)
            except Exception:
                pass

    def __del__(self):
        self.cleanup()

    def _create_client(self) -> httpx.AsyncClient:
        """Creates an httpx.AsyncClient pre-configured with client certs and Chrome-like TLS configuration."""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        }

        # Create custom SSL context configured to mimic Chrome's secure handshakes
        ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE  # equivalent to verify=False
        
        # Load custom client certificates for mTLS authentication
        ssl_context.load_cert_chain(certfile=self.cert_path, keyfile=self.key_path)

        # Set modern Chrome-like secure cipher suites to reduce TLS fingerprint mismatch on WAF
        ssl_context.set_ciphers(
            "ECDHE-ECDSA-AES128-GCM-SHA256:"
            "ECDHE-RSA-AES128-GCM-SHA256:"
            "ECDHE-ECDSA-AES256-GCM-SHA384:"
            "ECDHE-RSA-AES256-GCM-SHA384:"
            "ECDHE-ECDSA-CHACHA20-POLY1305:"
            "ECDHE-RSA-CHACHA20-POLY1305"
        )
        
        # Enforce high-security TLS protocols only (TLS 1.2 and TLS 1.3)
        ssl_context.options |= ssl.OP_NO_SSLv2
        ssl_context.options |= ssl.OP_NO_SSLv3
        ssl_context.options |= ssl.OP_NO_TLSv1
        ssl_context.options |= ssl.OP_NO_TLSv1_1

        transport = httpx.AsyncHTTPTransport(verify=ssl_context)

        return httpx.AsyncClient(
            transport=transport,
            headers=headers,
            follow_redirects=True,
            timeout=30.0,
        )

    async def warmup(self, client: httpx.AsyncClient):
        """Warms up the SII session using standard HTTP requests to mimic real user navigation."""
        try:
            await client.get("https://www.sii.cl/", headers={"Referer": ""})
            await client.get(
                "https://www.sii.cl/servicios_online/1039-.html",
                headers={"Referer": "https://www.sii.cl/"},
            )
            await client.get(f"{self.base_url}/", headers={"Referer": "https://www.sii.cl/servicios_online/1039-.html"})
        except Exception:
            # Warmup is best-effort, continue on error
            pass

    async def probe_auth(self) -> str:
        """Tests the AUT2000 login without executing the folio wizard."""
        self.log(f"[sii-client] [{self.environment}] Starting certificate authentication probe against AUT2000...")
        async with self._create_client() as client:
            self.log(f"[sii-client] [{self.environment}] Warming up session with standard requests...")
            await self.warmup(client)

            entry_url = f"{self.base_url}{FOLIO_PATH}"
            self.log(f"[sii-client] [{self.environment}] Navigating to entry URL: {entry_url}")
            response = await client.get(entry_url, headers={"Referer": "https://www.sii.cl/"})

            # Check if we were served the certificate login page
            if is_certificate_auth_page(response.url, response.text):
                self.log(f"[sii-client] [{self.environment}] Login redirection detected (CAutInicio.cgi).")
                # We need to perform the POST login
                reference = extract_login_reference(str(response.url), response.text, fallback=entry_url)

                self.log(f"[sii-client] [{self.environment}] Reference extracted: {reference}. Performing POST certificate login...")
                login_url = f"{CERT_AUTH_URL}?{reference}"
                login_response = await client.post(
                    login_url,
                    data={"referencia": reference},
                    headers={"Referer": str(response.url)},
                )

                self.log(f"[sii-client] [{self.environment}] Certificate login POST submitted. Re-accessing entry URL...")
                # Check retry
                retry_response = await client.get(entry_url, headers={"Referer": str(login_response.url)})
                final_html = retry_response.text
                final_url = str(retry_response.url)
            else:
                self.log(f"[sii-client] [{self.environment}] Already authenticated. No redirection to login page required.")
                final_html = response.text
                final_url = str(response.url)

            # Check if login was successful
            if is_certificate_auth_page(final_url, final_html):
                self.log(f"[sii-client] [{self.environment}] ERROR: Landing page still shows login fields. AUT2000 rejected the certificate.")
                err_code = classify_certificate_auth_failure(final_html)
                raise SiiException(
                    err_code,
                    "AUT2000 rejected the certificate; the certificate may be invalid, expired, or not authorized.",
                )

            self.log(f"[sii-client] [{self.environment}] Success: AUT2000 authentication verified.")
            return "Authentication verified successfully!"

    async def request_folios(
        self,
        rut_sender: str,
        rut_company: str,
        document_type: int,
        amount: int,
    ) -> str:
        """Executes the full wizard flow to request and download folios (CAF XML)."""
        self.log(f"[sii-client] [{self.environment}] Starting automated CAF request: Sender={rut_sender}, Company={rut_company}, DTE={document_type}, Qty={amount}")
        async with self._create_client() as client:
            self.log(f"[sii-client] [{self.environment}] Warming up session with standard requests...")
            await self.warmup(client)

            entry_url = f"{self.base_url}{FOLIO_PATH}"
            self.log(f"[sii-client] [{self.environment}] Navigating to folio wizard entry URL: {entry_url}")
            current_resp = await client.get(entry_url, headers={"Referer": "https://www.sii.cl/"})

            # 1. Handle certificate authentication if redirected
            if is_certificate_auth_page(current_resp.url, current_resp.text):
                self.log(f"[sii-client] [{self.environment}] Redirection to AUT2000 login detected. Starting handshake...")
                reference = extract_login_reference(str(current_resp.url), current_resp.text, fallback=entry_url)

                self.log(f"[sii-client] [{self.environment}] Reference extracted: {reference}. Performing POST certificate login...")
                login_url = f"{CERT_AUTH_URL}?{reference}"
                
                # Add human-like pacing delay before certificate login POST
                login_delay = random.uniform(0.8, 1.6)
                self.log(f"[sii-client] [{self.environment}] Pausing for {login_delay:.2f}s to simulate human certificate selection delay...")
                await asyncio.sleep(login_delay)

                login_resp = await client.post(
                    login_url,
                    data={"referencia": reference},
                    headers={"Referer": str(current_resp.url)},
                )

                self.log(f"[sii-client] [{self.environment}] Certificate login submitted. Re-accessing entry URL...")
                retry_resp = await client.get(entry_url, headers={"Referer": str(login_resp.url)})
                current_resp = retry_resp

            # Check if auth failed
            if is_certificate_auth_page(current_resp.url, current_resp.text):
                self.log(f"[sii-client] [{self.environment}] ERROR: Landing page still shows login fields. Handshake failed.")
                err_code = classify_certificate_auth_failure(current_resp.text)
                raise SiiException(err_code, f"AUT2000 Authentication failed during folio wizard: {err_code}")

            self.log(f"[sii-client] [{self.environment}] Handshake successful. Navigating the folio wizard steps...")
            # Clean company RUT
            company_body, company_dv = clean_rut(rut_company)

            # 2. Iterate through forms steps to request CAF
            for step in range(12):  # Maximum form steps
                html = current_resp.text
                self.log(f"[sii-client] [{self.environment}] [Step {step}] Landed on URL: {current_resp.url}")

                # Check if WAF blocked us
                if is_blocked_sii_page(html):
                    support_id = extract_support_id(html)
                    self.log(f"[sii-client] [{self.environment}] [Step {step}] ERROR: WAF Block page detected! Support ID: {support_id or 'unknown'}")
                    raise SiiException(
                        "SII_FOLIO_REQUEST_BLOCKED",
                        f"Request was blocked by SII classic portal. Support ID: {support_id or 'unknown'}",
                    )

                # Check if we have successfully obtained the CAF XML
                caf_xml = extract_caf_xml(html)
                if caf_xml:
                    self.log(f"[sii-client] [{self.environment}] [Step {step}] SUCCESS! CAF XML extracted: {len(caf_xml)} bytes.")
                    return caf_xml

                # Parse the forms in the page
                forms = self._parse_html_forms(html)
                self.log(f"[sii-client] [{self.environment}] [Step {step}] Parsed {len(forms)} HTML form(s) on the page.")
                if not forms:
                    self.log(f"[sii-client] [{self.environment}] [Step {step}] ERROR: No usable forms found on the page. HTML preview: {html[:600]}")
                    raise SiiException(
                        "SII_FOLIO_FORM_NOT_FOUND",
                        f"No usable form found in page. Step {step}. Excerpt: {html[:800]}",
                    )

                # Select best form
                selected_form = self._pick_form(forms, str(current_resp.url), document_type)
                if not selected_form:
                    self.log(f"[sii-client] [{self.environment}] [Step {step}] No specific wizard form matched. Falling back to the first available form.")
                    # Try first form
                    selected_form = forms[0]

                # Prepare fields for submission
                fields = dict(selected_form["inputs"])

                # Handle company RUT fields
                for f_name in RUT_EMP_FIELD_CANDIDATES:
                    if f_name in fields:
                        fields[f_name] = company_body
                for f_name in DV_EMP_FIELD_CANDIDATES:
                    if f_name in fields:
                        fields[f_name] = company_dv

                # Handle document type field
                for f_name in DOCUMENT_TYPE_FIELD_CANDIDATES:
                    if f_name in fields:
                        fields[f_name] = str(document_type)

                # Handle quantity / amount field
                for f_name in QUANTITY_FIELD_CANDIDATES:
                    if f_name in fields:
                        fields[f_name] = str(amount)

                # Resolve action URL
                action = selected_form["action"] or ""
                action_url = urllib.parse.urljoin(str(current_resp.url), action)

                self.log(f"[sii-client] [{self.environment}] [Step {step}] Submitting {selected_form['method']} to {action_url}")
                self.log(f"[sii-client] [{self.environment}] [Step {step}] Form fields: {list(fields.keys())}")

                # Submit form with randomized human-like pacing delay
                delay = random.uniform(0.65, 1.45)
                self.log(f"[sii-client] [{self.environment}] [Step {step}] Pausing for {delay:.2f}s to simulate human navigation pacing...")
                await asyncio.sleep(delay)

                # Submit form
                if selected_form["method"] == "POST":
                    current_resp = await client.post(
                        action_url,
                        data=fields,
                        headers={"Referer": str(current_resp.url)},
                    )
                else:
                    current_resp = await client.get(
                        action_url,
                        params=fields,
                        headers={"Referer": str(current_resp.url)},
                    )

            # If we reached the step limit without CAF
            self.log(f"[sii-client] [{self.environment}] ERROR: Exceeded step limit (12 steps) without extracting CAF XML.")
            raise SiiException(
                "SII_FOLIO_FORM_FLOW_LIMIT",
                "Exceeded maximum form wizard steps without retrieving CAF XML.",
            )

    def _parse_html_forms(self, html_content: str) -> List[Dict]:
        """Parses HTML and extracts all form details."""
        soup = BeautifulSoup(html_content, "lxml")
        forms = []
        for form_el in soup.find_all("form"):
            form_data = {
                "action": form_el.get("action"),
                "method": form_el.get("method", "GET").upper(),
                "inputs": {},
            }
            # Find all inputs, selects, and textareas
            for input_el in form_el.find_all(["input", "select", "textarea"]):
                name = input_el.get("name")
                if not name:
                    continue
                value = input_el.get("value", "")

                if input_el.name == "select":
                    selected_opt = input_el.find("option", selected=True)
                    if selected_opt:
                        value = selected_opt.get("value", "")
                    else:
                        first_opt = input_el.find("option")
                        if first_opt:
                            value = first_opt.get("value", "")

                form_data["inputs"][name] = value

            forms.append(form_data)
        return forms

    def _pick_form(self, forms: List[Dict], current_url: str, document_type: int) -> Optional[Dict]:
        """Selects the best form to submit based on available form paths and inputs."""
        url_path = urllib.parse.urlparse(current_url).path

        # 1. Company input page or document type page
        if MAULLIN_COMPANY_FORM_PATH in url_path or MAULLIN_COMPANY_FORM_PATH.lower() in [f.get("action", "").lower() for f in forms]:
            for f in forms:
                # Check if it has document type candidates or RUT fields
                if any(x in f["inputs"] for x in RUT_EMP_FIELD_CANDIDATES) or any(x in f["inputs"] for x in DOCUMENT_TYPE_FIELD_CANDIDATES):
                    return f

        # 2. Document type select page
        if MAULLIN_DOCUMENT_TYPE_FORM_PATH in url_path:
            for f in forms:
                if any(x in f["inputs"] for x in DOCUMENT_TYPE_FIELD_CANDIDATES):
                    return f

        # 3. Generate folios page (where quantity is entered)
        if MAULLIN_GENERATE_FOLIOS_FORM_PATH in url_path:
            for f in forms:
                if any(x in f["inputs"] for x in QUANTITY_FIELD_CANDIDATES):
                    return f

        # 4. Confirmation paths
        for path in MAULLIN_CONFIRM_FOLIOS_FORM_PATHS:
            if path in url_path:
                for f in forms:
                    return f

        # 5. Download paths
        for path in MAULLIN_DOWNLOAD_FOLIOS_FORM_PATHS:
            if path in url_path:
                for f in forms:
                    return f

        # Fallback: find any form containing relevant wizard fields
        for f in forms:
            field_names = f["inputs"].keys()
            if any(x in field_names for x in QUANTITY_FIELD_CANDIDATES + DOCUMENT_TYPE_FIELD_CANDIDATES + RUT_EMP_FIELD_CANDIDATES):
                return f

        return None
