from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clientes.models import Cliente


class PermissoesClientesTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente_clientes",
            password="senha123",
            tipo_usuario="atendente",
        )
        self.gerente = user_model.objects.create_user(
            username="gerente_clientes",
            password="senha123",
            tipo_usuario="gerente",
        )
        self.cliente = Cliente.objects.create(
            nome="Cliente Teste",
            documento="52998224725",
            telefone="11999998888",
            estado="SP",
        )

    def test_excluir_cliente_bloqueia_atendente(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("clientes:excluir_cliente", args=[self.cliente.id]))
        self.assertEqual(response.status_code, 403)

    def test_excluir_cliente_permite_gerente(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("clientes:excluir_cliente", args=[self.cliente.id]))
        self.assertEqual(response.status_code, 200)
