param(
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1",
    [string]$PythonExe = "C:\Users\Xandy\AppData\Local\Programs\Python\Python312\python.exe",
    [string]$DbName = "assistencia_dev",
    [string]$DbUser = "alexandre",
    [string]$DbPassword = "Xandy1234*",
    [string]$DbHost = "127.0.0.1",
    [int]$DbPort = 5433,
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

$env:DJANGO_DB_ENGINE = "postgres"
$env:DJANGO_DB_NAME = $DbName
$env:DJANGO_DB_USER = $DbUser
$env:DJANGO_DB_PASSWORD = $DbPassword
$env:DJANGO_DB_HOST = $DbHost
$env:DJANGO_DB_PORT = [string]$DbPort

Write-Host ""
Write-Host "Ambiente PostgreSQL configurado:"
Write-Host "  DB:   $env:DJANGO_DB_NAME"
Write-Host "  USER: $env:DJANGO_DB_USER"
Write-Host "  HOST: $env:DJANGO_DB_HOST"
Write-Host "  PORT: $env:DJANGO_DB_PORT"
Write-Host ""

& $PythonExe $managePy check_postgres_ready --check-connection
if ($CheckOnly) {
    Write-Host "CheckOnly ativo: conexao validada, sem iniciar runserver."
    exit 0
}

& $PythonExe $managePy runserver "$BindHost`:$Port"
