@echo off
REM ============================================================================
REM Edible House Automator - Web UI Server
REM ============================================================================

cd /d "%~dp0"

echo.
echo ================================================================
echo          EDIBLE HOUSE AUTOMATOR - Web UI
echo ================================================================
echo.

REM Python selection
if exist "python\python.exe" (
    set PYTHON=python\python.exe
) else if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM Check .env
if not exist config\.env (
    echo ERROR: config\.env not found!
    echo Please run setup.bat first.
    pause
    exit /b 1
)

echo Starting Web UI server...
echo.
echo ----------------------------------------------------------------
echo   Dashboard:  http://localhost:8000
echo   Control:    http://localhost:8000/control
echo   API Docs:   http://localhost:8000/docs
echo ----------------------------------------------------------------
echo.
echo Press Ctrl+C to stop the server.
echo.

%PYTHON% run_web.py --host 0.0.0.0

pause
