#!/usr/bin/env pwsh
# Register AI Employee Orchestrator with Windows Task Scheduler
# Usage: .\scripts\setup_scheduler.ps1 [-Remove]
# Requires: Administrator privileges for scheduled task registration

[CmdletBinding()]
param(
    [switch]$Remove,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    Write-Host "Usage: .\scripts\setup_scheduler.ps1 [-Remove]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Remove  Remove the scheduled task instead of creating it"
    Write-Host "  -Help    Show this help message"
    Write-Host ""
    Write-Host "Creates a Windows scheduled task that:"
    Write-Host "  - Starts the orchestrator on user logon"
    Write-Host "  - Restarts on failure (up to 3 times)"
    exit 0
}

$taskName = "AIEmployee-Orchestrator"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

if ($Remove) {
    try {
        $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Host "Scheduled task '$taskName' removed."
        } else {
            Write-Host "Scheduled task '$taskName' not found."
        }
    } catch {
        Write-Error "Failed to remove scheduled task: $_"
    }
    exit 0
}

# Find uv executable
$uvPath = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uvPath) {
    Write-Error "uv not found in PATH. Please install uv first."
    exit 1
}

# Build action: run uv in the project directory
$action = New-ScheduledTaskAction `
    -Execute $uvPath `
    -Argument "run python -m backend.orchestrator" `
    -WorkingDirectory $projectRoot

# Trigger: on user logon
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn

# Settings: restart on failure, don't stop on idle
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd

# Check for existing task
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Updating existing scheduled task '$taskName'..."
    Set-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggerLogon -Settings $settings | Out-Null
} else {
    Write-Host "Creating scheduled task '$taskName'..."
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggerLogon `
        -Settings $settings `
        -Description "AI Employee Orchestrator - starts watchers and action executor on logon" | Out-Null
}

Write-Host ""
Write-Host "Scheduled task '$taskName' registered successfully!"
Write-Host "  Trigger: At user logon"
Write-Host "  Restart: Up to 3 times on failure (1 min interval)"
Write-Host "  Working Directory: $projectRoot"
Write-Host ""
Write-Host "Verify: Get-ScheduledTask -TaskName '$taskName'"
Write-Host "Remove: .\scripts\setup_scheduler.ps1 -Remove"
