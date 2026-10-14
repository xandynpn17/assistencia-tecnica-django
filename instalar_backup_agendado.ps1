param([string]$TaskName = "ABGestBackupDiario")
$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "executar_backup_rotina.ps1"
if (-not (Test-Path -LiteralPath $runner)) { throw "Rotina de backup não encontrada." }
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runner + '"') -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 30)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
# SYSTEM permite backup sem login. A pasta sincronizada deve ser local e acessível;
# o aplicativo da nuvem pode só realizar o upload quando o utilizador iniciar sessão.
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Tarefa instalada. Habilite a rotina e o horário nas configurações de backup."
