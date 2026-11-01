@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Reasonable Engine - сборка установщика
echo ============================================
echo.

python tools\build_installer.py %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo Сборка установщика не удалась. Код: %RESULT%
    pause
)
exit /b %RESULT%
