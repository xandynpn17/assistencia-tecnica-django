from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from configuracoes.models import FornecedorGarantia, MarcaGarantia
from configuracoes.forms import MarcaGarantiaForm


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
                "numero_vendedor": "22",
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

    def test_gerente_acessa_marcas_fornecedores(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:marcas_fornecedores"))
        self.assertEqual(response.status_code, 200)

    def test_gerente_edita_e_exclui_fornecedor_na_tela_unica(self):
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor X")
        self.client.force_login(self.gerente)
        response_edit = self.client.post(
            reverse("configuracoes:marcas_fornecedores"),
            {
                "form_type": "fornecedor_edit",
                "fornecedor_id": fornecedor.id,
                "nome": "Fornecedor X2",
                "modalidade_pagamento": "pix",
                "prazo_pagamento_dias": 15,
                "ativo": "on",
            },
        )
        self.assertEqual(response_edit.status_code, 302)
        fornecedor.refresh_from_db()
        self.assertEqual(fornecedor.nome, "Fornecedor X2")

        response_delete = self.client.post(
            reverse("configuracoes:marcas_fornecedores"),
            {"form_type": "fornecedor_delete", "fornecedor_id": fornecedor.id},
        )
        self.assertEqual(response_delete.status_code, 302)
        self.assertFalse(FornecedorGarantia.objects.filter(id=fornecedor.id).exists())

    def test_gerente_edita_e_exclui_marca_na_tela_unica(self):
        marca = MarcaGarantia.objects.create(nome="Marca T", valor_mao_obra_garantia=10)
        self.client.force_login(self.gerente)
        response_edit = self.client.post(
            reverse("configuracoes:marcas_fornecedores"),
            {
                "form_type": "marca_edit",
                "marca_id": marca.id,
                "nome": "Marca T2",
                "valor_mao_obra_garantia": "30.00",
                "procedimentos": "Teste",
                "ativo": "on",
            },
        )
        self.assertEqual(response_edit.status_code, 302)
        marca.refresh_from_db()
        self.assertEqual(marca.nome, "Marca T2")

        response_delete = self.client.post(
            reverse("configuracoes:marcas_fornecedores"),
            {"form_type": "marca_delete", "marca_id": marca.id},
        )
        self.assertEqual(response_delete.status_code, 302)
        self.assertFalse(MarcaGarantia.objects.filter(id=marca.id).exists())

    def test_consulta_fornecedores_tem_paginacao(self):
        self.client.force_login(self.gerente)
        for i in range(12):
            FornecedorGarantia.objects.create(nome=f"Fornecedor Pag {i}")
        response = self.client.get(reverse("configuracoes:marcas_fornecedores"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pagina 1 de 2")

    def test_marca_form_pode_vincular_fornecedor_igual_nome(self):
        form = MarcaGarantiaForm(
            data={
                "nome": "MarcaFornecedorX",
                "fornecedor_igual_marca": "on",
                "parceira_garantia": "on",
                "procedimentos": "",
                "valor_mao_obra_garantia": "0.00",
                "ativo": "on",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        marca = form.save()
        self.assertIsNotNone(marca.fornecedor)
        self.assertEqual(marca.fornecedor.nome, "MarcaFornecedorX")

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
