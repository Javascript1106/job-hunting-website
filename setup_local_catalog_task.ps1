param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,
    [string]$TaskName = "PathForge Catalog Sync"
)

$ErrorActionPreference = "Stop"
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$maintenanceScript = Join-Path $projectDirectory "catalog_maintenance.py"

if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Python was not found at: $PythonExecutable"
}
if (-not (Test-Path -LiteralPath $maintenanceScript -PathType Leaf)) {
    throw "PathForge maintenance script was not found at: $maintenanceScript"
}

$quotedScript = '"' + $maintenanceScript + '"'
$action = New-ScheduledTaskAction `
    -Execute $PythonExecutable `
    -Argument $quotedScript `
    -WorkingDirectory $projectDirectory
$trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Tuesday, Thursday -At 2:30PM
$trigger.StartBoundary = (Get-Date -Hour 14 -Minute 30 -Second 0).ToString("yyyy-MM-dd'T'HH:mm:ss")
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Back up and refresh the PathForge job catalog every Tuesday and Thursday at 2:30 PM." `
    -Force | Out-Null

$registeredTask = Get-ScheduledTask -TaskName $TaskName
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
[pscustomobject]@{
    TaskName = $registeredTask.TaskName
    State = $registeredTask.State
    LastRunTime = $taskInfo.LastRunTime
    LastTaskResult = $taskInfo.LastTaskResult
    NextRunTime = $taskInfo.NextRunTime
} | Format-List
