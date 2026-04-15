FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install OS deps required by some Python packages.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY bridge/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the bridge package and the legacy faqs/ directory used for the
# initial knowledge-base seed.
COPY bridge/ /app/bridge/
COPY faqs/ /app/faqs/

# A persistent location for APScheduler's SQLite jobstore so that
# scheduled jobs survive container restarts without double-firing.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENV BRIDGE_DATA_DIR=/app/data \
    BRIDGE_FAQ_DIR=/app/faqs

CMD ["python", "-m", "bridge.main"]
