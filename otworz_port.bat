@echo off
rem Otwiera w Zaporze Windows port TCP 54331, na ktory laczy sie robot. Wystarczy raz.
rem Inny port:  otworz_port.bat 54332
set "PORT=%~1"
if "%PORT%"=="" set "PORT=54331"

net session >nul 2>&1
if errorlevel 1 (
    echo Potrzebne uprawnienia administratora - zaraz pojawi sie pytanie UAC...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%PORT%' -Verb RunAs"
    exit /b
)

powershell -NoProfile -Command "Remove-NetFirewallRule -DisplayName 'NAO WoZ %PORT%' -ErrorAction SilentlyContinue; New-NetFirewallRule -DisplayName 'NAO WoZ %PORT%' -Direction Inbound -Protocol TCP -LocalPort %PORT% -Action Allow -Profile Any | Out-Null"
if errorlevel 1 (
    echo BLAD: nie udalo sie dodac reguly zapory.
) else (
    echo OK: port TCP %PORT% jest otwarty dla polaczen przychodzacych - regula "NAO WoZ %PORT%".
)
pause
