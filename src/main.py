import asyncio
import re

import uvicorn
from fastapi import Depends, FastAPI
from src.config import settings
from src.auth import verify_token
from src.coordinator import FolioBusy, FolioCoordinator
from src.schemas import ProbeAuthRequest, ProbeAuthResponse, FolioRequest, FolioResponse, AvailabilityRequest, AvailabilityResponse
from src.sii import SiiClient, SiiException


folio_coordinator = FolioCoordinator(
    max_concurrent=settings.SII_MAX_CONCURRENT_REQUESTS,
    queue_timeout=min(settings.SII_QUEUE_TIMEOUT, settings.SII_OPERATION_TIMEOUT),
)


def _company_key(rut_company: str) -> str:
    return re.sub(r"[^0-9kK]", "", rut_company).upper()


def _operation_deadline() -> float:
    return asyncio.get_running_loop().time() + settings.SII_OPERATION_TIMEOUT


def _remaining_time(deadline: float) -> float:
    return max(0.0, deadline - asyncio.get_running_loop().time())

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
    client = None
    deadline = _operation_deadline()
    try:
        async with folio_coordinator.slot(
            request.environment, f"probe-{id(request)}"
        ):
            client = SiiClient(
                pfx_base64=request.pfx_base64,
                pfx_password=request.pfx_password,
                environment=request.environment,
            )
            message = await asyncio.wait_for(
                client.probe_auth(), timeout=_remaining_time(deadline)
            )
            return ProbeAuthResponse(success=True, message=message, trace=client.logs)
    except FolioBusy:
        return ProbeAuthResponse(
            success=False,
            message="SII_FOLIO_BUSY: SII request capacity is currently exhausted.",
            trace=[],
        )
    except asyncio.TimeoutError:
        return ProbeAuthResponse(
            success=False,
            message="SII_FOLIO_UNEXPECTED_ERROR: SII operation deadline exceeded.",
            trace=client.logs if client else [],
        )
    except SiiException as e:
        return ProbeAuthResponse(success=False, message=f"{e.code}: {e.message}", trace=client.logs if client else [])
    except Exception as e:
        return ProbeAuthResponse(success=False, message=f"Unexpected error: {str(e)}", trace=client.logs if client else [])
    finally:
        if client:
            client.cleanup()


@app.post(
    "/api/v1/folios/request",
    response_model=FolioResponse,
    dependencies=[Depends(verify_token)],
    summary="Request and download CAF folios from SII portal",
)
async def request_folios(request: FolioRequest):
    client = None
    deadline = _operation_deadline()
    try:
        async with folio_coordinator.slot(
            request.environment, _company_key(request.rut_company)
        ):
            client = SiiClient(
                pfx_base64=request.pfx_base64,
                pfx_password=request.pfx_password,
                environment=request.environment,
            )
            try:
                caf_xml = await asyncio.wait_for(
                    client.request_folios(
                        rut_sender=request.rut_sender,
                        rut_company=request.rut_company,
                        document_type=request.document_type,
                        amount=request.amount,
                    ),
                    timeout=_remaining_time(deadline),
                )
                return FolioResponse(
                    success=True,
                    caf_xml=caf_xml,
                    message="Folios retrieved successfully",
                    trace=client.logs,
                    unused_folios=client.unused_folios,
                    max_authorized=client.max_authorized,
                    last_range_start=client.last_range_start,
                    last_range_end=client.last_range_end,
                    availability_status=client.availability_status,
                )
            finally:
                client.cleanup()
    except FolioBusy:
        return FolioResponse(
            success=False,
            error_code="SII_FOLIO_BUSY",
            message="SII request capacity is currently exhausted.",
            trace=[],
            availability_status="unknown",
        )
    except asyncio.TimeoutError:
        outcome_unknown = bool(
            client and getattr(client, "final_submission_started", False)
        )
        return FolioResponse(
            success=False,
            error_code=(
                "SII_FOLIO_OUTCOME_UNKNOWN"
                if outcome_unknown
                else "SII_FOLIO_UNEXPECTED_ERROR"
            ),
            message=(
                "SII final submission timed out; do not retry automatically."
                if outcome_unknown
                else "SII operation deadline exceeded."
            ),
            trace=client.logs if client else [],
            unused_folios=client.unused_folios if client else None,
            max_authorized=client.max_authorized if client else None,
            last_range_start=client.last_range_start if client else None,
            last_range_end=client.last_range_end if client else None,
            availability_status=client.availability_status if client else "unknown",
        )
    except SiiException as e:
        return FolioResponse(
            success=False,
            error_code=e.code,
            message=e.message,
            trace=client.logs if client else [],
            unused_folios=client.unused_folios if client else None,
            max_authorized=client.max_authorized if client else None,
            last_range_start=client.last_range_start if client else None,
            last_range_end=client.last_range_end if client else None,
            availability_status=client.availability_status if client else "unknown",
        )
    except Exception as e:
        return FolioResponse(
            success=False,
            error_code="SII_FOLIO_UNEXPECTED_ERROR",
            message=f"Unexpected error: {str(e)}",
            trace=client.logs if client else [],
            unused_folios=client.unused_folios if client else None,
            max_authorized=client.max_authorized if client else None,
            last_range_start=client.last_range_start if client else None,
            last_range_end=client.last_range_end if client else None,
            availability_status=client.availability_status if client else "unknown",
        )


@app.post(
    "/api/v1/folios/check-availability",
    response_model=AvailabilityResponse,
    dependencies=[Depends(verify_token)],
    summary="Check folio limits and unused counts from SII portal without generating a CAF",
)
async def check_availability(request: AvailabilityRequest):
    client = None
    deadline = _operation_deadline()
    try:
        async with folio_coordinator.slot(
            request.environment, _company_key(request.rut_company)
        ):
            client = SiiClient(
                pfx_base64=request.pfx_base64,
                pfx_password=request.pfx_password,
                environment=request.environment,
            )
            try:
                for attempt in range(2):
                    try:
                        info = await asyncio.wait_for(
                            client.check_availability(
                                rut_sender=request.rut_sender,
                                rut_company=request.rut_company,
                                document_type=request.document_type,
                            ),
                            timeout=_remaining_time(deadline),
                        )
                        break
                    except SiiException as error:
                        if attempt or error.code != "SII_FOLIO_CERTIFICATE_AUTH_FAILED":
                            raise
                        # Availability opens a fresh HTTP session on each call.
                        # Retry only ambiguous authentication, never CAF generation.
                        client.logs.append("[sii-client] Retrying availability authentication once with a fresh session.")
                        await asyncio.wait_for(asyncio.sleep(1), timeout=_remaining_time(deadline))
                # Boletas can reach the quantity form without exposing a numeric
                # maximum. This is not a failed navigation or an unlimited grant.
                if info.get("max_authorized") is None and request.document_type not in (39, 41):
                    return AvailabilityResponse(
                        success=False,
                        unused_folios=info.get("unused_folios"),
                        max_authorized=None,
                        last_range_start=info.get("last_range_start"),
                        last_range_end=info.get("last_range_end"),
                        availability_status="unknown",
                        error_code="SII_FOLIO_AVAILABILITY_UNAVAILABLE",
                        message="SII did not expose the maximum authorized folio amount.",
                        trace=client.logs,
                    )
                return AvailabilityResponse(
                    success=True,
                    unused_folios=info.get("unused_folios"),
                    max_authorized=info.get("max_authorized"),
                    last_range_start=info.get("last_range_start"),
                    last_range_end=info.get("last_range_end"),
                    availability_status=info.get("availability_status"),
                    message="Folio availability retrieved successfully",
                    trace=client.logs,
                )
            finally:
                client.cleanup()
    except FolioBusy:
        return AvailabilityResponse(
            success=False,
            error_code="SII_FOLIO_BUSY",
            message="SII request capacity is currently exhausted.",
            trace=[],
            availability_status="unknown",
        )
    except asyncio.TimeoutError:
        return AvailabilityResponse(
            success=False,
            error_code="SII_FOLIO_UNEXPECTED_ERROR",
            message="SII operation deadline exceeded.",
            trace=client.logs if client else [],
            unused_folios=client.unused_folios if client else None,
            max_authorized=client.max_authorized if client else None,
            last_range_start=client.last_range_start if client else None,
            last_range_end=client.last_range_end if client else None,
            availability_status=client.availability_status if client else "unknown",
        )
    except SiiException as e:
        return AvailabilityResponse(
            success=False,
            error_code=e.code,
            message=e.message,
            trace=client.logs if client else [],
            unused_folios=client.unused_folios if client else None,
            max_authorized=client.max_authorized if client else None,
            last_range_start=client.last_range_start if client else None,
            last_range_end=client.last_range_end if client else None,
            availability_status=client.availability_status if client else "unknown",
        )
    except Exception as e:
        return AvailabilityResponse(
            success=False,
            error_code="SII_FOLIO_UNEXPECTED_ERROR",
            message=f"Unexpected error: {str(e)}",
            trace=client.logs if client else [],
            unused_folios=client.unused_folios if client else None,
            max_authorized=client.max_authorized if client else None,
            last_range_start=client.last_range_start if client else None,
            last_range_end=client.last_range_end if client else None,
            availability_status=client.availability_status if client else "unknown",
        )


if __name__ == "__main__":
    # If run directly as a script, start Uvicorn with standard parameters (without mTLS) for testing.
    # Production uses runner.py which configures SSL and Client Certificate Verification (mTLS).
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, reload=True)
