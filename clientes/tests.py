from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from caixa.models import Caixa, Pagamento
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

    def test_rota_textual_invalida_nao_vira_listagem(self):
        self.client.force_login(self.atendente)
        response = self.client.get("/clientes/Heloise Julia Goncalves/")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.cliente.nome, status_code=404)

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


class DetalhesClienteTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_detalhes_cliente",
            password="senha123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Detalhado",
            tipo_cliente="pj",
            documento="",
            telefone="11999990000",
            origem_cliente="google",
            email="cliente@detalhes.com",
            logradouro="Rua das Flores",
            numero="123",
            complemento="Sala 4",
            bairro="Centro",
            cidade="Lisboa",
            estado="SP",
            codigo_postal="01000-000",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca C",
            modelo_equipamento="Modelo C",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
        )
        caixa = Caixa.objects.create(aberto=True, saldo_inicial=Decimal("0.00"))
        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("75.00"),
            metodo="pix",
        )

    def test_detalhes_cliente_exibe_tipo_e_endereco_montado(self):
        response = self.client.get(reverse("clientes:detalhes_cliente", args=[self.cliente.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Google")
        self.assertContains(response, "Pessoa Jurídica")
        self.assertContains(response, "Rua das Flores 123")
        self.assertContains(response, "Sala 4")
        self.assertContains(response, "Centro, Lisboa")

    def test_detalhes_cliente_exibe_resumo_financeiro(self):
        response = self.client.get(reverse("clientes:detalhes_cliente", args=[self.cliente.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total pago")
        self.assertContains(response, "Em aberto")
        self.assertContains(response, "Ticket médio")
        self.assertContains(response, "75,00")
