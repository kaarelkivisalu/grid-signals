FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy project source
COPY src/ src/
COPY prefect.yaml ./
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "prefect", "worker", "start", "--pool", "default-agent-pool"]
