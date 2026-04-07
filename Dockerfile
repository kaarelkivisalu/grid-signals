FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# AWS CLI for S3 backups, postgresql-client for pg_dump
RUN apt-get update && apt-get install -y --no-install-recommends awscli git postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV APP_DIR=/app
# Let uv sync in the pull step reuse this venv instead of creating a new one
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# Install dependencies first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy project source and install it
COPY src/ src/
COPY prefect.yaml ./
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "prefect", "worker", "start", "--pool", "grid-signals"]
