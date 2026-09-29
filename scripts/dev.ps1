# DevAgent Local Development Launcher (PowerShell)
param(
    [ValidateSet("backend", "frontend", "all")]
    [string]$Target = "all",
    [switch]$WithWorker = $false
)

$ErrorActionPreference = "Stop"
$WorkspaceRoot = (Resolve-Path "$PSScriptRoot\..").Path

function Start-Backend {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "  Starting DevAgent FastAPI Backend on http://127.0.0.1:8000" -ForegroundColor Cyan
    Write-Host "  API Documentation: http://127.0.0.1:8000/docs" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan
    Set-Location "$WorkspaceRoot\backend"
    if (-not (Test-Path ".venv")) {
        Write-Host "Virtualenv not found in backend/.venv. Please initialize python venv." -ForegroundColor Red
        exit 1
    }
    & ".\.venv\Scripts\uvicorn.exe" app.main:app --reload --host 127.0.0.1 --port 8000
}

function Start-Frontend {
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "  Starting DevAgent React UI on http://localhost:5173" -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Green
    Set-Location "$WorkspaceRoot\frontend"
    npm run dev -- --host
}

if ($Target -eq "backend") {
    Start-Backend
} elseif ($Target -eq "frontend") {
    Start-Frontend
} else {
    Write-Host "Launching DevAgent Backend (Port 8000) and Frontend (Port 5173)..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "Set-Location '$WorkspaceRoot'; .\scripts\dev.ps1 -Target backend"
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "Set-Location '$WorkspaceRoot'; .\scripts\dev.ps1 -Target frontend"
}
