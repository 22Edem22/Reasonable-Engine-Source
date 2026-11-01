@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
python run_editor.py
if errorlevel 1 (
  echo.
  echo Reasonable Engine не запустилась. Проверьте Python 3.10+ и зависимости:
  echo   python -m pip install -r requirements.txt
  pause
)
