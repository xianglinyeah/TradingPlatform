# Stop execution_adapter_gm service
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "STOP execution_adapter_gm"

# Find process
$Process = Get-Process -Name "execution_adapter_gm" -ErrorAction SilentlyContinue

if ($Process) {
    Write-Host "[INFO] Process found (PID: $($Process.Id)), stopping..." -ForegroundColor Cyan

    try {
        # Try graceful stop
        Stop-Process -Id $Process.Id -Force
        Start-Sleep -Seconds 2

        # Confirm process has stopped
        $Process = Get-Process -Name "execution_adapter_gm" -ErrorAction SilentlyContinue
        if (-not $Process) {
            Write-Host "[OK] execution_adapter_gm stopped" -ForegroundColor Green
            exit 0
        } else {
            Write-Host "[WARN] Process still running, force stopping" -ForegroundColor Yellow
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            Write-Host "[OK] execution_adapter_gm force stopped" -ForegroundColor Green
            exit 0
        }
    } catch {
        Write-Host "[ERROR] Failed to stop process: $_" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[INFO] execution_adapter_gm is not running" -ForegroundColor Cyan
    exit 0
}