#Requires -Version 5.1
<#
.SYNOPSIS
    Instalador del agente NEXUS IT para Windows.

.DESCRIPTION
    Descarga el paquete completo desde el servidor NEXUS IT,
    verifica el hash SHA-256, extrae y llama a nexus-agent-ctl.ps1 install.

    Requiere HTTPS. HTTP solo se permite en loopback para desarrollo.
    El token nunca se escribe en disco en texto plano; se protege con DPAPI.

.PARAMETER ServerUrl
    URL HTTPS del servidor NEXUS IT. Requerido.

.PARAMETER DeviceId
    UUID del dispositivo enrolado en la consola. Requerido.

.PARAMETER PublicKeysJson
    JSON con claves publicas Ed25519. Requerido.

.PARAMETER ArtifactBaseUrl
    URL base para descargar el paquete ZIP. Default: igual a ServerUrl.

.PARAMETER PackageVersion
    Version del paquete a instalar. Default: "1.0.0"

.PARAMETER ExpectedSha256
    Hash SHA-256 esperado del paquete ZIP. Recomendado para produccion.

.PARAMETER InstallPath
    Ruta de instalacion. Default: C:\ProgramData\NexusIT\Agent

.PARAMETER AllowInsecureHttp
    Permitir HTTP solo en loopback para desarrollo. No usar en produccion.

.EXAMPLE
    .\install-agent.ps1 `
        -ServerUrl "https://nexus.empresa.com" `
        -DeviceId "00000000-0000-4000-0000-000000000000" `
        -PublicKeysJson '{"1":"<clave-ed25519-base64>"}' `
        -ExpectedSha256 "<sha256-del-zip>"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ServerUrl,

    [Parameter(Mandatory = $true)]
    [string]$DeviceId,

    [Parameter(Mandatory = $true)]
    [string]$PublicKeysJson,

    [string]$ArtifactBaseUrl = "",
    [string]$PackageVersion  = "1.0.0",
    [Parameter(Mandatory = $true)]
    [string]$ExpectedSha256,
    [string]$InstallPath     = "$env:ProgramData\NexusIT\Agent",
    [switch]$AllowInsecureHttp
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Step([string]$Msg) { Write-Host "  $Msg" -ForegroundColor Cyan }
function Write-OK([string]$Msg)   { Write-Host "  [OK] $Msg" -ForegroundColor Green }
function Write-Fail([string]$Msg) { Write-Host "  [X] $Msg"  -ForegroundColor Red }

function Get-FileSha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower()
}

function Assert-PublicKeys($Keys) {
    if ($null -eq $Keys -or $Keys.PSObject.Properties.Count -eq 0) {
        throw "PublicKeysJson debe contener al menos una clave Ed25519 versionada."
    }
    foreach ($property in $Keys.PSObject.Properties) {
        $version = 0
        if (-not [int]::TryParse($property.Name, [ref]$version) -or $version -le 0) {
            throw "Cada version de clave Ed25519 debe ser un entero positivo."
        }
        try { $decoded = [Convert]::FromBase64String([string]$property.Value) }
        catch { throw "La clave Ed25519 version $version no es base64 valido." }
        if ($decoded.Length -ne 32) {
            throw "La clave Ed25519 version $version debe contener 32 bytes."
        }
    }
}

function Assert-DeviceId([string]$Value) {
    $parsed = [Guid]::Empty
    if (-not [Guid]::TryParse($Value, [ref]$parsed) -or
        $parsed.ToString() -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') {
        throw "DeviceId debe ser un UUIDv4 valido."
    }
}

# ---------------------------------------------------------------------------
# Validacion de URL - coherente con validate_server_url del agente
# ---------------------------------------------------------------------------
function Assert-ServerUrl([string]$Url, [bool]$AllowHttp) {
    $uri = [Uri]$Url
    if (-not $uri.IsAbsoluteUri -or -not $uri.Host -or $uri.UserInfo -or
        $uri.AbsolutePath -ne "/" -or $uri.Query -or $uri.Fragment) {
        throw "ServerUrl solo puede contener esquema, host y puerto opcional."
    }
    if ($uri.Scheme -eq "https") { return }
    if ($AllowHttp) {
        $loopback = $uri.Host -in @("localhost", "127.0.0.1", "::1")
        if ($loopback) {
            Write-Host "  [!] HTTP permitido solo en loopback (modo desarrollo)." -ForegroundColor Yellow
            return
        }
        # Rechazar HTTP en red privada aunque se pase -AllowInsecureHttp
        throw "HTTP inseguro solo se permite en loopback (localhost/127.0.0.1/::1). Use HTTPS para produccion."
    }
    throw "ServerUrl debe comenzar con https://. Para desarrollo en loopback use -AllowInsecureHttp."
}

# ---------------------------------------------------------------------------
# Validaciones previas
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "   NEXUS IT Agent - Instalador v$PackageVersion      " -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

try {
    Assert-ServerUrl $ServerUrl $AllowInsecureHttp.IsPresent
    Assert-DeviceId $DeviceId
    $keys = $PublicKeysJson | ConvertFrom-Json -ErrorAction Stop
    Assert-PublicKeys $keys
    if ($ExpectedSha256 -notmatch "^[0-9a-fA-F]{64}$") {
        throw "ExpectedSha256 debe contener exactamente 64 caracteres hexadecimales."
    }
} catch {
    Write-Fail $_.Exception.Message
    exit 1
}

if (-not $ArtifactBaseUrl) { $ArtifactBaseUrl = $ServerUrl }
$ArtifactBaseUrl = $ArtifactBaseUrl.TrimEnd("/")
Assert-ServerUrl $ArtifactBaseUrl $AllowInsecureHttp.IsPresent

# ---------------------------------------------------------------------------
# Descargar paquete completo
# ---------------------------------------------------------------------------
$TempDir     = Join-Path $env:TEMP "nexus-agent-install-$(Get-Random)"
$PackageName = "nexus-it-agent-windows-x64-$PackageVersion.zip"
$DownloadUrl = "$ArtifactBaseUrl/$PackageName"
$ZipPath     = Join-Path $TempDir $PackageName
$ExtractPath = Join-Path $TempDir "package"

New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

try {
    Write-Step "[1/4] Descargando paquete desde $DownloadUrl..."

    # Usar HttpClient para TLS moderno
    $handler = [System.Net.Http.HttpClientHandler]::new()
    # NO deshabilitar validacion de certificados - falla cerrado
    $client  = [System.Net.Http.HttpClient]::new($handler)
    $client.DefaultRequestHeaders.Add("User-Agent", "NEXUS-IT-Installer/1.0")

    $response = $client.GetAsync($DownloadUrl).GetAwaiter().GetResult()
    if (-not $response.IsSuccessStatusCode) {
        throw "Error descargando paquete: HTTP $($response.StatusCode)"
    }
    $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    [System.IO.File]::WriteAllBytes($ZipPath, $bytes)
    Write-OK "Descargado: $ZipPath ($([Math]::Round($bytes.Length / 1MB, 1)) MB)"

    # ---------------------------------------------------------------------------
    # Verificar hash SHA-256
    # ---------------------------------------------------------------------------
    Write-Step "[2/4] Verificando integridad SHA-256..."
    $ActualHash = Get-FileSha256 $ZipPath
    Write-Host "      Hash calculado : $ActualHash" -ForegroundColor Gray

    if ($ActualHash -ne $ExpectedSha256.ToLower()) {
        throw "Hash SHA-256 incorrecto.`nEsperado: $ExpectedSha256`nObtenido: $ActualHash`nEl paquete puede estar danado o manipulado. Abortando."
    }
    Write-OK "Hash verificado."

    # ---------------------------------------------------------------------------
    # Verificar contenido minimo antes de extraer (no instalar paquetes incompletos)
    # ---------------------------------------------------------------------------
    Write-Step "[3/4] Verificando contenido del paquete..."
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    $entries = $zip.Entries | Select-Object -ExpandProperty FullName
    $zip.Dispose()

    # Reject absolute paths and parent traversal before Expand-Archive.
    $extractRoot = [System.IO.Path]::GetFullPath($ExtractPath + [System.IO.Path]::DirectorySeparatorChar)
    foreach ($entry in $entries) {
        $normalized = $entry.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $destination = [System.IO.Path]::GetFullPath((Join-Path $ExtractPath $normalized))
        if (-not $destination.StartsWith($extractRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Paquete ZIP contiene una ruta insegura: $entry"
        }
    }

    $required = @("runtime/python.exe", "agent/run_agent.py",
                  "service/nexus-agent-ctl.ps1", "service/nexus_agent_service.py",
                  "MANIFEST.sha256")
    $missing = @()
    foreach ($r in $required) {
        $found = $entries | Where-Object { $_.Replace('\', '/') -eq $r }
        if (-not $found) { $missing += $r }
    }
    if ($missing.Count -gt 0) {
        throw "Paquete incompleto. Archivos requeridos faltantes: $($missing -join ', ')"
    }
    Write-OK "Contenido verificado ($($entries.Count) archivos)."

    # ---------------------------------------------------------------------------
    # Extraer e instalar
    # ---------------------------------------------------------------------------
    Write-Step "[4/4] Instalando servicio..."
    New-Item -ItemType Directory -Force -Path $ExtractPath | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force

    $CtlScript = Join-Path $ExtractPath "service\nexus-agent-ctl.ps1"
    if (-not (Test-Path $CtlScript)) {
        throw "nexus-agent-ctl.ps1 no encontrado en el paquete extraido."
    }

    # Llamar al script de control con los parametros validados
    $CtlArgs = @(
        "install",
        "-ServerUrl", $ServerUrl,
        "-DeviceId", $DeviceId,
        "-PublicKeysJson", $PublicKeysJson,
        "-PackagePath", $ExtractPath,
        "-InstallPath", $InstallPath
    )
    if ($AllowInsecureHttp) { $CtlArgs += "-AllowInsecureHttp" }

    & powershell -ExecutionPolicy Bypass -File $CtlScript @CtlArgs
    if ($LASTEXITCODE -ne 0) {
        throw "nexus-agent-ctl.ps1 install fallo (exit $LASTEXITCODE)."
    }

} catch {
    Write-Fail "Error durante la instalacion: $($_.Exception.Message)"
    # Limpiar instalacion parcial
    if (Test-Path $TempDir) { Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host "  Los temporales se limpiaron. Si el control reporto limpieza incompleta, revise $InstallPath." -ForegroundColor Yellow
    exit 1
} finally {
    if (Test-Path $TempDir) { Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue }
}

Write-Host ""
Write-Host "====================================================" -ForegroundColor Green
Write-Host "   NEXUS IT Agent instalado correctamente.           " -ForegroundColor Green
Write-Host "   Verifique el estado con:" -ForegroundColor Green
Write-Host "   sc query NexusITAgent" -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Green
