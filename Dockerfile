# ─────────────────────────────────────────────────────
# Faraday AI Memory — Cloud Run Container
# ─────────────────────────────────────────────────────
# Multi-stage build:
#   1. Pre-download the embedding model at build time
#   2. Install all Python dependencies
#   3. Runs cloud_server.py on port 8080

FROM python:3.11-slim AS base

# System dependencies for faiss-cpu
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model at build time
# This avoids a ~100MB download on every cold start
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code
COPY config.py .
COPY database/ database/
COPY processing/ processing/
COPY ingestion/ ingestion/
COPY mcp_server/ mcp_server/

# Create data directories
RUN mkdir -p /tmp/faraday-data data_raw data_processed embeddings

# Hugging Face Spaces uses PORT env var (default 7860)
ENV PORT=7860
ENV CLOUD_DATA_DIR=/tmp/faraday-data

# Expose the port
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health')" || exit 1

# Run the cloud MCP server
CMD ["python", "mcp_server/cloud_server.py"]
