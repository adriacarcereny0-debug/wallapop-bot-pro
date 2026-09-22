<#
.SYNOPSIS
    Prepara el entorno de desarrollo de LOT Bot en Windows.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_dev.ps1
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "=== LOT Bot · entorno de desarrollo ===" -ForegroundColor Cyan

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "Instala Python 3.11 o superior desde https://www.python.org/downloads/"
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creando entorno virtual..." -ForegroundColor Yellow
    & python -m venv .venv
}

Write-Host "Instalando dependencias..." -ForegroundColor Yellow
& .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .venv\Scripts\python.exe -m pip install -r requirements-dev.txt

if (-not (Test-Path ".env")) {
    Write-Host "Creando .env a partir de .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "Edita .env con tus credenciales. Mientras no las tengas, LOT Bot"
    Write-Host "funcionará en MODO DEMO con datos simulados."
}

Write-Host ""
Write-Host "=== Listo ===" -ForegroundColor Green
Write-Host "Arrancar la aplicación:   .venv\Scripts\python.exe run_lot_bot.py"
Write-Host "Ejecutar las pruebas:     .venv\Scripts\python.exe -m pytest"
Write-Host "Generar el ejecutable:    powershell -ExecutionPolicy Bypass -File build\build_windows.ps1"
