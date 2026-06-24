#!/usr/bin/env pwsh
# Stop market_data_gm Windows Service

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Stop market_data_gm Service" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Derive path from script location
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$PID_FILE = "$ProjectRoot\logs\marketdata-gm\marketdata-gm.pid"

if (-not (Test-Path $PID_FILE)) {
    Write-Host "[INFO] No PID file found. market_data_gm may not be running." -ForegroundColor Yellow
    exit 0
}

$servicePid = Get-Content $PID_FILE -ErrorAction SilentlyContinue
if ($servicePid) {
    $process = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
    if ($process) {
        Write-Host "[STOP] Stopping market_data_gm (PID: $servicePid)..." -ForegroundColor Yellow
        Stop-Process -Id $servicePid -Force
        Start-Sleep -Seconds 1
        Write-Host "[SUCCESS] market_data_gm stopped" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Process $pid not found. Cleaning up PID file." -ForegroundColor Yellow
    }
}

# Remove PID file
Remove-Item $PID_FILE -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "[DONE] Service stopped" -ForegroundColor Green
