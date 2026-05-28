# Folio Bridge (Python Microservice)

Internal high-performance microservice written in **Python + FastAPI** for secure and robust automated folio requesting against the SII classic portal (`maullin` / `palena`). 

This microservice acts as the **primary** transport driver for the main Node/TypeScript application, leaving legacy drivers in standby as fallbacks.

## Architecture

```
Node (Public :3000) --[mTLS (Port 8000)]--> Python Bridge (Private) --[httpx+cert]--> SII (palena/maullin)
```

1. **Mutual TLS (mTLS)**: All communication between Node and Python is encrypted and authenticated at the transport layer. The Python service requires a valid client certificate signed by a shared Certificate Authority (CA) to authorize requests.
2. **Bearer Token Authorization**: An additional layer of security (Defense-in-Depth) verifies an API bearer token on all microservice requests.
3. **Pure Python PFX Handling**: Avoids parsing digital certificates via external binary subprocesses, extracting certs securely in-memory using `cryptography`.

---

## Local Setup & Development

### 1. Requirements
Ensure you have Python 3.10+ installed.

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Generate Mutual TLS Certificates
A helper script is provided to automatically generate a shared CA, server certificates, and client certificates:
```bash
python scripts/generate_certs.py
```
This generates the following files in the `certs/` folder:
- `ca.crt` / `ca.key`: Trust root authority
- `server.crt` / `server.key`: For the Python FastAPI microservice
- `client.crt` / `client.key`: For the Node client

### 4. Configuration
Create a `.env` file based on `.env.example`:
```ini
HOST=127.0.0.1
PORT=8000
API_BEARER_TOKEN=super-secret-folio-bridge-token
```

### 5. Running the Microservice
Start the server in production-ready mTLS mode:
```bash
python runner.py
```
To run tests:
```bash
set PYTHONPATH=.
pytest
```

---

## Dokploy Deployment Guide (Manual Configuration)

To deploy `folio-bridge-py` in Dokploy as a secure internal service, follow these steps:

### Step 1: Create a New Application
1. Open your **Dokploy Panel**.
2. Navigate to your **Project** and click **Create Application**.
3. Select **Multi-stage Dockerfile** as the build method (Dokploy will automatically read the provided `Dockerfile`).

### Step 2: Configure Environment Variables
In the **Environment** tab of the Dokploy application, configure:
- `HOST`: `0.0.0.0`
- `PORT`: `8000`
- `API_BEARER_TOKEN`: `<your-secure-shared-token>`

### Step 3: Configure Network & Security
To keep this microservice completely private and inaccessible from the public internet (internal-only), configure Traefik / Routing:
1. Under **Domain**, do **not** bind any public domain.
2. The service will be accessible internally within the Dokploy Docker network at `http://<dokploy-app-name>:8000` or via mTLS at `https://<dokploy-app-name>:8000`.

### Step 4: Persistent Volumes (Optional)
By default, the provided `Dockerfile` generates fresh self-signed mTLS certificates on startup.
If you prefer to persist the generated certificates across restarts (highly recommended to avoid rotating certificates on every container restart):
1. In Dokploy, add a **Persistent Volume**.
2. Mount it at `/app/certs`.
3. Set the volume type to `bind` or `volume`.
4. This ensures `ca.crt`, `server.crt`, `server.key`, `client.crt`, and `client.key` persist indefinitely.

### Step 5: Transfer Client Certificates to the Main Node Application
Once the application starts in Dokploy and generates the certificates (or if you generate them locally):
1. Download or copy `ca.crt`, `client.crt`, and `client.key` from `/app/certs` (or the persistent volume).
2. Save them in the main Node project structure (or load them via environment variables).
3. Set the following environment variables in the main Node `.env` file:
   ```ini
   SII_FOLIO_TRANSPORT_DRIVER=python
   SII_FOLIO_BRIDGE_URL=https://<dokploy-app-name>:8000
   SII_FOLIO_BRIDGE_TOKEN=<your-secure-shared-token>
   SII_FOLIO_BRIDGE_CA_PATH=apps/folio-bridge-py/certs/ca.crt
   SII_FOLIO_BRIDGE_CERT_PATH=apps/folio-bridge-py/certs/client.crt
   SII_FOLIO_BRIDGE_KEY_PATH=apps/folio-bridge-py/certs/client.key
   ```
