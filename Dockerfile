# syntax=docker/dockerfile:1
# Multi-stage build for the QuantBot Python services (engine + API share one image).

# --- Builder: install dependencies into a venv ---
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build tools needed for some wheels (e.g. asyncpg, cryptography on slim).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src ./src

# Install the package with API, notify and report extras (no dev/ai by default;
# build with --build-arg EXTRAS to customise).
ARG EXTRAS="api,notify,report"
RUN pip install --upgrade pip && pip install ".[${EXTRAS}]"

# --- Runtime: slim image with only the venv + source ---
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/src"

# Create an unprivileged user.
RUN useradd --create-home --uid 10001 quantbot

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config

USER quantbot

# Default command runs the trading engine; compose overrides for the API service.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -m quantbot version || exit 1

ENTRYPOINT ["python", "-m", "quantbot"]
CMD ["run"]
