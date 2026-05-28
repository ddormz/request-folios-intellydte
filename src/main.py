import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status
from src.config import settings
from src.auth import verify_token
from src.schemas import ProbeAuthRequest, ProbeAuthResponse, FolioRequest, FolioResponse
from src.sii import SiiClient, SiiException

app = FastAPI(
    title="Folio Bridge Python Microservice",
    description="Secure internal microservice for requesting SII folios using mutual TLS and Bearer Token authentication.",
    version="1.0.0",
)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "folio-bridge-py"}


@app.post(
    "/api/v1/folios/probe-auth",
    response_model=ProbeAuthResponse,
    dependencies=[Depends(verify_token)],
    summary="Probe certificate authentication against AUT2000 without generating CAF",
)
async def probe_auth(request: ProbeAuthRequest):
    try:
        client = SiiClient(
            pfx_base64=request.pfx_base64,
            pfx_password=request.pfx_password,
            environment=request.environment,
        )
        message = await client.probe_auth()
        return ProbeAuthResponse(success=True, message=message)
    except SiiException as e:
        return ProbeAuthResponse(success=False, message=f"{e.code}: {e.message}")
    except Exception as e:
        return ProbeAuthResponse(success=False, message=f"Unexpected error: {str(e)}")


@app.post(
    "/api/v1/folios/request",
    response_model=FolioResponse,
    dependencies=[Depends(verify_token)],
    summary="Request and download CAF folios from SII portal",
)
async def request_folios(request: FolioRequest):
    try:
        client = SiiClient(
            pfx_base64=request.pfx_base64,
            pfx_password=request.pfx_password,
            environment=request.environment,
        )
        caf_xml = await client.request_folios(
            rut_sender=request.rut_sender,
            rut_company=request.rut_company,
            document_type=request.document_type,
            amount=request.amount,
        )
        return FolioResponse(
            success=True,
            caf_xml=caf_xml,
            message="Folios retrieved successfully",
        )
    except SiiException as e:
        return FolioResponse(
            success=False,
            error_code=e.code,
            message=e.message,
        )
    except Exception as e:
        return FolioResponse(
            success=False,
            error_code="SII_FOLIO_UNEXPECTED_ERROR",
            message=f"Unexpected error: {str(e)}",
        )


if __name__ == "__main__":
    # If run directly as a script, start Uvicorn with standard parameters (without mTLS) for testing.
    # Production uses runner.py which configures SSL and Client Certificate Verification (mTLS).
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, reload=True)
