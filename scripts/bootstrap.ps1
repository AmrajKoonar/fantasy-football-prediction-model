# Install Python and Node dependencies (Windows PowerShell)
$ErrorActionPreference = "Stop"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".\python\[dev]"
Copy-Item -Force .env.example .env
Set-Location web
npm install
Set-Location ..
Write-Host "Bootstrap complete. Run: python -m fantasy_football_prediction_model.cli pipeline run-all --fixture"
