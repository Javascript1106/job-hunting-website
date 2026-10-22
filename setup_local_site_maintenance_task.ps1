param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,
    [string]$TaskName = "PathForge Site Maintenance"
)

$ErrorActionPreference = "Stop"
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$maintenanceScript = Join-Path $projectDirectory "site_maintenance.py"

if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Python was not found at: $PythonExecutable"
}
if (-not (Test-Path -LiteralPath $maintenanceScript -PathType Leaf)) {
    throw "PathForge site-maintenance script was not found at: $maintenanceScript"
}

$quotedScript = '"' + $maintenanceScript + '"'
$action = New-ScheduledTaskAction `
    -Execute $PythonExecutable `
    -Argument $quotedScript `
    -WorkingDirectory $projectDirectory
$trigger = New-ScheduledTaskTrigger -Daily -At 9:15AM
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
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
    -Description "Run local PathForge integrity, security, link, backup, and showcase-readiness checks daily." `
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
