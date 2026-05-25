param(
    [int]$Port = 8000,
    [string]$HostIp = "",
    [string]$SourceDbEnv = ".env.postgres.local",
    [string]$OutputEnv = ".env.local",
    [switch]$Overwrite
)

$ErrorActionPreference = "Stop"

function Get-LocalPrivateIPv4 {
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -and
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            (
                $_.IPAddress -like "192.168.*" -or
                $_.IPAddress -like "10.*" -or
                $_.IPAddress -match "^172\.(1[6-9]|2[0-9]|3[0-1])\."
            )
        } |
        Select-Object -ExpandProperty IPAddress -Unique

    return $ips | Select-Object -First 1
}

function New-DjangoSecretKey {
    $bytes = New-Object byte[] 50
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd("=") -replace "\+", "-" -replace "/", "_"
}

function Read-EnvFile {
    param([string]$Path)

    $data = @{}
    if (-not (Test-Path $Path)) {
        return $data
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim("'").Trim('"')
        if ($key) {
            $data[$key] = $value
        }
    }
    return $data
}

if (-not $HostIp) {
    $HostIp = Get-LocalPrivateIPv4
}

if (-not $HostIp) {
    throw "Nao foi possivel detectar um IPv4 local. Informe manualmente com -HostIp."
}

if ((Test-Path $OutputEnv) -and -not $Overwrite) {
    throw "Arquivo '$OutputEnv' ja existe. Use -Overwrite para recriar."
}

$dbEnv = Read-EnvFile -Path $SourceDbEnv
$required = @("DJANGO_DB_ENGINE", "DJANGO_DB_NAME", "DJANGO_DB_USER", "DJANGO_DB_PASSWORD", "DJANGO_DB_HOST", "DJANGO_DB_PORT")
$missing = @()
foreach ($key in $required) {
    if (-not $dbEnv.ContainsKey($key) -or -not $dbEnv[$key]) {
        $missing += $key
    }
}
if ($missing.Count -gt 0) {
    throw "Variaveis ausentes em '$SourceDbEnv': $($missing -join ', ')"
}

$allowedHosts = @("127.0.0.1", "localhost", $HostIp) -join ","
$csrfOrigins = @("http://127.0.0.1:$Port", "http://localhost:$Port", "http://$HostIp`:$Port") -join ","
$secretKey = New-DjangoSecretKey
$connMaxAge = if ($dbEnv.ContainsKey("DJANGO_DB_CONN_MAX_AGE") -and $dbEnv["DJANGO_DB_CONN_MAX_AGE"]) { $dbEnv["DJANGO_DB_CONN_MAX_AGE"] } else { "60" }
$connectTimeout = if ($dbEnv.ContainsKey("DJANGO_DB_CONNECT_TIMEOUT") -and $dbEnv["DJANGO_DB_CONNECT_TIMEOUT"]) { $dbEnv["DJANGO_DB_CONNECT_TIMEOUT"] } else { "5" }

$lines = @(
    "# Ambiente local em rede - nao versionar",
    "DJANGO_DEBUG=0",
    "DJANGO_LOCAL_NETWORK_MODE=1",
    "DJANGO_SECRET_KEY=$secretKey",
    "DJANGO_ALLOWED_HOSTS=$allowedHosts",
    "DJANGO_CSRF_TRUSTED_ORIGINS=$csrfOrigins",
    "DJANGO_DB_ENGINE=$($dbEnv['DJANGO_DB_ENGINE'])",
    "DJANGO_DB_NAME=$($dbEnv['DJANGO_DB_NAME'])",
    "DJANGO_DB_USER=$($dbEnv['DJANGO_DB_USER'])",
    "DJANGO_DB_PASSWORD=$($dbEnv['DJANGO_DB_PASSWORD'])",
    "DJANGO_DB_HOST=$($dbEnv['DJANGO_DB_HOST'])",
    "DJANGO_DB_PORT=$($dbEnv['DJANGO_DB_PORT'])",
    "DJANGO_DB_CONN_MAX_AGE=$connMaxAge",
    "DJANGO_DB_CONNECT_TIMEOUT=$connectTimeout"
)

$lines | Set-Content -Path $OutputEnv -Encoding UTF8

Write-Host "Arquivo local criado: $OutputEnv"
Write-Host "IP do servidor local: $HostIp"
Write-Host "Endereco para outros PCs: http://$HostIp`:$Port/"
Write-Host "Segredos e senha nao foram exibidos."
