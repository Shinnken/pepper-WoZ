@echo off
rem Uruchamia panel w lokalnym srodowisku .venv (z paramiko do SSH).
rem Argumenty przekazywane dalej, np.:  start.bat --demo
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto run

echo Pierwsze uruchomienie: tworze srodowisko .venv ...
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython

%PY% -m venv .venv
if errorlevel 1 goto nopython
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 goto pipfail

:run
".venv\Scripts\python.exe" server.py %*
if errorlevel 1 pause
exit /b

:nopython
echo.
echo BLAD: nie znaleziono Pythona 3.7+.
echo Zainstaluj Pythona z https://www.python.org/downloads/ (zaznacz "Add python.exe to PATH")
echo i uruchom start.bat jeszcze raz.
if exist ".venv" rmdir /s /q ".venv"
pause
exit /b 1

:pipfail
echo.
echo BLAD: nie udalo sie zainstalowac paramiko (potrzebny internet przy pierwszym uruchomieniu).
if exist ".venv" rmdir /s /q ".venv"
pause
exit /b 1
