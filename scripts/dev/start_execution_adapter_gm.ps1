# Start execution_adapter_gm service
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ExePath = "$ProjectRoot\src\execution-adapter-gm\bin\Release\net8.0\execution_adapter_gm.exe"

Write-Host "[START] Starting execution_adapter_gm..." -ForegroundColor Green

# Check whether process is already running
$ExistingProcess = Get-Process -Name "execution_adapter_gm" -ErrorAction SilentlyContinue
if ($ExistingProcess) {
    Write-Host "[WARN] execution_adapter_gm is already running (PID: $($ExistingProcess.Id))" -ForegroundColor Yellow
    exit 0
}

# Check whether exe file exists
if (-not (Test-Path $ExePath)) {
    Write-Host "[ERROR] Executable not found: $ExePath" -ForegroundColor Red
    Write-Host "[INFO] Please build the project first: dotnet build src\execution-adapter-gm" -ForegroundColor Yellow
    exit 1
}

# Start process
Write-Host "[INFO] Starting process: $ExePath" -ForegroundColor Cyan
$ProcessInfo = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path $ExePath) -WindowStyle Hidden -PassThru

if ($ProcessInfo) {
    Write-Host "[OK] execution_adapter_gm started (PID: $($ProcessInfo.Id))" -ForegroundColor Green
    Write-Host "[INFO] gRPC service address: http://localhost:5005" -ForegroundColor Cyan
    exit 0
} else {
    Write-Host "[ERROR] Start failed" -ForegroundColor Red
    exit 1
}