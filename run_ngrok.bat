@echo off
chcp 65001 >nul
echo ========================================
echo  Edible House Automator - ngrok Tunnel
echo ========================================
echo.

cd /d "%~dp0"

REM Check if ngrok exists
if not exist "ngrok.exe" (
    echo ERROR: ngrok.exe not found!
    echo.
    echo Download ngrok from: https://ngrok.com/download
    echo Place ngrok.exe in this folder
    echo.
    pause
    exit /b 1
)

REM Check if authtoken is configured
ngrok.exe config check >nul 2>&1
if errorlevel 1 (
    echo WARNING: ngrok authtoken may not be configured
    echo.
    echo To configure, run:
    echo   ngrok.exe config add-authtoken YOUR_TOKEN
    echo.
    echo Get your token at: https://dashboard.ngrok.com/get-started/your-authtoken
    echo.
)

echo Starting ngrok tunnel to port 8000...
echo.
echo After ngrok starts, look for the "Forwarding" URL like:
echo   https://xxxx-xxxx-xxxx.ngrok-free.dev
echo.
echo Use this URL on your phone to access the Control Panel!
echo.
echo Press Ctrl+C to stop ngrok
echo.

ngrok.exe http 8000

pause
