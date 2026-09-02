from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from caixa.models import CategoriaFinanceira, ContaReceber
from clientes.models import Cliente
from configuracoes.models import Empresa, FornecedorGarantia, MarcaGarantia, RegraGarantiaMarca
from caixa.view_modules.helpers import _garantir_conta_garantia
from estoque.models import (
    PontoOperacional,
    Produto,
    SaldoEstoquePonto,
    SaldoEstoqueUbicacao,
    UbicacaoEstoque,
)
from estoque.services import consumir_itens_estoque_ordem, devolver_itens_estoque_ordem
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.models import CustoOrdemServico, OrdemServico, ServicoPeca
from ordens.services.fechamento_os import garantir_conta_receber_os


class CustosEFechamentoFinanceiroOSTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Custos OS", cnpj="44.444.444/0001-44")
        self.usuario = get_user_model().objects.create_user(
            username="gestor_custos_os",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
        )
        self.cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Cliente Custos OS",
            documento="52998224725",
            telefone="11999998888",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            tipo_equipamento="climatizador",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Teclas sem funcionar",
            tipo_reparo="Fora de Garantia",
        )

    def test_os_nao_cobravel_cancela_recebivel_sem_criar_pagamento_zero(self):
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Recuperação da placa",
            quantidade=1,
            valor_unitario=Decimal("250.00"),
        )
        conta = garantir_conta_receber_os(self.ordem)
        self.assertEqual(conta.status, "aberta")

        self.ordem.resultado_financeiro = "cortesia"
        self.ordem.motivo_sem_cobranca = "Cortesia comercial autorizada"
        self.ordem.save(update_fields=["resultado_financeiro", "motivo_sem_cobranca"])
        garantir_conta_receber_os(self.ordem)

        conta.refresh_from_db()
        self.assertEqual(conta.status, "cancelada")
        self.assertEqual(conta.valor_aberto, Decimal("0.00"))

    def test_os_garantia_mista_separa_cliente_e_fabricante(self):
        fornecedor = FornecedorGarantia.objects.create(
            empresa=self.empresa, nome="Fabricante", razao_social="Fabricante"
        )
        marca = MarcaGarantia.objects.create(
            empresa=self.empresa,
            nome="Marca",
            fornecedor=fornecedor,
            parceira_garantia=True,
        )
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="climatizador",
            valor_mao_obra=Decimal("18.00"),
            valor_mao_obra_tecnico=Decimal("10.00"),
            inicio_vigencia=timezone.localdate(),
        )
        self.ordem.tipo_reparo = "Garantia"
        self.ordem.marca_garantia = marca
        self.ordem.save(update_fields=["tipo_reparo", "marca_garantia"])
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            responsavel_cobranca="fabricante",
            nome="Mao de obra da garantia",
            quantidade=1,
            valor_unitario=Decimal("18.00"),
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            responsavel_cobranca="cliente",
            nome="Servico adicional fora da garantia",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
        )

        conta_cliente = garantir_conta_receber_os(self.ordem)
        conta_fabricante = _garantir_conta_garantia(self.ordem)

        self.assertEqual(conta_cliente.valor_original, Decimal("100.00"))
        self.assertEqual(conta_fabricante.valor_original, Decimal("18.00"))

    def test_custo_real_substitui_estimativa_e_insumo_compoe_margem(self):
        orcamento = Orcamento.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            ordem_servico=self.ordem,
        )
        item_orcamento = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Teclas avulsas",
            tipo_item="peca",
            origem="manual",
            quantidade=1,
            valor_unitario=Decimal("90.00"),
            custo_estimado_unitario=Decimal("40.00"),
            situacao_aquisicao="a_comprar",
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=item_orcamento,
            tipo="peca",
            nome="Teclas avulsas",
            quantidade=1,
            valor_unitario=Decimal("90.00"),
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Recuperação da placa",
            quantidade=1,
            valor_unitario=Decimal("160.00"),
        )

        self.assertEqual(self.ordem.custo_estimado_pendente_financeiro(), Decimal("40.00"))

        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=self.ordem,
            item_orcamento=item_orcamento,
            tipo="peca",
            origem="compra_especifica",
            descricao="Teclas compradas",
            quantidade=1,
            custo_unitario=Decimal("35.00"),
            criado_por=self.usuario,
        )
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=self.ordem,
            tipo="insumo",
            origem="manual",
            descricao="Solda e fluxo",
            quantidade=1,
            custo_unitario=Decimal("5.00"),
            data_competencia=timezone.localdate(),
            criado_por=self.usuario,
        )

        self.assertEqual(self.ordem.custo_estimado_pendente_financeiro(), Decimal("0.00"))
        self.assertEqual(self.ordem.custo_real_financeiro(), Decimal("40.00"))
        self.assertEqual(self.ordem.lucro_bruto_financeiro(), Decimal("210.00"))

    def test_baixa_de_estoque_gera_custo_real_e_reabertura_estorna_sem_duplicar(self):
        ponto = PontoOperacional.objects.create(
            empresa=self.empresa,
            codigo="LAB",
            nome="Laboratório",
        )
        ubicacao = UbicacaoEstoque.objects.create(
            ponto_operacional=ponto,
            codigo="A-01",
            ativo=True,
        )
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Tecla do climatizador",
            tipo_item="peca",
            quantidade=5,
            custo_unitario=Decimal("12.50"),
            custo_medio=Decimal("12.50"),
            preco=Decimal("30.00"),
            preco_final=Decimal("30.00"),
            ponto_operacional=ponto,
            ubicacao_padrao=ubicacao,
            permite_os=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=5)
        SaldoEstoqueUbicacao.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            ubicacao=ubicacao,
            quantidade=5,
        )
        item = ServicoPeca.objects.create(
            ordem=self.ordem,
            produto_estoque=produto,
            ponto_operacional_reserva=ponto,
            tipo="peca",
            nome=produto.nome,
            quantidade=2,
            valor_unitario=Decimal("30.00"),
        )

        self.assertEqual(consumir_itens_estoque_ordem(self.ordem, self.usuario), 1)
        custo = CustoOrdemServico.objects.get(servico_peca=item, estornado_em__isnull=True)
        self.assertEqual(custo.total, Decimal("25.00"))
        self.assertIsNotNone(custo.movimentacao_estoque_id)
        self.assertEqual(devolver_itens_estoque_ordem(self.ordem, self.usuario), 1)
        custo.refresh_from_db()
        self.assertTrue(custo.estornado)

        self.assertEqual(consumir_itens_estoque_ordem(self.ordem, self.usuario), 1)
        self.assertEqual(
            CustoOrdemServico.objects.filter(servico_peca=item, estornado_em__isnull=True).count(),
            1,
        )
        self.assertEqual(CustoOrdemServico.objects.filter(servico_peca=item).count(), 2)
        saldo = SaldoEstoquePonto.objects.get(produto=produto, ponto_operacional=ponto)
        self.assertEqual(saldo.quantidade, 3)


class RecebivelZeroHistoricoTests(TestCase):
    def test_conta_zero_existente_fica_cancelada(self):
        empresa = Empresa.objects.create(nome="Empresa OS Zero", cnpj="55.555.555/0001-55")
        cliente = Cliente.objects.create(
            empresa=empresa,
            nome="Cliente OS Zero",
            documento="39053344705",
            telefone="11999990000",
            estado="SP",
        )
        ordem = OrdemServico.objects.create(
            empresa=empresa,
            cliente=cliente,
            tipo_equipamento="outros",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Sem reparo",
            tipo_reparo="Fora de Garantia",
        )
        categoria = CategoriaFinanceira.objects.create(empresa=empresa, nome="Cliente OS", tipo="receber")
        conta = ContaReceber.objects.create(
            empresa=empresa,
            ordem_servico=ordem,
            categoria=categoria,
            descricao="OS zero antiga",
            tipo_origem="cliente_os",
            valor_original=Decimal("0.00"),
            valor_aberto=Decimal("0.00"),
            vencimento=timezone.localdate(),
        )

        garantir_conta_receber_os(ordem)

        conta.refresh_from_db()
        self.assertEqual(conta.status, "cancelada")
