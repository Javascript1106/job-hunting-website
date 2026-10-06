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
$trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Tuesday -At 1:00PM
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
    -Description "Back up and refresh the PathForge job catalog every Tuesday at 1 PM." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime, LastTaskResult, NextRunTime
