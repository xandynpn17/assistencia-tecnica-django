$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
& (Join-Path $PSScriptRoot "manage_local.ps1") -EnvPath ".env.local" executar_backup_agendado
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
