param(
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1",
    [string]$PythonExe = "C:\Users\Xandy\AppData\Local\Programs\Python\Python312\python.exe",
    [string]$DbName = "assistencia_dev",
    [string]$DbUser = "alexandre",
    [string]$DbPassword = "",
    [string]$DbHost = "127.0.0.1",
    [int]$DbPort = 5433,
    [string]$LocalEnvPath = ".env.postgres.local",
    [switch]$StartLocalPg = $true,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

function Test-TcpPort {
    param(
        [string]$TargetHost,
        [int]$TargetPort,
        [int]$TimeoutMs = 1000
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($TargetHost, $TargetPort, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $ok) {
            return $false
        }
        $client.EndConnect($iar) | Out-Null
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Ensure-LocalPostgres {
    param(
        [int]$TargetPort
    )

    if (Test-TcpPort -TargetHost $DbHost -TargetPort $TargetPort) {
        Write-Host "PostgreSQL ja esta ativo em ${DbHost}:$TargetPort"
        return
    }

    $pgCtl = "C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe"
    $pgData = Join-Path $PSScriptRoot "pgdata_codex"
    $pgLog = Join-Path $pgData "server.log"

    if (-not (Test-Path $pgCtl)) {
        throw "pg_ctl nao encontrado em '$pgCtl'. Inicie o PostgreSQL manualmente."
    }
    if (-not (Test-Path $pgData)) {
        throw "Diretorio de dados local nao encontrado em '$pgData'."
    }

    Write-Host "Iniciando PostgreSQL local em ${DbHost}:$TargetPort ..."
    & $pgCtl -D $pgData -l $pgLog -o "-p $TargetPort" start | Out-Host

    Start-Sleep -Seconds 2
    if (-not (Test-TcpPort -TargetHost $DbHost -TargetPort $TargetPort -TimeoutMs 2000)) {
        throw "PostgreSQL nao respondeu em ${DbHost}:$TargetPort apos tentativa de start."
    }
}

function Load-LocalEnvConfig {
    param([string]$Path)

    if (-not $Path) {
        return
    }
    if (-not (Test-Path $Path)) {
        return
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        $parts = $line.Split("=", 2)
        if ($parts.Count -ne 2) {
            return
        }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim("'").Trim('"')
        if (-not $key) {
            return
        }
        if (-not [Environment]::GetEnvironmentVariable($key, "Process")) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

if (-not (Test-Path $PythonExe)) {
    throw "Python 3.12 nao encontrado em '$PythonExe'."
}

$managePy = Join-Path $PSScriptRoot "manage.py"
if (-not (Test-Path $managePy)) {
    throw "manage.py nao encontrado em '$managePy'. Execute este script na raiz do projeto."
}

if ($StartLocalPg) {
    Ensure-LocalPostgres -TargetPort $DbPort
}

Load-LocalEnvConfig -Path (Join-Path $PSScriptRoot $LocalEnvPath)

$resolvedPassword = $DbPassword
if (-not $resolvedPassword) {
    $resolvedPassword = $env:DJANGO_DB_PASSWORD
}
if (-not $resolvedPassword) {
    throw "Senha do PostgreSQL nao definida. Use -DbPassword ou DJANGO_DB_PASSWORD (ex.: arquivo local .env.postgres.local)."
}

$env:DJANGO_DB_ENGINE = "postgres"
$env:DJANGO_DB_NAME = $DbName
$env:DJANGO_DB_USER = $DbUser
$env:DJANGO_DB_PASSWORD = $resolvedPassword
$env:DJANGO_DB_HOST = $DbHost
$env:DJANGO_DB_PORT = [string]$DbPort
if (-not $env:DJANGO_DB_CONN_MAX_AGE) {
    $env:DJANGO_DB_CONN_MAX_AGE = "0"
}
if (-not $env:DJANGO_DB_CONNECT_TIMEOUT) {
    $env:DJANGO_DB_CONNECT_TIMEOUT = "5"
}

Write-Host ""
Write-Host "Ambiente PostgreSQL configurado:"
Write-Host "  DB:   $env:DJANGO_DB_NAME"
Write-Host "  USER: $env:DJANGO_DB_USER"
Write-Host "  HOST: $env:DJANGO_DB_HOST"
Write-Host "  PORT: $env:DJANGO_DB_PORT"
Write-Host "  CONN_MAX_AGE: $env:DJANGO_DB_CONN_MAX_AGE"
Write-Host ""

& $PythonExe $managePy check_postgres_ready --check-connection
if ($CheckOnly) {
    Write-Host "CheckOnly ativo: conexao validada, sem iniciar runserver."
    exit 0
}

& $PythonExe $managePy runserver "$BindHost`:$Port"
