[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..')
)
$environmentPath = Join-Path $repositoryRoot '.env'

if (Test-Path -LiteralPath $environmentPath) {
    Write-Output '.env already exists; no changes made.'
    exit 0
}

function New-RandomSecret {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes)
}

$lines = @(
    'NEXUS_ENV=development'
    'NEXUS_API_PORT=8000'
    'NEXUS_POSTGRES_DB=nexus_it'
    'NEXUS_POSTGRES_USER=nexus_bootstrap'
    "NEXUS_POSTGRES_PASSWORD=$(New-RandomSecret)"
    "NEXUS_RUNTIME_POSTGRES_PASSWORD=$(New-RandomSecret)"
    "NEXUS_MAINTENANCE_POSTGRES_PASSWORD=$(New-RandomSecret)"
    "NEXUS_REDIS_PASSWORD=$(New-RandomSecret)"
    "NEXUS_SERVER_PEPPER=$(New-RandomSecret)"
)

[System.IO.File]::WriteAllLines(
    $environmentPath,
    $lines,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Output '.env created with independent random local passwords.'
