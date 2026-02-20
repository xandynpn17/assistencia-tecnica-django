from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clientes.models import Cliente
from ordens.models import OrdemServico


class DashboardFluxoStatusTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="dashboard_user",
            password="senha-forte-123",
        )
        self.client.force_login(self.user)

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

    def test_dashboard_exibe_link_para_lista_filtrada_por_status(self):
        self._criar_ordem(status="diagnosticar", fechada=False)

        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("ordens:lista_ordens")}?status=diagnosticar"',
        )

    def test_dashboard_conta_status_apenas_de_ordens_abertas(self):
        self._criar_ordem(status="diagnosticar", fechada=False)
        self._criar_ordem(status="diagnosticar", fechada=True)

        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)

        status_cards = response.context["status_cards"]
        diagnosticar = next(card for card in status_cards if card["status"] == "diagnosticar")
        self.assertEqual(diagnosticar["total"], 1)

    def test_lista_filtrada_por_status_retorna_apenas_abertas_daquele_status(self):
        ordem_aberta = self._criar_ordem(status="diagnosticar", fechada=False)
        self._criar_ordem(status="diagnosticar", fechada=True)
        self._criar_ordem(status="pendente_pecas", fechada=False)

        response = self.client.get(reverse("ordens:lista_ordens"), {"status": "diagnosticar"})
        self.assertEqual(response.status_code, 200)

        ordens = list(response.context["ordens"])
        self.assertEqual(len(ordens), 1)
        self.assertEqual(ordens[0].id, ordem_aberta.id)
