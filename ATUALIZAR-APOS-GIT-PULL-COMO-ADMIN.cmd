@echo off
setlocal
cd /d "%~dp0"
echo ABGest - Atualizacao controlada com backup previo
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0atualizar_gradual.ps1"
exit /b %errorlevel%
