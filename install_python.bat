@echo off
REM ============================================================================
REM Автоматична установка Python 3.11.9 для Edible House Automator
REM ============================================================================

echo ========================================
echo   Python 3.11.9 Auto Installer
echo ========================================
echo.

REM Перевірка чи вже встановлений Python
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo Python вже встановлено:
    python --version
    echo.
    echo Якщо хочеш перевстановити, видали Python спочатку.
    pause
    exit /b 0
)

echo Python не знайдено. Починаю автоматичну установку...
echo.

REM Створення тимчасової папки
set TEMP_DIR=%TEMP%\python_install
if not exist "%TEMP_DIR%" mkdir "%TEMP_DIR%"

REM Завантаження Python 3.11.9 installer (64-bit)
set PYTHON_INSTALLER=%TEMP_DIR%\python-3.11.9-amd64.exe
set PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe

echo [1/3] Завантаження Python 3.11.9 installer...
echo URL: %PYTHON_URL%
echo.

REM Використання PowerShell для завантаження
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%'}"

if not exist "%PYTHON_INSTALLER%" (
    echo ERROR: Не вдалося завантажити Python installer!
    echo Спробуй завантажити вручну з: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Завантаження завершено: %PYTHON_INSTALLER%
echo.

REM Установка Python
echo [2/3] Встановлення Python 3.11.9...
echo.
echo Параметри установки:
echo   - Тиха установка (без діалогів)
echo   - Додавання в PATH
echo   - pip включено
echo   - Для всіх користувачів
echo.

REM Запуск установки з параметрами:
REM /quiet - тиха установка
REM InstallAllUsers=1 - для всіх користувачів
REM PrependPath=1 - додати в PATH
REM Include_pip=1 - встановити pip
REM Include_test=0 - не встановлювати тести

"%PYTHON_INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_test=0

REM Чекаємо завершення установки
timeout /t 10 /nobreak >nul

echo.
echo [3/3] Перевірка установки...
echo.

REM Оновлюємо PATH в поточній сесії
call refreshenv >nul 2>&1

REM Перевірка
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo ========================================
    echo   Python встановлено успішно!
    echo ========================================
    echo.
    python --version
    echo.
    echo pip version:
    pip --version
    echo.
    echo ========================================
    echo.
    echo ВАЖЛИВО: Закрий це вікно і відкрий НОВЕ
    echo Command Prompt, щоб PATH оновився.
    echo.
    echo Потім запусти: setup.bat
    echo.
) else (
    echo.
    echo ========================================
    echo   Потрібен рестарт Command Prompt
    echo ========================================
    echo.
    echo Python встановлено, але PATH ще не оновився.
    echo.
    echo ЩО РОБИТИ:
    echo   1. Закрий це вікно
    echo   2. Відкрий НОВЕ Command Prompt
    echo   3. Запусти: setup.bat
    echo.
)

REM Очищення
echo Очищення тимчасових файлів...
del "%PYTHON_INSTALLER%" >nul 2>&1

pause
