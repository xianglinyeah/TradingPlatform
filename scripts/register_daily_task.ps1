# Derive project root from script location
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -NoProfile -File `"$ProjectRoot\scripts\daily_incremental.ps1`"" -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 6:00PM
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "TradingPlatform_DailyIncremental" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Daily incremental: fundamentals_incremental + kline_incremental (weekdays 18:00)" -Force | Out-Null

Write-Host "Task registered successfully"
