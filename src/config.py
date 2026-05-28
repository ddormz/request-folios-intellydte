import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings:
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Security Token for bearer authentication (Defense-in-depth)
    API_BEARER_TOKEN: str = os.getenv("API_BEARER_TOKEN", "super-secret-folio-bridge-token")
    
    # Mutual TLS paths
    CA_CERT_PATH: str = os.getenv("CA_CERT_PATH", str(BASE_DIR / "certs" / "ca.crt"))
    SERVER_CERT_PATH: str = os.getenv("SERVER_CERT_PATH", str(BASE_DIR / "certs" / "server.crt"))
    SERVER_KEY_PATH: str = os.getenv("SERVER_KEY_PATH", str(BASE_DIR / "certs" / "server.key"))
    
    # SII Settings
    SII_TIMEOUT: int = int(os.getenv("SII_TIMEOUT", "30"))

settings = Settings()
