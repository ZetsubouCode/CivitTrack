@echo off
setlocal EnableExtensions
title CivitTrack
cd /d "%~dp0"

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "APP_URL=http://127.0.0.1:8787"

echo.
echo ==========================================
echo   CivitTrack - local creator analytics
echo ==========================================
echo.

if not exist "%VENV_PYTHON%" (
    echo ERROR: CivitTrack is not installed yet.
    echo Double-click INSTALL_CIVITTRACK.bat first.
    goto :fail
)

if not exist ".env" (
    echo ERROR: The local .env configuration file is missing.
    echo Double-click INSTALL_CIVITTRACK.bat to create it.
    goto :fail
)

"%VENV_PYTHON%" -c "import flask, requests, dotenv" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Required Python packages are missing.
    echo Double-click INSTALL_CIVITTRACK.bat to repair the installation.
    goto :fail
)

set "URL_FILE=%TEMP%\civittrack-url-%RANDOM%-%RANDOM%.txt"
"%VENV_PYTHON%" -c "from services.config import get_config; c=get_config(); print('http://{}:{}'.format(c.app_host, c.app_port))" > "%URL_FILE%"
if not errorlevel 1 set /p "APP_URL="<"%URL_FILE%"
del /Q "%URL_FILE%" >nul 2>&1

if /I "%~1"=="--check" (
    echo Starter check passed for %APP_URL%.
    exit /b 0
)

echo Starting CivitTrack at %APP_URL%
echo Keep this window open while using the dashboard.
echo Press Ctrl+C in this window to stop CivitTrack.
echo.

start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%APP_URL%'"
"%VENV_PYTHON%" app.py

echo.
echo CivitTrack has stopped.
pause
exit /b 0

:fail
echo.
echo CivitTrack could not start. Review the message above.
pause
exit /b 1
