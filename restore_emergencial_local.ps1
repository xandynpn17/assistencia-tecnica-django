param(
    [string]$EnvPath = ".env.local",
    [string]$BackupPath = "",
    [switch]$RestoreMedia,
    [switch]$RepairSingleTenant = $true
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$backupRoot = Join-Path $projectRoot "backups"
$manageLocal = Join-Path $projectRoot "manage_local.ps1"

if (-not (Test-Path $manageLocal)) {
    throw "manage_local.ps1 nao encontrado em '$manageLocal'."
}

if (-not (Test-Path $backupRoot)) {
    throw "Pasta de backups nao encontrada em '$backupRoot'."
}

function Get-BackupsOficiais {
    Get-ChildItem -Path $backupRoot -Force |
        Where-Object { $_.PSIsContainer -or $_.Extension -in @(".sqlite3", ".gz", ".dump", ".zip") } |
        Sort-Object LastWriteTime -Descending
}

$backups = Get-BackupsOficiais
if (-not $backups) {
    throw "Nenhum backup oficial foi encontrado em '$backupRoot'."
}

if (-not $BackupPath) {
    Write-Host ""
    Write-Host "Recuperacao emergencial local - backups disponiveis" -ForegroundColor Cyan
    Write-Host ""
    for ($i = 0; $i -lt $backups.Count; $i++) {
        $item = $backups[$i]
        Write-Host ("[{0}] {1}  ({2})" -f ($i + 1), $item.Name, $item.LastWriteTime.ToString("dd/MM/yyyy HH:mm"))
    }
    Write-Host ""
    $choice = Read-Host "Escolha o numero do backup a restaurar"
    $parsed = 0
    if (-not [int]::TryParse($choice, [ref]$parsed)) {
        throw "Escolha invalida."
    }
    $index = $parsed - 1
    if ($index -lt 0 -or $index -ge $backups.Count) {
        throw "Indice fora da lista."
    }
    $BackupPath = $backups[$index].FullName
}

if (-not (Test-Path $BackupPath)) {
    throw "Backup informado nao existe: $BackupPath"
}

Write-Host ""
Write-Host "Backup selecionado: $BackupPath" -ForegroundColor Yellow
Write-Host "Restore de media: $($RestoreMedia.IsPresent)" -ForegroundColor Yellow
Write-Host "Repair single tenant: $($RepairSingleTenant.IsPresent)" -ForegroundColor Yellow
Write-Host ""

$confirm = Read-Host "Digite RESTAURAR para continuar"
if ($confirm -ne "RESTAURAR") {
    throw "Operacao cancelada."
}

$args = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $manageLocal,
    "-EnvPath", $EnvPath,
    "restore_db", $BackupPath,
    "--force"
)
if ($RestoreMedia) {
    $args += "--restore-media"
}
if ($RepairSingleTenant) {
    $args += "--repair-single-tenant"
}

& powershell @args
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao restaurar backup."
}

Write-Host ""
Write-Host "Restore concluido. Agora valide login, dashboard e ordens principais." -ForegroundColor Green
