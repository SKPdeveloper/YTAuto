@echo off
REM ============================================================================
REM Edible House Automator - Main Launcher
REM ============================================================================

:menu
cls
echo ================================================================
echo          EDIBLE HOUSE AUTOMATOR v2.0
echo          AI Video Generation Pipeline
echo ================================================================
echo.
echo   [1] Web UI           - Start web interface (localhost:8000)
echo   [2] Pipeline (FREE)  - Run pipeline with free topic
echo   [3] Pipeline (TOPIC) - Run pipeline with specific topic
echo   [4] Video Gen        - Generate video for project
echo   [5] Resume           - Resume project
echo.
echo   [S] Setup            - Setup and installation
echo   [Q] Quit             - Exit
echo.
echo ----------------------------------------------------------------
set /p choice="Select option: "

if /i "%choice%"=="1" goto web
if /i "%choice%"=="2" goto pipeline_free
if /i "%choice%"=="3" goto pipeline_topic
if /i "%choice%"=="4" goto video_gen
if /i "%choice%"=="5" goto resume
if /i "%choice%"=="s" goto setup
if /i "%choice%"=="q" goto end
goto menu

:check_env
cd /d "%~dp0"
if exist "python\python.exe" (
    set PYTHON=python\python.exe
) else if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)
if not exist config\.env (
    echo.
    echo ERROR: config\.env not found!
    echo Please run Setup first or copy config\.env.example to config\.env
    pause
    goto menu
)
goto :eof

:web
call :check_env
echo.
echo ================================================================
echo   Starting Web UI...
echo   Local:   http://localhost:8000
echo   Control: http://localhost:8000/control
echo ================================================================
echo.
%PYTHON% run_web.py
pause
goto menu

:pipeline_free
call :check_env
echo.
echo ================================================================
echo   Starting Pipeline with FREE topic...
echo   AI will generate a random topic
echo ================================================================
echo.
%PYTHON% run_real_pipeline.py --free -y
pause
goto menu

:pipeline_topic
call :check_env
echo.
echo ================================================================
echo   Enter topic for video generation:
echo ================================================================
echo.
set /p topic="Topic: "
if "%topic%"=="" (
    echo No topic entered!
    pause
    goto menu
)
echo.
echo Starting pipeline with topic: %topic%
echo.
%PYTHON% run_real_pipeline.py "%topic%" -y
pause
goto menu

:video_gen
call :check_env
echo.
echo ================================================================
echo   Video Generation for existing project
echo ================================================================
echo.
echo Available projects:
dir /b projects\proj_* 2>nul
echo.
set /p project_id="Enter project ID (e.g., proj_abc123): "
if "%project_id%"=="" (
    echo No project ID entered!
    pause
    goto menu
)
echo.
echo Generating videos for: %project_id%
echo.
%PYTHON% run_video_gen.py %project_id%
pause
goto menu

:resume
call :check_env
echo.
echo ================================================================
echo   Resume existing project
echo ================================================================
echo.
echo Available projects:
dir /b projects\proj_* 2>nul
echo.
set /p project_id="Enter project ID to resume: "
if "%project_id%"=="" (
    echo No project ID entered!
    pause
    goto menu
)
echo.
echo Resuming project: %project_id%
echo.
%PYTHON% run_real_pipeline.py --resume %project_id% -y
pause
goto menu

:setup
echo.
call setup.bat
goto menu

:end
echo.
echo Goodbye!
exit /b 0
