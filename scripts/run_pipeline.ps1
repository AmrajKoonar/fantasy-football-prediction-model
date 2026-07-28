# Run fixture or full pipeline (Windows)
param(
  [switch]$Fixture
)
$ErrorActionPreference = "Stop"
.\.venv\Scripts\Activate.ps1
if ($Fixture) {
  python -m fantasy_football_prediction_model.cli pipeline run-all --fixture
} else {
  python -m fantasy_football_prediction_model.cli pipeline run-all
}
