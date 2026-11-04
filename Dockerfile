# ==============================================================================
# Production Dockerfile: Audio Transcription & Speaker Identification App
# Base: Python 3.11 Slim (Debian GNU/Linux)
# Security: Non-root execution under appuser (matching host UID/GID)
# Multimedia: FFmpeg & FFprobe system binaries
# ==============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc bytecode and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/venv/bin:$PATH"

# Build arguments for host UID/GID alignment
ARG APP_UID=1000
ARG APP_GID=1000
# Set to "true" to include pytest in the image (CI / local test runs)
ARG INSTALL_DEV_DEPS=false

# 1. Install system runtime dependencies: ffmpeg (audio processing) & curl (healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        curl && \
    rm -rf /var/lib/apt/lists/*

# 2. Create non-root application user matching host UID/GID
RUN (getent group ${APP_GID} || groupadd -g ${APP_GID} appuser) && \
    (getent passwd ${APP_UID} || useradd -u ${APP_UID} -g ${APP_GID} -d /home/appuser -m -s /bin/bash appuser)

# 3. Create isolated Python virtual environment
RUN python -m venv /opt/venv

# 4. Set application working directory
WORKDIR /app

# 5. Copy dependency definitions first (cached unless they change); the image installs exact versions
COPY requirements.txt requirements.lock requirements-dev.txt ./

# 6. Install Python dependencies inside virtual environment
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock && \
    if [ "$INSTALL_DEV_DEPS" = "true" ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

# 7. Create storage directories for audio uploads, outputs, and temp chunk processing
RUN mkdir -p /app/uploads /app/outputs /app/temp && \
    chown -R ${APP_UID}:${APP_GID} /app/uploads /app/outputs /app/temp /home/appuser

# 8. Copy application code with non-root user ownership
COPY --chown=${APP_UID}:${APP_GID} . .

# 9. Switch to non-root execution
USER appuser

# 10. Expose application HTTP port
EXPOSE 8000

# 11. Define container healthcheck targeting FastAPI health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# 12. Start Uvicorn ASGI server
#     - Single worker on purpose: transcription jobs live in process memory.
#     - Proxy headers are trusted so HTTPS/real client IPs work behind a reverse proxy.
ENV ENVIRONMENT=production
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header", "--timeout-keep-alive", "30"]
