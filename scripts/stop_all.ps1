#!/usr/bin/env pwsh
# Stop the AI Employee Orchestrator
# Usage: .\scripts\stop_all.ps1 [-RemoveSchedule]

[CmdletBinding()]
param(
    [switch]$RemoveSchedule,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    Write-Host "Usage: .\scripts\stop_all.ps1 [-RemoveSchedule]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -RemoveSchedule  Also remove the Windows scheduled task"
    Write-Host "  -Help            Show this help message"
    exit 0
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$lockFile = Join-Path $projectRoot "config/.orchestrator.lock"

# Stop via lock file PID
if (Test-Path $lockFile) {
    $content = Get-Content $lockFile -Raw
    $pidMatch = [regex]::Match($content, 'PID:\s*(\d+)')

    if ($pidMatch.Success) {
        $pid = [int]$pidMatch.Groups[1].Value

        try {
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "Stopping orchestrator (PID: $pid)..."
                Stop-Process -Id $pid -Force
                Write-Host "Orchestrator stopped."
            } else {
                Write-Host "Process $pid not found (already stopped?)."
            }
        } catch {
            Write-Host "Could not stop process $pid`: $_"
        }
    }

    Remove-Item $lockFile -Force
    Write-Host "Lock file removed."
} else {
    Write-Host "No lock file found at $lockFile — orchestrator may not be running."
}

# Stop background PowerShell jobs
Get-Job | Where-Object { $_.Command -like '*backend.orchestrator*' } | ForEach-Object {
    Write-Host "Stopping background job $($_.Id)..."
    Stop-Job -Id $_.Id
    Remove-Job -Id $_.Id
}

# Remove scheduled task if requested
if ($RemoveSchedule) {
    $taskName = "AIEmployee-Orchestrator"
    try {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($task) {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Host "Scheduled task '$taskName' removed."
        } else {
            Write-Host "Scheduled task '$taskName' not found."
        }
    } catch {
        Write-Host "Error removing scheduled task: $_"
    }
}
