# Shared ClickHouse HTTP helper for reporting scripts. Dot-source this file.
# Endpoint: Rancher Desktop ClickHouse forwarded to localhost:8123.
# Credentials: user dev_user; password read from the k8s secret so nothing
# lands in files or shell history.

$script:ChUrl = "http://localhost:8123"
$script:ChUser = "dev_user"

function Get-ChPassword {
    if (-not $script:ChPassword) {
        $b64 = kubectl get secret db-credentials -n infrastructure -o jsonpath="{.data.clickhouse-password}"
        if (-not $b64) { throw "Cannot read ClickHouse password from k8s secret db-credentials" }
        $script:ChPassword = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64))
    }
    $script:ChPassword
}

# Run a query. -Body, if given, is posted as the request body with the query
# in the URL (the INSERT ... FORMAT JSONEachRow pattern).
function Invoke-Ch {
    param(
        [Parameter(Mandatory)][string]$Query,
        [string]$Body,
        [string]$BodyFile
    )
    $headers = @{
        "X-ClickHouse-User" = $script:ChUser
        "X-ClickHouse-Key"  = Get-ChPassword
    }
    $uri = "$script:ChUrl/?query=$([uri]::EscapeDataString($Query))"
    if ($BodyFile) {
        (Invoke-WebRequest -Uri $uri -Method Post -Headers $headers -InFile $BodyFile -ContentType "text/plain; charset=utf-8" -UseBasicParsing -TimeoutSec 300).Content
    } elseif ($null -ne $Body -and $Body -ne "") {
        (Invoke-WebRequest -Uri $uri -Method Post -Headers $headers -Body ([Text.Encoding]::UTF8.GetBytes($Body)) -ContentType "text/plain; charset=utf-8" -UseBasicParsing -TimeoutSec 300).Content
    } else {
        # Always POST: the CH HTTP interface treats GET as readonly, which
        # rejects DDL/INSERT. Query goes in the body.
        (Invoke-WebRequest -Uri $script:ChUrl -Method Post -Headers $headers -Body ([Text.Encoding]::UTF8.GetBytes($Query)) -ContentType "text/plain; charset=utf-8" -UseBasicParsing -TimeoutSec 300).Content
    }
}
