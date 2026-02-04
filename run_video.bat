@echo off
REM ============================================================================
REM Edible House Automator - Video Generator
REM Video generation for existing project
REM
REM Usage:
REM   run_video.bat                  - Interactive project selection
REM   run_video.bat proj_abc123      - Generate for specific project
REM ============================================================================

cd /d "%~dp0"

echo.
echo ================================================================
echo          EDIBLE HOUSE AUTOMATOR - Video Generator
echo          SimpleVideoGenerator (Kling 2.6)
echo ================================================================
echo.

REM Вибір Python
if exist "python\python.exe" (
    set PYTHON=python\python.exe
) else if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM Перевірка .env
if not exist config\.env (
    echo ERROR: config\.env not found!
    pause
    exit /b 1
)

REM Обробка аргументів
if "%~1"=="" (
    echo Available projects:
    echo ----------------------------------------------------------------
    dir /b projects\proj_* 2>nul
    if errorlevel 1 (
        echo No projects found in projects\ directory.
        pause
        exit /b 1
    )
    echo ----------------------------------------------------------------
    echo.
    set /p PROJECT_ID="Enter project ID: "
) else (
    set PROJECT_ID=%~1
)

if "%PROJECT_ID%"=="" (
    echo No project ID entered!
    pause
    exit /b 1
)

REM Перевірка що проект існує
if not exist "projects\%PROJECT_ID%" (
    echo ERROR: Project not found: projects\%PROJECT_ID%
    pause
    exit /b 1
)

echo.
echo Project: %PROJECT_ID%
echo ----------------------------------------------------------------
echo.

REM Показати статус сцен
echo Scene status:
for /d %%d in (projects\%PROJECT_ID%\scene_*) do (
    if exist "%%d\video.mp4" (
        echo   %%~nxd: VIDEO EXISTS
    ) else if exist "%%d\image.png" (
        echo   %%~nxd: image ready, no video
    ) else (
        echo   %%~nxd: no image
    )
)

echo.
echo ----------------------------------------------------------------
echo Starting video generation...
echo.

%PYTHON% run_video_gen.py %PROJECT_ID%

echo.
echo ----------------------------------------------------------------
echo Video generation finished.
echo.
pause
