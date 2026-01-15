@echo off
chcp 65001 >nul
REM ============================================================================
REM Edible House Automator - Setup Script
REM Перший запуск: створює venv та встановлює dependencies
REM ============================================================================

cd /d "%~dp0"

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║         EDIBLE HOUSE AUTOMATOR - Setup                       ║
echo ║         Version 2.0                                          ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

REM ============================================================================
REM [1/6] Перевірка Python
REM ============================================================================
echo [1/6] Checking Python installation...

REM Спочатку перевіряємо portable Python
if exist "python\python.exe" (
    set PYTHON=python\python.exe
    echo Found: Portable Python
    %PYTHON% --version
    goto :python_ok
)

REM Потім системний Python
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python not found!
    echo.
    echo Please either:
    echo   1. Install Python 3.11+ and add to PATH
    echo   2. Run install_python.bat to download portable Python
    echo.
    pause
    exit /b 1
)
set PYTHON=python
python --version
:python_ok
echo.

REM ============================================================================
REM [2/6] Створення virtual environment (якщо немає portable)
REM ============================================================================
echo [2/6] Setting up environment...

if exist "python\python.exe" (
    echo Using portable Python - no venv needed
) else (
    if exist venv (
        echo Virtual environment already exists.
    ) else (
        echo Creating virtual environment...
        python -m venv venv
        if errorlevel 1 (
            echo ERROR: Failed to create virtual environment
            pause
            exit /b 1
        )
        echo Virtual environment created!
    )
    set PYTHON=venv\Scripts\python.exe
    call venv\Scripts\activate.bat
)
echo.

REM ============================================================================
REM [3/6] Встановлення dependencies
REM ============================================================================
echo [3/6] Installing dependencies...
%PYTHON% -m pip install --upgrade pip -q
%PYTHON% -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo Dependencies installed successfully!
echo.

REM ============================================================================
REM [4/6] Створення директорій
REM ============================================================================
echo [4/6] Creating directories...
if not exist "projects" mkdir projects
if not exist "logs" mkdir logs
if not exist "data" mkdir data
echo Directories ready!
echo.

REM ============================================================================
REM [5/6] Налаштування конфігурації
REM ============================================================================
echo [5/6] Setting up configuration...
if not exist config\.env (
    copy config\.env.example config\.env >nul
    echo.
    echo ╔══════════════════════════════════════════════════════════════╗
    echo ║   IMPORTANT: Configure your API keys!                        ║
    echo ╚══════════════════════════════════════════════════════════════╝
    echo.
    echo File config\.env has been created from template.
    echo.
    echo Required keys:
    echo   - GOOGLE_GEMINI_API_KEY     (for script generation)
    echo   - ADSPOWER_PROFILE_ID       (for browser automation)
    echo.
    echo Optional keys:
    echo   - ELEVENLABS_API_KEY        (for voiceover)
    echo   - TELEGRAM_BOT_TOKEN        (for notifications)
    echo.
) else (
    echo config\.env already exists.
)
echo.

REM ============================================================================
REM [6/6] Перевірка Topaz
REM ============================================================================
echo [6/6] Checking Topaz Video AI...
if exist "C:\Program Files\Topaz Labs LLC\Topaz Video AI\ffmpeg.exe" (
    echo Topaz Video AI: FOUND
) else (
    echo Topaz Video AI: NOT FOUND (upscaling will be skipped)
)
echo.

REM ============================================================================
REM Завершення
REM ============================================================================
echo ════════════════════════════════════════════════════════════════
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                    Setup Complete!                           ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
echo Available commands:
echo.
echo   run.bat           - Main menu (interactive)
echo   run_pipeline.bat  - Run pipeline without UI
echo   run_video.bat     - Generate videos only
echo   run_web.bat       - Start Web UI
echo.
echo Next steps:
echo   1. Edit config\.env and add your API keys
echo   2. Start AdsPower and open Higgsfield profile
echo   3. Run: run.bat
echo.
echo ════════════════════════════════════════════════════════════════
echo.
pause
