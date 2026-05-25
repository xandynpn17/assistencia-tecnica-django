param(
    [int]$Port = 8000,
    [string]$BindHost = "0.0.0.0",
    [string]$EnvPath = ".env.local",
    [string]$PythonExe = "",
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

$envFullPath = Join-Path $PSScriptRoot $EnvPath
$managePy = Join-Path $PSScriptRoot "manage.py"

if (-not (Test-Path $managePy)) {
    throw "manage.py nao encontrado em '$managePy'."
}

Load-EnvFile -Path $envFullPath
$python = Resolve-PythonExe -Preferred $PythonExe

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
& $python.File @($python.Args + @($managePy, "runserver", "$BindHost`:$Port"))
