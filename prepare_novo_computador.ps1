param(
    [string]$PythonVersion = "3.12",
    [string]$PythonExe = "",
    [string]$SourceDbEnv = ".env.postgres.local",
    [string]$LocalEnv = ".env.local",
    [string]$HostIp = "",
    [int]$Port = 8000,
    [string]$RecoveryKey = "",
    [string]$RestoreBackup = "",
    [switch]$RestoreMedia,
    [switch]$RepairSingleTenant = $true,
    [switch]$SkipRequirements,
    [switch]$SkipMigrate,
    [switch]$SkipCollectstatic,
    [switch]$SkipChecks,
    [switch]$OverwriteLocalEnv,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

function Resolve-Python {
    param(
        [string]$PreferredExe,
        [string]$Version
    )

    if ($PreferredExe -and (Test-Path $PreferredExe)) {
        return @{ File = $PreferredExe; Args = @() }
    }

    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return @{ File = $venvPython; Args = @() }
    }

    return @{ File = "py"; Args = @("-$Version") }
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Args
    )

    & $Python.File @($Python.Args + $Args)
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar: $($Python.File) $($Args -join ' ')"
    }
}

$projectRoot = $PSScriptRoot
$managePy = Join-Path $projectRoot "manage.py"
$requirements = Join-Path $projectRoot "requirements.txt"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$sourceDbEnvPath = Join-Path $projectRoot $SourceDbEnv
$localEnvPath = Join-Path $projectRoot $LocalEnv
$backupRoot = Join-Path $projectRoot "backups"

if (-not (Test-Path $managePy)) {
    throw "manage.py nao encontrado em '$managePy'."
}

if (-not (Test-Path $requirements)) {
    throw "requirements.txt nao encontrado em '$requirements'."
}

if (-not (Test-Path $backupRoot)) {
    New-Item -ItemType Directory -Path $backupRoot | Out-Null
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Criando ambiente virtual .venv..."
    & py "-$PythonVersion" -m venv (Join-Path $projectRoot ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        throw "Nao foi possivel criar a .venv com Python $PythonVersion."
    }
}

$python = Resolve-Python -PreferredExe $PythonExe -Version $PythonVersion

if (-not $SkipRequirements) {
    Write-Host "Atualizando pip e instalando dependencias..."
    Invoke-Python -Python $python -Args @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Python -Python $python -Args @("-m", "pip", "install", "-r", $requirements)
}

if (-not (Test-Path $sourceDbEnvPath)) {
    $sourceExample = Join-Path $projectRoot ".env.postgres.example"
    if (Test-Path $sourceExample) {
        Copy-Item $sourceExample $sourceDbEnvPath
        Write-Host "Arquivo base criado: $SourceDbEnv"
        Write-Host "Preencha usuario, senha, host e porta do PostgreSQL antes de continuar."
    } else {
        throw "Arquivo '$SourceDbEnv' nao encontrado e nao existe exemplo para copiar."
    }
}

if (-not (Test-Path $localEnvPath) -or $OverwriteLocalEnv) {
    $setupArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $projectRoot "setup_local_env.ps1"),
        "-SourceDbEnv", $SourceDbEnv,
        "-OutputEnv", $LocalEnv,
        "-Port", "$Port"
    )
    if ($HostIp) {
        $setupArgs += @("-HostIp", $HostIp)
    }
    if ($RecoveryKey) {
        $setupArgs += @("-RecoveryKey", $RecoveryKey)
    }
    if ($OverwriteLocalEnv) {
        $setupArgs += "-Overwrite"
    }
    Write-Host "Gerando ambiente local..."
    & powershell @setupArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao gerar '$LocalEnv'."
    }
}

if (-not $SkipMigrate) {
    Write-Host "Aplicando migracoes..."
    & powershell -ExecutionPolicy Bypass -File (Join-Path $projectRoot "manage_local.ps1") "-EnvPath" $LocalEnv "migrate"
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao aplicar migracoes."
    }
}

if ($RestoreBackup) {
    $restoreArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $projectRoot "manage_local.ps1"),
        "-EnvPath", $LocalEnv,
        "restore_db", $RestoreBackup, "--force"
    )
    if ($RestoreMedia) {
        $restoreArgs += "--restore-media"
    }
    if ($RepairSingleTenant) {
        $restoreArgs += "--repair-single-tenant"
    }
    Write-Host "Restaurando backup informado..."
    & powershell @restoreArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao restaurar backup '$RestoreBackup'."
    }
}

if (-not $SkipCollectstatic) {
    Write-Host "Gerando arquivos estaticos..."
    & powershell -ExecutionPolicy Bypass -File (Join-Path $projectRoot "manage_local.ps1") "-EnvPath" $LocalEnv "collectstatic" "--noinput"
    if ($LASTEXITCODE -ne 0) {
        throw "Falha em collectstatic."
    }
}

if (-not $SkipChecks) {
    Write-Host "Executando validacoes locais..."
    foreach ($cmd in @(
        @("check"),
        @("check_go_live"),
        @("check_postgres_ready", "--check-connection"),
        @("check_tenant_data", "--strict")
    )) {
        & powershell -ExecutionPolicy Bypass -File (Join-Path $projectRoot "manage_local.ps1") "-EnvPath" $LocalEnv @cmd
        if ($LASTEXITCODE -ne 0) {
            throw "Falha na validacao: manage.py $($cmd -join ' ')"
        }
    }
}

Write-Host ""
Write-Host "Preparacao do novo computador concluida."
Write-Host "Arquivo de ambiente local: $LocalEnv"
Write-Host "Comando oficial para subir o sistema:"
Write-Host "powershell -ExecutionPolicy Bypass -File .\\run_local.ps1 -EnvPath $LocalEnv"
if ($CheckOnly) {
    exit 0
}
