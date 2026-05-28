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
    libxslt \
    && rm -rf /var/lib/apt/lists/*

COPY --from:builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Copy source code and scripts
COPY src/ ./src/
COPY runner.py .
COPY scripts/ ./scripts/

# Create certs directory and set permissions
RUN mkdir -p certs && chmod 700 certs

EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONPATH=.

# By default, generate certificates on startup if they don't exist, then start runner with mTLS
CMD python scripts/generate_certs.py && python runner.py
