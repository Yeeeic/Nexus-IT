#Requires -Version 5.1
<#
.SYNOPSIS
    Script de construccion del paquete distribuible de NEXUS IT Agent para Windows.

.DESCRIPTION
    Descarga Python 3.13 embeddable oficial, instala dependencias minimas,
    copia el codigo canonico desde agent/, genera MANIFEST.sha256, SBOM.json
    y empaqueta el ZIP versionado.

    NO incluye tokens, UUIDs de despliegue, IPs ni claves privadas.

.PARAMETER Version
    Version del paquete a construir. Default: 1.0.0

.PARAMETER PythonVersion
    Version exacta de Python embeddable a usar. Default: 3.13.3

.PARAMETER OutputDir
    Directorio de salida. Default: directorio actual.

.PARAMETER Verify
    Verificar el hash del paquete producido contra MANIFEST.sha256.

.PARAMETER SkipDownload
    Omitir la descarga si el runtime ya existe en el cache.

.EXAMPLE
    .\build-package.ps1
    .\build-package.ps1 -Version 1.1.0 -OutputDir C:\Artifacts
#>
[CmdletBinding()]
param(
    [string]$Version = "1.0.0",
    [string]$PythonVersion = "3.13.3",
    [string]$OutputDir = $PSScriptRoot,
    [switch]$Verify,
    [switch]$SkipDownload
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Hashes conocidos - actualizar con cada nueva version de Python
# SHA-256 del archivo python-<ver>-embed-amd64.zip de python.org
# ---------------------------------------------------------------------------
$PYTHON_HASHES = @{
    "3.13.3" = "59ff76e16e6597de47474fb22be69e7191a89116910d728ab735079b078e52db"
    # Agregar nuevas versiones aqui antes de actualizar $PythonVersion
}
$PIP_VERSION = "26.2.1"
$GET_PIP_HASH = "fb24e693bab954209a063d90953621412ccad4a500905a726286e038f508ddf6"
$CRYPTOGRAPHY_VERSION = "50.0.1"
$CFFI_VERSION = "2.1.1"
$PYCPARSER_VERSION = "2.23"
$PYWIN32_VERSION = "312"

# ---------------------------------------------------------------------------
# Validar version de Python
# ---------------------------------------------------------------------------
if (-not $PYTHON_HASHES.ContainsKey($PythonVersion)) {
    Write-Error ("Python $PythonVersion no tiene hash registrado en este script. " +
        "Agreguelo a `$PYTHON_HASHES antes de construir.")
    exit 1
}

$PythonHash = $PYTHON_HASHES[$PythonVersion]
$PythonZip  = "python-$PythonVersion-embed-amd64.zip"
$PythonUrl  = "https://www.python.org/ftp/python/$PythonVersion/$PythonZip"

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
$RepoRoot    = (Get-Item $PSScriptRoot).Parent.FullName
$AgentSrc    = Join-Path $RepoRoot "agent"
$BuildDir    = Join-Path $env:TEMP "nexus-agent-build-$Version"
$RuntimeDir  = Join-Path $BuildDir "runtime"
$AgentDst    = Join-Path $BuildDir "agent"
$ServiceDir  = Join-Path $BuildDir "service"
$CacheDir    = Join-Path $PSScriptRoot ".build-cache"
$PackageName = "nexus-it-agent-windows-x64-$Version.zip"
$PackagePath = Join-Path $OutputDir $PackageName
$DependencyLock = Join-Path $PSScriptRoot "requirements-windows.lock"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Get-FileSha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower()
}

function Assert-Hash([string]$Path, [string]$Expected) {
    $actual = Get-FileSha256 $Path
    if ($actual -ne $Expected.ToLower()) {
        throw "Hash SHA-256 incorrecto para $(Split-Path $Path -Leaf)`nEsperado: $Expected`nObtenido: $actual"
    }
    Write-Host "  [hash OK] $(Split-Path $Path -Leaf)" -ForegroundColor Green
}

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  NEXUS IT Agent - Build $Version (Python $PythonVersion)" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 0. Validar que la fuente canonica exista
# ---------------------------------------------------------------------------
Write-Host "[0/7] Validando fuente canonica..." -ForegroundColor Yellow
if (-not (Test-Path (Join-Path $AgentSrc "run_agent.py"))) {
    throw "Fuente canonica no encontrada en: $AgentSrc"
}
if (-not (Test-Path (Join-Path $AgentSrc "nexus_agent" "actions.py"))) {
    throw "nexus_agent/actions.py no encontrado en: $AgentSrc"
}
if (-not (Test-Path $DependencyLock)) {
    throw "Lock de dependencias no encontrado: $DependencyLock"
}
$LockText = Get-Content -LiteralPath $DependencyLock -Raw
foreach ($ExpectedDependency in @(
    "cryptography==$CRYPTOGRAPHY_VERSION",
    "cffi==$CFFI_VERSION",
    "pycparser==$PYCPARSER_VERSION",
    "pywin32==$PYWIN32_VERSION"
)) {
    if ($LockText -notmatch "(?m)^$([regex]::Escape($ExpectedDependency))\s") {
        throw "requirements-windows.lock no coincide con el SBOM: $ExpectedDependency"
    }
}
Write-Host "  [OK] Fuente canonica verificada: $AgentSrc" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 1. Descargar y verificar Python embeddable
# ---------------------------------------------------------------------------
Write-Host "[1/7] Obteniendo Python $PythonVersion embeddable..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
$CachedZip = Join-Path $CacheDir $PythonZip

if ($SkipDownload -and (Test-Path $CachedZip)) {
    Write-Host "  [cache] Usando runtime en cache: $CachedZip" -ForegroundColor DarkGray
} else {
    Write-Host "  Descargando desde $PythonUrl..."
    $wc = New-Object System.Net.WebClient
    $wc.DownloadFile($PythonUrl, $CachedZip)
    Write-Host "  [OK] Descargado." -ForegroundColor Green
}
Assert-Hash $CachedZip $PythonHash

# ---------------------------------------------------------------------------
# 2. Preparar directorio de construccion
# ---------------------------------------------------------------------------
Write-Host "[2/7] Preparando directorio de build..." -ForegroundColor Yellow
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $ServiceDir | Out-Null

Expand-Archive -Path $CachedZip -DestinationPath $RuntimeDir -Force

# Habilitar site-packages en el runtime embeddable
$PthFile = Get-ChildItem $RuntimeDir -Filter "python*._pth" | Select-Object -First 1
if ($PthFile) {
    $content = Get-Content $PthFile.FullName
    $content = $content -replace "^#import site", "import site"
    $content | Set-Content $PthFile.FullName -Encoding ASCII
}

Write-Host "  [OK] Runtime extraido en: $RuntimeDir" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 3. Instalar pip en el runtime embeddable
# ---------------------------------------------------------------------------
Write-Host "[3/7] Instalando pip en runtime embeddable..." -ForegroundColor Yellow
$GetPipUrl  = "https://bootstrap.pypa.io/get-pip.py"
$GetPipPath = Join-Path $BuildDir "get-pip.py"
(New-Object System.Net.WebClient).DownloadFile($GetPipUrl, $GetPipPath)
Assert-Hash $GetPipPath $GET_PIP_HASH

$pythonExe = Join-Path $RuntimeDir "python.exe"
& $pythonExe $GetPipPath "pip==$PIP_VERSION" --no-warn-script-location 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Error instalando pip en el runtime embeddable" }
Remove-Item -LiteralPath $GetPipPath -Force
Write-Host "  [OK] pip instalado." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 4. Instalar dependencias en runtime embeddable
# ---------------------------------------------------------------------------
Write-Host "[4/7] Instalando dependencias en runtime..." -ForegroundColor Yellow
$pipExe = Join-Path $RuntimeDir "Scripts" "pip.exe"

# All direct and transitive dependencies are exact and hash-locked.
& $pipExe install --only-binary=:all: --require-hashes -r $DependencyLock 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Error instalando dependencias bloqueadas" }

Write-Host "  [OK] cryptography + pywin32 instalados." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 5. Copiar codigo del agente desde fuente canonica
# ---------------------------------------------------------------------------
Write-Host "[5/7] Copiando codigo canonico desde agent/..." -ForegroundColor Yellow
if (Test-Path $AgentDst) { Remove-Item $AgentDst -Recurse -Force }
Copy-Item $AgentSrc $AgentDst -Recurse -Exclude @("__pycache__", "*.pyc", "agent_config.json")

# Remove generated/private files even when PowerShell recursive exclusions miss them.
Get-ChildItem $AgentDst -Directory -Recurse -Force |
    Where-Object { $_.Name -eq "__pycache__" } |
    Remove-Item -Recurse -Force
Get-ChildItem $AgentDst -File -Recurse -Force -Include "*.pyc", "agent_config.json" |
    Remove-Item -Force

# Build tooling is not required at runtime. Remove it and all generated bytecode.
$SitePackages = Join-Path $RuntimeDir "Lib\site-packages"
Get-ChildItem $SitePackages -Force -Filter "pip*" | Remove-Item -Recurse -Force
Get-ChildItem (Join-Path $RuntimeDir "Scripts") -Force -Filter "pip*" |
    Remove-Item -Force
Get-ChildItem $RuntimeDir -Directory -Recurse -Force |
    Where-Object { $_.Name -eq "__pycache__" } |
    Remove-Item -Recurse -Force
Get-ChildItem $RuntimeDir -File -Recurse -Force -Filter "*.pyc" |
    Remove-Item -Force

# Copiar scripts de servicio
$ServiceSrc = Join-Path $PSScriptRoot "service"
if (Test-Path $ServiceSrc) {
    Copy-Item (Join-Path $ServiceSrc "*") $ServiceDir -Recurse
}

# Copiar archivos raiz del paquete
$RootFiles = @("BUILD.md", "INSTALL.md", "LEEME.txt")
foreach ($f in $RootFiles) {
    $src = Join-Path $PSScriptRoot $f
    if (Test-Path $src) { Copy-Item $src $BuildDir }
}
$CanonicalExample = Join-Path $AgentSrc "agent_config.example.json"
if (-not (Test-Path -LiteralPath $CanonicalExample -PathType Leaf)) {
    throw "Plantilla canonica no encontrada: $CanonicalExample"
}
Copy-Item -LiteralPath $CanonicalExample -Destination (Join-Path $BuildDir "agent_config.example.json")

# Tests and local imports may create bytecode after the runtime cleanup above.
# Sanitize the entire staged package after every source copy.
Get-ChildItem $BuildDir -Directory -Recurse -Force |
    Where-Object { $_.Name -eq "__pycache__" } |
    Remove-Item -Recurse -Force
Get-ChildItem $BuildDir -File -Recurse -Force -Filter "*.pyc" |
    Remove-Item -Force

Write-Host "  [OK] Codigo canonico copiado." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 6. Generar MANIFEST.sha256 y SBOM.json
# ---------------------------------------------------------------------------
Write-Host "[6/7] Generando MANIFEST.sha256 y SBOM.json..." -ForegroundColor Yellow

# SBOM basico
$Sbom = @{
    format = "nexus-it-sbom-v1"
    package = "nexus-it-agent-windows-x64"
    version = $Version
    built_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    components = @(
        @{ name = "CPython"; version = $PythonVersion; license = "PSF-2.0"; source = "python.org" }
        @{ name = "cryptography"; version = $CRYPTOGRAPHY_VERSION; license = "Apache-2.0 / BSD"; source = "pypi" }
        @{ name = "cffi"; version = $CFFI_VERSION; license = "MIT-0"; source = "pypi" }
        @{ name = "pycparser"; version = $PYCPARSER_VERSION; license = "BSD-3-Clause"; source = "pypi" }
        @{ name = "pywin32"; version = $PYWIN32_VERSION; license = "PSF-2.0"; source = "pypi" }
    )
}
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$SbomJson = $Sbom | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText((Join-Path $BuildDir "SBOM.json"), $SbomJson, $Utf8NoBom)

# The manifest is generated last so it covers SBOM.json and every payload file.
$ManifestPath = Join-Path $BuildDir "MANIFEST.sha256"
$ManifestLines = @()
Get-ChildItem $BuildDir -Recurse -File |
    Where-Object { $_.Name -ne "MANIFEST.sha256" } |
    ForEach-Object {
        $rel = $_.FullName.Substring($BuildDir.Length + 1).Replace("\", "/")
        $hash = Get-FileSha256 $_.FullName
        $ManifestLines += "$hash  $rel"
    }
[System.IO.File]::WriteAllLines($ManifestPath, ($ManifestLines | Sort-Object), $Utf8NoBom)

Write-Host "  [OK] MANIFEST.sha256 y SBOM.json generados." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 7. Empaquetar ZIP
# ---------------------------------------------------------------------------
Write-Host "[7/7] Empaquetando $PackageName..." -ForegroundColor Yellow
if (Test-Path $PackagePath) { Remove-Item $PackagePath -Force }
Compress-Archive -Path "$BuildDir\*" -DestinationPath $PackagePath -CompressionLevel Optimal
$PackageHash = Get-FileSha256 $PackagePath

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Green
Write-Host "  BUILD COMPLETADO" -ForegroundColor Green
Write-Host "  Paquete : $PackagePath" -ForegroundColor Green
Write-Host "  SHA-256 : $PackageHash" -ForegroundColor Green
Write-Host "  NOTA    : Firma Authenticode PENDIENTE (SIGN_PENDING)" -ForegroundColor Yellow
Write-Host "=====================================================" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Verificacion opcional
# ---------------------------------------------------------------------------
if ($Verify) {
    Write-Host "[VERIFY] Verificando MANIFEST.sha256..." -ForegroundColor Yellow
    $errors = 0
    $tempVerify = Join-Path $env:TEMP "nexus-verify-$Version"
    if (Test-Path -LiteralPath $tempVerify) {
        Remove-Item -LiteralPath $tempVerify -Recurse -Force
    }
    Expand-Archive -Path $PackagePath -DestinationPath $tempVerify -Force
    $verifyRoot = [System.IO.Path]::GetFullPath($tempVerify + [System.IO.Path]::DirectorySeparatorChar)
    $verifyManifest = [System.IO.Path]::GetFullPath((Join-Path $tempVerify "MANIFEST.sha256"))
    $manifestFiles = @{}
    foreach ($line in (Get-Content -LiteralPath $verifyManifest)) {
        if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') {
            Write-Host "  [INVALID MANIFEST LINE]" -ForegroundColor Red
            $errors++
            continue
        }
        $expectedHash = $Matches[1].ToLowerInvariant()
        $relPath = $Matches[2]
        $fullPath = [System.IO.Path]::GetFullPath(
            (Join-Path $tempVerify $relPath.Replace("/", [System.IO.Path]::DirectorySeparatorChar))
        )
        if (-not $fullPath.StartsWith($verifyRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            $manifestFiles.ContainsKey($fullPath)) {
            Write-Host "  [UNSAFE OR DUPLICATE] $relPath" -ForegroundColor Red
            $errors++
            continue
        }
        $manifestFiles[$fullPath] = $true
        if (-not (Test-Path $fullPath)) {
            Write-Host "  [MISSING] $relPath" -ForegroundColor Red
            $errors++
        } else {
            $actual = Get-FileSha256 $fullPath
            if ($actual -ne $expectedHash) {
                Write-Host "  [HASH MISMATCH] $relPath" -ForegroundColor Red
                $errors++
            }
        }
    }
    $actualFiles = Get-ChildItem -LiteralPath $tempVerify -Recurse -File |
        Where-Object { $_.FullName -ne $verifyManifest }
    foreach ($file in $actualFiles) {
        if (-not $manifestFiles.ContainsKey($file.FullName)) {
            Write-Host "  [UNDECLARED] $($file.FullName)" -ForegroundColor Red
            $errors++
        }
    }
    if ($manifestFiles.Count -ne $actualFiles.Count) { $errors++ }
    Remove-Item -LiteralPath $tempVerify -Recurse -Force
    if ($errors -gt 0) {
        throw "Verificacion fallida: $errors archivos con error."
    }
    Write-Host "  [OK] Verificacion completa. Todos los hashes correctos." -ForegroundColor Green
}
