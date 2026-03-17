from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ConfiguracaoFiscal, DocumentoFiscal


class FiscalViewsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.gerente = user_model.objects.create_user(
            username="gerente_fiscal",
            password="senha-forte-123",
            tipo_usuario="gerente",
        )
        self.atendente = user_model.objects.create_user(
            username="atendente_fiscal",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )

    def test_gerente_cria_documento_na_fila(self):
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("fiscal:novo_documento_fiscal"),
            {
                "tipo": "NFE",
                "origem": "MANUAL",
                "origem_referencia": "TESTE-001",
                "valor_total": "150.00",
                "xml_envio": "<xml/>",
            },
        )
        self.assertEqual(response.status_code, 302)
        documento = DocumentoFiscal.objects.get()
        self.assertEqual(documento.status, "fila")
        self.assertEqual(documento.criado_por_id, self.gerente.id)

    def test_processar_fila_autoriza_nfe_incrementando_numeracao(self):
        self.client.force_login(self.gerente)
        config = ConfiguracaoFiscal.get_solo()
        documento = DocumentoFiscal.objects.create(
            tipo="NFE",
            origem="MANUAL",
            origem_referencia="OS-10",
            status="fila",
            valor_total=Decimal("220.00"),
        )

        response = self.client.post(reverse("fiscal:processar_fila_fiscal"))
        self.assertEqual(response.status_code, 302)

        documento.refresh_from_db()
        config.refresh_from_db()
        self.assertEqual(documento.status, "autorizada")
        self.assertEqual(documento.numero, 1)
        self.assertEqual(documento.serie, config.serie_nfe)
        self.assertTrue(bool(documento.chave_acesso))
        self.assertTrue(bool(documento.protocolo_autorizacao))
        self.assertEqual(config.proximo_numero_nfe, 2)

    def test_processar_fila_rejeita_nfse_no_mvp(self):
        self.client.force_login(self.gerente)
        documento = DocumentoFiscal.objects.create(
            tipo="NFSE",
            origem="MANUAL",
            origem_referencia="OS-11",
            status="fila",
            valor_total=Decimal("90.00"),
        )

        response = self.client.post(reverse("fiscal:processar_fila_fiscal"))
        self.assertEqual(response.status_code, 302)

        documento.refresh_from_db()
        self.assertEqual(documento.status, "rejeitada")
        self.assertIn("NFS-e ainda não integrada", documento.mensagem_retorno)

    def test_atendente_sem_acesso_ao_painel_fiscal(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("fiscal:painel_fiscal"))
        self.assertEqual(response.status_code, 403)
