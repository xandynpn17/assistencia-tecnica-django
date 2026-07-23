param(
    [int]$Port = 8000,
    [string]$BindHost = "0.0.0.0",
    [string]$EnvPath = ".env.local",
    [string]$PythonExe = "",
    [switch]$StartProjectPg = $true,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

function Load-EnvFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Arquivo de ambiente '$Path' nao encontrado. Execute primeiro: .\setup_local_env.ps1"
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

function Get-ProjectRunserverProcesses {
    param([string]$ManagePyPath)

    $managePyNormalizado = $ManagePyPath.ToLowerInvariant()
    return @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -and
        $_.CommandLine.ToLowerInvariant().Contains($managePyNormalizado) -and
        $_.CommandLine -match "\brunserver\b"
    } | Sort-Object ProcessId -Unique)
}

function Stop-ProjectRunserverProcesses {
    param([string]$ManagePyPath)

    $processos = @(Get-ProjectRunserverProcesses -ManagePyPath $ManagePyPath)
    if (-not $processos.Count) {
        return
    }

    Write-Host "Instancias antigas do Django encontradas para este projeto. Limpando antes de subir a nova sessao..."
    foreach ($processo in $processos) {
        try {
            Stop-Process -Id $processo.ProcessId -Force -ErrorAction Stop
            Write-Host (" - PID {0} encerrado." -f $processo.ProcessId)
        } catch {
            Write-Warning ("Nao foi possivel encerrar PID {0}: {1}" -f $processo.ProcessId, $_.Exception.Message)
        }
    }

    Start-Sleep -Seconds 1
}

function Get-ListeningProcessIdsForPort {
    param([int]$TargetPort)

    try {
        return @(Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        return @()
    }
}

function Assert-PortAvailableForProject {
    param(
        [string]$ManagePyPath,
        [int]$TargetPort
    )

    $escutando = @(Get-ListeningProcessIdsForPort -TargetPort $TargetPort)
    if (-not $escutando.Count) {
        return
    }

    $runserversProjeto = @(Get-ProjectRunserverProcesses -ManagePyPath $ManagePyPath)
    $pidsProjeto = @($runserversProjeto | ForEach-Object { $_.ProcessId })
    $conflitantes = @($escutando | Where-Object { $_ -notin $pidsProjeto })

    if ($conflitantes.Count) {
        throw "A porta $TargetPort ja esta ocupada por outro processo (PID(s): $($conflitantes -join ', ')). Feche esse processo ou use outra porta no run_local.ps1."
    }
}

function Clear-ProjectSessionsIfNeeded {
    param(
        [string]$PythonFile,
        [string[]]$PythonArgs,
        [string]$ManagePyPath
    )

    $clearOnStartRaw = [Environment]::GetEnvironmentVariable("DJANGO_CLEAR_SESSIONS_ON_SERVER_START", "Process")
    $clearOnStart = $false

    if ([string]::IsNullOrWhiteSpace($clearOnStartRaw)) {
        $clearOnStart = ($env:DJANGO_LOCAL_NETWORK_MODE -eq "1")
    } else {
        $clearOnStart = $clearOnStartRaw -eq "1"
    }

    if (-not $clearOnStart) {
        return
    }

    Write-Host "Limpando sessoes ativas antes de subir o servidor local..."
    & $PythonFile @($PythonArgs + @($ManagePyPath, "clear_all_sessions")) | Out-Host
}

$envFullPath = Join-Path $PSScriptRoot $EnvPath
$managePy = Join-Path $PSScriptRoot "manage.py"

if (-not (Test-Path $managePy)) {
    throw "manage.py nao encontrado em '$managePy'."
}

Load-EnvFile -Path $envFullPath
$python = Resolve-PythonExe -Preferred $PythonExe

if ($StartProjectPg -and $env:DJANGO_DB_ENGINE -eq "postgres") {
    $dbHost = if ($env:DJANGO_DB_HOST) { $env:DJANGO_DB_HOST } else { "127.0.0.1" }
    $dbPort = if ($env:DJANGO_DB_PORT) { [int]$env:DJANGO_DB_PORT } else { 5432 }
    Ensure-ProjectPostgres -DbHost $dbHost -DbPort $dbPort
}

Write-Host ""
Write-Host "Assistencia - modo local em rede"
Write-Host "DEBUG: $env:DJANGO_DEBUG"
Write-Host "LOCAL_NETWORK_MODE: $env:DJANGO_LOCAL_NETWORK_MODE"
Write-Host "ALLOWED_HOSTS: $env:DJANGO_ALLOWED_HOSTS"
Write-Host "CSRF_TRUSTED_ORIGINS: $env:DJANGO_CSRF_TRUSTED_ORIGINS"
Write-Host "DB: $env:DJANGO_DB_NAME em $env:DJANGO_DB_HOST`:$env:DJANGO_DB_PORT"
Write-Host ""

& $python.File @($python.Args + @($managePy, "check"))
& $python.File @($python.Args + @($managePy, "check_go_live"))
if ($CheckOnly) {
    Write-Host "CheckOnly ativo: configuracao local validada, sem iniciar servidor."
    exit 0
}

Stop-ProjectRunserverProcesses -ManagePyPath $managePy
Assert-PortAvailableForProject -ManagePyPath $managePy -TargetPort $Port
Clear-ProjectSessionsIfNeeded -PythonFile $python.File -PythonArgs $python.Args -ManagePyPath $managePy

& $python.File @($python.Args + @($managePy, "runserver", "$BindHost`:$Port", "--noreload"))
