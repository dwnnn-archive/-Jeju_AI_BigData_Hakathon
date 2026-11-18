# Registers a Windows Task Scheduler job that collects recent ASOS observations once a day (03:30).
# ASOS only serves data up to the previous day, so one run a day is enough. The collector fetches the
# previous and current month into runtime\asos_recent (it never touches the training folder runtime\asos).
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File backend\scripts\register_asos_task.ps1
#   powershell -ExecutionPolicy Bypass -File backend\scripts\register_asos_task.ps1 -Remove
#
# - Runs as the current user, only while that user is logged on (no password is stored).
# - If the PC was off, the missed run starts as soon as possible and the collector catches up
#   on issues from the last ~70 hours (KMA only serves about 72 hours).
# - Log: backend\runtime\collect.log. Run it once by hand:
#   Start-ScheduledTask -TaskName JejuForecastArchive-Collect
param(
    [switch]$Remove,
    [string]$TaskName = "JejuForecastArchive-ASOS"
)
$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    "removed: $TaskName"
    return
}

$script = Join-Path $PSScriptRoot "collect_asos_recent.cmd"
if (-not (Test-Path -LiteralPath $script)) { throw "not found: $script" }
$backend = Split-Path $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $backend ".venv\Scripts\python.exe"))) {
    throw "backend\.venv is missing. Run 'uv sync --frozen --extra dev --extra ml' in backend first."
}
if (-not (Test-Path -LiteralPath (Join-Path $backend ".env"))) {
    Write-Warning "backend\.env is missing: collection needs ASOS_API_KEY there."
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -Daily -At "03:30"
$action = New-ScheduledTaskAction -Execute $script -WorkingDirectory $backend
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description "Jeju ASOS observation collection once a day. Remove: register_asos_task.ps1 -Remove" | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $TaskName
"registered: $TaskName (user $user), next run: $($info.NextRunTime)"
