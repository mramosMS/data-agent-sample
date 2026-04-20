# scripts/setup_local.ps1
# Local development setup for the FinSAGE agent service.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot\..

try {
    Write-Host "Setting up local development environment..." -ForegroundColor Cyan

    if (-not (Test-Path ".venv")) {
        python -m venv .venv
        Write-Host "Virtual environment created." -ForegroundColor Green
    }

    & .\.venv\Scripts\Activate.ps1

    pip install -e ".[dev]"

    if (-not (Test-Path ".env")) {
        Copy-Item ".env.template" ".env"
        Write-Host ".env created from template — fill in the required values before running." -ForegroundColor Yellow
    }

    Write-Host "Setup complete. Run 'python main.py' to start the agent service." -ForegroundColor Green
}
finally {
    Pop-Location
}
