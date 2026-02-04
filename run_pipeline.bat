@echo off
REM ============================================================================
REM Edible House Automator - Pipeline Runner (No UI)
REM Run full pipeline without web interface
REM
REM Usage:
REM   run_pipeline.bat                    - Run with free topic
REM   run_pipeline.bat "Chocolate Castle" - Run with specific topic
REM   run_pipeline.bat --resume proj_xxx  - Resume project
REM ============================================================================

cd /d "%~dp0"

echo.
echo ================================================================
echo          EDIBLE HOUSE AUTOMATOR - Pipeline
echo          Headless Mode (No UI)
echo ================================================================
echo.

REM Вибір Python
if exist "python\python.exe" (
    set PYTHON=python\python.exe
    echo Using: Portable Python
) else if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
    echo Using: Virtual Environment
) else (
    set PYTHON=python
    echo Using: System Python
)

REM Перевірка .env
if not exist config\.env (
    echo.
    echo ERROR: config\.env not found!
    echo Please copy config\.env.example to config\.env and configure API keys.
    echo.
    pause
    exit /b 1
)

echo.
echo ----------------------------------------------------------------

REM Обробка аргументів
if "%~1"=="" (
    echo Mode: FREE topic (AI will choose)
    echo.
    %PYTHON% run_real_pipeline.py --free -y
) else if "%~1"=="--resume" (
    if "%~2"=="" (
        echo ERROR: --resume requires project_id
        echo Usage: run_pipeline.bat --resume proj_xxx
        pause
        exit /b 1
    )
    echo Mode: RESUME project %~2
    echo.
    %PYTHON% run_real_pipeline.py --resume %~2 -y
) else if "%~1"=="--free" (
    echo Mode: FREE topic (AI will choose)
    echo.
    %PYTHON% run_real_pipeline.py --free -y
) else (
    echo Mode: Custom topic
    echo Topic: %*
    echo.
    %PYTHON% run_real_pipeline.py %* -y
)

echo.
echo ----------------------------------------------------------------
echo Pipeline finished.
echo.
pause
