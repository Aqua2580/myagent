[CmdletBinding()]
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$dockerRoot = Join-Path $projectRoot "docker"
$secretsRoot = Join-Path $dockerRoot "secrets"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function New-HexSecret {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [System.Convert]::ToHexString($bytes).ToLowerInvariant()
}

function Write-ProtectedFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    if ((Test-Path -LiteralPath $Path) -and -not $Force) {
        throw "Refusing to overwrite existing local secret: $Path. Use -Force explicitly."
    }
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

New-Item -ItemType Directory -Path $secretsRoot -Force | Out-Null

$postgresPassword = New-HexSecret
$redisPassword = New-HexSecret

$postgresSecretPath = Join-Path $secretsRoot "postgres_password.txt"
$redisSecretPath = Join-Path $secretsRoot "redis.conf"
$redisTemplatePath = Join-Path $secretsRoot "redis.conf.example"
$dockerEnvPath = Join-Path $dockerRoot ".env"
$dockerEnvTemplatePath = Join-Path $dockerRoot ".env.example"
$generatedAppEnvPath = Join-Path $dockerRoot ".env.app.generated"
$appEnvPath = Join-Path $projectRoot ".env"

Write-ProtectedFile -Path $postgresSecretPath -Content $postgresPassword

$redisConfig = [System.IO.File]::ReadAllText($redisTemplatePath).Replace(
    "replace-with-a-long-random-redis-password",
    $redisPassword
)
Write-ProtectedFile -Path $redisSecretPath -Content $redisConfig

if ((Test-Path -LiteralPath $dockerEnvPath) -and -not $Force) {
    Write-Host "Keeping existing docker/.env."
}
else {
    [System.IO.File]::Copy($dockerEnvTemplatePath, $dockerEnvPath, $true)
}

$appEnv = @"
MYAGENT_ENVIRONMENT=development
MYAGENT_HOST=0.0.0.0
MYAGENT_PORT=8000
MYAGENT_LOG_LEVEL=INFO
MYAGENT_DATABASE_URL=postgresql+asyncpg://myagent:${postgresPassword}@localhost:5432/myagent
MYAGENT_DATABASE_ECHO=false
MYAGENT_DATABASE_POOL_SIZE=10
MYAGENT_DATABASE_MAX_OVERFLOW=20
MYAGENT_REDIS_URL=redis://:${redisPassword}@localhost:6379/0
MYAGENT_CHECKPOINT_KEY_PREFIX=myagent:checkpoint:v1
MYAGENT_CHECKPOINT_TTL_SECONDS=86400
"@
[System.IO.File]::WriteAllText($generatedAppEnvPath, $appEnv, $utf8NoBom)

if (-not (Test-Path -LiteralPath $appEnvPath)) {
    [System.IO.File]::Copy($generatedAppEnvPath, $appEnvPath, $false)
    Write-Host "Created local application .env."
}
else {
    Write-Warning "Application .env already exists. Merge docker/.env.app.generated manually."
}

Write-Host "Docker secrets and local configuration created without printing secret values."
