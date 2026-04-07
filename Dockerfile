FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# AWS CLI for S3 backups
RUN apt-get update && apt-get install -y --no-install-recommends awscli git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV APP_DIR=/app
# Let uv sync in the pull step reuse this venv instead of creating a new one
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# Install dependencies first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    && rm pyproject.toml uv.lock

# prefect.yaml is needed by the worker; source code comes via git_clone pull step
COPY prefect.yaml ./

# Create data and briefings directories for volume mounts
RUN mkdir -p data briefings

CMD ["uv", "run", "--no-project", "prefect", "worker", "start", "--pool", "grid-signals"]
