from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from clientes.models import Cliente
from ordens.models import OrdemServico


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

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_operational"])
        self.assertContains(response, "Abrir Nova Ordem")
        self.assertContains(response, "Registrar Pagamento")
        self.assertContains(response, "Consultar Estoque")
        self.assertContains(response, "Ordens por Status (Abertas)")
        self.assertIn("?carregar=1&amp;status=em_andamento", response.content.decode())

    def test_dashboard_gerencial_exibe_status_e_acesso_caixa(self):
        self.client.force_login(self.gerente)
        self._criar_ordem(status="pronto_contactado", fechada=False)

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_operational"])
        self.assertTrue(response.context["is_managerial"])
        self.assertContains(response, "Teclas Rápidas")
        self.assertContains(response, "Dashboard Caixa")
        self.assertContains(response, "Ordens por Status (Abertas)")
        self.assertContains(response, "Últimas 5 Ordens Abertas")
        self.assertContains(response, "Atendente")
        self.assertContains(response, "Técnico responsável")
        self.assertIn("?carregar=1&amp;status=pronto_contactado", response.content.decode())
        self.assertNotContains(response, "Faturamento Total")
        self.assertNotContains(response, "A Receber")
        self.assertNotContains(response, "Periodo de Analise")

    def test_dashboard_gerencial_conta_sem_tecnico_quando_campo_tem_atendente(self):
        self.client.force_login(self.gerente)
        ordem = self._criar_ordem(status="diagnosticar", fechada=False)
        ordem.tecnico_responsavel = self.atendente
        ordem.save(update_fields=["tecnico_responsavel"])

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["gerencial_cards"]["sem_tecnico"], 1)

    def test_dashboard_gerencial_limita_ultimas_ordens_abertas(self):
        self.client.force_login(self.gerente)
        for _ in range(7):
            self._criar_ordem(status="diagnosticar", fechada=False)
        self._criar_ordem(status="concluida", fechada=True)

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        ordens_recentes = list(response.context["ordens_recentes"])
        self.assertEqual(len(ordens_recentes), 5)
        self.assertTrue(all(not ordem.fechada for ordem in ordens_recentes))

    def test_superuser_recebe_dashboard_gerencial(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_managerial"])
        self.assertFalse(response.context["is_operational"])

    def test_dashboard_gerencial_contabiliza_paradas_ha_15_dias(self):
        self.client.force_login(self.gerente)
        ordem_antiga_pendente = self._criar_ordem(status="pendente_cliente", fechada=False)
        ordem_recente_pendente = self._criar_ordem(status="pendente_tecnico", fechada=False)
        self._criar_ordem(status="em_andamento", fechada=False)

        agora = timezone.now()
        OrdemServico.objects.filter(pk=ordem_antiga_pendente.pk).update(data_abertura=agora - timedelta(days=20))
        OrdemServico.objects.filter(pk=ordem_recente_pendente.pk).update(data_abertura=agora - timedelta(days=5))

        response = self.client.get(reverse("core:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["gerencial_cards"]["paradas"], 1)
