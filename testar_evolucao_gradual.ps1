$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
# Django usa banco de testes separado; não criar pagamentos no banco operacional.
$suites = @(
    "caixa.tests_evolucao_gradual", "configuracoes.tests_backup_automatico", "clientes.tests",
    "caixa.tests.CheckoutAgrupadoTests", "caixa.tests.PagamentoComDescontoTests",
    "caixa.tests.LivroFinanceiroFaseUmTests", "configuracoes.tests.ComandosConfiguracoesTests",
    "ordens.tests_financeiro_os", "estoque.tests_xml_compra"
)
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "manage_local.ps1") -EnvPath ".env.local" test @suites --noinput --keepdb
if ($LASTEXITCODE -ne 0) { throw "Regressão falhou. Não publicar esta versão antes de corrigir." }
Write-Host "Regressão concluída em banco de testes. A instalação e a nuvem ainda exigem validação própria."
