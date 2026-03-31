#!/usr/bin/env pwsh
# Start the AI Employee Orchestrator
# Usage: .\scripts\start_all.ps1 [-Background] [-DryRun]

[CmdletBinding()]
param(
    [switch]$Background,
    [switch]$DryRun,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    Write-Host "Usage: .\scripts\start_all.ps1 [-Background] [-DryRun]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Background  Run orchestrator in the background"
    Write-Host "  -DryRun      Start in dry-run mode (no real actions)"
    Write-Host "  -Help        Show this help message"
    exit 0
}

# Find project root
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

# Build command
$uvArgs = @("run", "python", "-m", "backend.orchestrator")
if ($DryRun) {
    $uvArgs += "--dry-run"
}

Write-Host "Starting AI Employee Orchestrator..."
Write-Host "  Project: $projectRoot"
Write-Host "  Dry Run: $DryRun"
Write-Host "  Background: $Background"

if ($Background) {
    # Start as background job
    $job = Start-Job -ScriptBlock {
        param($root, $args)
        Set-Location $root
        & uv @args
    } -ArgumentList $projectRoot, $uvArgs

    Write-Host "Orchestrator started in background (Job ID: $($job.Id))"
    Write-Host "Use 'Get-Job $($job.Id)' to check status"
    Write-Host "Use '.\scripts\stop_all.ps1' to stop"
} else {
    Write-Host "Press Ctrl+C to stop."
    Write-Host ""
    & uv @uvArgs
}
