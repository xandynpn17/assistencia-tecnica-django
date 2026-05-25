param(
    [string]$ServerIp = "",
    [int]$Port = 8000,
    [string]$Path = "/login/",
    [switch]$OpenBrowser
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

if (-not $ServerIp) {
    $ServerIp = Get-LocalPrivateIPv4
}

if (-not $ServerIp) {
    throw "Informe o IP do servidor com -ServerIp. Exemplo: .\test_local_network.ps1 -ServerIp 192.168.1.50"
}

$url = "http://$ServerIp`:$Port$Path"

Write-Host ""
Write-Host "Teste de rede local - Assistencia"
Write-Host "Servidor: $ServerIp"
Write-Host "Porta: $Port"
Write-Host "URL: $url"
Write-Host ""

$tcp = Test-NetConnection $ServerIp -Port $Port -WarningAction SilentlyContinue
if (-not $tcp.TcpTestSucceeded) {
    Write-Host "Falha: porta $Port inacessivel em $ServerIp." -ForegroundColor Red
    Write-Host "Verifique se o servidor esta rodando com .\run_local.ps1 e se o firewall liberou a porta." -ForegroundColor Yellow
    exit 1
}

Write-Host "OK: porta $Port acessivel." -ForegroundColor Green

try {
    $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
    Write-Host "OK: HTTP respondeu com status $($response.StatusCode)." -ForegroundColor Green
} catch {
    Write-Host "Aviso: porta respondeu, mas a requisicao HTTP falhou: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "Se estiver usando outro caminho, informe com -Path /dashboard/ ou /login/." -ForegroundColor Yellow
}

if ($OpenBrowser) {
    Start-Process $url
}
