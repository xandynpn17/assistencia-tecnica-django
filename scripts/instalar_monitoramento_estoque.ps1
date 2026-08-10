$ErrorActionPreference = "Stop"
$TaskName = "Assistencia-MonitoramentoEstoque"
$Runner = Join-Path $PSScriptRoot "monitorar_estoque_agendado.ps1"
$PowerShellExe = (Get-Command powershell.exe).Source

if (-not (Test-Path -LiteralPath $Runner)) {
    throw "Rotina de monitoramento nao encontrada: $Runner"
}

$Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
$Action = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$Principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Auditoria automatica de integridade do estoque por empresa a cada 15 minutos." -Force | Out-Null
Write-Output "Tarefa '$TaskName' instalada. Primeira execucao em aproximadamente 1 minuto; repeticao a cada 15 minutos."
