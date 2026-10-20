param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,
    [string]$TaskName = "PathForge User Automations"
)

$ErrorActionPreference = "Stop"
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$automationScript = Join-Path $projectDirectory "run_user_automations.py"

if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Python was not found at: $PythonExecutable"
}
if (-not (Test-Path -LiteralPath $automationScript -PathType Leaf)) {
    throw "PathForge automation script was not found at: $automationScript"
}

$quotedScript = '"' + $automationScript + '"'
$action = New-ScheduledTaskAction `
    -Execute $PythonExecutable `
    -Argument $quotedScript `
    -WorkingDirectory $projectDirectory
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00AM
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
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
    -Description "Create PathForge job alerts and tracker reminders every day at 9 AM." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime, LastTaskResult, NextRunTime
