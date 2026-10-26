#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
export PYTHONPATH="$PWD/research/src"
export MPLCONFIGDIR="${TMPDIR:-/tmp}/grid-signals-matplotlib"
export OMP_NUM_THREADS=4
export LOKY_MAX_CPU_COUNT=4
export OPENBLAS_NUM_THREADS=4
exec .venv/bin/python -m renewable_forecast.pipelines.daily "$@"
