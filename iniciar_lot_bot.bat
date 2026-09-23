@echo off
rem LOT Bot - arranque con doble clic (desarrollo).
rem La primera vez prepara el entorno; despues abre la aplicacion.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Preparando LOT Bot por primera vez. Puede tardar unos minutos...
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\install_dev.ps1"
    if errorlevel 1 (
        echo.
        echo No se ha podido preparar el entorno. Revisa el mensaje de arriba.
        pause
        exit /b 1
    )
)
start "" ".venv\Scripts\pythonw.exe" run_lot_bot.py
