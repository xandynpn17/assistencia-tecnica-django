from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import CategoriaFinanceira, ContaPagar, ContaReceber, Pagamento, PagamentoContaPagar
from clientes.models import Cliente
from ordens.models import OrdemServico
from orcamentos.models import Orcamento


class DashboardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="dashboard_atendente",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.gerente = user_model.objects.create_user(
            username="dashboard_gerente",
            password="senha-forte-123",
            tipo_usuario="gerente",
        )
        self.superuser = user_model.objects.create_superuser(
            username="dashboard_root",
            password="senha-forte-123",
            email="root@teste.com",
        )
        self.cliente = Cliente.objects.create(
            nome="Cliente Dashboard",
            documento="52998224725",
            telefone="11999990000",
            estado="SP",
        )

    def _criar_ordem(self, *, status="diagnosticar", fechada=False):
        return OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Sem ligar",
            tipo_reparo="Fora de Garantia",
            status=status,
            fechada=fechada,
        )

    def test_dashboard_operacional_exibe_acoes_rapidas_e_status(self):
        self.client.force_login(self.atendente)
        self._criar_ordem(status="em_andamento", fechada=False)
        concluida = self._criar_ordem(status="concluida", fechada=True)
        concluida.data_conclusao = timezone.now()
        concluida.save(update_fields=["data_conclusao"])

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_operational"])
        self.assertContains(response, "Operação diária da assistência técnica")
        self.assertContains(response, "Abrir Nova Ordem")
        self.assertContains(response, "Registrar Pagamento")
        self.assertContains(response, "Consultar Estoque")
        self.assertContains(response, "Ordens por Status (Abertas)")
        self.assertContains(response, "Concluídas no mês")
        self.assertContains(response, "Acumulado:")
        self.assertIn("?carregar=1&amp;status=em_andamento", response.content.decode())

    def test_dashboard_para_gerente_permanece_operacional(self):
        self.client.force_login(self.gerente)
        self._criar_ordem(status="pronto_contactado", fechada=False)
        concluida = self._criar_ordem(status="concluida", fechada=True)
        concluida.data_conclusao = timezone.now()
        concluida.save(update_fields=["data_conclusao"])

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_managerial"])
        self.assertContains(response, "Teclas Rápidas")
        self.assertContains(response, "Ordens por Status (Abertas)")
        self.assertContains(response, "Concluídas no mês")
        self.assertContains(response, "Últimas 5 Ordens Abertas")
        self.assertContains(response, "Atendente")
        self.assertContains(response, "Técnico responsável")
        self.assertNotContains(response, "Abertas sem Técnico")

    def test_indicadores_gerenciais_exibem_cards_tabela_e_blocos(self):
        self.client.force_login(self.gerente)
        self._criar_ordem(status="pronto_contactado", fechada=False)
        concluida = self._criar_ordem(status="concluida", fechada=True)
        concluida.data_conclusao = timezone.now()
        concluida.save(update_fields=["data_conclusao"])

        response = self.client.get(reverse("core:dashboard_indicadores"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Indicadores Gerenciais")
        self.assertContains(response, "Base do Negócio")
        self.assertContains(response, "Alertas e Gargalos")
        self.assertContains(response, "Financeiro Vinculado à OS")
        self.assertContains(response, "Leitura Comercial")
        self.assertContains(response, "Clientes cadastrados")
        self.assertContains(response, "Novos clientes no mês")
        self.assertContains(response, "Ordens registradas")
        self.assertContains(response, "Recusadas")
        self.assertContains(response, "Reabertas")
        self.assertContains(response, "Concluídas sem pagamento")
        self.assertContains(response, "Valor em aberto nas OS")
        self.assertContains(response, "Recebimentos do mês")
        self.assertContains(response, "Conversão de orçamento")
        self.assertContains(response, "Taxa de recusa")
        self.assertContains(response, "Ticket médio por OS concluída")
        self.assertContains(response, "CAC médio")
        self.assertContains(response, "Abertas sem Técnico")
        self.assertNotContains(response, "Últimas 5 Ordens Abertas")
        self.assertNotContains(response, "Atendente")
        self.assertNotContains(response, "Técnico responsável")
        self.assertContains(response, "Concluídas no mês")
        self.assertContains(response, "Acumulado:")
        self.assertIn("?carregar=1&amp;status=pronto_contactado", response.content.decode())

    def test_indicadores_gerenciais_contam_sem_tecnico_quando_campo_tem_atendente(self):
        self.client.force_login(self.gerente)
        ordem = self._criar_ordem(status="diagnosticar", fechada=False)
        ordem.tecnico_responsavel = self.atendente
        ordem.save(update_fields=["tecnico_responsavel"])

        response = self.client.get(reverse("core:dashboard_indicadores"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["gerencial_cards"]["sem_tecnico"], 1)

    def test_dashboard_limita_ultimas_ordens_abertas(self):
        self.client.force_login(self.gerente)
        for _ in range(7):
            self._criar_ordem(status="diagnosticar", fechada=False)
        self._criar_ordem(status="concluida", fechada=True)

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        ordens_recentes = list(response.context["ordens_recentes"])
        self.assertEqual(len(ordens_recentes), 5)
        self.assertTrue(all(not ordem.fechada for ordem in ordens_recentes))

    def test_dashboard_contabiliza_concluidas_no_mes_e_acumulado(self):
        self.client.force_login(self.gerente)
        ordem_mes = self._criar_ordem(status="concluida", fechada=True)
        ordem_antiga = self._criar_ordem(status="concluida", fechada=True)
        OrdemServico.objects.filter(pk=ordem_mes.pk).update(data_conclusao=timezone.now())
        OrdemServico.objects.filter(pk=ordem_antiga.pk).update(data_conclusao=timezone.now() - timedelta(days=40))

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ordens_finalizadas_mes"], 1)
        self.assertEqual(response.context["total_ordens_finalizadas"], 2)

        response_indicadores = self.client.get(reverse("core:dashboard_indicadores"))

        self.assertEqual(response_indicadores.status_code, 200)
        self.assertEqual(response_indicadores.context["gerencial_cards"]["fechadas_mes"], 1)
        self.assertEqual(response_indicadores.context["gerencial_cards"]["fechadas_total"], 2)

    def test_indicadores_gerenciais_exibem_novos_totais(self):
        self.client.force_login(self.gerente)
        ordem_autorizada = self._criar_ordem(status="autorizado", fechada=False)
        ordem_recusada = self._criar_ordem(status="recusado", fechada=False)
        self._criar_ordem(status="pendente_cliente", fechada=False)
        self._criar_ordem(status="pendente_pecas", fechada=False)
        ordem_reaberta = self._criar_ordem(status="concluida", fechada=False)
        Orcamento.objects.create(cliente=self.cliente, ordem_servico=ordem_autorizada, status="aprovado")
        Orcamento.objects.create(cliente=self.cliente, ordem_servico=ordem_recusada, status="recusado")

        response = self.client.get(reverse("core:dashboard_indicadores"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["gerencial_cards"]["autorizadas"], 1)
        self.assertEqual(response.context["gerencial_cards"]["recusadas"], 1)
        self.assertEqual(response.context["gerencial_cards"]["pendente_cliente"], 1)
        self.assertEqual(response.context["gerencial_cards"]["pendente_pecas"], 1)
        self.assertEqual(response.context["gerencial_cards"]["reabertas"], 1)
        self.assertEqual(response.context["gerencial_cards"]["orcamentos_total_mes"], 2)
        self.assertEqual(response.context["gerencial_cards"]["orcamentos_aprovados_mes"], 1)
        self.assertEqual(response.context["gerencial_cards"]["orcamentos_recusados_mes"], 1)
        self.assertEqual(response.context["gerencial_cards"]["conversao_orcamento"], 50.0)
        self.assertEqual(response.context["gerencial_cards"]["taxa_recusa"], 50.0)

    def test_indicadores_gerenciais_exibem_ticket_medio_e_clientes_mes(self):
        self.client.force_login(self.gerente)
        cliente_mes = Cliente.objects.create(
            nome="Cliente Novo",
            documento="39053344705",
            telefone="11999990001",
            estado="SP",
        )
        ordem_1 = OrdemServico.objects.create(
            cliente=cliente_mes,
            tipo_equipamento="celular",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo 1",
            defeito="Defeito 1",
            tipo_reparo="Fora de Garantia",
            status="concluida",
            fechada=True,
        )
        ordem_2 = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="notebook",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo 2",
            defeito="Defeito 2",
            tipo_reparo="Fora de Garantia",
            status="concluida",
            fechada=True,
        )
        OrdemServico.objects.filter(pk__in=[ordem_1.pk, ordem_2.pk]).update(data_conclusao=timezone.now())

        from ordens.models import ServicoPeca

        ServicoPeca.objects.create(ordem=ordem_1, tipo="servico", nome="Servico A", descricao="Servico A", quantidade=1, valor_unitario="100.00")
        ServicoPeca.objects.create(ordem=ordem_2, tipo="servico", nome="Servico B", descricao="Servico B", quantidade=1, valor_unitario="300.00")

        response = self.client.get(reverse("core:dashboard_indicadores"))

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.context["gerencial_cards"]["clientes_mes"], 1)
        self.assertEqual(response.context["gerencial_cards"]["ticket_medio_os_mes"], 200.0)

    def test_indicadores_gerenciais_exibem_metricas_financeiras_da_os(self):
        self.client.force_login(self.gerente)
        ordem_fechada = self._criar_ordem(status="concluida", fechada=True)
        ordem_pronta = self._criar_ordem(status="pronto_contactado", fechada=False)

        ContaReceber.objects.create(
            ordem_servico=ordem_fechada,
            descricao="OS fechada em aberto",
            tipo_origem="cliente_os",
            cliente_nome=self.cliente.nome,
            valor_original="120.00",
            valor_aberto="120.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        ContaReceber.objects.create(
            ordem_servico=ordem_pronta,
            descricao="OS pronta em aberto",
            tipo_origem="cliente_os",
            cliente_nome=self.cliente.nome,
            valor_original="80.00",
            valor_aberto="80.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        Pagamento.objects.create(
            ordem_servico=ordem_pronta,
            valor="50.00",
            metodo="pix",
        )

        response = self.client.get(reverse("core:dashboard_indicadores"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["gerencial_cards"]["concluidas_sem_pagamento"], 1)
        self.assertEqual(response.context["gerencial_cards"]["valor_aberto_ordens"], Decimal("200"))
        self.assertEqual(response.context["gerencial_cards"]["prontas_sem_recebimento_total"], Decimal("80"))
        self.assertEqual(response.context["gerencial_cards"]["recebimentos_mes_os"], Decimal("50"))

    def test_indicadores_gerenciais_exibem_despesas_marketing_cac_e_origem(self):
        self.client.force_login(self.gerente)
        self.cliente.origem_cliente = "google"
        self.cliente.save(update_fields=["origem_cliente"])
        categoria_marketing = CategoriaFinanceira.objects.create(
            nome="Marketing e Aquisição",
            tipo="saida",
            ativa=True,
        )
        conta_pagar = PagamentoContaPagar.objects.create(
            conta=ContaPagar.objects.create(
                fornecedor="Meta Ads",
                descricao="Campanha do mês",
                categoria=categoria_marketing,
                valor_total=Decimal("120.00"),
                valor_pago=Decimal("120.00"),
                vencimento=timezone.localdate(),
                status="paga",
            ),
            valor=Decimal("120.00"),
        )
        # garante uso da variável e data no período
        self.assertIsNotNone(conta_pagar.pk)

        response = self.client.get(reverse("core:dashboard_indicadores"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["gerencial_cards"]["despesas_marketing_mes"], Decimal("120.00"))
        self.assertEqual(response.context["gerencial_cards"]["despesas_totais_mes"], Decimal("120.00"))
        self.assertEqual(response.context["gerencial_cards"]["cac_medio"], Decimal("120.00"))
        self.assertContains(response, "Origem dos Novos Clientes")
        self.assertContains(response, "Google")

    def test_superuser_recebe_acesso_aos_indicadores(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_managerial"])

    def test_indicadores_gerenciais_contabilizam_paradas_ha_15_dias(self):
        self.client.force_login(self.gerente)
        ordem_antiga_pendente = self._criar_ordem(status="pendente_cliente", fechada=False)
        ordem_recente_pendente = self._criar_ordem(status="pendente_tecnico", fechada=False)
        self._criar_ordem(status="em_andamento", fechada=False)

        agora = timezone.now()
        OrdemServico.objects.filter(pk=ordem_antiga_pendente.pk).update(data_abertura=agora - timedelta(days=20))
        OrdemServico.objects.filter(pk=ordem_recente_pendente.pk).update(data_abertura=agora - timedelta(days=5))

        response = self.client.get(reverse("core:dashboard_indicadores"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["gerencial_cards"]["paradas"], 1)

    def test_indicadores_gerenciais_bloqueiam_atendente(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("core:dashboard_indicadores"))
        self.assertEqual(response.status_code, 403)
