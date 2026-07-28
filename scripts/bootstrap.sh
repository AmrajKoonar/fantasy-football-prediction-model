#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
source .venv/bin/activate
pip install -e "./python[dev]"
cp -n .env.example .env || true
(cd web && npm install)
echo "Bootstrap complete. Run: python -m fantasy_football_prediction_model.cli pipeline run-all --fixture"
