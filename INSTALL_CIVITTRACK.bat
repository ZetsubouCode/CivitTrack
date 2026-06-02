@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Install CivitTrack
cd /d "%~dp0"

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "READY_MARKER=%CD%\.venv\.civittrack-ready"

echo.
echo ==========================================
echo   Install CivitTrack
echo ==========================================
echo.

if not exist "requirements.txt" (
    echo ERROR: requirements.txt was not found.
    echo Keep INSTALL_CIVITTRACK.bat in the CivitTrack project folder.
    goto :fail
)

if not exist ".env.example" (
    echo ERROR: .env.example was not found.
    echo Keep INSTALL_CIVITTRACK.bat in the CivitTrack project folder.
    goto :fail
)

if exist ".venv\bin\python" if not exist "%VENV_PYTHON%" (
    echo ERROR: The existing .venv folder was created for Linux.
    echo Remove the .venv folder, then run this installer again on Windows.
    goto :fail
)

if not exist "%VENV_PYTHON%" (
    echo Creating the local Python environment...
    call :find_python
    if errorlevel 1 goto :fail

    !BOOTSTRAP_PYTHON! -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    if errorlevel 1 (
        echo ERROR: CivitTrack requires Python 3.10 or newer.
        echo Install a current Python release from https://www.python.org/downloads/
        goto :fail
    )

    !BOOTSTRAP_PYTHON! -m venv ".venv"
    if errorlevel 1 (
        echo ERROR: Python could not create the .venv folder.
        goto :fail
    )
)

"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo ERROR: The local .venv uses Python older than 3.10.
    echo Remove the .venv folder, install a current Python release, then run this installer again.
    goto :fail
)

echo Installing or updating CivitTrack requirements...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo ERROR: Requirements could not be installed.
    echo Check your internet connection, then run this file again.
    goto :fail
)
> "%READY_MARKER%" echo CivitTrack requirements installed.

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo.
    echo Created the local .env configuration file.
    if /I "%~1"=="--check" goto :done
    echo Add your CIVITAI_API_KEY and CIVITAI_USERNAME in Notepad,
    echo save the file, then close Notepad.
    echo.
    start /wait "" notepad.exe ".env"
) else (
    echo Keeping the existing local .env configuration file.
)

:done
echo.
echo Installation complete.
echo Double-click START_CIVITTRACK.bat to open the dashboard.
if /I "%~1"=="--check" exit /b 0
pause
exit /b 0

:find_python
where py >nul 2>&1
if not errorlevel 1 (
    set "BOOTSTRAP_PYTHON=py -3"
    exit /b 0
)

where python >nul 2>&1
if not errorlevel 1 (
    set "BOOTSTRAP_PYTHON=python"
    exit /b 0
)

echo ERROR: Python was not found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/
echo During setup, enable the option to add Python to PATH.
exit /b 1

:fail
echo.
echo Installation did not finish. Review the message above, then run this file again.
pause
exit /b 1
