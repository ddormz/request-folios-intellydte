from pydantic import BaseModel, Field
from typing import Optional, List


class ProbeAuthRequest(BaseModel):
    pfx_base64: str = Field(..., description="Base64 encoded PFX digital certificate")
    pfx_password: str = Field(..., description="PFX digital certificate password")
    environment: str = Field("maullin", description="SII environment: 'maullin' (test) or 'palena' (production)")


class ProbeAuthResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    message: str
    trace: Optional[List[str]] = Field(None, description="The scraping trace log lines")


class FolioRequest(BaseModel):
    pfx_base64: str = Field(..., description="Base64 encoded PFX digital certificate")
    pfx_password: str = Field(..., description="PFX digital certificate password")
    rut_sender: str = Field(..., description="RUT of the certificate holder (sender)")
    rut_company: str = Field(..., description="RUT of the company requesting folios")
    document_type: int = Field(..., description="SII document type code (e.g., 33, 39)")
    amount: int = Field(..., description="Number of folios to request")
    environment: str = Field("maullin", description="SII environment: 'maullin' or 'palena'")


class FolioResponse(BaseModel):
    success: bool
    caf_xml: Optional[str] = Field(None, description="The returned CAF XML string if successful")
    error_code: Optional[str] = Field(None, description="Error code if request failed")
    message: str
    trace: Optional[List[str]] = Field(None, description="The scraping trace log lines")
    unused_folios: Optional[int] = Field(None, description="Number of unused folios")
    max_authorized: Optional[int] = Field(None, description="Maximum authorized folios that can be requested")
    last_range_start: Optional[int] = Field(None, description="Start of the last authorized folio range")
    last_range_end: Optional[int] = Field(None, description="End of the last authorized folio range")


class AvailabilityRequest(BaseModel):
    pfx_base64: str = Field(..., description="Base64 encoded PFX digital certificate")
    pfx_password: str = Field(..., description="PFX digital certificate password")
    rut_sender: str = Field(..., description="RUT of the certificate holder (sender)")
    rut_company: str = Field(..., description="RUT of the company requesting folios")
    document_type: int = Field(..., description="SII document type code (e.g., 33, 39)")
    environment: str = Field("maullin", description="SII environment: 'maullin' or 'palena'")


class AvailabilityResponse(BaseModel):
    success: bool
    unused_folios: Optional[int] = Field(None, description="Number of unused folios")
    max_authorized: Optional[int] = Field(None, description="Maximum authorized folios that can be requested")
    last_range_start: Optional[int] = Field(None, description="Start of the last authorized folio range")
    last_range_end: Optional[int] = Field(None, description="End of the last authorized folio range")
    error_code: Optional[str] = Field(None, description="Error code if request failed")
    message: str
    trace: Optional[List[str]] = Field(None, description="The scraping trace log lines")

