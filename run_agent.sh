#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p data logs reports

export PAPER_CAPITAL="${PAPER_CAPITAL:-50000}"
export BENCHMARK_SYMBOL="${BENCHMARK_SYMBOL:-SPY}"
export PYTHONUNBUFFERED=1

python3 agent.py
