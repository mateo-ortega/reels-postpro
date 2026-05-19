# install.ps1 — Reels Postpro Sapiens
# Crea venv, instala torch CPU, instala el resto, copia fonts.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "=== Reels Postpro - Instalacion ===" -ForegroundColor Cyan
Write-Host ""

# 1. Verificar ffmpeg en PATH
Write-Host "[1/5] Verificando ffmpeg..." -ForegroundColor Yellow
try {
    $null = & ffmpeg -version
    Write-Host "      OK - ffmpeg encontrado" -ForegroundColor Green
} catch {
    Write-Host "      ERROR - ffmpeg NO encontrado en PATH" -ForegroundColor Red
    Write-Host "      Descarga: https://www.gyan.dev/ffmpeg/builds/ (full build)" -ForegroundColor Red
    exit 1
}

# 2. Crear venv si no existe
Write-Host ""
Write-Host "[2/5] Creando entorno virtual..." -ForegroundColor Yellow
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "      OK - venv creado en .venv\" -ForegroundColor Green
} else {
    Write-Host "      OK - venv ya existe" -ForegroundColor Green
}

# Helper: ejecuta pip y aborta si falla (PowerShell no detecta exit codes de .exe por defecto)
function Invoke-Pip {
    param([Parameter(ValueFromRemainingArguments)] [string[]] $Args)
    & python -m pip @Args
    if ($LASTEXITCODE -ne 0) {
        Write-Host "      ERROR - pip fallo con exit $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# 3. Activar venv, actualizar pip + setuptools (necesario para openai-whisper)
Write-Host ""
Write-Host "[3/5] Activando venv y actualizando pip + setuptools..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1
Invoke-Pip install --upgrade pip setuptools wheel --quiet
Write-Host "      OK - pip/setuptools/wheel actualizados" -ForegroundColor Green

# 4. Instalar PyTorch CPU + resto de dependencias
Write-Host ""
Write-Host "[4/5] Instalando PyTorch CPU (puede tardar varios minutos)..." -ForegroundColor Yellow
Invoke-Pip install torch==2.2.2 torchaudio==2.2.2 --index-url https://download.pytorch.org/whl/cpu
Write-Host "      OK - torch CPU instalado" -ForegroundColor Green

Write-Host ""
Write-Host "      Instalando dependencias restantes..." -ForegroundColor Yellow
Invoke-Pip install -r requirements.txt
Write-Host "      OK - dependencias instaladas" -ForegroundColor Green

# 5. Copiar fonts Sapiens desde sapiens-carrusel
Write-Host ""
Write-Host "[5/5] Copiando fonts Sapiens..." -ForegroundColor Yellow
$fontSrc = Join-Path $PSScriptRoot "..\skills\sapiens-carrusel\assets"
$fontDst = Join-Path $PSScriptRoot "assets\fonts"

if (-not (Test-Path $fontDst)) {
    New-Item -ItemType Directory -Force -Path $fontDst | Out-Null
}

$fonts = @("Outfit-Bold.ttf", "InstrumentSans-Bold.ttf")
foreach ($f in $fonts) {
    $src = Join-Path $fontSrc $f
    if (Test-Path $src) {
        Copy-Item $src -Destination $fontDst -Force
        Write-Host "      OK - $f copiada" -ForegroundColor Green
    } else {
        Write-Host "      WARN - $f no encontrada en $fontSrc" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Instalacion completa ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Para arrancar:" -ForegroundColor White
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host "  python app.py" -ForegroundColor Gray
Write-Host ""
Write-Host "La UI abrira en: http://localhost:7860" -ForegroundColor White
Write-Host ""
