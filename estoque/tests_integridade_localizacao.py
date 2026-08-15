from decimal import Decimal

from django.test import TestCase

from configuracoes.models import Empresa
from estoque.models import PontoOperacional, Produto, SaldoEstoquePonto, SaldoEstoqueUbicacao, UbicacaoEstoque
from estoque.services import normalizar_saldos_produto


class IntegridadeLocalizacaoTests(TestCase):
    def test_custo_adicional_manual_soma_sem_substituir_detalhes(self):
        empresa = Empresa.objects.create(nome="Empresa custos")
        produto = Produto.objects.create(
            empresa=empresa,
            nome="Produto custo completo",
            custo_unitario=Decimal("100.00"),
            custo_adicional_manual=Decimal("5.00"),
            custo_operacional=Decimal("999.00"),
            custo_frete=Decimal("10.00"),
            custo_impostos=Decimal("3.00"),
            custo_comissao=Decimal("2.00"),
            custo_cac=Decimal("4.00"),
            usar_taxa_canal_automatica=False,
            incluir_rateio_custo_fixo=False,
        )

        self.assertEqual(produto.custo_operacional, Decimal("24.00"))
        self.assertEqual(produto.custo_total, Decimal("124.00"))

    def test_trocar_localizacao_padrao_nao_copia_saldo_existente(self):
        empresa = Empresa.objects.create(nome="Empresa Localização")
        ponto = PontoOperacional.objects.create(empresa=empresa, codigo="PO1", nome="Loja")
        anterior = UbicacaoEstoque.objects.create(ponto_operacional=ponto, codigo="A1")
        nova = UbicacaoEstoque.objects.create(ponto_operacional=ponto, codigo="B1")
        produto = Produto.objects.create(
            empresa=empresa,
            nome="Produto localização",
            custo_unitario=Decimal("10.00"),
            preco_final=Decimal("20.00"),
            quantidade=1,
            ponto_operacional=ponto,
            ubicacao_padrao=anterior,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=1)
        SaldoEstoqueUbicacao.objects.create(
            produto=produto, ponto_operacional=ponto, ubicacao=anterior, quantidade=1
        )

        produto.ubicacao_padrao = nova
        produto.save(update_fields=["ubicacao_padrao"])
        normalizar_saldos_produto(produto)

        self.assertEqual(produto.saldos_por_ubicacao.count(), 1)
        self.assertFalse(produto.saldos_por_ubicacao.filter(ubicacao=nova).exists())
