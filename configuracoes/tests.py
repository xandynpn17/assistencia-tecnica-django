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
        self.tecnico = user_model.objects.create_user(
            username="tecnico",
            password="senha123",
            tipo_usuario="tecnico",
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

    def test_gerente_pode_abrir_cadastro_usuario(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:adicionar_usuario"))
        self.assertEqual(response.status_code, 200)

    def test_gerente_nao_pode_criar_admin(self):
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("configuracoes:adicionar_usuario"),
            {
                "username": "novo_admin_por_gerente",
                "email": "gerente@teste.com",
                "password": "senha12345",
                "is_active": "on",
                "is_staff": "on",
                "tipo_usuario": "adm",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gerente nao pode criar usuario Administrador.")

    def test_backup_permite_gerente(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:backup_banco"))
        self.assertEqual(response.status_code, 302)

    def test_backup_bloqueia_atendente(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("configuracoes:backup_banco"))
        self.assertEqual(response.status_code, 403)

    def test_tecnico_pode_abrir_lista_ordens(self):
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("ordens:lista_ordens"))
        self.assertEqual(response.status_code, 200)

    def test_tecnico_pode_consultar_estoque(self):
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("estoque:lista_produtos"))
        self.assertEqual(response.status_code, 200)

    def test_tecnico_nao_pode_criar_produto(self):
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("estoque:criar_produto"))
        self.assertEqual(response.status_code, 403)

    def test_tecnico_nao_pode_acessar_caixa(self):
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("caixa:dashboard_caixa"))
        self.assertEqual(response.status_code, 403)

    def test_tecnico_nao_pode_acessar_clientes(self):
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("clientes:lista_clientes"))
        self.assertEqual(response.status_code, 403)
