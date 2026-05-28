# Multi-stage production Dockerfile for folio-bridge-py

# --- Build Stage ---
FROM python:3.13-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Production Stage ---
FROM python:3.13-slim AS production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Copy source code and scripts
COPY src/ ./src/
COPY runner.py .

# Create certs directory (only used when MTLS_ENABLED=true)
RUN mkdir -p certs

EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONPATH=.
ENV MTLS_ENABLED=false

# Default: start in HTTP mode (internal network, Bearer token auth).
# To enable mTLS, set MTLS_ENABLED=true and mount certs/ volume.
CMD ["python", "runner.py"]
