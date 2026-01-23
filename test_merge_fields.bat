@echo off
echo ======================================================================
echo MERGE FIELD SYNCHRONIZATION TEST
echo ======================================================================
echo.

python tests\test_merge_fields.py %*

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [32mAll tests passed![0m
) else (
    echo.
    echo [31mTests failed! Check the output above.[0m
    echo.
    echo TIP: Run with --verbose to see all fields:
    echo   test_merge_fields.bat --verbose
)

echo.
pause
