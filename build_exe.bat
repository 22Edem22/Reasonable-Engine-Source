@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo Reasonable Engine · сборка Windows EXE
echo.

python tools\build_editor_exe.py %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo Сборка не удалась. Код: %RESULT%
    pause
)
exit /b %RESULT%
