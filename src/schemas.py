from pydantic import BaseModel, Field
from typing import Optional


class ProbeAuthRequest(BaseModel):
    pfx_base64: str = Field(..., description="Base64 encoded PFX digital certificate")
    pfx_password: str = Field(..., description="PFX digital certificate password")
    environment: str = Field("maullin", description="SII environment: 'maullin' (test) or 'palena' (production)")


class ProbeAuthResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    message: str


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
