@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "APP_PY=%SCRIPT_DIR%PepperApp\pepper_app.py"

if not exist "%VENV_PY%" (
    echo Virtual environment Python not found: "%VENV_PY%"
    pause
    exit /b 1
)

if not exist "%APP_PY%" (
    echo App file not found: "%APP_PY%"
    pause
    exit /b 1
)

pushd "%SCRIPT_DIR%PepperApp"
"%VENV_PY%" "%APP_PY%"
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo Application exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
