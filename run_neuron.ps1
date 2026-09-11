<#
.SYNOPSIS
    Neuron AI Windows PowerShell Launcher (Block 8)

.DESCRIPTION
    Launches the Neuron AI desktop shell application with optional demo mode,
    readiness pre-flight checks, and demo context launching.

.PARAMETER DemoMode
    Tutor reasoning mode: 'auto' (live-first with deterministic fallback),
    'fallback' (100% offline deterministic scenarios), or 'live' (direct Gemini LLM only).

.PARAMETER CheckReadiness
    Run readiness diagnostic checks before launching.

.PARAMETER LaunchDemo
    Pre-open a demo scenario context: '1' (Calculus), '2' (Discrete Math PDF), '3' (Coding Bug).

.EXAMPLE
    .\run_neuron.ps1 -DemoMode auto
    .\run_neuron.ps1 -CheckReadiness
    .\run_neuron.ps1 -LaunchDemo 1 -DemoMode fallback
#>

param (
    [ValidateSet("auto", "live", "fallback")]
    [string]$DemoMode = "auto",

    [switch]$CheckReadiness,

    [ValidateSet("1", "2", "3")]
    [string]$LaunchDemo = "",

    [switch]$Help
)

if ($Help) {
    Get-Help $PSCommandPath -Detailed
    exit 0
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Locate Python
$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = Join-Path $ScriptDir "venv\Scripts\python.exe"
    if (-not (Test-Path $PythonExe)) {
        $PythonExe = "python"
    }
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "                NEURON AI — AMBIENT TUTOR                  " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " [Python]   : $PythonExe" -ForegroundColor Gray
Write-Host " [Mode]     : $DemoMode" -ForegroundColor Yellow
Write-Host " [Hotkey]   : Ctrl+Shift+Space" -ForegroundColor Green
Write-Host " [Wake Word]: 'Hey Neuron'" -ForegroundColor Green
Write-Host " [Dismiss]  : Escape" -ForegroundColor Red
Write-Host "============================================================" -ForegroundColor Cyan

# Set demo mode environment variable
$env:NEURON_DEMO_MODE = $DemoMode

# Pre-flight readiness check if requested
if ($CheckReadiness) {
    Write-Host "`nRunning Pre-Flight Readiness Diagnostics..." -ForegroundColor Magenta
    & $PythonExe "scripts/check_readiness.py"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "One or more readiness checks reported issues."
    }
}

# Launch demo context if specified
if ($LaunchDemo) {
    Write-Host "`nLaunching Demo Context Scenario $LaunchDemo..." -ForegroundColor Cyan
    & $PythonExe "demo/run_demo.py" $LaunchDemo
}

# Start Neuron Application
Write-Host "`nStarting Neuron Desktop Shell..." -ForegroundColor Green
& $PythonExe "main.py"
$ExitCode = $LASTEXITCODE

Write-Host "`nNeuron AI exited with code: $ExitCode" -ForegroundColor Gray
exit $ExitCode
