param(
    [string]$OutputDir = "backups\local",
    [string]$PythonExe = "C:\Users\Xandy\AppData\Local\Programs\Python\Python312\python.exe",
    [string]$LocalEnvPath = ".env.postgres.local",
    [switch]$NoMedia
)

$ErrorActionPreference = "Stop"

function Load-LocalEnvConfig {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Arquivo de ambiente local nao encontrado: $Path"
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
        if ($key) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

$projectRoot = $PSScriptRoot
$managePy = Join-Path $projectRoot "manage.py"
$envPath = Join-Path $projectRoot $LocalEnvPath
$resolvedOutput = Join-Path $projectRoot $OutputDir

if (-not (Test-Path $PythonExe)) {
    throw "Python nao encontrado em: $PythonExe"
}
if (-not (Test-Path $managePy)) {
    throw "manage.py nao encontrado em: $managePy"
}

Load-LocalEnvConfig -Path $envPath

Write-Host "Validando PostgreSQL local..."
& $PythonExe $managePy check_postgres_ready --check-connection

$args = @($managePy, "backup_db", "--output-dir", $resolvedOutput)
if (-not $NoMedia) {
    $args += "--include-media"
}

Write-Host ""
Write-Host "Gerando backup em: $resolvedOutput"
& $PythonExe @args

Write-Host ""
Write-Host "Backup finalizado."
