#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Control del Windows Service de NEXUS IT Agent.

.DESCRIPTION
    Instala, actualiza, detiene, inicia, desinstala y verifica el estado del
    agente NEXUS IT como Windows Service real.

    Token almacenado con DPAPI (cifrado de maquina). Nunca en texto plano.
    ACL NTFS aplicada: solo SYSTEM y Administrators.
    Sin shell libre, sin PowerShell arbitrario, sin ejecucion de comandos externos
    mas alla del catalogo cerrado del agente.

.PARAMETER Action
    install | start | stop | status | update | rollback | uninstall

.PARAMETER ServerUrl
    URL HTTPS del servidor NEXUS IT. Requerido para install.

.PARAMETER DeviceId
    UUID del dispositivo. Requerido para install.

.PARAMETER PublicKeysJson
    JSON con claves publicas Ed25519 versionadas. Requerido para install.

.PARAMETER PackagePath
    Ruta al directorio del paquete extraido. Default: directorio del script.

.PARAMETER InstallPath
    Ruta de instalacion. Default: C:\ProgramData\NexusIT\Agent

.PARAMETER Purge
    En uninstall: eliminar TODOS los datos del agente (irreversible).

.EXAMPLE
    # Instalar
    .\nexus-agent-ctl.ps1 install -ServerUrl https://nexus.empresa.com -DeviceId <uuid> -PublicKeysJson '{"1":"<b64>"}'

    # Estado
    .\nexus-agent-ctl.ps1 status

    # Desinstalar preservando datos
    .\nexus-agent-ctl.ps1 uninstall

    # Desinstalar eliminando todo
    .\nexus-agent-ctl.ps1 uninstall -Purge
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("install", "start", "stop", "status", "update", "rollback", "uninstall")]
    [string]$Action,

    [string]$ServerUrl       = "",
    [string]$DeviceId        = "",
    [string]$PublicKeysJson  = "",
    [string]$PackagePath     = $PSScriptRoot,
    [string]$InstallPath     = "$env:ProgramData\NexusIT\Agent",
    [switch]$AllowInsecureHttp,
    [switch]$Purge
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ServiceName    = "NexusITAgent"
$ServiceDisplay = "NEXUS IT Agent"
$BackupPath     = "$InstallPath.backup"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Step([string]$Msg) {
    Write-Host "  $Msg" -ForegroundColor Cyan
}
function Write-OK([string]$Msg)    { Write-Host "  [OK] $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg)  { Write-Host "  [!] $Msg"  -ForegroundColor Yellow }
function Write-Fail([string]$Msg)  { Write-Host "  [X] $Msg"  -ForegroundColor Red }

function Require-Admin {
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = [System.Security.Principal.WindowsPrincipal]$id
    if (-not $p.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Este script requiere permisos de Administrador."
    }
}

function Apply-Acl([string]$Path) {
    # SIDs work on every Windows display language.
    if (Test-Path -LiteralPath $Path -PathType Container) {
        $systemGrant = "*S-1-5-18:(OI)(CI)(F)"
        $adminsGrant = "*S-1-5-32-544:(OI)(CI)(F)"
        & icacls.exe $Path /inheritance:r /grant:r $systemGrant /grant:r $adminsGrant /T /Q | Out-Null
    } else {
        $systemGrant = "*S-1-5-18:(F)"
        $adminsGrant = "*S-1-5-32-544:(F)"
        & icacls.exe $Path /inheritance:r /grant:r $systemGrant /grant:r $adminsGrant | Out-Null
    }
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo aplicar ACL segura a: $Path (icacls exit $LASTEXITCODE)."
    }
}

function Assert-PublicKeys($Keys) {
    if ($null -eq $Keys -or $Keys.PSObject.Properties.Count -eq 0) {
        throw "PublicKeysJson debe contener al menos una clave Ed25519."
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

function Get-RuntimePython {
    $pythonExe = Join-Path $InstallPath "runtime\python.exe"
    if (-not (Test-Path $pythonExe)) {
        throw "Runtime Python no encontrado en: $pythonExe"
    }
    return $pythonExe
}

function Invoke-Sc([string[]]$Arguments) {
    & sc.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "sc.exe fallo (exit $LASTEXITCODE): $($Arguments -join ' ')"
    }
}

function Assert-DirectoryIntegrity([string]$RootPath, [string]$ManifestName) {
    $manifestPath = [System.IO.Path]::GetFullPath((Join-Path $RootPath $ManifestName))
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "$ManifestName no encontrado."
    }

    $root = [System.IO.Path]::GetFullPath($RootPath + [System.IO.Path]::DirectorySeparatorChar)
    $manifestFiles = @{}
    foreach ($line in Get-Content -LiteralPath $manifestPath) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') {
            throw "Linea invalida en $ManifestName."
        }
        $expected = $Matches[1].ToLowerInvariant()
        $relative = $Matches[2].Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $fullPath = [System.IO.Path]::GetFullPath((Join-Path $RootPath $relative))
        if (-not $fullPath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "$ManifestName contiene una ruta insegura: $relative"
        }
        if ($manifestFiles.ContainsKey($fullPath)) {
            throw "$ManifestName contiene una ruta duplicada: $relative"
        }
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "Archivo listado en $ManifestName no encontrado: $relative"
        }
        $actual = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) {
            throw "Integridad invalida para archivo del paquete: $relative"
        }
        $manifestFiles[$fullPath] = $true
    }

    $actualFiles = Get-ChildItem -LiteralPath $RootPath -Recurse -File |
        Where-Object { $_.FullName -ne $manifestPath }
    foreach ($file in $actualFiles) {
        if (-not $manifestFiles.ContainsKey($file.FullName)) {
            throw "Archivo no declarado en $ManifestName`: $($file.FullName)"
        }
    }
    if ($manifestFiles.Count -ne $actualFiles.Count) {
        throw "$ManifestName no coincide con el contenido esperado."
    }
    Write-OK "Integridad interna del paquete verificada."
}

function Assert-PackageIntegrity {
    Assert-DirectoryIntegrity $PackagePath "MANIFEST.sha256"
}

function New-BackupManifest {
    $manifestPath = Join-Path $BackupPath "BACKUP.sha256"
    $lines = @()
    foreach ($file in Get-ChildItem -LiteralPath $BackupPath -Recurse -File |
             Where-Object { $_.FullName -ne $manifestPath } |
             Sort-Object FullName) {
        $relative = $file.FullName.Substring($BackupPath.Length).TrimStart('\').Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $lines += "$hash  $relative"
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($manifestPath, $lines, $utf8NoBom)
}

function Assert-BackupIntegrity {
    Assert-DirectoryIntegrity $BackupPath "BACKUP.sha256"
}

function Wait-ServiceStatus([string]$Status, [int]$TimeoutSec = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq $Status) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-ServiceStatus {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) { return $svc.Status }
    return "NotInstalled"
}

# ---------------------------------------------------------------------------
# Validacion de URL (coherente con validate_server_url del agente)
# ---------------------------------------------------------------------------
function Assert-ServerUrl([string]$Url) {
    $uri = [Uri]$Url
    if (-not $uri.IsAbsoluteUri -or -not $uri.Host -or $uri.UserInfo -or
        $uri.AbsolutePath -ne "/" -or $uri.Query -or $uri.Fragment) {
        throw "ServerUrl solo puede contener esquema, host y puerto opcional."
    }
    if ($uri.Scheme -eq "https") { return }
    if ($AllowInsecureHttp) {
        $loopback = $uri.Host -in @("localhost", "127.0.0.1", "::1")
        if ($loopback) {
            Write-Warn "HTTP permitido solo en loopback (modo desarrollo)."
            return
        }
        throw "HTTP inseguro solo se permite en loopback. Use HTTPS para produccion."
    }
    throw "ServerUrl debe comenzar con https://. Para desarrollo en loopback use -AllowInsecureHttp."
}

function Remove-PartialInstallation {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        if ($svc.Status -eq "Running") {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            [void](Wait-ServiceStatus "Stopped" 20)
        }
        Invoke-Sc @("delete", $ServiceName)
    }
    if (Test-Path -LiteralPath $InstallPath) {
        Remove-Item -LiteralPath $InstallPath -Recurse -Force
    }
}

# ---------------------------------------------------------------------------
# ACTION: install
# ---------------------------------------------------------------------------
function Install-Agent {
    if (-not $ServerUrl) { throw "-ServerUrl es requerido para install." }
    if (-not $DeviceId)  { throw "-DeviceId es requerido para install." }
    if (-not $PublicKeysJson) { throw "-PublicKeysJson es requerido para install." }

    Assert-ServerUrl $ServerUrl
    Assert-DeviceId $DeviceId
    $keys = $PublicKeysJson | ConvertFrom-Json -ErrorAction Stop
    Assert-PublicKeys $keys
    Assert-PackageIntegrity
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        throw "$ServiceName ya esta instalado. Use 'update' para binarios o desinstale antes de enrolar nuevamente."
    }
    if (Test-Path -LiteralPath $InstallPath) {
        throw "Ya existe $InstallPath. Revise o elimine manualmente los residuos antes de instalar."
    }

    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  NEXUS IT Agent - Instalacion" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan

    # 1. Verificar que el paquete contenga el runtime
    $runtimeSrc = Join-Path $PackagePath "runtime\python.exe"
    if (-not (Test-Path $runtimeSrc)) {
        throw "Runtime Python no encontrado en el paquete: $runtimeSrc"
    }

    try {
        # 2. Crear directorio de instalacion
        Write-Step "[1/6] Creando directorio de instalacion..."
        New-Item -ItemType Directory -Path $InstallPath | Out-Null
        Apply-Acl $InstallPath

    # 3. Copiar archivos del paquete
    Write-Step "[2/6] Copiando archivos del paquete..."
    # Copiar runtime, agent/, service/ - preservar datos existentes (agent.db, etc.)
    $Subdirs = @("runtime", "agent", "service")
    foreach ($sub in $Subdirs) {
        $src = Join-Path $PackagePath $sub
        $dst = Join-Path $InstallPath $sub
        if (Test-Path $src) {
            if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
            Copy-Item $src $dst -Recurse
        }
    }
    # Copiar example config (no sobrescribir config real si ya existe)
    $exampleConfig = Join-Path $PackagePath "agent_config.example.json"
    if (Test-Path $exampleConfig) {
        Copy-Item $exampleConfig $InstallPath
    }

    # 4. Generar config no-secreta
    Write-Step "[3/6] Generando configuracion no-secreta..."
    $Config = @{
        server_url        = $ServerUrl
        device_id         = $DeviceId
        hostname          = $env:COMPUTERNAME
        inventory_interval = 300
        public_keys       = $keys
    }
    $ConfigPath = Join-Path $InstallPath "agent_config.json"
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ConfigPath, ($Config | ConvertTo-Json -Depth 5), $Utf8NoBom)
    Write-OK "Config guardada (sin secretos): $ConfigPath"

    # 5. Guardar token con DPAPI
    Write-Step "[4/6] Protegiendo token con DPAPI..."
    $TokenSecure = Read-Host "Token del agente (entregado por la consola NEXUS IT)" -AsSecureString
    $TokenBstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($TokenSecure)
    $TokenPlain = $null
    $pythonExe = Join-Path $InstallPath "runtime\python.exe"
    $svcScript = Join-Path $InstallPath "service\nexus_agent_service.py"
    try {
        $TokenPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($TokenBstr)
        if (-not $TokenPlain -or $TokenPlain.Length -lt 10 -or $TokenPlain.Length -gt 512 -or $TokenPlain -match "\s") {
            throw "Token invalido o vacio."
        }
        # stdin keeps the secret out of the child process command line.
        $TokenPlain | & $pythonExe $svcScript --store-token-stdin
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo proteger el token con DPAPI."
        }
    } finally {
        if ($TokenBstr -ne [IntPtr]::Zero) {
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($TokenBstr)
        }
        $TokenPlain = $null
        $TokenSecure.Dispose()
    }
    Write-OK "Token protegido con DPAPI (cifrado de maquina)."

    # 6. Aplicar ACL
    Write-Step "[5/6] Aplicando ACL NTFS..."
    $SecurePaths = @($ConfigPath,
                     (Join-Path $InstallPath ".token.dpapi"),
                     $InstallPath)
    foreach ($p in $SecurePaths) {
        if (Test-Path $p) { Apply-Acl $p }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallPath "logs") | Out-Null
    Apply-Acl (Join-Path $InstallPath "logs")
    Write-OK "ACL aplicada."

    # 7. Registrar Windows Service
    Write-Step "[6/6] Registrando Windows Service..."
    # Crear servicio usando Python + pywin32
    $binPath = "`"$(Join-Path $InstallPath "runtime\python.exe")`" `"$svcScript`""
    Invoke-Sc @("create", $ServiceName, "binPath=", $binPath,
        "DisplayName=", $ServiceDisplay, "start=", "delayed-auto")

    # Descripcion
    Invoke-Sc @("description", $ServiceName,
        "NEXUS IT monitoring agent. Closed action catalog only.")

    # Configurar reinicio automatico tras fallos (1 min delay, 3 intentos)
    Invoke-Sc @("failure", $ServiceName, "reset=", "3600", "actions=",
        "restart/60000/restart/60000/restart/60000")

    # Iniciar servicio
    Start-Service -Name $ServiceName

    if (Wait-ServiceStatus "Running" 30) {
        Write-OK "Servicio $ServiceName RUNNING."
    } else {
        $status = Get-ServiceStatus
        throw "El servicio no arranco a tiempo. Estado: $status. Ver Event Log -> Application -> NexusITAgent."
    }

    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "  Instalacion completada." -ForegroundColor Green
    Write-Host "  Servicio: $ServiceName (inicio automatico retrasado)" -ForegroundColor Green
    Write-Host "  Datos   : $InstallPath" -ForegroundColor Green
    Write-Host "  Nota    : Firma Authenticode PENDIENTE (SIGN_PENDING)" -ForegroundColor Yellow
        Write-Host "============================================" -ForegroundColor Green
    } catch {
        $installFailure = $_
        Write-Warn "La instalacion fallo; limpiando servicio y archivos parciales..."
        try {
            Remove-PartialInstallation
        } catch {
            Write-Warn "La limpieza local no fue completa: $($_.Exception.Message)"
        }
        throw $installFailure
    }
}

# ---------------------------------------------------------------------------
# ACTION: start / stop / status
# ---------------------------------------------------------------------------
function Start-Agent {
    Write-Step "Iniciando $ServiceName..."
    Start-Service -Name $ServiceName
    if (Wait-ServiceStatus "Running" 20) { Write-OK "RUNNING" }
    else { throw "No arranco a tiempo. Ver Event Log." }
}

function Stop-Agent {
    Write-Step "Deteniendo $ServiceName..."
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    if (Wait-ServiceStatus "Stopped" 20) { Write-OK "STOPPED" }
    else { throw "No se detuvo a tiempo." }
}

function Show-Status {
    $status = Get-ServiceStatus
    $color = if ($status -eq "Running") { "Green" } elseif ($status -eq "Stopped") { "Yellow" } else { "Red" }
    Write-Host "  Servicio $ServiceName`: $status" -ForegroundColor $color
    $configPath = Join-Path $InstallPath "agent_config.json"
    if (Test-Path $configPath) {
        $cfg = Get-Content $configPath | ConvertFrom-Json
        Write-Host "  Servidor  : $($cfg.server_url)" -ForegroundColor Gray
        Write-Host "  Dispositivo: $($cfg.device_id)" -ForegroundColor Gray
    }
}

# ---------------------------------------------------------------------------
# ACTION: update
# ---------------------------------------------------------------------------
function Update-Agent {
    Write-Step "Actualizando $ServiceName..."
    Assert-PackageIntegrity
    $status = Get-ServiceStatus
    # Backup
    if (Test-Path $BackupPath) { Remove-Item $BackupPath -Recurse -Force }
    Write-Step "Creando respaldo en $BackupPath..."
    # Copiar solo runtime y agent (no datos)
    New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null
    Apply-Acl $BackupPath
    foreach ($sub in @("runtime", "agent", "service")) {
        $src = Join-Path $InstallPath $sub
        if (Test-Path $src) { Copy-Item $src (Join-Path $BackupPath $sub) -Recurse }
    }
    New-BackupManifest
    Apply-Acl $BackupPath
    Assert-BackupIntegrity

    try {
        if ($status -eq "Running") {
            Stop-Agent
        }
        # Instalar nueva version (sin tocar .token.dpapi ni agent.db)
        foreach ($sub in @("runtime", "agent", "service")) {
            $src = Join-Path $PackagePath $sub
            $dst = Join-Path $InstallPath $sub
            if (Test-Path $src) {
                if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
                Copy-Item $src $dst -Recurse
            }
        }
        Start-Agent
        if ((Get-ServiceStatus) -ne "Running") {
            throw "El servicio no arranco tras la actualizacion."
        }
        Write-OK "Actualizacion completada."
    } catch {
        Write-Fail "Error durante la actualizacion: $_"
        Write-Warn "Ejecutando rollback automatico..."
        Invoke-Rollback
        throw
    }
}

# ---------------------------------------------------------------------------
# ACTION: rollback
# ---------------------------------------------------------------------------
function Invoke-Rollback {
    if (-not (Test-Path $BackupPath)) {
        throw "No existe respaldo en $BackupPath. No es posible hacer rollback."
    }
    Assert-BackupIntegrity
    $status = Get-ServiceStatus
    if ($status -eq "Running") { Stop-Agent }

    foreach ($sub in @("runtime", "agent", "service")) {
        $src = Join-Path $BackupPath $sub
        $dst = Join-Path $InstallPath $sub
        if (Test-Path $src) {
            if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
            Copy-Item $src $dst -Recurse
        }
    }
    Start-Agent
    Write-OK "Rollback completado."
}

# ---------------------------------------------------------------------------
# ACTION: uninstall
# ---------------------------------------------------------------------------
function Uninstall-Agent {
    Write-Warn "Desinstalando $ServiceName..."
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        if ($svc.Status -eq "Running") { Stop-Agent }
        Invoke-Sc @("delete", $ServiceName)
        Write-OK "Servicio eliminado."
    }
    if ($Purge) {
        Write-Warn "Eliminando TODOS los datos (--purge)..."
        if (Test-Path $InstallPath) { Remove-Item $InstallPath -Recurse -Force }
        if (Test-Path $BackupPath)  { Remove-Item $BackupPath  -Recurse -Force }
        Write-OK "Datos eliminados."
    } else {
        Write-Warn "Datos conservados en $InstallPath. Use -Purge para eliminarlos."
    }
    Write-OK "Desinstalacion completada."
}

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------
Require-Admin

switch ($Action) {
    "install"   { Install-Agent }
    "start"     { Start-Agent }
    "stop"      { Stop-Agent }
    "status"    { Show-Status }
    "update"    { Update-Agent }
    "rollback"  { Invoke-Rollback }
    "uninstall" { Uninstall-Agent }
}
