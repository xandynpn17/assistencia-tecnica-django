param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$ManageArgs,
    [Parameter()]
    [string]$EnvPath = ".env.local",
    [Parameter()]
    [string]$PythonExe = "",
    [switch]$StartProjectPg = $true
)

$ErrorActionPreference = "Stop"

function Load-EnvFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Arquivo de ambiente '$Path' nao encontrado. Execute primeiro: .\setup_local_env.ps1 -Overwrite"
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
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Resolve-PythonExe {
    param([string]$Preferred)

    if ($Preferred -and (Test-Path $Preferred)) {
        return @{ File = $Preferred; Args = @() }
    }

    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return @{ File = $venvPython; Args = @() }
    }

    $python312 = "C:\Users\Xandy\AppData\Local\Programs\Python\Python312\python.exe"
    if (Test-Path $python312) {
        return @{ File = $python312; Args = @() }
    }

    return @{ File = "py"; Args = @("-3.12") }
}

function Test-TcpPort {
    param(
        [string]$TargetHost,
        [int]$TargetPort,
        [int]$TimeoutMs = 1200
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

function Ensure-ProjectPostgres {
    param(
        [string]$DbHost,
        [int]$DbPort
    )

    if (Test-TcpPort -TargetHost $DbHost -TargetPort $DbPort) {
        return
    }

    $isLocalHost = $DbHost -in @("127.0.0.1", "localhost", "::1")
    if (-not $isLocalHost) {
        throw "PostgreSQL indisponivel em ${DbHost}:$DbPort e host nao local."
    }

    $pgCtl = "C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe"
    $pgData = Join-Path $PSScriptRoot "pgdata_codex"
    $pgLog = Join-Path $PSScriptRoot "backups\pg5433.log"

    if (-not (Test-Path $pgCtl)) {
        throw "pg_ctl nao encontrado em '$pgCtl'."
    }
    if (-not (Test-Path $pgData)) {
        throw "Diretorio pgdata_codex nao encontrado em '$pgData'."
    }

    Write-Host "PostgreSQL em ${DbHost}:$DbPort nao respondeu. Tentando iniciar pgdata_codex..."
    & $pgCtl -D $pgData -l $pgLog -o "-p $DbPort" start | Out-Host
    Start-Sleep -Seconds 2

    if (-not (Test-TcpPort -TargetHost $DbHost -TargetPort $DbPort -TimeoutMs 2000)) {
        throw "Nao foi possivel iniciar PostgreSQL em ${DbHost}:$DbPort. Verifique $pgLog"
    }
}

$envFullPath = Join-Path $PSScriptRoot $EnvPath
$managePy = Join-Path $PSScriptRoot "manage.py"

if (-not (Test-Path $managePy)) {
    throw "manage.py nao encontrado em '$managePy'."
}

if (-not $ManageArgs -or $ManageArgs.Count -eq 0) {
    $ManageArgs = @("check")
}

Load-EnvFile -Path $envFullPath
$python = Resolve-PythonExe -Preferred $PythonExe

if ($StartProjectPg -and $env:DJANGO_DB_ENGINE -eq "postgres") {
    $dbHost = if ($env:DJANGO_DB_HOST) { $env:DJANGO_DB_HOST } else { "127.0.0.1" }
    $dbPort = if ($env:DJANGO_DB_PORT) { [int]$env:DJANGO_DB_PORT } else { 5432 }
    Ensure-ProjectPostgres -DbHost $dbHost -DbPort $dbPort
}

Write-Host ""
Write-Host "Assistencia - comandos locais no PostgreSQL"
Write-Host "DB: $env:DJANGO_DB_NAME em $env:DJANGO_DB_HOST`:$env:DJANGO_DB_PORT"
Write-Host "Comando: manage.py $($ManageArgs -join ' ')"
Write-Host ""

& $python.File @($python.Args + @($managePy) + $ManageArgs)
exit $LASTEXITCODE
