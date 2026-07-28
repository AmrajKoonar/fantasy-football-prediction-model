#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
if [[ "${1:-}" == "--fixture" ]]; then
  python -m fantasy_football_prediction_model.cli pipeline run-all --fixture
else
  python -m fantasy_football_prediction_model.cli pipeline run-all
fi
