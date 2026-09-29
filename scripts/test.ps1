# Run DevAgent backend tests
param(
    [string]$Marker = "not docker and not db"
)

$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\backend"
Write-Host "Running pytest with marker '$Marker'..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m pytest -m $Marker -v
