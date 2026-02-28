from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clientes.models import Cliente
from ordens.models import OrdemServico
from orcamentos.models import Orcamento


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
        self.adm = user_model.objects.create_user(
            username="adm_clientes",
            password="senha123",
            tipo_usuario="adm",
        )
        self.superuser = user_model.objects.create_superuser(
            username="root_clientes",
            password="senha123",
            email="root@clientes.com",
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

    def test_excluir_cliente_bloqueia_adm(self):
        self.client.force_login(self.adm)
        response = self.client.get(reverse("clientes:excluir_cliente", args=[self.cliente.id]))
        self.assertEqual(response.status_code, 403)

    def test_excluir_cliente_permite_superuser(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("clientes:excluir_cliente", args=[self.cliente.id]))
        self.assertEqual(response.status_code, 200)

    def test_busca_cliente_por_cpf_formatado(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("clientes:lista_clientes"), {"query": "529.982.247-25"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.cliente.nome)

    def test_busca_cliente_inexistente_exibe_botao_cadastro(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("clientes:lista_clientes"), {"query": "00000000000"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cadastrar novo cliente")

    def test_unificar_clientes_bloqueia_atendente(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("clientes:unificar_clientes"))
        self.assertEqual(response.status_code, 403)

    def test_unificar_clientes_permite_adm(self):
        self.client.force_login(self.adm)
        response = self.client.get(reverse("clientes:unificar_clientes"))
        self.assertEqual(response.status_code, 200)

    def test_unificar_clientes_transfere_registros(self):
        principal = Cliente.objects.create(
            nome="Principal",
            documento="11144477735",
            telefone="11911111111",
            estado="SP",
        )
        duplicado = Cliente.objects.create(
            nome="Duplicado",
            documento="39053344705",
            telefone="11922222222",
            estado="SP",
        )
        ordem = OrdemServico.objects.create(
            cliente=duplicado,
            tipo_equipamento="celular",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        orc = Orcamento.objects.create(cliente=duplicado, ordem_servico=ordem)

        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("clientes:unificar_clientes"),
            {"principal_id": principal.id, "duplicado_id": duplicado.id},
        )
        self.assertEqual(response.status_code, 302)
        ordem.refresh_from_db()
        orc.refresh_from_db()
        self.assertEqual(ordem.cliente_id, principal.id)
        self.assertEqual(orc.cliente_id, principal.id)
        self.assertFalse(Cliente.objects.filter(id=duplicado.id).exists())
