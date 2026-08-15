from decimal import Decimal

from django.test import TestCase

from clientes.models import Cliente
from configuracoes.models import Empresa
from ordens.models import CustoOrdemServico, OrdemServico, ServicoPeca


class CustosPrevistosOrdemTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa OS custos")
        cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Cliente custo previsto",
            telefone="11999999999",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            empresa=self.empresa,
            cliente=cliente,
            tipo_equipamento="climatizador",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Teclas danificadas",
            tipo_reparo="Fora de Garantia",
        )
        self.item = ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="peca",
            nome="Teclas avulsas",
            quantidade=3,
            valor_unitario=Decimal("20.00"),
            custo_previsto_final=Decimal("18.00"),
            situacao_custo="previsto_final",
        )

    def test_custo_previsto_entra_na_margem_mas_nao_no_realizado(self):
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=self.ordem,
            servico_peca=self.item,
            tipo="peca",
            origem="compra_especifica",
            estado="previsto",
            descricao="Custo final previsto",
            quantidade=1,
            custo_unitario=Decimal("18.00"),
        )

        self.assertEqual(self.ordem.custo_real_financeiro(), Decimal("0.00"))
        self.assertEqual(self.ordem.custo_estimado_pendente_financeiro(), Decimal("18.00"))
        self.assertEqual(self.ordem.lucro_bruto_financeiro(), Decimal("42.00"))

    def test_custo_real_substitui_previsao_do_mesmo_item(self):
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=self.ordem,
            servico_peca=self.item,
            tipo="peca",
            origem="compra_especifica",
            estado="previsto",
            descricao="Previsto",
            quantidade=1,
            custo_unitario=Decimal("18.00"),
        )
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=self.ordem,
            servico_peca=self.item,
            tipo="peca",
            origem="compra_especifica",
            estado="realizado",
            descricao="Realizado",
            quantidade=1,
            custo_unitario=Decimal("16.00"),
        )

        self.assertEqual(self.ordem.custo_real_financeiro(), Decimal("16.00"))
        self.assertEqual(self.ordem.custo_estimado_pendente_financeiro(), Decimal("0.00"))
        self.assertEqual(self.ordem.custo_total_financeiro(), Decimal("16.00"))
