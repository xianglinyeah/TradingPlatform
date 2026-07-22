# Import (or update) the paper-trading dashboard into local Grafana.
# Grafana admin creds come from the deployment env (GF_SECURITY_ADMIN_PASSWORD).
param(
    [string]$File = "$PSScriptRoot\grafana\hft-paper-trading.json",
    [string]$GrafanaUrl = "http://localhost:3000"
)
$ErrorActionPreference = "Stop"

$envJson = kubectl get deployment grafana -n infrastructure -o jsonpath="{.spec.template.spec.containers[0].env}" | ConvertFrom-Json
$user = ($envJson | Where-Object name -eq "GF_SECURITY_ADMIN_USER").value
$pass = ($envJson | Where-Object name -eq "GF_SECURITY_ADMIN_PASSWORD").value
$auth = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${user}:${pass}"))

$dashboard = Get-Content $File -Raw -Encoding UTF8 | ConvertFrom-Json
$payload = @{ dashboard = $dashboard; overwrite = $true; message = "import via scripts/reporting/import_dashboard.ps1" } | ConvertTo-Json -Depth 32

$resp = Invoke-WebRequest -Uri "$GrafanaUrl/api/dashboards/db" -Method Post -Headers @{Authorization = $auth} -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -ContentType "application/json" -UseBasicParsing
$result = $resp.Content | ConvertFrom-Json
Write-Host "status=$($result.status) url=$GrafanaUrl$($result.url)"
