@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Neuron AI — Windows Desktop Launcher (Block 8)
REM ============================================================================

title Neuron AI — Multimodal Ambient Tutor

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Detect virtual environment python
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
) else if exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo [NEURON] Starting Neuron AI Desktop Application...
echo [NEURON] Python Interpreter: %PYTHON_EXE%
echo [NEURON] Application Root:   %SCRIPT_DIR%

"%PYTHON_EXE%" main.py %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo [NEURON] Application exited with error code: %EXIT_CODE%
    pause
)

exit /b %EXIT_CODE%
