from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema


class VerificarClienteOSViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="tester",
            password="senha-forte-123",
        )
        self.client.force_login(self.user)

        self.config = ConfiguracaoSistema.get_configuracao()
        self.config.busca_minimo_caracteres = 5
        self.config.ddd_padrao = "11"
        self.config.estado_padrao = "SP"
        self.config.save()

        self.url = reverse("ordens:verificar_cliente_os")

    def test_usuario_sem_papel_operacional_sem_acesso(self):
        user_model = get_user_model()
        usuario_externo = user_model.objects.create_user(
            username="externo_portal",
            password="senha-forte-123",
            tipo_usuario="portal",
        )
        self.client.force_login(usuario_externo)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_busca_com_caracteres_invalidos_mostra_erro(self):
        response = self.client.get(self.url, {"cpf_telefone": "abc###"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Digite apenas numeros para busca.")

    def test_busca_abaixo_do_minimo_mostra_erro(self):
        response = self.client.get(self.url, {"cpf_telefone": "1234"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Digite pelo menos 5 numeros para buscar.")

    def test_busca_por_cpf_encontra_cliente(self):
        cliente = Cliente.objects.create(
            nome="Cliente CPF",
            documento="52998224725",
            telefone="11987654321",
            estado="SP",
        )

        response = self.client.get(self.url, {"cpf_telefone": "529.982.247-25"})

        self.assertEqual(response.status_code, 200)
        clientes = list(response.context["clientes"])
        self.assertEqual(len(clientes), 1)
        self.assertEqual(clientes[0].id, cliente.id)
        self.assertIsNone(response.context["form"])

    def test_busca_cpf_valido_sem_cliente_prefill_documento(self):
        response = self.client.get(
            self.url,
            {"cpf_telefone": "529.982.247-25", "novo_cliente": "true"},
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIsNotNone(form)
        self.assertEqual(form.initial.get("documento"), "52998224725")
        self.assertNotIn("telefone_numero", form.initial)

    def test_busca_11_digitos_prefill_documento(self):
        response = self.client.get(
            self.url,
            {"cpf_telefone": "11987654320", "novo_cliente": "true"},
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIsNotNone(form)
        self.assertEqual(form.initial.get("documento"), "11987654320")
        self.assertNotIn("telefone_numero", form.initial)

    def test_busca_10_digitos_prefill_telefone(self):
        response = self.client.get(
            self.url,
            {"cpf_telefone": "1132654321", "novo_cliente": "true"},
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial.get("ddd"), "11")
        self.assertEqual(form.initial.get("telefone_numero"), "3265-4321")

    def test_busca_9_digitos_prefill_com_ddd_padrao(self):
        response = self.client.get(
            self.url,
            {"cpf_telefone": "998765432", "novo_cliente": "true"},
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial.get("ddd"), "11")
        self.assertEqual(form.initial.get("telefone_numero"), "99876-5432")

    def test_cadastro_bloqueia_cliente_duplicado_por_email(self):
        Cliente.objects.create(
            nome="Cliente Existente",
            documento="52998224725",
            telefone="11987654321",
            email="duplicado@exemplo.com",
            estado="SP",
        )

        response = self.client.post(
            self.url,
            {
                "nome": "Cliente Novo",
                "documento": "123.456.789-09",
                "ddd": "11",
                "telefone_numero": "99999-9999",
                "email": "duplicado@exemplo.com",
                "estado": "SP",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Encontramos cliente(s) semelhante(s). Verifique antes de cadastrar duplicado.",
        )
        self.assertEqual(Cliente.objects.filter(email__iexact="duplicado@exemplo.com").count(), 1)
