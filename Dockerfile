FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# AWS CLI for S3 backups
RUN apt-get update && apt-get install -y --no-install-recommends awscli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy project source
COPY src/ src/
COPY prefect.yaml ./
RUN uv sync --frozen --no-dev

# Create data and briefings directories for volume mounts
RUN mkdir -p data briefings

CMD ["uv", "run", "prefect", "worker", "start", "--pool", "grid-signals"]
