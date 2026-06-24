<#
.SYNOPSIS
    Daily incremental data update - fundamentals + kline (minute + daily)
    Called by Windows Task Scheduler every weekday at 18:00.

.DESCRIPTION
    1. Pre-check: GM daemon (7001) + PostgreSQL (5432) + ClickHouse (32123)
    2. Build data_ingestion (if needed)
    3. Execute in order:
       a) fundamentals_incremental  (fundamentals Pt mode, 50-100x faster)
       b) kline_incremental          (minute bars + daily bars, dual write Parquet + ClickHouse)
    4. Log output to logs/daily_incremental_YYYYMMDD.log

.NOTES
    Dependencies:
    - GM daemon running on 127.0.0.1:7001 (Windows local process, must be manually kept running)
    - k8s (Rancher Desktop) running, ClickHouse NodePort 32123 automatically exposed
    - PG port-forward 5432 (if not running, script will start it automatically)
#>

$ErrorActionPreference = "Continue"
# Derive project root from script location instead of hardcoding
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ConfigPath = "$ProjectRoot\src\data-ingestion\config.yaml"
$DllPath = "$ProjectRoot\src\data-ingestion\bin\Debug\net8.0\data_ingestion.dll"
$LogFile = "$ProjectRoot\logs\daily_incremental_$(Get-Date -Format 'yyyyMMdd').log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts][$Level] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Test-Port {
    param([int]$Port, [int]$TimeoutMs = 2000)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if ($ok) { $tcp.EndConnect($iar); $tcp.Close(); return $true }
        $tcp.Close()
        return $false
    } catch { return $false }
}

function Ensure-PortForward {
    param([string]$Service, [string]$Namespace, [int]$LocalPort)
    if (Test-Port -Port $LocalPort) {
        Write-Log "port-forward $Service already up (localhost:$LocalPort)"
        return $true
    }
    Write-Log "Starting port-forward for $Service..." "WARN"
    Start-Process -FilePath "kubectl" `
        -ArgumentList "port-forward", "-n", $Namespace, "svc/$Service", "${LocalPort}:${LocalPort}" `
        -WindowStyle Hidden `
        -RedirectStandardError "$ProjectRoot\logs\pf_${Service}.err" `
        -RedirectStandardOutput "$ProjectRoot\logs\pf_${Service}.out" -PassThru | Out-Null
    Start-Sleep -Seconds 3
    if (Test-Port -Port $LocalPort) {
        Write-Log "port-forward $Service started"
        return $true
    }
    Write-Log "Failed to start port-forward for $Service" "ERROR"
    return $false
}

function Run-Mode {
    param([string]$Mode, [string]$Label)
    Write-Log "--- $Label ---"
    $stepStart = Get-Date
    & dotnet $DllPath $ConfigPath --mode=$Mode 2>&1 | ForEach-Object {
        Write-Log "$_"
    }
    $exitCode = $LASTEXITCODE
    $elapsed = [math]::Round(((Get-Date) - $stepStart).TotalSeconds)
    if ($exitCode -ne 0) {
        Write-Log "$Label FAILED (exit=$exitCode, ${elapsed}s)" "ERROR"
        return $false
    }
    Write-Log "$Label completed (${elapsed}s)"
    return $true
}

# ============================================================================
# 0. Setup
# ============================================================================
Set-Location $ProjectRoot
$logDir = Split-Path $LogFile -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$globalStart = Get-Date
Write-Log "=========================================="
Write-Log "Daily incremental update starting"
Write-Log "=========================================="

# ============================================================================
# 1. Pre-flight checks
# ============================================================================

# 1a. GM daemon (critical — can't auto-start, requires manual launch of GM terminal)
if (-not (Test-Port -Port 7001)) {
    Write-Log "GM daemon not reachable on 127.0.0.1:7001. Aborting." "ERROR"
    Write-Log "Please start GM terminal manually and re-run." "ERROR"
    exit 1
}
Write-Log "Pre-check: GM daemon OK (port 7001)"

# 1b. PostgreSQL port-forward
if (-not (Ensure-PortForward -Service "postgres" -Namespace "infrastructure" -LocalPort 5432)) {
    Write-Log "PostgreSQL not reachable. Aborting." "ERROR"
    exit 1
}

# 1c. ClickHouse (NodePort 32123, always up if k8s runs)
if (-not (Test-Port -Port 32123)) {
    Write-Log "ClickHouse NodePort 32123 not reachable. Is Rancher Desktop running?" "ERROR"
    exit 1
}
Write-Log "Pre-check: ClickHouse OK (NodePort 32123)"

# ============================================================================
# 2. Build (ensure latest code is compiled)
# ============================================================================
Write-Log "Building data_ingestion..."
$buildStart = Get-Date
& dotnet build "$ProjectRoot\src\data-ingestion\data_ingestion.csproj" --nologo 2>&1 | ForEach-Object {
    if ($_ -match "error|Error") { Write-Log "BUILD: $_" "ERROR" }
    elseif ($_ -match "Build succeeded") { Write-Log "BUILD: $_" }
}
$buildExit = $LASTEXITCODE
$buildElapsed = [math]::Round(((Get-Date) - $buildStart).TotalSeconds)
if ($buildExit -ne 0) {
    Write-Log "Build failed (exit=$buildExit, ${buildElapsed}s). Aborting." "ERROR"
    exit 1
}
Write-Log "Build OK (${buildElapsed}s)"

# ============================================================================
# 3. Run incremental updates
# ============================================================================
$ok1 = Run-Mode -Mode "fundamentals_incremental" -Label "Step 1/2: fundamentals_incremental"
$ok2 = Run-Mode -Mode "kline_incremental" -Label "Step 2/2: kline_incremental"

# ============================================================================
# 4. Summary
# ============================================================================
$totalMin = [math]::Round(((Get-Date) - $globalStart).TotalMinutes, 1)
Write-Log "=========================================="
Write-Log "Daily incremental update finished (${totalMin} min total)"
Write-Log "  fundamentals_incremental: $(if ($ok1) {'OK'} else {'FAILED'})"
Write-Log "  kline_incremental:         $(if ($ok2) {'OK'} else {'FAILED'})"
Write-Log "=========================================="

if (-not $ok1 -or -not $ok2) { exit 1 }
exit 0
