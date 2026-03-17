param(
    [int]$Port = 8000,
    [string]$HostIp = ""
)

$ErrorActionPreference = "Stop"

function Get-LocalPrivateIPv4 {
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -and
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            (
                $_.IPAddress -like "192.168.*" -or
                $_.IPAddress -like "10.*" -or
                $_.IPAddress -match "^172\.(1[6-9]|2[0-9]|3[0-1])\."
            )
        } |
        Select-Object -ExpandProperty IPAddress -Unique

    return $ips | Select-Object -First 1
}

function Merge-CsvValues {
    param(
        [string]$CurrentValue,
        [string[]]$ValuesToAdd
    )

    $merged = @()
    if ($CurrentValue) {
        $merged += ($CurrentValue -split ",")
    }
    $merged += $ValuesToAdd

    return ($merged |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ } |
        Select-Object -Unique) -join ","
}

if (-not $HostIp) {
    $HostIp = Get-LocalPrivateIPv4
}

if (-not $HostIp) {
    throw "Não foi possível detectar um IPv4 local. Informe manualmente com -HostIp."
}

$allowedHosts = Merge-CsvValues -CurrentValue $env:DJANGO_ALLOWED_HOSTS -ValuesToAdd @("127.0.0.1", "localhost", $HostIp)
$trustedOrigins = Merge-CsvValues -CurrentValue $env:DJANGO_CSRF_TRUSTED_ORIGINS -ValuesToAdd @("http://$HostIp`:$Port")

$env:DJANGO_ALLOWED_HOSTS = $allowedHosts
$env:DJANGO_CSRF_TRUSTED_ORIGINS = $trustedOrigins

Write-Host ""
Write-Host "Assistencia em rede local"
Write-Host "IP local: $HostIp"
Write-Host "Porta: $Port"
Write-Host "ALLOWED_HOSTS: $env:DJANGO_ALLOWED_HOSTS"
Write-Host "CSRF_TRUSTED_ORIGINS: $env:DJANGO_CSRF_TRUSTED_ORIGINS"
Write-Host ""
Write-Host "Acesse de outro PC em: http://$HostIp`:$Port/"
Write-Host ""

$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$managePy = Join-Path $PSScriptRoot "manage.py"

if (-not (Test-Path $pythonExe)) {
    throw "Nao foi encontrado o Python do projeto em '$pythonExe'. Recrie a .venv antes de usar este script."
}

& $pythonExe $managePy runserver 0.0.0.0:$Port
