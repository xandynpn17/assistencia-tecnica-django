@echo off
setlocal
cd /d "%~dp0"

echo.
echo ===============================================
echo ABGest - Atualizacao local apos git pull
echo ===============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: ambiente virtual nao encontrado em .venv\Scripts\python.exe
    exit /b 1
)

echo [1/5] Instalando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo [2/5] Aplicando migrations...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\manage_local.ps1" -EnvPath ".env.local" migrate
if errorlevel 1 exit /b 1

echo [3/5] Gerando staticfiles...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\manage_local.ps1" -EnvPath ".env.local" collectstatic --noinput
if errorlevel 1 exit /b 1

echo [4/5] Validando projeto...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\manage_local.ps1" -EnvPath ".env.local" check
if errorlevel 1 exit /b 1

echo [5/5] Reiniciando servico web...
sc query ABGestWaitress >nul 2>&1
if errorlevel 1 (
    echo Aviso: servico ABGestWaitress nao encontrado. Nada para reiniciar.
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Restart-Service -Name 'ABGestWaitress' -Force"
    if errorlevel 1 exit /b 1
)

sc query ABGestCaddy >nul 2>&1
if errorlevel 1 (
    echo Aviso: servico ABGestCaddy nao encontrado.
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$svc = Get-Service -Name 'ABGestCaddy'; if ($svc.Status -ne 'Running') { Start-Service -Name 'ABGestCaddy' }"
    if errorlevel 1 exit /b 1
)

echo.
echo Atualizacao concluida com sucesso.
echo.
exit /b 0
