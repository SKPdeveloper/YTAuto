@echo off
chcp 65001 >nul
title APPROVE — Topaz + Publish + A/B Daemon
cd /d "%~dp0"

echo ============================================
echo   APPROVE — Full Post-Edit Pipeline
echo   Topaz FPS + 4K + Publish + A/B Daemon
echo ============================================
echo.

:: --- Determine project ID from folder name ---
for %%I in ("%CD%") do set "PROJECT_ID=%%~nxI"
echo [PROJECT]  %PROJECT_ID%

:: --- Find YTAuto root (2 levels up from projects/proj_xxx/) ---
for %%I in ("%CD%\..\..\") do set "YTAUTO_ROOT=%%~fI"

:: Verify we're inside a project folder
if not exist "project_brief.json" (
    echo.
    echo [ERROR] project_brief.json not found!
    echo This script must be run from a project folder ^(projects/proj_xxx/^)
    pause
    exit /b 1
)

:: --- Find input video ---
set "INPUT="
if exist "final.mp4" set "INPUT=final.mp4"
if exist "final_video.mp4" set "INPUT=final_video.mp4"
if exist "assembled_video.mp4" set "INPUT=assembled_video.mp4"

if "%INPUT%"=="" (
    echo [ERROR] No video found! Expected final.mp4, final_video.mp4, or assembled_video.mp4
    pause
    exit /b 1
)

echo [INPUT]   %INPUT%
echo [ROOT]    %YTAUTO_ROOT%
echo.

:: ============================================
:: STAGE 1/2: FPS Interpolation
:: ============================================
echo [LOG] Topaz FPS interpolation starting...
echo ============================================
echo   STAGE 1/2: FPS Interpolation (60fps)
echo ============================================

set "TVAI_MODEL_DIR=C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models"
set "TVAI_MODEL_DATA_DIR=C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models"

"C:\Program Files\Topaz Labs LLC\Topaz Video AI\ffmpeg.exe" ^
    -hide_banner -nostdin -y ^
    -hwaccel auto ^
    -i "%INPUT%" ^
    -vf "tvai_fi=model=apf-1:fps=60:device=0" ^
    -c:v hevc_amf ^
    -b:v 65M ^
    -pix_fmt yuv420p ^
    -c:a copy ^
    "final_60fps.mp4"

if %ERRORLEVEL% neq 0 (
    echo [ERROR] FPS Interpolation failed!
    pause
    exit /b 1
)

echo [OK] FPS interpolation complete: final_60fps.mp4
echo.

:: ============================================
:: STAGE 2/2: 4K Upscaling
:: ============================================
echo [LOG] Topaz 4K upscaling starting...
echo ============================================
echo   STAGE 2/2: 4K Upscaling (2160x3840)
echo ============================================

"C:\Program Files\Topaz Labs LLC\Topaz Video AI\ffmpeg.exe" ^
    -hide_banner -nostdin -y ^
    -hwaccel auto ^
    -i "final_60fps.mp4" ^
    -vf "tvai_up=model=prob-3:scale=0:w=2160:h=3840:device=0,scale=2160:3840" ^
    -c:v hevc_amf ^
    -b:v 65M ^
    -pix_fmt yuv420p ^
    -c:a copy ^
    "final_4k.mp4"

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Upscaling failed!
    pause
    exit /b 1
)

:: Cleanup intermediate
del "final_60fps.mp4" 2>nul
echo [OK] Topaz complete: final_4k.mp4
echo.

:: ============================================
:: YOUTUBE PUBLISH
:: ============================================
echo [LOG] Publishing to YouTube...
echo ============================================
echo   PUBLISHING TO YOUTUBE
echo ============================================
echo.

cd /d "%YTAUTO_ROOT%"
python -X utf8 -c "import sys; sys.path.insert(0, '.'); from src.publisher.publisher import Publisher; p = Publisher(); ok, st = p.publish('%PROJECT_ID%'); sys.exit(0 if ok else 1)"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Publishing failed! Check logs above.
    cd /d "%~dp0"
    pause
    exit /b 1
)

cd /d "%~dp0"
echo.
echo [OK] Published successfully!
echo.

:: ============================================
:: A/B DAEMON (detached — survives after this window closes)
:: ============================================
echo [LOG] Ensuring A/B daemon is running...
cd /d "%YTAUTO_ROOT%"
python -X utf8 -c "import sys; sys.path.insert(0, '.'); from app.utils.ab_daemon_launcher import ensure_ab_daemon_running; ok = ensure_ab_daemon_running('APPROVE.bat'); print('[OK] A/B daemon running' if ok else '[WARN] A/B daemon failed to start')"
cd /d "%~dp0"
echo.

:: ============================================
:: ALL DONE
:: ============================================
echo ============================================
echo   ALL DONE!
echo   - Topaz 4K: final_4k.mp4
echo   - Published to YouTube
echo   - A/B daemon running in background
echo ============================================
echo.
pause
exit /b 0
