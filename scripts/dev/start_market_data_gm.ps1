#!/usr/bin/env pwsh
# market_data_gm Windows Service Launcher
# This script runs market_data_gm as a background Windows service

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  market_data_gm Service Launcher" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Configuration (derive paths from script location, not hardcoded)
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$SERVICE_PATH = "$ProjectRoot\src\market-data-gm"
$SERVICE_DLL = "$SERVICE_PATH\bin\Debug\net8.0\market_data_gm.dll"
$LOG_DIR = "$ProjectRoot\logs\marketdata-gm"
$PID_FILE = "$LOG_DIR\marketdata-gm.pid"

# Create log directory
if (-not (Test-Path $LOG_DIR)) {
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
}

# Check if already running
if (Test-Path $PID_FILE) {
    $oldPid = Get-Content $PID_FILE -ErrorAction SilentlyContinue
    if ($oldPid) {
        $process = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "[STATUS] market_data_gm is already running (PID: $oldPid)" -ForegroundColor Yellow
            $response = Read-Host "Stop existing instance and restart? (y/N)"
            if ($response -eq 'y' -or $response -eq 'Y') {
                Write-Host "[STOP] Stopping existing instance..." -ForegroundColor Yellow
                Stop-Process -Id $oldPid -Force
                Start-Sleep -Seconds 2
            } else {
                Write-Host "[ABORT] Operation cancelled" -ForegroundColor Red
                exit 1
            }
        }
    }
}

Write-Host "[INFO] Starting market_data_gm service..." -ForegroundColor Green
Write-Host "[INFO] Logs: $LOG_DIR\gm-market-data\gm-market-data-realtime.log" -ForegroundColor Green
Write-Host ""

# Check if dll exists
if (-not (Test-Path $SERVICE_DLL)) {
    Write-Host "[ERROR] market_data_gm.dll not found: $SERVICE_DLL" -ForegroundColor Red
    Write-Host "[INFO] Please build the project first: dotnet build" -ForegroundColor Yellow
    exit 1
}

# Load environment variables from .env file
$envFile = "$PSScriptRoot\..\..\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            # Map .env variables to application config format
            if ($name -eq 'GM_TOKEN') {
                [Environment]::SetEnvironmentVariable('GM__GmToken', $value)
            }
            elseif ($name -eq 'KAFKA_BOOTSTRAP_SERVERS') {
                [Environment]::SetEnvironmentVariable('Kafka__BootstrapServers', $value)
            }
            else {
                [Environment]::SetEnvironmentVariable($name, $value)
            }
        }
    }
}

# Start the service in background using Start-Process (non-blocking)
$process = Start-Process -FilePath "dotnet" -ArgumentList $SERVICE_DLL -WorkingDirectory $SERVICE_PATH -WindowStyle Hidden -PassThru -Environment @{
    GM__GmToken = $env:GM_TOKEN
    Kafka__BootstrapServers = $env:KAFKA_BOOTSTRAP_SERVERS
}

# Save PID immediately (don't wait for initialization)
$process.Id | Out-File -FilePath $PID_FILE -Force -Encoding ASCII

Write-Host "[SUCCESS] market_data_gm started!" -ForegroundColor Green
Write-Host "[INFO] PID: $($process.Id)" -ForegroundColor Green
Write-Host "[INFO] GM SDK is initializing in background (may take 5-10 minutes)..." -ForegroundColor Yellow
Write-Host "[INFO] Check logs to monitor initialization progress" -ForegroundColor Yellow
Write-Host "[INFO] To stop: .\scripts\dev\stop_market_data_gm.ps1" -ForegroundColor Yellow
Write-Host "[INFO] Monitor logs: Get-Content '$LOG_DIR\gm-market-data\*.log' -Tail 20" -ForegroundColor Yellow
Write-Host ""

Write-Host "[DONE] market_data_gm is starting in background" -ForegroundColor Green
