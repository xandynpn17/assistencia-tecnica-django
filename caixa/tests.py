from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from caixa.models import Caixa, ContaReceber
from clientes.models import Cliente
from estoque.models import MovimentacaoEstoque, PontoOperacional, Produto, SaldoEstoquePonto, VendaRapidaEstoque
from ordens.models import OrdemServico, ServicoPeca


class CaixaPermissoesTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente_caixa",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.gerente = user_model.objects.create_user(
            username="gerente_caixa",
            password="senha-forte-123",
            tipo_usuario="gerente",
        )
        self.superuser = user_model.objects.create_superuser(
            username="root_caixa",
            password="senha-forte-123",
            email="root@caixa.com",
        )
        Caixa.objects.create(aberto=True, saldo_inicial=0)
        self.cliente = Cliente.objects.create(
            nome="Cliente Caixa",
            documento="52998224725",
            telefone="11999998888",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="pronto_contactado",
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Mao de obra",
            quantidade=1,
            valor_unitario="100.00",
        )

    def test_atendente_sem_acesso_ao_dashboard_financeiro(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:dashboard_caixa"))
        self.assertEqual(response.status_code, 403)

    def test_atendente_sem_acesso_a_relatorios(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:relatorios"))
        self.assertEqual(response.status_code, 403)

    def test_atendente_com_acesso_a_registro_pagamento(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:registrar_pagamento"))
        self.assertEqual(response.status_code, 200)

    def test_atendente_com_acesso_a_abrir_e_fechar_caixa(self):
        self.client.force_login(self.atendente)
        response_abrir = self.client.get(reverse("caixa:abrir_caixa"))
        response_fechar = self.client.get(reverse("caixa:fechar_caixa"))
        self.assertEqual(response_abrir.status_code, 200)
        self.assertEqual(response_fechar.status_code, 200)

    def test_gerente_com_acesso_ao_dashboard_financeiro(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:dashboard_caixa"))
        self.assertEqual(response.status_code, 200)

    def test_superuser_com_acesso_a_relatorios(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("caixa:relatorios"))
        self.assertEqual(response.status_code, 200)

    def test_gerente_cria_conta_receber(self):
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("caixa:criar_conta_receber"),
            {
                "ordem_servico": self.ordem.id,
                "descricao": "OS teste",
                "cliente_nome": self.cliente.nome,
                "valor_original": "120.00",
                "vencimento": "2030-01-01",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ContaReceber.objects.exists())

    def test_atendente_sem_acesso_a_dre_e_comissoes(self):
        self.client.force_login(self.atendente)
        resp_dre = self.client.get(reverse("caixa:dre"))
        resp_comissao = self.client.get(reverse("caixa:comissoes_tecnicos"))
        self.assertEqual(resp_dre.status_code, 403)
        self.assertEqual(resp_comissao.status_code, 403)

    def test_gerente_com_acesso_a_dre_e_fluxo(self):
        self.client.force_login(self.gerente)
        resp_dre = self.client.get(reverse("caixa:dre"))
        resp_fluxo = self.client.get(reverse("caixa:fluxo_projetado"))
        self.assertEqual(resp_dre.status_code, 200)
        self.assertEqual(resp_fluxo.status_code, 200)

    def test_baixa_parcial_conta_receber(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="OS teste",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="100.00",
            vencimento="2030-01-01",
            status="aberta",
        )
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("caixa:detalhe_conta_receber", args=[conta.id]),
            {
                "valor": "40.00",
                "desconto": "0.00",
                "juros": "0.00",
                "referencia": "REC-1",
                "observacao": "",
                "metodo": "pix",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(str(conta.valor_aberto), "60.00")
        self.assertEqual(conta.status, "parcial")

    def test_finalizar_pre_reserva_no_caixa_da_baixa_no_estoque(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja")
        produto = Produto.objects.create(
            nome="Bateria X",
            ean="7899991110002",
            preco_final=Decimal("50.00"),
            preco=Decimal("50.00"),
            quantidade=5,
            ponto_operacional=ponto,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=5)
        venda = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=2,
            valor_unitario=Decimal("50.00"),
            valor_total=Decimal("100.00"),
            funcionario_numero="F01",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?venda={venda.id}",
            {"valor": "100.00", "metodo": "pix", "referencia": "PDV-1"},
        )
        self.assertEqual(response.status_code, 302)
        venda.refresh_from_db()
        self.assertEqual(venda.status, "vendida")
        saldo = SaldoEstoquePonto.objects.get(produto=produto, ponto_operacional=ponto)
        self.assertEqual(saldo.quantidade, 3)
        self.assertTrue(MovimentacaoEstoque.objects.filter(produto=produto, tipo="venda").exists())
