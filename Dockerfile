# ============================================================
# RTA-GUARD — Production Dockerfile
# Python dashboard + Discus guard engine
# ============================================================
FROM python:3.11-slim AS base

# Metadata
LABEL maintainer="RTA-GUARD" \
      description="RTA-GUARD AI session kill-switch" \
      version="0.6.1"

# Security: non-root user
RUN groupadd -r rta && useradd -r -g rta -d /app -s /sbin/nologin rta

WORKDIR /app

# Install system deps for compiled packages (then clean up)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory with correct ownership
RUN mkdir -p /app/data && chown -R rta:rta /app

# Switch to non-root
USER rta

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

EXPOSE 8080

CMD ["uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
