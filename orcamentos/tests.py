from decimal import Decimal
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph as reportlab_paragraph

from caixa.models import ComissaoItemOrcamento, RegraComissaoTecnico
from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema, Empresa
from core.pdf_theme import get_document_theme as real_get_document_theme
from estoque.models import Produto
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.models import OrdemServico
from core.pdf_utils import logo_or_paragraph, make_numbered_canvas as real_make_numbered_canvas


class ItemOrcamentoTecnicoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente_orc",
            password="senha-forte-123",
            tipo_usuario="atendente",
            perm_orcamento_editar=True,
            perm_orcamento_aprovar_item=True,
            perm_orcamento_recusar_item=True,
            perm_orcamento_migrar_item=True,
        )
        self.tecnico = user_model.objects.create_user(
            username="tecnico_orc",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.client.force_login(self.atendente)

        self.cliente = Cliente.objects.create(
            nome="Cliente Orcamento",
            documento="39053344705",
            telefone="11999998888",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca O",
            modelo_equipamento="Modelo O",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        self.orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)

    def test_criar_orcamento_get_redireciona_para_aba_da_os(self):
        response = self.client.get(reverse("orcamentos:criar_orcamento", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{self.ordem.get_absolute_url()}?tab=orcamentos")

    def test_editar_orcamento_get_redireciona_para_aba_da_os(self):
        response = self.client.get(reverse("orcamentos:editar_orcamento", args=[self.orcamento.id]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"{self.ordem.get_absolute_url()}?tab=orcamentos")

    def test_adicionar_item_perfil_operacional_pode_editar_orcamento(self):
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "7890001112223",
                "nome": "Troca de Tela",
                "descricao": "Servico",
                "valor_unitario": "200.00",
                "quantidade": "1",
                "tipo_item": "servico",
                "origem": "manual",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ItemOrcamento.objects.filter(orcamento=self.orcamento, nome="Troca de Tela").exists())

    def test_adicionar_item_com_tecnico_responsavel(self):
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "7890001112223",
                "nome": "Troca de Tela",
                "descricao": "Servico",
                "valor_unitario": "200.00",
                "quantidade": "1",
                "tipo_item": "servico",
                "origem": "manual",
                "tecnico_responsavel": str(self.tecnico.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        item = ItemOrcamento.objects.latest("id")
        self.assertEqual(item.tecnico_responsavel_id, self.tecnico.id)
        self.assertEqual(item.tipo_item, "servico")

    def test_editar_item_perfil_operacional_pode_editar_orcamento(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Bateria",
            descricao="Peca",
            valor_unitario="90.00",
            quantidade=1,
            origem="manual",
        )
        response = self.client.post(
            reverse("orcamentos:editar_item", args=[item.id]),
            {
                "nome": "Bateria Premium",
                "descricao": "Peca",
                "quantidade": "1",
                "valor_unitario": "95.00",
                "tipo_item": "peca",
                "origem": "manual",
            },
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.nome, "Bateria Premium")

    def test_editar_item_atualiza_tecnico_responsavel(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Bateria",
            descricao="Peca",
            valor_unitario="90.00",
            quantidade=1,
            origem="manual",
        )
        response = self.client.post(
            reverse("orcamentos:editar_item", args=[item.id]),
            {
                "nome": "Bateria",
                "descricao": "Peca",
                "quantidade": "1",
                "valor_unitario": "90.00",
                "tipo_item": "peca",
                "origem": "manual",
                "tecnico_responsavel": str(self.tecnico.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.tecnico_responsavel_id, self.tecnico.id)

    def test_adicionar_item_detecta_origem_estoque_por_ean(self):
        produto = Produto.objects.create(
            nome="Tela Original",
            ean="7891234567890",
            preco_final=Decimal("150.00"),
            quantidade=5,
        )
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": produto.ean,
                "nome": "Tela Original",
                "descricao": "Peca",
                "valor_unitario": "150.00",
                "quantidade": "1",
                "tipo_item": "peca",
                "origem": "manual",
            },
        )
        self.assertEqual(response.status_code, 302)
        item = ItemOrcamento.objects.latest("id")
        self.assertEqual(item.origem, "estoque")
        self.assertEqual(item.tipo_item, "peca")

    def test_editar_item_atualiza_ean_e_origem_automaticamente(self):
        produto = Produto.objects.create(
            nome="Conector Carga",
            ean="7891234567001",
            preco_final=Decimal("35.00"),
            quantidade=3,
        )
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Servico Solda",
            descricao="Manual",
            valor_unitario="35.00",
            quantidade=1,
            origem="manual",
        )
        response = self.client.post(
            reverse("orcamentos:editar_item", args=[item.id]),
            {
                "ean": produto.ean,
                "nome": produto.nome,
                "descricao": "Peca",
                "quantidade": "1",
                "valor_unitario": "35.00",
                "tipo_item": "peca",
                "origem": "manual",
            },
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.ean, produto.ean)
        self.assertEqual(item.origem, "estoque")

    def test_adicionar_item_sem_tipo_reabre_modal_orcamento(self):
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "7890001112223",
                "nome": "Item sem tipo",
                "descricao": "Teste",
                "valor_unitario": "50.00",
                "quantidade": "1",
                "tipo_item": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("open_modal=adicionar_item", response.url)

    def test_migrar_para_servicos_preserva_tecnico_responsavel(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Servico tecnico",
            descricao="Teste",
            valor_unitario="100.00",
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            status="aprovado",
            tecnico_responsavel=self.tecnico,
        )
        response = self.client.post(
            reverse("orcamentos:migrar_para_servicos", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
        )
        self.assertEqual(response.status_code, 302)
        servico = self.ordem.servicos_pecas.order_by("-id").first()
        self.assertIsNotNone(servico)
        self.assertEqual(servico.tecnico_responsavel_id, self.tecnico.id)

    def test_migrar_para_servicos_perfil_operacional_consegue_migrar(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Servico tecnico",
            descricao="Teste",
            valor_unitario="100.00",
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            status="aprovado",
            tecnico_responsavel=self.tecnico,
        )
        response = self.client.post(
            reverse("orcamentos:migrar_para_servicos", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.ordem.servicos_pecas.filter(item_orcamento=item).exists())

    def test_migrar_para_servicos_ignora_item_nao_aprovado(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Peca pendente",
            descricao="Teste",
            valor_unitario="50.00",
            quantidade=1,
            origem="manual",
            tipo_item="peca",
            status="pendente",
            tecnico_responsavel=self.tecnico,
        )
        response = self.client.post(
            reverse("orcamentos:migrar_para_servicos", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.ordem.servicos_pecas.filter(item_orcamento=item).exists())
        mensagens = [str(message) for message in response.context["messages"]]
        self.assertTrue(any("Somente itens aprovados" in mensagem for mensagem in mensagens))

    def test_aceitar_itens_nao_gera_comissao_legada_automaticamente(self):
        self.ordem.status = "pronto_contactado"
        self.ordem.save(update_fields=["status"])
        RegraComissaoTecnico.objects.create(
            usuario=self.tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Mao de obra",
            descricao="Servico",
            valor_unitario=Decimal("100.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="pendente",
        )
        response = self.client.post(
            reverse("orcamentos:aceitar_orcamento", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ComissaoItemOrcamento.objects.filter(
                item_orcamento=item,
                tecnico=self.tecnico,
                modo_pagamento="antecipado",
            ).exists()
        )
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "pronto_contactado")

    def test_aprovar_itens_perfil_operacional_consegue_aprovar(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Item pendente",
            descricao="Servico",
            valor_unitario=Decimal("100.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            status="pendente",
        )
        response = self.client.post(
            reverse("orcamentos:aceitar_orcamento", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, "aprovado")

    def test_recusar_itens_perfil_operacional_consegue_recusar(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Item pendente",
            descricao="Servico",
            valor_unitario=Decimal("100.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            status="pendente",
        )
        response = self.client.post(
            reverse("orcamentos:recusar_orcamento", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, "recusado")

    def test_aceitar_itens_muda_status_para_autorizado_quando_nao_final(self):
        self.ordem.status = "bancada"
        self.ordem.save(update_fields=["status"])
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Mao de obra",
            descricao="Servico",
            valor_unitario=Decimal("100.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="pendente",
        )
        response = self.client.post(
            reverse("orcamentos:aceitar_orcamento", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
        )
        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "autorizado")

    def test_aceitar_itens_parcial_muda_status_para_orcamentado(self):
        self.ordem.status = "diagnosticar"
        self.ordem.save(update_fields=["status"])
        item_aprovado = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Mao de obra",
            descricao="Servico",
            valor_unitario=Decimal("100.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="pendente",
        )
        ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Peca pendente",
            descricao="Peca",
            valor_unitario=Decimal("50.00"),
            quantidade=1,
            origem="manual",
            tipo_item="peca",
            status="pendente",
        )

        response = self.client.post(
            reverse("orcamentos:aceitar_orcamento", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item_aprovado.id)]},
        )

        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "orcamentado")
        self.assertTrue(
            self.ordem.linhas_trabalho.filter(
                descricao__icontains="item(ns) do orcamento aprovados pelo cliente"
            ).exists()
        )

    def test_orcamento_aplica_desconto_percentual_no_total(self):
        ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Servico desconto",
            descricao="Teste",
            valor_unitario=Decimal("200.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
        )
        self.orcamento.desconto_percentual = Decimal("10.00")
        self.orcamento.save(update_fields=["desconto_percentual"])
        self.orcamento.atualizar_total()
        self.orcamento.refresh_from_db()
        self.assertEqual(self.orcamento.subtotal_itens(), Decimal("200.00"))
        self.assertEqual(self.orcamento.desconto_calculado(), Decimal("20.00"))
        self.assertEqual(self.orcamento.valor_total, Decimal("180.00"))

    def test_item_aplica_desconto_por_valor_no_total(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Servico com desconto por valor",
            descricao="Teste",
            valor_unitario=Decimal("100.00"),
            quantidade=2,
            desconto_valor=Decimal("30.00"),
            origem="manual",
            tipo_item="servico",
        )
        self.assertEqual(item.subtotal(), Decimal("200.00"))
        self.assertEqual(item.desconto_calculado(), Decimal("30.00"))
        self.assertEqual(item.total(), Decimal("170.00"))

    def test_adicionar_item_nao_aceita_desconto_valor_e_percentual_juntos(self):
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "",
                "nome": "Item com desconto inválido",
                "descricao": "Teste",
                "valor_unitario": "100.00",
                "quantidade": "1",
                "tipo_item": "servico",
                "origem": "manual",
                "desconto_valor": "10.00",
                "desconto_percentual": "5.00",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ItemOrcamento.objects.filter(nome="Item com desconto inválido").exists())
        mensagens = [str(message) for message in response.context["messages"]]
        self.assertTrue(any("nunca os dois" in mensagem for mensagem in mensagens))

    def test_adicionar_item_com_desconto_exige_permissao(self):
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "",
                "nome": "Item com desconto bloqueado",
                "descricao": "Teste",
                "valor_unitario": "100.00",
                "quantidade": "1",
                "tipo_item": "servico",
                "origem": "manual",
                "desconto_valor": "10.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ItemOrcamento.objects.filter(nome="Item com desconto bloqueado").exists())

    def test_adicionar_item_com_desconto_funciona_com_permissao(self):
        self.atendente.perm_orcamento_aplicar_desconto = True
        self.atendente.save(update_fields=["perm_orcamento_aplicar_desconto"])
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "",
                "nome": "Item com desconto liberado",
                "descricao": "Teste",
                "valor_unitario": "100.00",
                "quantidade": "1",
                "tipo_item": "servico",
                "origem": "manual",
                "desconto_valor": "10.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        item = ItemOrcamento.objects.get(nome="Item com desconto liberado")
        self.assertEqual(item.desconto_valor, Decimal("10.00"))

    def test_garantia_de_servico_cria_item_sem_comissao_por_padrao(self):
        self.ordem.tipo_reparo = "Garantia de serviço"
        self.ordem.save(update_fields=["tipo_reparo"])
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "",
                "nome": "Retorno em garantia",
                "descricao": "Retorno",
                "valor_unitario": "80.00",
                "quantidade": "1",
                "tipo_item": "servico",
                "origem": "manual",
            },
        )
        self.assertEqual(response.status_code, 302)
        item = ItemOrcamento.objects.latest("id")
        self.assertFalse(item.comissionavel)

    def test_garantia_de_servico_permita_servico_extra_comissionavel(self):
        self.ordem.tipo_reparo = "Garantia de serviço"
        self.ordem.save(update_fields=["tipo_reparo"])
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "",
                "nome": "Servico extra",
                "descricao": "Cobrança extra",
                "valor_unitario": "80.00",
                "quantidade": "1",
                "tipo_item": "servico",
                "origem": "manual",
                "comissionavel": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        item = ItemOrcamento.objects.latest("id")
        self.assertTrue(item.comissionavel)


class ImpressaoLogoOrcamentoTests(TestCase):
    def test_logo_pdf_configurado_da_empresa_tem_prioridade_no_pdf_orcamento(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                empresa = Empresa.objects.create(nome="Empresa Orcamento")
                empresa.logo_pdf = SimpleUploadedFile("logo-pdf.png", b"logo-configurado", content_type="image/png")
                empresa.save(update_fields=["logo_pdf"])
                style = getSampleStyleSheet()["Normal"]

                with patch("core.pdf_utils.Image", side_effect=lambda path, width, height: path) as image_mock:
                    logo = logo_or_paragraph(empresa, style, "<b>LOGO</b>", 10, 10)

                self.assertEqual(logo, empresa.logo_pdf.path)
                self.assertEqual(image_mock.call_args.args[0], empresa.logo_pdf.path)

    def test_pdf_orcamento_sem_logo_exibe_nome_da_empresa(self):
        empresa = Empresa.objects.create(nome="Empresa sem Logo PDF")
        style = getSampleStyleSheet()["Normal"]

        logo = logo_or_paragraph(empresa, style, "<b>LOGO</b>", 10, 10)

        self.assertEqual(logo.text, "<b>Empresa sem Logo PDF</b>")


class ImpressaoOrcamentoPdfTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente_orc_pdf",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.atendente)
        self.cliente = Cliente.objects.create(
            nome="Cliente Orc PDF",
            documento="39053344705",
            telefone="11999998888",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca O",
            modelo_equipamento="Modelo O",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        self.orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Servico base",
            descricao="Diagnostico",
            valor_unitario=Decimal("100.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
        )

    @staticmethod
    def _pdf_page_counts(pdf_bytes):
        return [int(value) for value in re.findall(br"/Count\s+(\d+)", pdf_bytes)]

    def test_imprimir_orcamento_retorna_pdf_sameorigin(self):
        response = self.client.get(reverse("orcamentos:imprimir_orcamento", args=[self.orcamento.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/pdf"))
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertEqual(response.get("X-Frame-Options"), "SAMEORIGIN")

    def test_imprimir_orcamento_preview_remove_x_frame_options(self):
        response = self.client.get(
            reverse("orcamentos:imprimir_orcamento", args=[self.orcamento.id]),
            {"_preview": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIsNone(response.get("X-Frame-Options"))

    def test_imprimir_orcamento_exibe_paginacao_total(self):
        with patch("orcamentos.views.make_numbered_canvas", wraps=real_make_numbered_canvas) as factory_mock:
            response = self.client.get(reverse("orcamentos:imprimir_orcamento", args=[self.orcamento.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(factory_mock.called)
        self.assertIn(1, self._pdf_page_counts(response.content))

    def test_imprimir_orcamento_exibe_observacoes_e_detalhes_sem_status_interno(self):
        self.orcamento.descricao = "Observação geral para o cliente."
        self.orcamento.save(update_fields=["descricao"])
        item = self.orcamento.itens.first()
        item.descricao = "Detalhe técnico do serviço."
        item.status = "pendente"
        item.save(update_fields=["descricao", "status"])
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("orcamentos.views.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("orcamentos:imprimir_orcamento", args=[self.orcamento.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Detalhes e observações do orçamento", texto_unificado)
        self.assertIn("Observação geral para o cliente.", texto_unificado)
        self.assertIn("Detalhe técnico do serviço.", texto_unificado)
        self.assertNotIn("Status: Pendente", texto_unificado)
        self.assertIn("R$ 100,00", texto_unificado)

    def test_imprimir_orcamento_nunca_exibe_custos_ou_fornecedor_internos(self):
        item = self.orcamento.itens.first()
        item.custo_estimado_unitario = Decimal("73.45")
        item.fornecedor_estimado = "FORNECEDOR INTERNO SIGILOSO"
        item.referencia_cotacao = "COTACAO-SECRETA-987"
        item.save(update_fields=["custo_estimado_unitario", "fornecedor_estimado", "referencia_cotacao"])
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("orcamentos.views.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("orcamentos:imprimir_orcamento", args=[self.orcamento.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertNotIn("73,45", texto_unificado)
        self.assertNotIn("FORNECEDOR INTERNO SIGILOSO", texto_unificado)
        self.assertNotIn("COTACAO-SECRETA-987", texto_unificado)

    def test_imprimir_orcamento_preview_aplica_layout_documentos(self):
        observado = {}

        def _theme_spy(config):
            observado["preset"] = config.layout_documentos_preset
            observado["cor"] = config.layout_documentos_cor
            return real_get_document_theme(config)

        with patch("orcamentos.views.get_document_theme", side_effect=_theme_spy):
            response = self.client.get(
                reverse("orcamentos:imprimir_orcamento", args=[self.orcamento.id]),
                {"_preview": "1", "layout_documentos_preset": "executivo", "layout_documentos_cor": "pb"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(observado.get("preset"), "executivo")
        self.assertEqual(observado.get("cor"), "pb")

    def test_imprimir_orcamento_longo_gera_multiplas_paginas_com_total(self):
        ItemOrcamento.objects.bulk_create(
            [
                ItemOrcamento(
                    orcamento=self.orcamento,
                    nome=f"Servico extra {i:03d}",
                    descricao="Item longo para forcar quebra de pagina",
                    valor_unitario=Decimal("19.90"),
                    quantidade=1,
                    origem="manual",
                    tipo_item="servico" if i % 2 == 0 else "peca",
                )
                for i in range(1, 150)
            ]
        )
        with patch("orcamentos.views.make_numbered_canvas", wraps=real_make_numbered_canvas) as factory_mock:
            response = self.client.get(reverse("orcamentos:imprimir_orcamento", args=[self.orcamento.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertTrue(factory_mock.called)
        self.assertTrue(any(total >= 2 for total in self._pdf_page_counts(response.content)))

    def test_imprimir_orcamento_respeita_campos_ocultos_configurados(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_orcamento_exibir_documento_cliente = False
        config.pdf_orcamento_exibir_defeito = False
        config.pdf_orcamento_exibir_peritagem = False
        config.pdf_orcamento_exibir_condicoes = False
        config.pdf_orcamento_exibir_aprovacao = False
        config.save(
            update_fields=[
                "pdf_orcamento_exibir_documento_cliente",
                "pdf_orcamento_exibir_defeito",
                "pdf_orcamento_exibir_peritagem",
                "pdf_orcamento_exibir_condicoes",
                "pdf_orcamento_exibir_aprovacao",
            ]
        )
        OrdemServico.objects.filter(pk=self.ordem.pk).update(
            defeito="Nao deveria aparecer como defeito no or?amento.",
            peritagem="Nao deveria aparecer no or?amento.",
        )
        self.ordem.refresh_from_db()
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("orcamentos.views.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("orcamentos:imprimir_orcamento", args=[self.orcamento.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertNotIn("Documento", texto_unificado)
        self.assertNotIn("Defeito", texto_unificado)
        self.assertNotIn("Nao deveria aparecer como defeito no or?amento.", texto_unificado)
        self.assertNotIn("Peritagem", texto_unificado)
        self.assertNotIn("Nao deveria aparecer no or?amento.", texto_unificado)
        self.assertNotIn("Condi??es Comerciais e Aprova??o", texto_unificado)
        self.assertNotIn("Assinatura do Cliente", texto_unificado)
