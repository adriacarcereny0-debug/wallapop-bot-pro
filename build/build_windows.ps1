<#
.SYNOPSIS
    Genera LOT-Bot.exe para Windows.

.DESCRIPTION
    Crea un entorno virtual limpio, instala las dependencias y empaqueta la
    aplicación con PyInstaller. El resultado queda en dist\LOT-Bot\LOT-Bot.exe.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build\build_windows.ps1
#>

param(
    [switch]$SkipInstall,
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "=== LOT Bot · generación del ejecutable ===" -ForegroundColor Cyan
Write-Host "Proyecto: $ProjectRoot"

# --- 1. Comprobar Python ---
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "No se ha encontrado Python. Instala Python 3.11 o superior desde python.org."
    exit 1
}
$version = & python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
Write-Host "Python detectado: $version"
if ([version]$version -lt [version]"3.11") {
    Write-Error "Se requiere Python 3.11 o superior (detectado $version)."
    exit 1
}

# --- 2. Entorno virtual ---
$venv = Join-Path $ProjectRoot ".venv-build"
if (-not (Test-Path $venv)) {
    Write-Host "Creando entorno virtual de compilación..." -ForegroundColor Yellow
    & python -m venv $venv
}
$venvPython = Join-Path $venv "Scripts\python.exe"

# --- 3. Dependencias ---
if (-not $SkipInstall) {
    Write-Host "Instalando dependencias..." -ForegroundColor Yellow
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r requirements.txt --quiet
    & $venvPython -m pip install pyinstaller --quiet
}

# --- 4. Pruebas rápidas (opcional pero recomendado) ---
Write-Host "Comprobando que la aplicación importa correctamente..." -ForegroundColor Yellow
& $venvPython -c "import lot_bot; from lot_bot.app import main; print('OK', lot_bot.__version__)"

# --- 5. Limpiar compilaciones anteriores ---
foreach ($folder in @("dist", "build\work")) {
    $path = Join-Path $ProjectRoot $folder
    if (Test-Path $path) {
        Write-Host "Limpiando $folder ..."
        Remove-Item $path -Recurse -Force
    }
}

# --- 6. Empaquetar ---
Write-Host "Empaquetando con PyInstaller (esto puede tardar varios minutos)..." -ForegroundColor Yellow
$specFile = Join-Path $PSScriptRoot "LOT-Bot.spec"
& $venvPython -m PyInstaller $specFile --noconfirm --clean --workpath "build\work" --distpath "dist"

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller ha terminado con errores."
    exit $LASTEXITCODE
}

# --- 7. Añadir ficheros que el cliente debe poder editar ---
$distDir = Join-Path $ProjectRoot "dist\LOT-Bot"
Copy-Item (Join-Path $ProjectRoot ".env.example") (Join-Path $distDir ".env.example") -Force
$configDir = Join-Path $distDir "config"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
Copy-Item (Join-Path $ProjectRoot "config\access_profile.example.yaml") $configDir -Force
if (Test-Path (Join-Path $ProjectRoot "docs\cliente")) {
    Copy-Item (Join-Path $ProjectRoot "docs\cliente") (Join-Path $distDir "documentacion") -Recurse -Force
}

$exePath = Join-Path $distDir "LOT-Bot.exe"
if (Test-Path $exePath) {
    $size = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
    Write-Host ""
    Write-Host "=== Compilación terminada ===" -ForegroundColor Green
    Write-Host "Ejecutable: $exePath ($size MB)"
    Write-Host "Carpeta a entregar al cliente: $distDir"
    Write-Host ""
    Write-Host "Comprímela en un .zip y el cliente solo tendrá que descomprimirla"
    Write-Host "y hacer doble clic en LOT-Bot.exe."
} else {
    Write-Error "No se ha generado el ejecutable."
    exit 1
}
