$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Ambiente Python não encontrado." }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $PSScriptRoot ("backups\pre_atualizacao_" + $stamp)
$web = Get-Service -Name "ABGestWaitress" -ErrorAction SilentlyContinue
$estavaAtivo = $web -and $web.Status -eq "Running"
$backupTask = Get-ScheduledTask -TaskName "ABGestBackupDiario" -ErrorAction SilentlyContinue
$taskAtiva = $backupTask -and $backupTask.State -ne "Disabled"
function Invoke-ManageStep([string[]]$StepArgs) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "manage_local.ps1") -EnvPath ".env.local" @StepArgs
    if ($LASTEXITCODE -ne 0) { throw "Etapa de atualização falhou. Aplicação permanece parada; não restaure banco por tentativa e erro." }
}
try {
    if ($taskAtiva) { Disable-ScheduledTask -TaskName "ABGestBackupDiario" | Out-Null }
    if ($backupTask -and $backupTask.State -eq "Running") { throw "Backup já em execução. Aguarde terminar antes de atualizar." }
    if ($estavaAtivo) { Stop-Service -Name "ABGestWaitress" }
    Write-Host "Gerando backup completo antes de migrations..."
    Invoke-ManageStep -StepArgs @("backup_db", "--include-media", "--output-dir", $backupDir)
    if (-not (Get-ChildItem -LiteralPath $backupDir -Filter "backup_*.zip")) { throw "Backup não confirmado. Atualização interrompida." }
    Write-Host "Revendo plano de migrations..."
    Invoke-ManageStep -StepArgs @("migrate", "--plan")
    & $python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Instalação de dependências falhou." }
    Invoke-ManageStep -StepArgs @("migrate")
    Invoke-ManageStep -StepArgs @("collectstatic", "--noinput")
    Invoke-ManageStep -StepArgs @("check")
    Invoke-ManageStep -StepArgs @("makemigrations", "--check", "--dry-run")
    if ($estavaAtivo) { Start-Service -Name "ABGestWaitress" }
    if ($taskAtiva) { Enable-ScheduledTask -TaskName "ABGestBackupDiario" | Out-Null }
    Write-Host "Atualização técnica concluída. Confirme login, OS, anexos e valores antes de libertar o uso."
    Write-Host "Backup preservado: $backupDir"
} catch {
    Write-Host "FALHA: manutenção interrompida. Preserve o banco atual e consulte o procedimento de recuperação."
    Write-Host "Não restaurar backup antigo se houve trabalho novo sem avaliação."
    throw
}
