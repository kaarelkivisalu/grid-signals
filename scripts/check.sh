#!/usr/bin/env bash
# Run the same checks locally and in GitHub Actions.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."

usage() {
    echo "Usage: bash scripts/check.sh [all|lint|test|demo|runner]"
    echo "Default: all. Image checks require a running Docker daemon."
}

if (( $# > 1 )); then
    usage >&2
    exit 2
fi

check="${1:-all}"
case "$check" in
    all|lint|test|demo|runner) ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

if [[ "$check" == all || "$check" == demo || "$check" == runner ]] && ! docker info > /dev/null 2>&1; then
    echo "Docker is required for $check checks. Start Docker and ensure your user can access it." >&2
    exit 1
fi

if [[ "$check" != demo && "$check" != runner ]]; then
    uv sync --frozen --group research
fi

if [[ "$check" == all || "$check" == lint ]]; then
    uv run --frozen python -m ruff check .
    uv run --frozen python -m ruff format --check --diff .
fi

if [[ "$check" == all || "$check" == test ]]; then
    uv run --frozen python -m pytest --tb=short --cov=grid_signals --cov-report=term-missing
fi

if [[ "$check" == all || "$check" == demo ]]; then
    docker build -f Dockerfile.demo -t grid-signals-demo:ci .
    docker run --rm -i --network none --entrypoint python grid-signals-demo:ci < tests/demo_image_check.py
fi

if [[ "$check" == all || "$check" == runner ]]; then
    docker build -f Dockerfile.runner -t grid-signals-runner:ci .
    docker run --rm -i --network none --entrypoint python grid-signals-runner:ci < tests/runner_image_check.py
fi
