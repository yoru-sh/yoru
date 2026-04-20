# Multi-stage Dockerfile for SaaS API
# Base image with Python 3.11 slim

# ============================================
# Stage 1: Base image with common settings
# ============================================
FROM python:3.11-slim AS base

WORKDIR /app

# Python environment settings
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# ============================================
# Stage 2: Dependencies installation
# ============================================
FROM base AS dependencies

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements/base.txt requirements/api.txt ./
RUN pip install --no-cache-dir -r base.txt -r api.txt

# ============================================
# Stage 3: Final production image
# ============================================
FROM base AS final

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from dependencies stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Copy application code with proper ownership
COPY --chown=appuser:appuser apps/__init__.py /app/apps/__init__.py
COPY --chown=appuser:appuser apps/api /app/apps/api
COPY --chown=appuser:appuser libs /app/libs

# Create logs directory with proper permissions
RUN mkdir -p /app/logs && chown -R appuser:appuser /app/logs

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
