from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse


class PermissoesConfiguracoesTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente",
            password="senha123",
            tipo_usuario="atendente",
        )
        self.gerente = user_model.objects.create_user(
            username="gerente",
            password="senha123",
            tipo_usuario="gerente",
        )
        self.admin = user_model.objects.create_user(
            username="admin",
            password="senha123",
            tipo_usuario="adm",
        )

    def test_painel_bloqueia_atendente(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 403)

    def test_painel_permitem_gerente(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 200)

    def test_lista_usuarios_bloqueia_gerente(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:lista_usuarios"))
        self.assertEqual(response.status_code, 403)

    def test_lista_usuarios_permitem_admin(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("configuracoes:lista_usuarios"))
        self.assertEqual(response.status_code, 200)
