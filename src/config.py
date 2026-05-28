import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

def _bool_env(key: str, default: bool) -> bool:
    val = os.getenv(key, "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default

class Settings:
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Security Token for bearer authentication (Defense-in-depth)
    API_BEARER_TOKEN: str = os.getenv("API_BEARER_TOKEN", "super-secret-folio-bridge-token")
    
    # Mutual TLS (optional, disabled by default for internal network)
    MTLS_ENABLED: bool = _bool_env("MTLS_ENABLED", False)
    
    # Mutual TLS paths (only used when MTLS_ENABLED=true)
    CA_CERT_PATH: str = os.getenv("CA_CERT_PATH", str(BASE_DIR / "certs" / "ca.crt"))
    SERVER_CERT_PATH: str = os.getenv("SERVER_CERT_PATH", str(BASE_DIR / "certs" / "server.crt"))
    SERVER_KEY_PATH: str = os.getenv("SERVER_KEY_PATH", str(BASE_DIR / "certs" / "server.key"))
    
    # SII Settings
    SII_TIMEOUT: int = int(os.getenv("SII_TIMEOUT", "30"))

settings = Settings()
