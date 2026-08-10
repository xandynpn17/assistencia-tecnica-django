$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectDir "logs"
$LogFile = Join-Path $LogDir "monitoramento_estoque_agendado.log"

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -LiteralPath $LogFile -Value "[$StartedAt] Inicio" -Encoding UTF8
try {
    $CommandOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectDir "manage_local.ps1") monitorar_estoque --todas-empresas --origem agendada --falhar-se-divergir 2>&1
    $CommandOutput | Out-File -LiteralPath $LogFile -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        throw "O monitoramento retornou o codigo $LASTEXITCODE."
    }
    $FinishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogFile -Value "[$FinishedAt] Concluido com sucesso" -Encoding UTF8
    exit 0
}
catch {
    $FailedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogFile -Value "[$FailedAt] Falha: $($_.Exception.Message)" -Encoding UTF8
    exit 1
}
