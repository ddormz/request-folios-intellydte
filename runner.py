import os
import ssl
import uvicorn
from src.config import settings


def start_server():
    print("--------------------------------------------------")
    print("Starting Folio Bridge Python microservice with mTLS...")
    print(f"Host: {settings.HOST}")
    print(f"Port: {settings.PORT}")
    print(f"CA Cert (Trust Store): {settings.CA_CERT_PATH}")
    print(f"Server Cert: {settings.SERVER_CERT_PATH}")
    print(f"Server Key: {settings.SERVER_KEY_PATH}")
    print("Client Certificate Verification: REQUIRED (mTLS)")
    print("--------------------------------------------------")

    # Verify certificate files exist
    for path_name, path_val in [
        ("CA Cert", settings.CA_CERT_PATH),
        ("Server Cert", settings.SERVER_CERT_PATH),
        ("Server Key", settings.SERVER_KEY_PATH),
    ]:
        if not os.path.exists(path_val):
            print(f"CRITICAL ERROR: {path_name} file not found at: {path_val}")
            print("Please generate certificates first using:")
            print("  python scripts/generate_certs.py")
            return

    # Run Uvicorn programmatically with mTLS settings
    uvicorn.run(
        "src.main:app",
        host=settings.HOST,
        port=settings.PORT,
        ssl_keyfile=settings.SERVER_KEY_PATH,
        ssl_certfile=settings.SERVER_CERT_PATH,
        ssl_ca_certs=settings.CA_CERT_PATH,
        ssl_cert_reqs=ssl.CERT_REQUIRED,  # Enforce Client Certificate Verification (mTLS)
    )


if __name__ == "__main__":
    start_server()
