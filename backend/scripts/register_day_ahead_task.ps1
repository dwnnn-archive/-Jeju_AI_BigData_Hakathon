# Registers a Windows Task Scheduler job that runs the day-ahead analysis once a day (17:30),
# so judgement records (evaluations) accumulate in runtime\forecasts.sqlite.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File backend\scripts\register_day_ahead_task.ps1
#   powershell -ExecutionPolicy Bypass -File backend\scripts\register_day_ahead_task.ps1 -Remove
#
# - Runs as the current user, only while that user is logged on (no password is stored).
# - The script targets tomorrow and only runs between 17:15 and 23:50. If the PC was off and the
#   task starts late as a catch-up, the script skips that day (the judgement record is not recovered).
# - Log: backend\runtime\collect.log. Run it once by hand:
#   Start-ScheduledTask -TaskName JejuDayAhead-Analysis
param(
    [switch]$Remove,
    [string]$TaskName = "JejuDayAhead-Analysis"
)
$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    "removed: $TaskName"
    return
}

$script = Join-Path $PSScriptRoot "run_day_ahead.cmd"
if (-not (Test-Path -LiteralPath $script)) { throw "not found: $script" }
$backend = Split-Path $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $backend ".venv\Scripts\python.exe"))) {
    throw "backend\.venv is missing. Run 'uv sync --frozen --extra dev --extra ml' in backend first."
}
if (-not (Test-Path -LiteralPath (Join-Path $backend ".env"))) {
    Write-Warning "backend\.env is missing: the analysis needs KMA_API_KEY there."
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -Daily -At "17:30"
$action = New-ScheduledTaskAction -Execute $script -WorkingDirectory $backend
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description "Jeju day-ahead analysis once a day (17:30). Remove: register_day_ahead_task.ps1 -Remove" | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $TaskName
"registered: $TaskName (user $user), next run: $($info.NextRunTime)"
