from datetime import datetime, timedelta
from io import BytesIO
from decimal import Decimal
import json
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Frame, Paragraph as reportlab_paragraph

from caixa.models import Caixa, ContaReceber, Pagamento
from caixa.models import AuditoriaGarantia
from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema, Empresa, ParceiroExpedicao
from core.pdf_theme import get_document_theme as real_get_document_theme
from configuracoes.models import FornecedorGarantia, MarcaGarantia, ModeloMensagem
from estoque.models import PontoOperacional, Produto, ReservaEstoque, SaldoEstoquePonto, SaldoEstoqueUbicacao, UbicacaoEstoque
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.forms import LinhaTrabalhoForm
from ordens.models import ConciliacaoOrdem, ConciliacaoOrdemItem, GuiaExpedicaoItem, GuiaExpedicaoParceiro, LogOS, OrdemArquivo, OrdemServico, LinhaTrabalho, NotificacaoCliente, OrdemTalao, PedidoCompra, ServicoPeca
from ordens.services.fluxo_os_policy import FluxoOSPolicyService
from ordens.services.resumo_operacional import ResumoOperacionalService
from ordens.view_modules.impressao import _draw_etiquetas_corte, _quebrar_tokens_longos
from core.pdf_utils import logo_or_paragraph, make_numbered_canvas as real_make_numbered_canvas


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
        self.assertContains(response, "Digite apenas letras e numeros validos para CPF, CNPJ ou telefone.")

    def test_busca_abaixo_do_minimo_mostra_erro(self):
        response = self.client.get(self.url, {"cpf_telefone": "1234"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Digite pelo menos 5 caracteres para buscar.")
        self.assertNotContains(response, "Nenhum Cliente Encontrado")

    def test_busca_por_cnpj_alfanumerico_encontra_cliente(self):
        cliente = Cliente.objects.create(
            nome="Cliente PJ Alfa",
            documento="12ABC34501DE35",
            telefone="11987654321",
            estado="SP",
        )

        response = self.client.get(self.url, {"cpf_telefone": "12.ABC.345/01DE-35"})

        self.assertEqual(response.status_code, 200)
        clientes = list(response.context["clientes"])
        self.assertEqual(len(clientes), 1)
        self.assertEqual(clientes[0].id, cliente.id)

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

    def test_cadastro_bloqueia_cliente_duplicado_por_documento(self):
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
                "documento": "529.982.247-25",
                "ddd": "11",
                "telefone_numero": "99999-9999",
                "email": "duplicado@exemplo.com",
                "estado": "SP",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Cliente.objects.filter(documento="52998224725").count(), 1)

    def test_cadastro_permite_email_duplicado(self):
        Cliente.objects.create(
            nome="Cliente Existente",
            documento="52998224725",
            telefone="11987654321",
            email="duplicado2@exemplo.com",
            estado="SP",
        )

        response = self.client.post(
            self.url,
            {
                "nome": "Cliente Novo",
                "documento": "123.456.789-09",
                "ddd": "11",
                "telefone_numero": "99999-9999",
                "email": "duplicado2@exemplo.com",
                "estado": "SP",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Cliente.objects.filter(email__iexact="duplicado2@exemplo.com").count(), 2)

    def test_cadastro_permite_telefone_duplicado(self):
        Cliente.objects.create(
            nome="Cliente Existente",
            documento="39053344705",
            telefone="11999999999",
            estado="SP",
        )

        response = self.client.post(
            self.url,
            {
                "nome": "Cliente Novo",
                "documento": "111.444.777-35",
                "ddd": "11",
                "telefone_numero": "99999-9999",
                "email": "tel2@exemplo.com",
                "estado": "SP",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Cliente.objects.filter(telefone="11999999999").count(), 2)


class FluxoStatusOrdemServicoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="tecnico_status",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.cliente = Cliente.objects.create(
            nome="Cliente OS",
            documento="11144477735",
            telefone="11999998888",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="MarcaX",
            modelo_equipamento="ModeloY",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

    def test_transicao_valida_registra_linha(self):
        self.ordem.transicionar_status(
            "pendente_pecas",
            usuario=self.user,
            motivo="Aguardando componente",
        )
        self.ordem.refresh_from_db()

        self.assertEqual(self.ordem.status, "pendente_pecas")
        linha = LinhaTrabalho.objects.get(ordem=self.ordem, status="pendente_pecas")
        self.assertEqual(linha.tipo_evento, "automatico")

    def test_status_destino_invalido_dispara_erro(self):
        with self.assertRaises(ValueError):
            self.ordem.transicionar_status("criada", usuario=self.user, motivo="Status nao permitido para OS")

    def test_conclusao_exige_relatorio_e_tipo_reparacao(self):
        self.ordem.status = "em_andamento"
        self.ordem.save()
        with self.assertRaises(ValueError):
            self.ordem.transicionar_status("concluida", usuario=self.user, motivo="Sem laudo")

    def test_reabertura_da_concluida_para_em_andamento(self):
        self.ordem.status = "em_andamento"
        self.ordem.relatorio_tecnico = "Laudo tecnico final"
        self.ordem.tipo_reparacao = "substituicao"
        self.ordem.save()
        self.ordem.transicionar_status("concluida", usuario=self.user, motivo="Entrega")
        self.ordem.refresh_from_db()
        self.assertTrue(self.ordem.fechada)
        self.assertIsNotNone(self.ordem.data_conclusao)

        self.ordem.transicionar_status("em_andamento", usuario=self.user, motivo="Retorno")
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "em_andamento")
        self.assertFalse(self.ordem.fechada)


class FluxoOperacionalPolicyTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.usuario = user_model.objects.create_user(
            username="gerente_policy_os",
            password="senha-forte-123",
            tipo_usuario="gerente",
        )
        self.client.force_login(self.usuario)
        self.cliente = Cliente.objects.create(
            nome="Cliente Policy OS",
            documento="52998224725",
            telefone="11977776666",
            estado="SP",
        )

    def test_policy_de_pendente_orcamento_destaca_acao_de_orcamento(self):
        policy = FluxoOSPolicyService.obter_policy("pendente_orcamento")
        self.assertIn("abrir_orcamento", policy.acoes_destaque)
        self.assertIn("enviar_mensagem_cliente", policy.acoes_destaque)

    def test_resumo_operacional_inclui_bloqueio_quando_os_fechada(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Policy",
            modelo_equipamento="Modelo Policy",
            defeito="Sem imagem",
            tipo_reparo="Fora de Garantia",
            status="concluida",
        )
        ordem.fechada = True
        ordem.save(update_fields=["fechada"])

        resumo = ResumoOperacionalService.construir(
            ordem,
            total_os=Decimal("100.00"),
            total_pago=Decimal("0.00"),
            saldo_financeiro=Decimal("100.00"),
            os_pago=False,
        )

        self.assertIn("A OS esta fechada para edicao operacional.", resumo.bloqueios_operacionais)
        self.assertIn("ir_para_caixa", resumo.acoes_destaque)

    def test_resumo_operacional_considera_os_gratuita_como_quitada(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Cortesia",
            modelo_equipamento="Modelo Cortesia",
            defeito="Atendimento gratuito",
            tipo_reparo="Fora de Garantia",
            status="concluida",
            fechada=True,
        )

        resumo = ResumoOperacionalService.construir(ordem)

        self.assertTrue(resumo.liberada_para_entrega)
        self.assertFalse(resumo.pode_receber_no_caixa)
        self.assertEqual(resumo.fluxo_label, "Concluída e liberada para entrega")

    def test_detalhes_recebe_destaque_orcamento_em_status_pendente_orcamento(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Policy",
            modelo_equipamento="Modelo Policy",
            defeito="Sem audio",
            tipo_reparo="Fora de Garantia",
            status="pendente_orcamento",
        )

        response = self.client.get(reverse("ordens:detalhes_ordem", args=[ordem.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["destacar_abrir_orcamento"])


class CriacaoOrdemServicoHistoricoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_criacao_os",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Criacao OS",
            documento="39053344705",
            telefone="11912345678",
            estado="SP",
        )

    def test_criacao_os_registra_linha_criada_e_diagnosticar(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        payload = {
            "tipo_equipamento": "celular",
            "marca_catalogo": "__outros__",
            "marca_manual": "Marca A",
            "marca_equipamento": "",
            "modelo_equipamento": "Modelo B",
            "numero_serie_equipamento": "SN-123",
            "defeito": "Nao liga",
            "acessorios": "Cabo",
            "tipo_reparo": "Fora de Garantia",
            "status": "concluida",
            "peritagem": "Sem danos visiveis",
        }
        response_revisao = self.client.post(url, payload)
        self.assertEqual(response_revisao.status_code, 200)
        self.assertContains(response_revisao, "Revisão antes de criar a OS")
        self.assertFalse(OrdemServico.objects.exists())

        payload["confirmar_criacao"] = "1"
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/resumo/", response.url)

        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(ordem.status, "diagnosticar")

        linhas = list(LinhaTrabalho.objects.filter(ordem=ordem).order_by("id"))
        self.assertGreaterEqual(len(linhas), 2)
        self.assertEqual(linhas[0].status, "criada")
        self.assertEqual(linhas[0].descricao, "Ordem criada")
        self.assertEqual(linhas[0].tipo_evento, "automatico")
        self.assertEqual(linhas[1].status, "diagnosticar")
        self.assertEqual(linhas[1].tipo_evento, "automatico")

    def test_criacao_os_com_tipo_equipamento_outros_persiste_valor_manual(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        payload = {
            "tipo_equipamento": "__outros__",
            "tipo_equipamento_manual": "Depilador a laser",
            "marca_catalogo": "__outros__",
            "marca_manual": "Marca Livre",
            "marca_equipamento": "",
            "modelo_equipamento": "Modelo Livre",
            "numero_serie_equipamento": "SN-OUTROS-001",
            "defeito": "Nao liga",
            "acessorios": "",
            "tipo_reparo": "Fora de Garantia",
            "peritagem": "",
            "confirmar_criacao": "1",
        }

        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(ordem.tipo_equipamento, "Depilador a laser")
        self.assertEqual(ordem.marca_equipamento, "Marca Livre")

    def test_criacao_os_aceita_tipo_reparo_encomenda(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        payload = {
            "tipo_equipamento": "celular",
            "marca_catalogo": "__outros__",
            "marca_manual": "Marca Encomenda",
            "marca_equipamento": "",
            "modelo_equipamento": "Modelo Encomenda",
            "numero_serie_equipamento": "",
            "defeito": "Encomenda de peça para cliente externo",
            "acessorios": "",
            "tipo_reparo": "Encomenda",
            "peritagem": "",
            "confirmar_criacao": "1",
        }

        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(ordem.tipo_reparo, "Encomenda")

    def test_criacao_os_com_nonce_repetido_nao_duplica_ordem(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        payload = {
            "tipo_equipamento": "celular",
            "marca_catalogo": "__outros__",
            "marca_manual": "Marca Dedupe",
            "marca_equipamento": "",
            "modelo_equipamento": "Modelo Dedupe",
            "numero_serie_equipamento": "SN-DEDUPE-01",
            "defeito": "Nao liga",
            "acessorios": "",
            "tipo_reparo": "Fora de Garantia",
            "peritagem": "",
            "confirmar_criacao": "1",
            "create_nonce": "nonce-fixo-dedupe",
        }

        response_1 = self.client.post(url, payload)
        self.assertEqual(response_1.status_code, 302)
        self.assertEqual(OrdemServico.objects.count(), 1)
        ordem = OrdemServico.objects.first()
        self.assertIsNotNone(ordem)

        response_2 = self.client.post(url, payload)
        self.assertEqual(response_2.status_code, 302)
        self.assertEqual(OrdemServico.objects.count(), 1)
        self.assertEqual(response_2.url, reverse("ordens:resumo_ordem", args=[ordem.id]))

    def test_criacao_os_com_nonce_novo_e_dados_identicos_recentes_nao_duplica(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        payload = {
            "tipo_equipamento": "celular",
            "marca_catalogo": "__outros__",
            "marca_manual": "Marca Dedupe 2",
            "marca_equipamento": "",
            "modelo_equipamento": "Modelo Dedupe 2",
            "numero_serie_equipamento": "SN-DEDUPE-02",
            "defeito": "Nao liga",
            "acessorios": "",
            "tipo_reparo": "Fora de Garantia",
            "peritagem": "Sem danos",
            "confirmar_criacao": "1",
            "create_nonce": "nonce-1-dedupe-2",
        }

        response_1 = self.client.post(url, payload)
        self.assertEqual(response_1.status_code, 302)
        self.assertEqual(OrdemServico.objects.count(), 1)
        ordem = OrdemServico.objects.first()
        self.assertIsNotNone(ordem)

        payload["create_nonce"] = "nonce-2-dedupe-2"
        response_2 = self.client.post(url, payload)
        self.assertEqual(response_2.status_code, 302)
        self.assertEqual(OrdemServico.objects.count(), 1)
        self.assertEqual(response_2.url, reverse("ordens:resumo_ordem", args=[ordem.id]))

    def test_criacao_os_com_dados_identicos_fora_da_janela_permite_nova_ordem(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        payload = {
            "tipo_equipamento": "celular",
            "marca_catalogo": "__outros__",
            "marca_manual": "Marca Janela",
            "marca_equipamento": "",
            "modelo_equipamento": "Modelo Janela",
            "numero_serie_equipamento": "SN-JANELA-01",
            "defeito": "Nao liga",
            "acessorios": "",
            "tipo_reparo": "Fora de Garantia",
            "peritagem": "",
            "confirmar_criacao": "1",
            "create_nonce": "nonce-1-janela",
        }

        response_1 = self.client.post(url, payload)
        self.assertEqual(response_1.status_code, 302)
        self.assertEqual(OrdemServico.objects.count(), 1)
        ordem_1 = OrdemServico.objects.first()
        self.assertIsNotNone(ordem_1)
        OrdemServico.objects.filter(id=ordem_1.id).update(
            data_abertura=timezone.now() - timedelta(minutes=40)
        )

        payload["create_nonce"] = "nonce-2-janela"
        response_2 = self.client.post(url, payload)
        self.assertEqual(response_2.status_code, 302)
        self.assertEqual(OrdemServico.objects.count(), 2)

    def test_criacao_os_sem_sn_nao_bloqueia_duplicidade_por_conteudo(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        payload = {
            "tipo_equipamento": "celular",
            "marca_catalogo": "__outros__",
            "marca_manual": "Marca Sem SN",
            "marca_equipamento": "",
            "modelo_equipamento": "Modelo Sem SN",
            "numero_serie_equipamento": "",
            "defeito": "Nao liga",
            "acessorios": "",
            "tipo_reparo": "Fora de Garantia",
            "peritagem": "",
            "confirmar_criacao": "1",
            "create_nonce": "nonce-sem-sn-1",
        }

        response_1 = self.client.post(url, payload)
        self.assertEqual(response_1.status_code, 302)
        self.assertEqual(OrdemServico.objects.count(), 1)

        payload["create_nonce"] = "nonce-sem-sn-2"
        response_2 = self.client.post(url, payload)
        self.assertEqual(response_2.status_code, 302)
        self.assertEqual(OrdemServico.objects.count(), 2)

    def test_resumo_ordem_exibe_dados_principais(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_resumo_os",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca A",
            modelo_equipamento="Modelo B",
            numero_serie_equipamento="SN-ABC",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
            tecnico_responsavel=tecnico,
        )
        LinhaTrabalho.objects.create(
            ordem=ordem,
            usuario=self.user,
            status="criada",
            descricao="Ordem criada",
            tipo_evento="manual",
        )
        response = self.client.get(reverse("ordens:resumo_ordem", args=[ordem.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.cliente.nome)
        self.assertContains(response, ordem.marca_equipamento)
        self.assertContains(response, ordem.modelo_equipamento)
        self.assertContains(response, "Atendente")
        self.assertContains(response, self.user.username)
        self.assertContains(response, "Tecnico responsavel")
        self.assertContains(response, tecnico.username)

    def test_resumo_ordem_oculta_canal_digital_quando_desativado(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.usar_confirmacao_assinatura_digital = False
        config.save(update_fields=["usar_confirmacao_assinatura_digital"])

        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca X",
            modelo_equipamento="Modelo Y",
            numero_serie_equipamento="SN-DIGITAL-OFF",
            defeito="Sem audio",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

        response = self.client.get(reverse("ordens:resumo_ordem", args=[ordem.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Canal digital")
        self.assertNotContains(response, "Reenviar WhatsApp")
        self.assertContains(response, "Validacao presencial")

    def test_resumo_ordem_nao_exibe_bloco_de_termos_e_condicoes(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca X",
            modelo_equipamento="Modelo Y",
            numero_serie_equipamento="SN-RESUMO-01",
            defeito="Nao carrega",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

        response = self.client.get(reverse("ordens:resumo_ordem", args=[ordem.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Termos e condicoes da OS")

    def test_criacao_os_com_marca_outros_preenche_marca_manual(self):
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Marca")
        MarcaGarantia.objects.create(
            nome="Marca Conhecida",
            fornecedor=fornecedor,
            valor_mao_obra_garantia="0.00",
            parceira_garantia=True,
            ativo=True,
        )
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        response = self.client.post(
            url,
            {
                "tipo_equipamento": "celular",
                "marca_catalogo": "__outros__",
                "marca_manual": "Marca Nova",
                "marca_equipamento": "",
                "modelo_equipamento": "Modelo C",
                "numero_serie_equipamento": "SN-321",
                "defeito": "Nao liga",
                "acessorios": "",
                "tipo_reparo": "Garantia",
                "data_compra": "2026-01-10",
                "numero_nota_fiscal": "NF-12345",
                "status": "diagnosticar",
                "peritagem": "",
                "confirmar_criacao": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(ordem.marca_equipamento, "Marca Nova")

    def test_criacao_os_salva_referencia_parceiro(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        response = self.client.post(
            url,
            {
                "tipo_equipamento": "celular",
                "marca_catalogo": "__outros__",
                "marca_manual": "Marca Parceiro",
                "marca_equipamento": "",
                "modelo_equipamento": "Modelo PX",
                "numero_serie_equipamento": "SN-PARC-1",
                "defeito": "Sem imagem",
                "acessorios": "",
                "tipo_reparo": "Fora de Garantia",
                "referencia_parceiro": "PARC-2026-001",
                "status": "diagnosticar",
                "peritagem": "",
                "confirmar_criacao": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(ordem.referencia_parceiro, "PARC-2026-001")

    def test_criacao_os_nao_aceita_marca_manual_sem_escolher_outros(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        response = self.client.post(
            url,
            {
                "tipo_equipamento": "celular",
                "marca_catalogo": "",
                "marca_manual": "Marca Solta",
                "marca_equipamento": "",
                "modelo_equipamento": "Modelo C",
                "numero_serie_equipamento": "SN-888",
                "defeito": "Nao liga",
                "acessorios": "",
                "tipo_reparo": "Fora de Garantia",
                "status": "diagnosticar",
                "peritagem": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione uma marca ou escolha Outros.")

    def test_criacao_os_garantia_sem_nota_fiscal_exibe_erro(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        response = self.client.post(
            url,
            {
                "tipo_equipamento": "celular",
                "marca_catalogo": "__outros__",
                "marca_manual": "Marca Sem Nota",
                "marca_equipamento": "",
                "modelo_equipamento": "Modelo D",
                "numero_serie_equipamento": "SN-654",
                "defeito": "Sem video",
                "acessorios": "",
                "tipo_reparo": "Garantia",
                "data_compra": "2026-01-10",
                "status": "diagnosticar",
                "peritagem": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "informe o número da nota fiscal")

    def test_criacao_os_garantia_sem_data_compra_exibe_erro(self):
        url = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        response = self.client.post(
            url,
            {
                "tipo_equipamento": "celular",
                "marca_catalogo": "__outros__",
                "marca_manual": "Marca Sem Data",
                "marca_equipamento": "",
                "modelo_equipamento": "Modelo E",
                "numero_serie_equipamento": "SN-777",
                "defeito": "Sem audio",
                "acessorios": "",
                "tipo_reparo": "Garantia",
                "numero_nota_fiscal": "NF-777",
                "status": "diagnosticar",
                "peritagem": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "informe a data da compra")


class OrdemServicoListagemTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_lista_os",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Lista OS",
            documento="12345678909",
            telefone="11987654321",
            estado="SP",
        )

    def _criar_ordem(self, sufixo, status="diagnosticar"):
        return OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento=f"Marca {sufixo}",
            modelo_equipamento=f"Modelo {sufixo}",
            numero_serie_equipamento=f"SN-{sufixo}",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status=status,
        )

    def test_lista_ordens_sem_filtros_nao_carrega_resultados(self):
        self._criar_ordem("001")

        response = self.client.get(reverse("ordens:lista_ordens"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione um status para listar ordens")
        self.assertFalse(response.context["filtros_aplicados"])
        self.assertEqual(response.context["total_filtrado"], 0)
        self.assertEqual(len(response.context["ordens"]), 0)

    def test_lista_ordens_com_status_aplica_paginacao(self):
        for indice in range(27):
            self._criar_ordem(f"{indice:03d}", status="diagnosticar")
        self._criar_ordem("fechada", status="concluida")

        response = self.client.get(reverse("ordens:lista_ordens"), {"status": "diagnosticar"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filtros_aplicados"])
        self.assertEqual(response.context["total_filtrado"], 27)
        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(len(response.context["ordens"]), 25)

    def test_lista_ordens_com_carregar_sem_status_mostra_abertas(self):
        ordem_aberta = self._criar_ordem("aberta", status="diagnosticar")
        ordem_fechada = self._criar_ordem("fechada", status="concluida")
        ordem_fechada.fechada = True
        ordem_fechada.save(update_fields=["fechada"])

        response = self.client.get(reverse("ordens:lista_ordens"), {"carregar": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filtros_aplicados"])
        self.assertTrue(response.context["carregar_lista"])
        self.assertEqual(list(response.context["ordens"]), [ordem_aberta])

    def test_lista_ordens_com_status_abertas_mostra_apenas_ordens_em_aberto(self):
        ordem_aberta = self._criar_ordem("aberta-status", status="em_andamento")
        ordem_fechada = self._criar_ordem("fechada-status", status="concluida")
        ordem_fechada.fechada = True
        ordem_fechada.save(update_fields=["fechada"])

        response = self.client.get(reverse("ordens:lista_ordens"), {"status": "abertas"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filtros_aplicados"])
        self.assertEqual(response.context["status_filtro_label"], "Ordens abertas")
        self.assertEqual(list(response.context["ordens"]), [ordem_aberta])

    def test_lista_ordens_filtra_por_local_armazenamento(self):
        ordem_loja = self._criar_ordem("loja", status="diagnosticar")
        ordem_loja.local_armazenamento = "Prateleira A"
        ordem_loja.save(update_fields=["local_armazenamento"])

        ordem_bancada = self._criar_ordem("bancada", status="em_andamento")
        ordem_bancada.local_armazenamento = "Bancada 02"
        ordem_bancada.save(update_fields=["local_armazenamento"])

        response = self.client.get(
            reverse("ordens:lista_ordens"),
            {"status": "abertas", "local_armazenamento": "prateleira"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filtros_aplicados"])
        self.assertEqual(response.context["local_armazenamento"], "prateleira")
        self.assertEqual(list(response.context["ordens"]), [ordem_loja])

    def test_lista_ordens_concluidas_mostra_apenas_fechadas(self):
        ordem_fechada = self._criar_ordem("concluida", status="concluida")
        ordem_fechada.fechada = True
        ordem_fechada.save(update_fields=["fechada"])

        self._criar_ordem("reaberta", status="concluida")

        response = self.client.get(reverse("ordens:lista_ordens"), {"status": "concluida"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["ordens"]), [ordem_fechada])

    def test_lista_ordens_com_filtro_rapido_sem_tecnico(self):
        ordem_sem_tecnico = self._criar_ordem("sem-tech")
        ordem_com_atendente_no_campo_tecnico = self._criar_ordem("com-atendente", status="diagnosticar")
        ordem_com_atendente_no_campo_tecnico.tecnico_responsavel = self.user
        ordem_com_atendente_no_campo_tecnico.save(update_fields=["tecnico_responsavel"])
        outro_user = get_user_model().objects.create_user(
            username="tecnico_lista_os",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        ordem_com_tecnico = self._criar_ordem("com-tech", status="diagnosticar")
        ordem_com_tecnico.tecnico_responsavel = outro_user
        ordem_com_tecnico.save(update_fields=["tecnico_responsavel"])

        response = self.client.get(reverse("ordens:lista_ordens"), {"quick": "sem_tecnico"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filtros_aplicados"])
        self.assertEqual(response.context["quick_filter"], "sem_tecnico")
        self.assertEqual(
            list(response.context["ordens"]),
            [ordem_com_atendente_no_campo_tecnico, ordem_sem_tecnico],
        )

    def test_lista_ordens_com_filtro_rapido_minhas_os(self):
        ordem_minha = self._criar_ordem("minha", status="diagnosticar")
        ordem_minha.tecnico_responsavel = self.user
        ordem_minha.save(update_fields=["tecnico_responsavel"])

        outro_user = get_user_model().objects.create_user(
            username="tecnico_outra_os",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        ordem_outra = self._criar_ordem("outra", status="diagnosticar")
        ordem_outra.tecnico_responsavel = outro_user
        ordem_outra.save(update_fields=["tecnico_responsavel"])

        response = self.client.get(reverse("ordens:lista_ordens"), {"quick": "minhas"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filtros_aplicados"])
        self.assertEqual(response.context["quick_filter"], "minhas")
        self.assertEqual(list(response.context["ordens"]), [ordem_minha])


class DashboardPedidosCompraTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_pedidos_dashboard",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.tecnico = user_model.objects.create_user(
            username="tecnico_dashboard",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.cliente = Cliente.objects.create(
            nome="Cliente Pedidos",
            documento="39053344705",
            telefone="11999999999",
            estado="SP",
        )

    def _criar_ordem(self, sufixo, status="diagnosticar", tecnico=None):
        return OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento=f"Marca {sufixo}",
            modelo_equipamento=f"Modelo {sufixo}",
            numero_serie_equipamento=f"SN-PED-{sufixo}",
            defeito="Sem imagem",
            tipo_reparo="Fora de Garantia",
            status=status,
            tecnico_responsavel=tecnico,
        )

    def _criar_pedido(self, ordem, titulo, status="contactar", dias_atras=0):
        pedido = PedidoCompra.objects.create(
            ordem=ordem,
            titulo=titulo,
            status=status,
            criado_por=self.user,
        )
        if dias_atras:
            PedidoCompra.objects.filter(pk=pedido.pk).update(
                criado_em=timezone.now() - timedelta(days=dias_atras)
            )
            pedido.refresh_from_db()
        return pedido

    def test_dashboard_pedidos_filtro_rapido_sem_tecnico(self):
        ordem_sem_tecnico = self._criar_ordem("sem", tecnico=None)
        ordem_com_tecnico = self._criar_ordem("com", tecnico=self.tecnico)
        pedido_sem = self._criar_pedido(ordem_sem_tecnico, "Pedido sem tecnico")
        self._criar_pedido(ordem_com_tecnico, "Pedido com tecnico")

        response = self.client.get(reverse("ordens:dashboard_pedidos"), {"quick": "sem_tecnico"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["quick_filter"], "sem_tecnico")
        self.assertEqual(list(response.context["pedidos"]), [pedido_sem])

    def test_dashboard_pedidos_filtro_rapido_atrasados(self):
        ordem = self._criar_ordem("atr", tecnico=self.tecnico)
        pedido_atrasado = self._criar_pedido(ordem, "Pedido atrasado", dias_atras=8)
        self._criar_pedido(ordem, "Pedido recente", dias_atras=2)

        response = self.client.get(reverse("ordens:dashboard_pedidos"), {"quick": "atrasados"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["quick_filter"], "atrasados")
        self.assertEqual(list(response.context["pedidos"]), [pedido_atrasado])

class LinhaTrabalhoFormTests(TestCase):
    def test_status_criada_nao_aparece_para_selecao_manual(self):
        form = LinhaTrabalhoForm()
        valores = [valor for valor, _ in form.fields["status"].choices if valor]
        self.assertNotIn("criada", valores)
        self.assertNotIn("concluida", valores)

    def test_novos_status_operacionais_aparecem_para_selecao_manual(self):
        form = LinhaTrabalhoForm()
        valores = [valor for valor, _ in form.fields["status"].choices if valor]
        self.assertIn("transito_outdoor", valores)
        self.assertIn("enviado_parceiro", valores)


class IntegracaoFluxoOSCaixaTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_fluxo",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Integracao",
            documento="11144477735",
            telefone="11912345678",
            estado="SP",
        )

    def test_fluxo_criar_os_relatorio_finalizar_sem_redirecionamento_automatico(self):
        url_criar = reverse("ordens:nova_ordem_cliente", args=[self.cliente.id])
        response_criar = self.client.post(
            url_criar,
            {
                "tipo_equipamento": "celular",
                "marca_catalogo": "__outros__",
                "marca_manual": "Marca T",
                "marca_equipamento": "",
                "modelo_equipamento": "Modelo Z",
                "numero_serie_equipamento": "SN-999",
                "defeito": "Nao liga",
                "acessorios": "Capa",
                "tipo_reparo": "Fora de Garantia",
                "status": "concluida",
                "peritagem": "",
                "confirmar_criacao": "1",
            },
        )
        self.assertEqual(response_criar.status_code, 302)

        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(ordem.status, "diagnosticar")
        self.assertGreaterEqual(LinhaTrabalho.objects.filter(ordem=ordem).count(), 2)

        url_detalhes = reverse("ordens:detalhes_ordem", args=[ordem.id])
        response_relatorio = self.client.post(
            url_detalhes,
            {
                "form_type": "relatorio",
                "relatorio_tecnico": "Equipamento reparado com sucesso.",
                "tipo_reparacao": "substituicao",
            },
        )
        self.assertEqual(response_relatorio.status_code, 302)

        response_finalizar = self.client.post(url_detalhes, {"form_type": "finalizar_caixa"})
        self.assertEqual(response_finalizar.status_code, 302)

        ordem.refresh_from_db()
        self.assertEqual(ordem.status, "concluida")
        self.assertTrue(ordem.fechada)
        self.assertIsNotNone(ordem.data_conclusao)
        self.assertIn("?tab=servicos", response_finalizar.url)

    def test_finalizar_com_opcao_ir_caixa_nao_cria_pendencia_quando_total_zero(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca T",
            modelo_equipamento="Modelo Z",
            numero_serie_equipamento="SN-888",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
            relatorio_tecnico="Laudo tecnico pronto",
            tipo_reparacao="substituicao",
        )
        url_detalhes = reverse("ordens:detalhes_ordem", args=[ordem.id])
        response_finalizar = self.client.post(url_detalhes, {"form_type": "finalizar_caixa", "ir_caixa": "1"})
        self.assertEqual(response_finalizar.status_code, 302)
        self.assertIn("?tab=servicos", response_finalizar.url)
        self.assertFalse(ContaReceber.objects.filter(ordem_servico=ordem, tipo_origem="cliente_os").exists())
        self.assertFalse(ordem.alertas.filter(mensagem__icontains="saldo pendente").exists())

        response_detalhes = self.client.get(url_detalhes + "?tab=servicos")
        self.assertTrue(response_detalhes.context["os_pago"])
        self.assertFalse(response_detalhes.context["pode_receber_no_caixa"])
        self.assertContains(response_detalhes, "Sem recebimento pendente")

    def test_fechar_os_sem_ir_caixa_permanece_nos_detalhes(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca T",
            modelo_equipamento="Modelo Z",
            numero_serie_equipamento="SN-001",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
            relatorio_tecnico="Laudo ok",
            tipo_reparacao="substituicao",
        )
        response = self.client.get(reverse("ordens:toggle_fechamento_os", args=[ordem.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/detalhes/?tab=detalhes", response.url)

    def test_fechar_os_com_ir_caixa_redireciona_para_pagamento(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca T",
            modelo_equipamento="Modelo Z",
            numero_serie_equipamento="SN-002",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
            relatorio_tecnico="Laudo ok",
            tipo_reparacao="substituicao",
        )
        ServicoPeca.objects.create(
            ordem=ordem,
            tipo="servico",
            nome="Troca de componente",
            quantidade=1,
            valor_unitario="150.00",
        )
        response = self.client.get(reverse("ordens:toggle_fechamento_os", args=[ordem.id]) + "?ir_caixa=1")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("caixa:registrar_pagamento"), response.url)
        self.assertIn(f"os={ordem.id}", response.url)

    def test_fechar_os_com_saldo_pendente_exige_confirmacao_previa(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca T",
            modelo_equipamento="Modelo Z",
            numero_serie_equipamento="SN-002A",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
            relatorio_tecnico="Laudo ok",
            tipo_reparacao="substituicao",
        )
        ServicoPeca.objects.create(
            ordem=ordem,
            tipo="servico",
            nome="Troca de componente",
            quantidade=1,
            valor_unitario="150.00",
        )
        response = self.client.get(reverse("ordens:toggle_fechamento_os", args=[ordem.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("confirmar_fechamento=1", response.url)
        ordem.refresh_from_db()
        self.assertFalse(ordem.fechada)

    def test_fechar_os_com_confirmacao_financeira_cria_alerta_e_conta_receber(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca T",
            modelo_equipamento="Modelo Z",
            numero_serie_equipamento="SN-002B",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
            relatorio_tecnico="Laudo ok",
            tipo_reparacao="substituicao",
        )
        ServicoPeca.objects.create(
            ordem=ordem,
            tipo="servico",
            nome="Troca de componente",
            quantidade=1,
            valor_unitario="150.00",
        )
        response = self.client.get(reverse("ordens:toggle_fechamento_os", args=[ordem.id]) + "?confirmar_financeiro=1")
        self.assertEqual(response.status_code, 302)
        ordem.refresh_from_db()
        self.assertTrue(ordem.fechada)
        self.assertTrue(ordem.alertas.filter(mensagem__startswith="Fechamento com saldo pendente").exists())
        self.assertTrue(ContaReceber.objects.filter(ordem_servico=ordem, tipo_origem="cliente_os").exists())

    def test_fechar_os_com_ir_caixa_e_saldo_pendente_fecha_sem_alerta_intermediario(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca T",
            modelo_equipamento="Modelo Z",
            numero_serie_equipamento="SN-002C",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
            relatorio_tecnico="Laudo ok",
            tipo_reparacao="substituicao",
        )
        ServicoPeca.objects.create(
            ordem=ordem,
            tipo="servico",
            nome="Troca de componente",
            quantidade=1,
            valor_unitario="150.00",
        )

        response = self.client.get(reverse("ordens:toggle_fechamento_os", args=[ordem.id]) + "?ir_caixa=1")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("caixa:registrar_pagamento"), response.url)
        self.assertNotIn("confirmar_fechamento=1", response.url)
        ordem.refresh_from_db()
        self.assertTrue(ordem.fechada)

    def test_fechar_os_garantia_cria_auditoria_financeira(self):
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor G")
        marca = MarcaGarantia.objects.create(
            nome="Marca G",
            fornecedor=fornecedor,
            valor_mao_obra_garantia="150.00",
            parceira_garantia=True,
            ativo=True,
        )
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca G",
            marca_garantia=marca,
            modelo_equipamento="Modelo G",
            numero_serie_equipamento="SN-003",
            defeito="Nao liga",
            tipo_reparo="Garantia",
            status="em_andamento",
            relatorio_tecnico="Laudo ok",
            tipo_reparacao="substituicao",
        )
        response = self.client.get(reverse("ordens:toggle_fechamento_os", args=[ordem.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AuditoriaGarantia.objects.filter(ordem_servico=ordem).exists())

    def test_box_financeiro_em_servicos_exibe_referencias_e_status_pago(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca F",
            modelo_equipamento="Modelo F",
            numero_serie_equipamento="SN-FIN",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        ServicoPeca.objects.create(
            ordem=ordem,
            tipo="servico",
            nome="Servico 1",
            quantidade=1,
            valor_unitario="100.00",
        )
        Pagamento.objects.create(
            ordem_servico=ordem,
            valor="100.00",
            metodo="pix",
            referencia="TALAO-001",
        )

        response = self.client.get(reverse("ordens:detalhes_ordem", args=[ordem.id]) + "?tab=servicos")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pago?")
        self.assertContains(response, "Sim")
        self.assertContains(response, "TALAO-001")

    def test_detalhes_ordem_lista_tecnicos_no_select_responsavel(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_select_os",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca T",
            modelo_equipamento="Modelo Z",
            numero_serie_equipamento="SN-TEC",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        response = self.client.get(reverse("ordens:detalhes_ordem", args=[ordem.id]) + "?tab=detalhes")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, tecnico.username)

    def test_detalhes_ordem_exibe_resumo_operacional_por_status(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Resumo",
            modelo_equipamento="Modelo Resumo",
            numero_serie_equipamento="",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="pendente_pecas",
        )
        response = self.client.get(reverse("ordens:detalhes_ordem", args=[ordem.id]) + "?tab=detalhes")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Serviços &amp; Peças")
        self.assertContains(response, "Orçamentos")
        self.assertContains(response, "Relatório Técnico")
        self.assertContains(response, "Acompanhar chegada de pecas para continuar o reparo.")
        self.assertContains(response, "Numero de serie nao informado.")
        self.assertContains(response, 'data-toggle="tooltip"')

    def test_editar_os_permite_apenas_numero_serie_e_registra_linha(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Fixa",
            modelo_equipamento="Modelo Fixo",
            numero_serie_equipamento="SN-OLD",
            defeito="Defeito original",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        response = self.client.post(
            reverse("ordens:editar_ordem", args=[ordem.id]),
            {"numero_serie_equipamento": "SN-NEW"},
        )
        self.assertEqual(response.status_code, 302)
        ordem.refresh_from_db()
        self.assertEqual(ordem.numero_serie_equipamento, "SN-NEW")
        self.assertEqual(ordem.defeito, "Defeito original")
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=ordem,
                descricao__icontains="Número de série alterado",
            ).exists()
        )


class OrdemFechadaBloqueioEdicaoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_bloqueio",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Bloqueio",
            documento="39053344705",
            telefone="11912340000",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca B",
            modelo_equipamento="Modelo C",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="concluida",
            fechada=True,
            relatorio_tecnico="Laudo final",
            tipo_reparacao="substituicao",
        )
        self.orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        self.item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Item 1",
            descricao="Teste",
            valor_unitario="50.00",
            quantidade=1,
        )

    def test_nao_permite_adicionar_linha_em_os_fechada(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(url, {"status": "diagnosticar", "descricao": "Tentativa"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(LinhaTrabalho.objects.filter(ordem=self.ordem).count(), 0)

    def test_nao_permite_adicionar_item_orcamento_em_os_fechada(self):
        url = reverse("orcamentos:adicionar_item", args=[self.orcamento.id])
        response = self.client.post(
            url,
            {"nome": "Novo item", "quantidade": 1, "valor_unitario": "10.00", "origem": "manual", "tipo_item": "servico"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ItemOrcamento.objects.filter(orcamento=self.orcamento).count(), 1)

    def test_nao_permite_excluir_item_orcamento_em_os_fechada(self):
        url = reverse("orcamentos:excluir_item", args=[self.item.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ItemOrcamento.objects.filter(id=self.item.id).exists())


class LinhaTrabalhoAjaxAtualizaStatusTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_ajax_status",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente AJAX",
            documento="39053344705",
            telefone="11912340000",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca B",
            modelo_equipamento="Modelo C",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
            fechada=False,
        )

    def test_adicionar_linha_ajax_transiciona_status_da_os(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(
            url,
            {"status": "autorizado", "descricao": "Equipamento autorizado"},
        )

        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "autorizado")
        self.assertTrue(LinhaTrabalho.objects.filter(ordem=self.ordem, status="autorizado").exists())
        self.assertFalse(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                tipo_evento="automatico",
                descricao__startswith="Status alterado de",
            ).exists()
        )

    def test_adicionar_linha_ajax_mantem_status_orcamentado_distinto(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(
            url,
            {"status": "orcamentado", "descricao": "Orcamento enviado ao cliente"},
        )

        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "orcamentado")
        self.assertTrue(LinhaTrabalho.objects.filter(ordem=self.ordem, status="orcamentado").exists())

    def test_status_em_bancada_atualiza_os_com_mesmo_status(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(url, {"status": "em_andamento", "descricao": "Em bancada"})
        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "em_andamento")
        self.assertTrue(LinhaTrabalho.objects.filter(ordem=self.ordem, status="em_andamento").exists())

    def test_status_pendente_cliente_atualiza_os_com_mesmo_status(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(url, {"status": "pendente_cliente", "descricao": "Aguardando cliente"})
        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "pendente_cliente")
        self.assertTrue(LinhaTrabalho.objects.filter(ordem=self.ordem, status="pendente_cliente").exists())

    def test_status_devolucao_atualiza_os_com_mesmo_status(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(url, {"status": "devolucao", "descricao": "Sem reparo"})
        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "devolucao")
        self.assertTrue(LinhaTrabalho.objects.filter(ordem=self.ordem, status="devolucao").exists())

    def test_concluida_nao_pode_ser_adicionada_manual_via_ajax(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(url, {"status": "concluida", "descricao": "Tentativa de conclusao"})
        self.assertEqual(response.status_code, 400)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "diagnosticar")
        self.assertFalse(LinhaTrabalho.objects.filter(ordem=self.ordem, status="concluida").exists())

    def test_atualizar_tecnico_ajax_retorna_historico_e_persiste(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_ajax_os",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.user.perm_os_alterar_tecnico = True
        self.user.save(update_fields=["perm_os_alterar_tecnico"])

        response = self.client.post(
            reverse("ordens:atualizar_tecnico", args=[self.ordem.id]),
            data=json.dumps({"tecnico_id": tecnico.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["tecnico_nome"], tecnico.get_full_name() or tecnico.username)
        self.assertIn("linha", payload)

        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.tecnico_responsavel_id, tecnico.id)
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                descricao__icontains="Tecnico responsavel alterado para",
            ).exists()
        )


class GuiasExpedicaoParceiroTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_expedicao",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Expedicao",
            documento="39053344705",
            telefone="11955554444",
            estado="SP",
        )
        self.parceiro = ParceiroExpedicao.objects.create(nome="Parceiro Teste", ativo=True)
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca XP",
            modelo_equipamento="Modelo XP",
            defeito="Falha intermitente",
            tipo_reparo="Fora de Garantia",
            status="pronto_envio_parceiro",
        )
        self.ordem_2 = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="tablet",
            marca_equipamento="Marca XP",
            modelo_equipamento="Modelo Z",
            defeito="Sem imagem",
            tipo_reparo="Fora de Garantia",
            status="pronto_envio_parceiro",
        )

    def test_expedir_parceiro_cria_guia_com_varias_ordens(self):
        response = self.client.post(
            reverse("ordens:expedir_parceiro"),
            {
                "ordens_servico": [str(self.ordem.id), str(self.ordem_2.id)],
                "parceiro_config": str(self.parceiro.id),
                "referencia_externa": "EXT-123",
                "observacoes_saida": "Segue para analise externa",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.ordem_2.refresh_from_db()
        self.assertEqual(self.ordem.status, "enviado_parceiro")
        self.assertEqual(self.ordem_2.status, "enviado_parceiro")
        guia = GuiaExpedicaoParceiro.objects.get()
        self.assertEqual(guia.total_ordens, 2)
        self.assertEqual(guia.referencia_externa, "EXT-123")
        self.assertEqual(GuiaExpedicaoItem.objects.filter(guia=guia, status="expedida").count(), 2)

    def test_recepcionar_parceiro_fecha_item_e_define_status_retorno(self):
        guia = GuiaExpedicaoParceiro.objects.create(
            parceiro_nome="Parceiro Teste",
            referencia_externa="EXT-123",
            expedida_por=self.user,
        )
        item = GuiaExpedicaoItem.objects.create(guia=guia, ordem_servico=self.ordem)
        self.ordem.aplicar_status_sem_historico("enviado_parceiro")

        response = self.client.post(
            reverse("ordens:recepcionar_parceiro"),
            {
                "itens_expedicao": [str(item.id)],
                "status_retorno": "em_andamento",
                "observacoes_retorno": "Retornou para bancada",
            },
        )

        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.ordem.refresh_from_db()
        self.assertEqual(item.status, "recepcionada")
        self.assertEqual(self.ordem.status, "em_andamento")
        self.assertIsNotNone(item.recepcionada_em)

    def test_guia_expedicao_pdf_com_textos_longos_retorna_pdf_valido(self):
        parceiro_longo = "Parceiro " + ("MuitoLongo" * 25)
        guia = GuiaExpedicaoParceiro.objects.create(
            parceiro_nome=parceiro_longo,
            referencia_externa="REF-" + ("1234567890" * 8),
            expedida_por=self.user,
        )
        cliente_longo = Cliente.objects.create(
            nome="Cliente " + ("ComNomeExtremamenteLongo" * 8),
            documento="11144477735",
            telefone="11999999999",
            estado="SP",
        )
        ordem_longa = OrdemServico.objects.create(
            cliente=cliente_longo,
            tipo_equipamento="celular",
            marca_equipamento="Marca Teste",
            modelo_equipamento="Modelo Muito Longo",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="enviado_parceiro",
        )
        GuiaExpedicaoItem.objects.create(guia=guia, ordem_servico=ordem_longa)

        response = self.client.get(reverse("ordens:guia_expedicao_pdf", args=[guia.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/pdf"))
        self.assertTrue(response.content.startswith(b"%PDF"))


class PortalClienteTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_notif",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.cliente = Cliente.objects.create(
            nome="Cliente Portal",
            documento="11144477735",
            telefone="11912345678",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca P",
            modelo_equipamento="Modelo P",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

    def test_portal_cliente_consulta_por_codigo(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_portal_os",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.ordem.tecnico_responsavel = tecnico
        self.ordem.save(update_fields=["tecnico_responsavel"])
        LinhaTrabalho.objects.create(
            ordem=self.ordem,
            usuario=self.user,
            status="criada",
            descricao="Ordem criada",
            tipo_evento="manual",
        )
        response = self.client.get(
            reverse("ordens:portal_cliente"),
            {"codigo": self.ordem.codigo_portal, "cpf": self.cliente.documento},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ordem.numero_os)
        self.assertContains(response, "Atendente:")
        self.assertContains(response, self.user.username)
        self.assertContains(response, "Técnico responsável:")
        self.assertContains(response, tecnico.username)

    def test_portal_cliente_documento_invalido_bloqueia(self):
        response = self.client.get(
            reverse("ordens:portal_cliente"),
            {"codigo": self.ordem.codigo_portal, "cpf": "00000000000"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CPF não confere")

    def test_portal_cliente_sem_cpf_bloqueia(self):
        response = self.client.get(
            reverse("ordens:portal_cliente"),
            {"codigo": self.ordem.codigo_portal},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informe o CPF do titular")

    def test_portal_cliente_nao_exibe_descricao_interna_de_linha(self):
        LinhaTrabalho.objects.create(
            ordem=self.ordem,
            status="diagnosticar",
            descricao="Observacao interna sigilosa",
            tipo_evento="manual",
        )
        response = self.client.get(
            reverse("ordens:portal_cliente"),
            {"codigo": self.ordem.codigo_portal, "cpf": self.cliente.documento},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Observacao interna sigilosa")

    def test_notificar_whatsapp_mantem_usuario_no_sistema(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ordens:notificar_cliente_ordem", args=[self.ordem.id, "pronto"]),
            {"canal": "whatsapp"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("?tab=detalhes&wa=", response.url)

    def test_notificar_orcamento_whatsapp_registra_pendente_cliente(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ordens:notificar_cliente_ordem", args=[self.ordem.id, "orcamento"]),
            {"canal": "whatsapp"},
        )
        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "pendente_cliente")
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                status="pendente_cliente",
                descricao__icontains="Orçamento enviado por WhatsApp",
            ).exists()
        )

    def test_notificar_orcamento_whatsapp_pode_voltar_para_aba_orcamentos(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ordens:notificar_cliente_ordem", args=[self.ordem.id, "orcamento"]),
            {"canal": "whatsapp", "next_tab": "orcamentos"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("?tab=orcamentos&wa=", response.url)

    def test_notificar_pronto_whatsapp_atualiza_status_para_pronto_contactado(self):
        self.client.force_login(self.user)
        self.ordem.status = "em_andamento"
        self.ordem.save(update_fields=["status"])

        response = self.client.post(
            reverse("ordens:notificar_cliente_ordem", args=[self.ordem.id, "pronto"]),
            {"canal": "whatsapp"},
        )

        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "pronto_contactado")
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                status="pronto_contactado",
                descricao__icontains="pronto para retirada",
            ).exists()
        )

    def test_notificar_recusado_whatsapp_registra_linha_sem_alterar_status_principal(self):
        self.client.force_login(self.user)
        self.ordem.status = "recusado"
        self.ordem.relatorio_tecnico = "Cliente nao aprovou o reparo."
        self.ordem.tipo_reparacao = "recusado_preco"
        self.ordem.save(update_fields=["status", "relatorio_tecnico", "tipo_reparacao"])

        response = self.client.post(
            reverse("ordens:notificar_cliente_ordem", args=[self.ordem.id, "recusado"]),
            {"canal": "whatsapp", "next_tab": "relatorio"},
        )

        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "recusado")
        self.assertIn("?tab=relatorio&wa=", response.url)
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                status="recusado",
                descricao__icontains="recusa/devolucao",
            ).exists()
        )

    def test_notificar_orcamento_usa_itens_do_orcamento_na_mensagem_padrao(self):
        self.client.force_login(self.user)
        config = ConfiguracaoSistema.get_configuracao()
        config.mensagem_orcamento_whatsapp = ""
        config.save(update_fields=["mensagem_orcamento_whatsapp"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Troca de bateria",
            descricao="Item principal",
            valor_unitario=Decimal("80.00"),
            quantidade=1,
            tipo_item="peca",
            origem="manual",
            status="pendente",
        )
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Mao de obra",
            descricao="Servico",
            valor_unitario=Decimal("50.00"),
            quantidade=1,
            tipo_item="servico",
            origem="manual",
            status="pendente",
        )

        response = self.client.post(
            reverse("ordens:notificar_cliente_ordem", args=[self.ordem.id, "orcamento"]),
            {"canal": "whatsapp"},
        )

        self.assertEqual(response.status_code, 302)
        notif = NotificacaoCliente.objects.filter(ordem=self.ordem, canal="whatsapp").latest("id")
        self.assertIn("Troca de bateria", notif.mensagem)
        self.assertIn("Mao de obra", notif.mensagem)
        self.assertIn("130.00", notif.mensagem)

    def test_notificar_orcamento_padrao_inclui_link_pdf_quando_ha_orcamento(self):
        self.client.force_login(self.user)
        config = ConfiguracaoSistema.get_configuracao()
        config.mensagem_orcamento_whatsapp = ""
        config.save(update_fields=["mensagem_orcamento_whatsapp"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Display",
            descricao="Troca completa",
            valor_unitario=Decimal("150.00"),
            quantidade=1,
            tipo_item="peca",
            origem="manual",
            status="pendente",
        )

        response = self.client.post(
            reverse("ordens:notificar_cliente_ordem", args=[self.ordem.id, "orcamento"]),
            {"canal": "whatsapp"},
        )

        self.assertEqual(response.status_code, 302)
        notif = NotificacaoCliente.objects.filter(ordem=self.ordem, canal="whatsapp").latest("id")
        self.assertIn("PDF do orçamento:", notif.mensagem)
        self.assertIn(reverse("orcamentos:imprimir_orcamento", args=[orcamento.id]), notif.mensagem)


class OrdemEstoqueIntegracaoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_estoque_os",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)

        self.cliente = Cliente.objects.create(
            nome="Cliente Reserva OS",
            documento="39053344705",
            telefone="11988887777",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca E",
            modelo_equipamento="Modelo E",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
            relatorio_tecnico="Relatorio pronto",
            tipo_reparacao="substituicao",
        )
        self.ponto = PontoOperacional.objects.create(codigo="LOJA2", nome="Loja 2")
        self.ubicacao = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto,
            codigo="B-01",
            descricao="Prateleira B-01",
            ativo=True,
        )
        self.produto = Produto.objects.create(
            nome="Display",
            sku="DSP-01",
            ean="7894561230001",
            preco_final=100,
            preco=100,
            quantidade=5,
            ponto_operacional=self.ponto,
            ubicacao_padrao=self.ubicacao,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=self.ponto, quantidade=5)
        SaldoEstoqueUbicacao.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto,
            ubicacao=self.ubicacao,
            quantidade=5,
        )
        self.reserva = ReservaEstoque.objects.create(
            codigo_reserva="RES-OS0001",
            produto=self.produto,
            ponto_operacional=self.ponto,
            ubicacao=self.ubicacao,
            quantidade=2,
            nome_contato=self.cliente.nome,
            valido_ate=timezone.localdate() + timedelta(days=2),
            status="ativa",
            ordem_servico=self.ordem,
            usuario=self.user,
        )

    def test_fechamento_os_consume_reservas(self):
        response = self.client.get(
            reverse("ordens:toggle_fechamento_os", args=[self.ordem.id]),
            {"confirmar_financeiro": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.status, "convertida")
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto)
        self.assertEqual(saldo.quantidade, 3)

    def test_reabertura_os_devolve_reservas(self):
        self.client.get(
            reverse("ordens:toggle_fechamento_os", args=[self.ordem.id]),
            {"confirmar_financeiro": "1"},
        )
        self.ordem.refresh_from_db()
        self.assertTrue(self.ordem.fechada)

        response = self.client.get(
            reverse("ordens:toggle_fechamento_os", args=[self.ordem.id]),
            {"confirmar_financeiro": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.status, "cancelada")
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto)
        self.assertEqual(saldo.quantidade, 5)


class MensagensPorModeloTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_modelos_msg",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Mensagens",
            documento="39053344705",
            telefone="11999998888",
            email="cliente.msg@exemplo.com",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="notebook",
            marca_equipamento="Marca M",
            modelo_equipamento="Modelo M",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        self.modelo_ambos = ModeloMensagem.objects.create(
            nome="Modelo Teste Ambos",
            tipo="ambos",
            assunto="Assunto OS #{numero_os}",
            corpo="Ola {nome_cliente}, OS #{numero_os}.",
            ativo=True,
        )
        self.modelo_whats = ModeloMensagem.objects.create(
            nome="Modelo Teste Whats",
            tipo="whatsapp",
            assunto="",
            corpo="Whats para {nome_cliente}",
            ativo=True,
        )
        ModeloMensagem.objects.create(
            nome="Modelo Inativo",
            tipo="ambos",
            assunto="Inativo",
            corpo="Nao usar",
            ativo=False,
        )

    def test_detalhes_os_carrega_payload_modelos_ativos_com_variaveis(self):
        response = self.client.get(reverse("ordens:detalhes_ordem", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.context.get("modelos_mensagem_payload", [])
        nomes = {item["nome"] for item in payload}
        self.assertIn("Modelo Teste Ambos", nomes)
        self.assertIn("Modelo Teste Whats", nomes)
        self.assertNotIn("Modelo Inativo", nomes)
        item_ambos = next(item for item in payload if item["nome"] == "Modelo Teste Ambos")
        self.assertIn(self.ordem.numero_os, item_ambos["assunto"])
        self.assertIn(self.cliente.nome, item_ambos["corpo"])

    def test_envio_por_modelo_whatsapp_registra_notificacao_e_historico(self):
        response = self.client.post(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {
                "form_type": "enviar_mensagem_modelo",
                "canal": "whatsapp",
                "modelo_id": str(self.modelo_whats.id),
                "assunto": "",
                "mensagem": "Mensagem Whats customizada",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("wa=", response.url)
        notif = NotificacaoCliente.objects.filter(ordem=self.ordem, canal="whatsapp").latest("id")
        self.assertEqual(notif.mensagem, "Mensagem Whats customizada")
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
            ).filter(
                Q(descricao__icontains="Modelo Teste Whats")
                & Q(descricao__icontains="WHATSAPP")
            ).exists()
        )

    def test_envio_por_modelo_email_exige_assunto(self):
        response = self.client.post(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {
                "form_type": "enviar_mensagem_modelo",
                "canal": "email",
                "modelo_id": str(self.modelo_ambos.id),
                "assunto": "",
                "mensagem": "Mensagem Email sem assunto",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            NotificacaoCliente.objects.filter(
                ordem=self.ordem,
                canal="email",
                mensagem="Mensagem Email sem assunto",
            ).exists()
        )

    def test_envio_por_modelo_evento_orcamento_muda_status_para_pendente_cliente(self):
        self.modelo_whats.evento_chave = "orcamento.pronto"
        self.modelo_whats.save(update_fields=["evento_chave"])

        response = self.client.post(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {
                "form_type": "enviar_mensagem_modelo",
                "canal": "whatsapp",
                "modelo_id": str(self.modelo_whats.id),
                "assunto": "",
                "mensagem": "Orçamento pronto para aprovação",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "pendente_cliente")
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                status="pendente_cliente",
            ).exists()
        )

    def test_envio_por_modelo_evento_pronto_muda_status_para_pronto_contactado(self):
        self.modelo_whats.evento_chave = "equipamento.pronto"
        self.modelo_whats.save(update_fields=["evento_chave"])
        self.ordem.status = "em_andamento"
        self.ordem.save(update_fields=["status"])

        response = self.client.post(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {
                "form_type": "enviar_mensagem_modelo",
                "canal": "whatsapp",
                "modelo_id": str(self.modelo_whats.id),
                "assunto": "",
                "mensagem": "Seu equipamento está pronto para retirada",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "pronto_contactado")
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                status="pronto_contactado",
                descricao__icontains="pronto para retirada",
            ).exists()
        )

    def test_envio_por_modelo_evento_recusado_mantem_status_e_registra_contato(self):
        self.modelo_whats.evento_chave = "equipamento.recusado"
        self.modelo_whats.save(update_fields=["evento_chave"])
        self.ordem.status = "devolucao"
        self.ordem.relatorio_tecnico = "Cliente optou por nao reparar."
        self.ordem.tipo_reparacao = "recusado_tempo"
        self.ordem.save(update_fields=["status", "relatorio_tecnico", "tipo_reparacao"])

        response = self.client.post(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {
                "form_type": "enviar_mensagem_modelo",
                "canal": "whatsapp",
                "modelo_id": str(self.modelo_whats.id),
                "assunto": "",
                "mensagem": "Seu equipamento sera devolvido sem reparo.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "devolucao")
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                status="devolucao",
                descricao__icontains="recusa/devolucao",
            ).exists()
        )


class BuscarOrdensPrefixosTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="busca_prefixos",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Busca Prefixo",
            documento="39053344705",
            telefone="11933334444",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca B",
            modelo_equipamento="Modelo B",
            numero_serie_equipamento="SN-ABC-001",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

    def test_busca_por_sn_retorna_resultado_somente_com_match_completo(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "sn:SN-ABC-001"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        if "redirect" in payload:
            self.assertIn(f"/ordens/{self.ordem.id}/detalhes/", payload["redirect"])
        else:
            self.assertTrue(payload["resultados"])
            self.assertEqual(payload["resultados"][0]["id"], self.ordem.id)

    def test_busca_por_sn_parcial_nao_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "sn:ABC"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resultados"], [])

    def test_busca_por_cpf_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "cpf:390.533.447-05"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        if "redirect" in payload:
            self.assertIn(f"/ordens/{self.ordem.id}/detalhes/", payload["redirect"])
        else:
            self.assertTrue(payload["resultados"])
            self.assertEqual(payload["resultados"][0]["id"], self.ordem.id)

    def test_busca_por_os_exata_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": self.ordem.numero_os})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["resultados"])
        self.assertEqual(payload["resultados"][0]["id"], self.ordem.id)

    def test_busca_sem_prefixo_por_cpf_nao_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "390.533.447-05"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resultados"], [])

    def test_busca_sem_prefixo_por_telefone_nao_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "(11) 93333-4444"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resultados"], [])

    def test_busca_curta_sem_prefixo_nao_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "10"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resultados"], [])


class FluxoCriticoE2ETests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_e2e",
            password="senha-forte-123",
            tipo_usuario="atendente",
            perm_orcamento_editar=True,
            perm_orcamento_aprovar_item=True,
            perm_orcamento_recusar_item=True,
            perm_orcamento_migrar_item=True,
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente E2E",
            documento="39053344705",
            telefone="11998765432",
            email="cliente.e2e@exemplo.com",
            estado="SP",
        )
        self.caixa = Caixa.objects.create(aberto=True, saldo_inicial=Decimal("0.00"))

    def test_e2e_abertura_os_garantia_com_dados_obrigatorios(self):
        response = self.client.post(
            reverse("ordens:nova_ordem_cliente", args=[self.cliente.id]),
            {
                "tipo_equipamento": "celular",
                "marca_catalogo": "__outros__",
                "marca_manual": "Marca Garantia E2E",
                "marca_equipamento": "",
                "modelo_equipamento": "Modelo Garantia",
                "numero_serie_equipamento": "SN-GAR-001",
                "peritagem": "Sem danos externos",
                "tipo_reparo": "Garantia",
                "data_compra": "2026-02-10",
                "numero_nota_fiscal": "NF-E2E-001",
                "defeito": "Nao liga",
                "acessorios": "Carregador original",
                "notas_internas": "Fluxo E2E garantia",
                "confirmar_criacao": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(ordem.tipo_reparo, "Garantia")
        self.assertEqual(str(ordem.data_compra), "2026-02-10")
        self.assertEqual(ordem.numero_nota_fiscal, "NF-E2E-001")
        self.assertIsNone(ordem.tecnico_responsavel)

    def test_abertura_os_sem_confirmacao_digital_nao_envia_whatsapp_automatico(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.usar_confirmacao_assinatura_digital = False
        config.save(update_fields=["usar_confirmacao_assinatura_digital"])

        response = self.client.post(
            reverse("ordens:nova_ordem_cliente", args=[self.cliente.id]),
            {
                "tipo_equipamento": "celular",
                "marca_catalogo": "__outros__",
                "marca_manual": "Marca Sem Link",
                "marca_equipamento": "",
                "modelo_equipamento": "Modelo Sem Link",
                "numero_serie_equipamento": "SN-SEM-LINK-001",
                "peritagem": "Sem avarias",
                "tipo_reparo": "Fora de Garantia",
                "defeito": "Nao liga",
                "acessorios": "Carregador",
                "notas_internas": "Sem confirmacao digital",
                "confirmar_criacao": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(response.url, reverse("ordens:resumo_ordem", args=[ordem.id]))
        self.assertFalse(NotificacaoCliente.objects.filter(ordem=ordem, canal="whatsapp").exists())
        self.assertIsNone(ordem.tecnico_responsavel)

    def test_e2e_orcamento_aprovado_migrado_para_servicos_e_pecas(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_e2e_orc",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca E2E",
            modelo_equipamento="Modelo E2E",
            defeito="Nao carrega",
            tipo_reparo="Fora de Garantia",
            status="pendente_orcamento",
            tecnico_responsavel=tecnico,
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=ordem)
        item_servico = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico de bancada",
            descricao="Ajuste do conector",
            valor_unitario=Decimal("80.00"),
            quantidade=1,
            tipo_item="servico",
            origem="manual",
            status="pendente",
            tecnico_responsavel=tecnico,
        )
        item_peca = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Conector de carga",
            descricao="Peca de reposicao",
            valor_unitario=Decimal("25.00"),
            quantidade=1,
            tipo_item="peca",
            origem="estoque",
            status="pendente",
            tecnico_responsavel=tecnico,
        )

        response_aceitar = self.client.post(
            reverse("orcamentos:aceitar_orcamento", args=[orcamento.id]),
            {"itens_selecionados": [str(item_servico.id), str(item_peca.id)]},
        )
        self.assertEqual(response_aceitar.status_code, 302)
        item_servico.refresh_from_db()
        item_peca.refresh_from_db()
        self.assertEqual(item_servico.status, "aprovado")
        self.assertEqual(item_peca.status, "aprovado")

        response_migrar = self.client.post(
            reverse("orcamentos:migrar_para_servicos", args=[orcamento.id]),
            {"itens_selecionados": [str(item_servico.id), str(item_peca.id)]},
        )
        self.assertEqual(response_migrar.status_code, 302)
        servicos_pecas = ServicoPeca.objects.filter(
            ordem=ordem,
            item_orcamento__in=[item_servico, item_peca],
        )
        self.assertEqual(servicos_pecas.count(), 2)
        self.assertSetEqual(set(servicos_pecas.values_list("tipo", flat=True)), {"servico", "peca"})

    def test_fluxo_critico_completo_os_confirmacao_orcamento_notificacao_fechamento_caixa(self):
        # 1) criar OS
        resp_criar = self.client.post(
            reverse("ordens:nova_ordem_cliente", args=[self.cliente.id]),
            {
                "tipo_equipamento": "celular",
                "marca_catalogo": "__outros__",
                "marca_manual": "Marca E2E",
                "marca_equipamento": "",
                "modelo_equipamento": "Modelo E2E",
                "numero_serie_equipamento": "SN-E2E-001",
                "peritagem": "Sem danos aparentes",
                "tipo_reparo": "Fora de Garantia",
                "defeito": "Nao liga",
                "acessorios": "Carregador",
                "notas_internas": "Nota interna",
                "confirmar_criacao": "1",
            },
        )
        self.assertEqual(resp_criar.status_code, 302)
        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(ordem.status, "diagnosticar")

        # 2) confirmar por link publico
        resp_confirmar = self.client.post(reverse("confirmar_os_publico", kwargs={"token": ordem.token_confirmacao}))
        self.assertEqual(resp_confirmar.status_code, 302)
        ordem.refresh_from_db()
        self.assertTrue(ordem.confirmado)

        # 3) orcar
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=ordem)
        resp_item = self.client.post(
            reverse("orcamentos:adicionar_item", args=[orcamento.id]),
            {
                "ean": "",
                "nome": "Mao de obra",
                "descricao": "Diagnostico e reparo",
                "valor_unitario": "150.00",
                "quantidade": "1",
                "tipo_item": "servico",
            },
        )
        self.assertEqual(resp_item.status_code, 302)
        item = ItemOrcamento.objects.latest("id")
        self.assertEqual(item.origem, "manual")

        # 4) notificar cliente
        resp_notif = self.client.post(
            reverse("ordens:notificar_cliente_ordem", args=[ordem.id, "orcamento"]),
            {"canal": "whatsapp"},
        )
        self.assertEqual(resp_notif.status_code, 302)
        self.assertTrue(
            NotificacaoCliente.objects.filter(ordem=ordem, canal="whatsapp").exists()
        )

        # 5) registrar servico e fechar
        ServicoPeca.objects.create(
            ordem=ordem,
            tipo="servico",
            nome="Reparo placa",
            quantidade=1,
            valor_unitario=Decimal("150.00"),
        )
        ordem.relatorio_tecnico = "Reparo executado com sucesso."
        ordem.tipo_reparacao = "substituicao"
        ordem.save(update_fields=["relatorio_tecnico", "tipo_reparacao"])
        resp_fechar = self.client.get(
            reverse("ordens:toggle_fechamento_os", args=[ordem.id]),
            {"ir_caixa": "1"},
        )
        self.assertEqual(resp_fechar.status_code, 302)
        ordem.refresh_from_db()
        self.assertTrue(ordem.fechada)
        self.assertEqual(ordem.status, "concluida")
        self.assertIn(reverse("caixa:registrar_pagamento"), resp_fechar.url)

        # 6) caixa: registrar pagamento da OS
        resp_pag = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={ordem.id}",
            {"valor": "150.00", "metodo": "pix", "referencia": "E2E-001"},
        )
        self.assertEqual(resp_pag.status_code, 302)
        pagamento = Pagamento.objects.filter(ordem_servico=ordem, referencia="E2E-001").first()
        self.assertIsNotNone(pagamento)
        item = ServicoPeca.objects.filter(ordem=ordem).order_by("id").first()
        self.assertIsNotNone(item)
        self.assertIn(pagamento.numero_talao, item.numeros_taloes)
        self.assertTrue(OrdemTalao.objects.filter(ordem=ordem, numero=pagamento.numero_talao).exists())

    def test_fechamento_migra_itens_aprovados_do_orcamento_para_servicos_pecas(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_migracao_fechamento",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Mig",
            modelo_equipamento="Modelo Mig",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=ordem)
        item_orc = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Troca de conector",
            descricao="Servico aprovado",
            valor_unitario=Decimal("80.00"),
            quantidade=1,
            tipo_item="servico",
            origem="manual",
            status="aprovado",
            tecnico_responsavel=tecnico,
        )
        ordem.relatorio_tecnico = "Relatorio de fechamento com migracao"
        ordem.tipo_reparacao = "substituicao"
        ordem.save(update_fields=["relatorio_tecnico", "tipo_reparacao"])

        response = self.client.get(
            reverse("ordens:toggle_fechamento_os", args=[ordem.id]),
            {"confirmar_financeiro": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ServicoPeca.objects.filter(ordem=ordem, item_orcamento=item_orc).exists())


class OSConfirmadaBloqueioEdicaoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_confirmada",
            password="senha-forte-123",
            tipo_usuario="atendente",
            perm_os_excluir_servico_peca=True,
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Confirmacao",
            documento="39053344705",
            telefone="11977776666",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca C",
            modelo_equipamento="Modelo C",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
            confirmado=True,
        )

    def test_permite_adicao_de_servico_em_os_confirmada(self):
        url = reverse("ordens:detalhes_ordem", args=[self.ordem.id])
        response = self.client.post(
            url,
            {
                "form_type": "servico_peca",
                "tipo": "servico",
                "nome": "Mao de obra",
                "quantidade": "1",
                "valor_unitario": "100.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ServicoPeca.objects.filter(ordem=self.ordem).count(), 1)

    def test_permite_excluir_item_servico_peca(self):
        item = ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Teste excluir",
            quantidade=1,
            valor_unitario=Decimal("90.00"),
        )
        response = self.client.post(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {
                "form_type": "excluir_servico_peca",
                "item_id": str(item.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ServicoPeca.objects.filter(id=item.id).exists())


class PermissoesGranularesOSTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_os_perms",
            password="senha-forte-123",
            tipo_usuario="atendente",
            perm_os_editar_observacoes_internas=False,
            perm_os_editar_local_armazenamento=False,
            perm_os_excluir_servico_peca=False,
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Permissao OS",
            documento="39053344705",
            telefone="11999995555",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca P",
            modelo_equipamento="Modelo P",
            defeito="Teste granular",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

    def test_atualizar_local_permite_usuario_operacional_e_audita(self):
        response = self.client.post(
            reverse("ordens:atualizar_local", args=[self.ordem.id]),
            data='{"local":"Prateleira A"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.local_armazenamento, "Prateleira A")
        self.assertTrue(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                descricao__icontains="Local de armazenamento alterado",
            ).exists()
        )

    def test_atualizar_local_funciona_para_gerente(self):
        self.user.tipo_usuario = "gerente"
        self.user.save(update_fields=["tipo_usuario"])
        response = self.client.post(
            reverse("ordens:atualizar_local", args=[self.ordem.id]),
            data='{"local":"Prateleira A"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.local_armazenamento, "Prateleira A")

    def test_atualizar_observacoes_exige_permissao_granular(self):
        response = self.client.post(
            reverse("ordens:atualizar_observacoes", args=[self.ordem.id]),
            data='{"observacoes":"Nao expor ao cliente"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.notas_internas, "")

    def test_excluir_servico_peca_exige_permissao_granular(self):
        item = ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Teste exclusao",
            quantidade=1,
            valor_unitario=Decimal("50.00"),
        )
        response = self.client.post(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {"form_type": "excluir_servico_peca", "item_id": str(item.id)},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ServicoPeca.objects.filter(id=item.id).exists())

    def test_excluir_servico_peca_funciona_com_permissao(self):
        self.user.perm_os_excluir_servico_peca = True
        self.user.save(update_fields=["perm_os_excluir_servico_peca"])
        item = ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Teste exclusao",
            quantidade=1,
            valor_unitario=Decimal("50.00"),
        )
        response = self.client.post(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {"form_type": "excluir_servico_peca", "item_id": str(item.id)},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ServicoPeca.objects.filter(id=item.id).exists())


class IntegracaoServicoPecaEstoqueTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="estoque_os",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Estoque OS",
            documento="52998224725",
            telefone="11999990000",
            estado="SP",
        )
        self.ponto = PontoOperacional.objects.create(codigo="PO1", nome="Matriz")
        self.ubicacao = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto,
            codigo="A-01",
            descricao="Prateleira A-01",
            ativo=True,
        )
        self.produto = Produto.objects.create(
            nome="Bateria A1",
            tipo_item="peca",
            quantidade=5,
            estoque_minimo=1,
            preco_final=Decimal("80.00"),
            preco=Decimal("80.00"),
            custo_unitario=Decimal("30.00"),
            ponto_operacional=self.ponto,
            ubicacao_padrao=self.ubicacao,
            permite_os=True,
        )
        SaldoEstoquePonto.objects.update_or_create(
            produto=self.produto,
            ponto_operacional=self.ponto,
            defaults={"quantidade": 5},
        )
        SaldoEstoqueUbicacao.objects.update_or_create(
            produto=self.produto,
            ponto_operacional=self.ponto,
            ubicacao=self.ubicacao,
            defaults={"quantidade": 5},
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca E",
            modelo_equipamento="Modelo E",
            defeito="Nao segura carga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
            relatorio_tecnico="Troca de bateria",
            tipo_reparacao="substituicao",
        )

    def test_adiciona_item_os_vinculado_ao_estoque(self):
        response = self.client.post(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {
                "form_type": "servico_peca",
                "produto_estoque_id": str(self.produto.id),
                "tipo": "peca",
                "nome": self.produto.nome,
                "quantidade": "1",
                "valor_unitario": "80.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        item = ServicoPeca.objects.get(ordem=self.ordem)
        self.assertEqual(item.produto_estoque_id, self.produto.id)

    def test_fechamento_consume_estoque_do_item_vinculado(self):
        item = ServicoPeca.objects.create(
            ordem=self.ordem,
            produto_estoque=self.produto,
            tipo="peca",
            nome="Bateria A1",
            quantidade=2,
            valor_unitario=Decimal("80.00"),
        )

        response = self.client.get(
            reverse("ordens:toggle_fechamento_os", args=[self.ordem.id]),
            {"confirmar_financeiro": "1"},
        )
        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto)
        self.assertIsNotNone(item.estoque_consumido_em)
        self.assertEqual(saldo.quantidade, 3)

    def test_reabertura_devolve_estoque_do_item_vinculado(self):
        item = ServicoPeca.objects.create(
            ordem=self.ordem,
            produto_estoque=self.produto,
            tipo="peca",
            nome="Bateria A1",
            quantidade=1,
            valor_unitario=Decimal("80.00"),
        )

        self.client.get(
            reverse("ordens:toggle_fechamento_os", args=[self.ordem.id]),
            {"confirmar_financeiro": "1"},
        )
        response = self.client.get(reverse("ordens:toggle_fechamento_os", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto)
        self.assertIsNone(item.estoque_consumido_em)
        self.assertEqual(saldo.quantidade, 5)


class ConfirmacaoManualResumoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_confirmacao_manual",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Presencial",
            documento="39053344705",
            telefone="11970001111",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca P",
            modelo_equipamento="Modelo P",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

    def test_confirmacao_manual_no_resumo(self):
        response = self.client.post(reverse("ordens:confirmar_manual_resumo", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("ordens:resumo_ordem", args=[self.ordem.id]))

        self.ordem.refresh_from_db()
        self.assertTrue(self.ordem.confirmado)
        self.assertEqual(self.ordem.tipo_confirmacao, "impresso")
        self.assertEqual(self.ordem.confirmado_por_id, self.user.id)
        self.assertIsNotNone(self.ordem.data_confirmacao)
        self.assertTrue(self.ordem.logs_confirmacao.exists())

    def test_confirmacao_manual_ja_confirmada_nao_duplica_log(self):
        self.ordem.confirmado = True
        self.ordem.tipo_confirmacao = "impresso"
        self.ordem.data_confirmacao = timezone.now()
        self.ordem.confirmado_por = self.user
        self.ordem.save(update_fields=["confirmado", "tipo_confirmacao", "data_confirmacao", "confirmado_por"])
        logs_antes = self.ordem.logs_confirmacao.count()

        response = self.client.post(reverse("ordens:confirmar_manual_resumo", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.logs_confirmacao.count(), logs_antes)


class ConfirmacaoPublicaTemplateTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(
            nome="Cliente Confirmacao Publica",
            documento="11144477735",
            telefone="11911112222",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Publica",
            modelo_equipamento="Modelo Publico",
            numero_serie_equipamento="SERIE-PUBLICA-1",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        config = ConfiguracaoSistema.get_configuracao()
        config.termos_ordem_servico = "Termo publico de teste da OS."
        config.condicoes_orcamento = "Condicao geral publica para o cliente."
        config.save(update_fields=["termos_ordem_servico", "condicoes_orcamento"])

    def test_confirmacao_publica_exibe_termos_sem_layout_interno(self):
        response = self.client.get(reverse("confirmar_os_publico", kwargs={"token": self.ordem.token_confirmacao}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirma\u00e7\u00e3o da Ordem de Servi\u00e7o")
        self.assertContains(response, "Cliente")
        self.assertContains(response, "Equipamento")
        self.assertContains(response, "Atendimento")
        self.assertContains(response, "Atendente")
        self.assertContains(response, "T&eacute;cnico respons&aacute;vel")
        self.assertContains(response, "Termo publico de teste da OS.")
        self.assertContains(response, "Condicao geral publica para o cliente.")
        self.assertNotContains(response, "main-sidebar")


class DetalhesOrdemCabecalhoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="gerente_detalhes_os",
            password="senha-forte-123",
            tipo_usuario="gerente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Detalhes",
            documento="39053344705",
            telefone="11970000000",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca D",
            modelo_equipamento="Modelo D",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        self.ordem.data_abertura = timezone.now() - timedelta(days=3)
        self.ordem.save(update_fields=["data_abertura"])
        LogOS.objects.create(
            ordem_servico=self.ordem,
            tipo_evento="alteracao_status",
            descricao="Teste de log operacional.",
            usuario_responsavel=self.user,
        )

    def test_detalhes_exibe_botao_de_logs_e_dias_em_aberto_sem_tab_logs(self):
        response = self.client.get(reverse("ordens:detalhes_ordem", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dias aberta:")
        self.assertContains(response, 'data-target="#modalLogsOS"', html=False)
        self.assertNotContains(response, "?tab=logs")

    def test_detalhes_exibe_status_operacional_padronizado(self):
        self.ordem.status = "em_andamento"
        self.ordem.save(update_fields=["status"])

        response = self.client.get(reverse("ordens:detalhes_ordem", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bancada")

    def test_detalhes_exibe_aba_relatorio_tecnico(self):
        response = self.client.get(reverse("ordens:detalhes_ordem", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Relatório Técnico")
        self.assertContains(response, 'id="relatorio_tecnico"', html=False)


    def test_detalhes_exibe_aba_arquivos_mesmo_sem_anexos(self):
        response = self.client.get(reverse("ordens:detalhes_ordem", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        abas = response.context["tabs"]
        self.assertIn("arquivos", [aba["id"] for aba in abas])
        self.assertContains(response, 'id="arquivos"', html=False)

    def test_detalhes_exibe_etapa_fluxo_para_os_fechada_sem_pagamento(self):
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Mao de obra",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
        )
        self.ordem.fechada = True
        self.ordem.status = "concluida"
        self.ordem.save(update_fields=["fechada", "status"])

        response = self.client.get(reverse("ordens:detalhes_ordem", args=[self.ordem.id]) + "?tab=servicos")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Concluída aguardando pagamento")
        self.assertContains(response, "Ir para o Caixa")

    def test_detalhes_exibe_painel_operacional_do_orcamento(self):
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico painel",
            descricao="Teste",
            valor_unitario=Decimal("90.00"),
            quantidade=1,
            tipo_item="servico",
            origem="manual",
            status="pendente",
        )

        response = self.client.get(reverse("ordens:detalhes_ordem", args=[self.ordem.id]) + "?tab=orcamentos")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Painel operacional")
        self.assertContains(response, "Enviar ao cliente no WhatsApp")
        self.assertContains(response, "Imprimir")


class OrdemArquivoUploadTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_arquivos_os",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Arquivos",
            documento="39053344705",
            telefone="11990000000",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca A",
            modelo_equipamento="Modelo A",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

    @staticmethod
    def _imagem_upload(nome="foto.jpg", tamanho=(2600, 1800), color=(30, 90, 160)):
        imagem = Image.new("RGB", tamanho, color)
        buffer = BytesIO()
        imagem.save(buffer, format="JPEG", quality=96)
        return SimpleUploadedFile(nome, buffer.getvalue(), content_type="image/jpeg")

    def test_upload_arquivos_limita_total_de_fotos(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                for idx in range(5):
                    OrdemArquivo.objects.create(
                        ordem=self.ordem,
                        arquivo=self._imagem_upload(f"existente-{idx}.jpg", tamanho=(800, 600)),
                        enviado_por=self.user,
                    )

                response = self.client.post(
                    reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
                    {
                        "form_type": "arquivo",
                        "descricao": "Fotos extras",
                    },
                    format="multipart",
                    files={
                        "arquivos": [
                            self._imagem_upload("nova-1.jpg"),
                            self._imagem_upload("nova-2.jpg"),
                        ]
                    },
                )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(OrdemArquivo.objects.filter(ordem=self.ordem).count(), 5)

    def test_upload_arquivos_otimiza_imagem_grande(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                response = self.client.post(
                    reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
                    {
                        "form_type": "arquivo",
                        "descricao": "Imagem otimizada",
                        "arquivos": [self._imagem_upload("grande.jpg", tamanho=(3200, 2400))],
                    },
                )

                self.assertEqual(response.status_code, 302)
                anexo = OrdemArquivo.objects.get(ordem=self.ordem)
                with Image.open(anexo.arquivo.path) as imagem_salva:
                    self.assertLessEqual(imagem_salva.width, 1800)
                    self.assertLessEqual(imagem_salva.height, 1800)


class ImpressaoLogoEmpresaTests(TestCase):
    def test_logo_pdf_configurado_da_empresa_tem_prioridade_no_pdf(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                empresa = Empresa.objects.create(nome="Empresa Logo")
                empresa.logo_pdf = SimpleUploadedFile("logo-pdf.png", b"logo-configurado", content_type="image/png")
                empresa.save(update_fields=["logo_pdf"])
                style = getSampleStyleSheet()["Normal"]

                with patch("core.pdf_utils.Image", side_effect=lambda path, width, height: path) as image_mock:
                    logo = logo_or_paragraph(empresa, style, "<b>LOGO</b>", 10, 10)

                self.assertEqual(logo, empresa.logo_pdf.path)
                self.assertEqual(image_mock.call_args.args[0], empresa.logo_pdf.path)

    def test_pdf_sem_logo_exibe_nome_da_empresa(self):
        empresa = Empresa.objects.create(nome="Empresa sem Logo PDF")
        style = getSampleStyleSheet()["Normal"]

        logo = logo_or_paragraph(empresa, style, "<b>LOGO</b>", 10, 10)

        self.assertEqual(logo.text, "<b>Empresa sem Logo PDF</b>")


class ImpressaoPdfHeadersTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.usuario = user_model.objects.create_user(
            username="atendente_pdf",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.usuario)
        self.cliente = Cliente.objects.create(
            nome="Cliente PDF",
            documento="39053344705",
            telefone="11990001111",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca PDF",
            modelo_equipamento="Modelo PDF",
            defeito="Teste de impressao",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

    @staticmethod
    def _pdf_page_counts(pdf_bytes):
        return [int(value) for value in re.findall(br"/Count\s+(\d+)", pdf_bytes)]

    def test_imprimir_ordem_servico_retorna_pdf_sameorigin(self):
        response = self.client.get(reverse("ordens:imprimir_ordem_servico", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/pdf"))
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertEqual(response.get("X-Frame-Options"), "SAMEORIGIN")

    def test_imprimir_ordem_servico_preview_remove_x_frame_options(self):
        response = self.client.get(
            reverse("ordens:imprimir_ordem_servico", args=[self.ordem.id]),
            {"_preview": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIsNone(response.get("X-Frame-Options"))

    def test_imprimir_ordem_servico_exibe_paginacao_total(self):
        with patch("ordens.view_modules.impressao.make_numbered_canvas", wraps=real_make_numbered_canvas) as factory_mock:
            response = self.client.get(reverse("ordens:imprimir_ordem_servico", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(factory_mock.called)
        contagens = self._pdf_page_counts(response.content)
        self.assertTrue(contagens)
        self.assertGreaterEqual(max(contagens), 1)

    def test_imprimir_ordem_servico_preview_aplica_layout_documentos(self):
        observado = {}

        def _theme_spy(config):
            observado["preset"] = config.layout_documentos_preset
            observado["cor"] = config.layout_documentos_cor
            return real_get_document_theme(config)

        with patch("ordens.view_modules.impressao.get_document_theme", side_effect=_theme_spy):
            response = self.client.get(
                reverse("ordens:imprimir_ordem_servico", args=[self.ordem.id]),
                {"_preview": "1", "layout_documentos_preset": "executivo", "layout_documentos_cor": "pb"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(observado.get("preset"), "executivo")
        self.assertEqual(observado.get("cor"), "pb")

    def test_imprimir_ordem_servico_confirmacao_usa_data_confirmacao_e_mostra_abertura(self):
        data_abertura = timezone.now() - timedelta(days=3, hours=2)
        data_confirmacao = timezone.now() - timedelta(days=1, hours=1)
        OrdemServico.objects.filter(pk=self.ordem.pk).update(
            data_abertura=data_abertura,
            confirmado=True,
            tipo_confirmacao="link",
            data_confirmacao=data_confirmacao,
        )
        self.ordem.refresh_from_db()

        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        abertura_fmt = data_abertura.strftime("%d/%m/%Y %H:%M")
        confirmacao_fmt = data_confirmacao.strftime("%d/%m/%Y %H:%M")
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Data de abertura", texto_unificado)
        self.assertIn(abertura_fmt, texto_unificado)
        self.assertIn(f"em {confirmacao_fmt}", texto_unificado)
        self.assertNotIn(f"em {abertura_fmt}", texto_unificado)

    def test_imprimir_ordem_servico_inclui_peritagem(self):
        OrdemServico.objects.filter(pk=self.ordem.pk).update(peritagem="Tela com trinca no canto superior.")
        self.ordem.refresh_from_db()
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Peritagem", texto_unificado)
        self.assertIn("Tela com trinca no canto superior.", texto_unificado)

    def test_imprimir_ordem_servico_inclui_acessorios_quando_ativo(self):
        OrdemServico.objects.filter(pk=self.ordem.pk).update(acessorios="Carregador, cabo USB e capa protetora.")
        self.ordem.refresh_from_db()
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Acessórios", texto_unificado)
        self.assertIn("Carregador, cabo USB e capa protetora.", texto_unificado)

    def test_imprimir_ordem_servico_respeita_campos_ocultos_configurados(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_os_exibir_peritagem = False
        config.pdf_os_exibir_acessorios = False
        config.pdf_os_exibir_termos = False
        config.pdf_os_exibir_assinaturas = False
        config.save(update_fields=["pdf_os_exibir_peritagem", "pdf_os_exibir_acessorios", "pdf_os_exibir_termos", "pdf_os_exibir_assinaturas"])
        OrdemServico.objects.filter(pk=self.ordem.pk).update(
            peritagem="Nao deveria aparecer no PDF.",
            acessorios="Acessorio oculto no PDF.",
        )
        self.ordem.refresh_from_db()
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertNotIn("Peritagem", texto_unificado)
        self.assertNotIn("Nao deveria aparecer no PDF.", texto_unificado)
        self.assertNotIn("Acessórios", texto_unificado)
        self.assertNotIn("Acessorio oculto no PDF.", texto_unificado)
        self.assertNotIn("Termos e Condicoes", texto_unificado)
        self.assertNotIn("Assinatura do Cliente:", texto_unificado)

    def test_imprimir_ordem_servico_impressao_preview_remove_x_frame_options(self):
        response = self.client.get(
            reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id]),
            {"_preview": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIsNone(response.get("X-Frame-Options"))

    def test_imprimir_ordem_servico_impressao_preserva_termos_longos_em_anexo(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.termos_ordem_servico = "MARCADOR_INICIO " + ("termo contratual muito longo " * 300) + "MARCADOR_FIM."
        config.save(update_fields=["termos_ordem_servico"])
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        counts = self._pdf_page_counts(response.content)
        self.assertTrue(counts)
        self.assertGreaterEqual(max(counts), 3)
        texto_unificado = "\n".join(textos_pdf)
        self.assertGreaterEqual(texto_unificado.count("MARCADOR_INICIO"), 2)
        self.assertGreaterEqual(texto_unificado.count("MARCADOR_FIM"), 2)

    def test_imprimir_ordem_servico_impressao_inclui_peritagem(self):
        OrdemServico.objects.filter(pk=self.ordem.pk).update(peritagem="Carcaca com marcas e tampa solta.")
        self.ordem.refresh_from_db()
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Peritagem", texto_unificado)
        self.assertIn("Carcaca com marcas e tampa solta.", texto_unificado)

    def test_imprimir_ordem_servico_impressao_inclui_acessorios_quando_ativo(self):
        OrdemServico.objects.filter(pk=self.ordem.pk).update(acessorios="Fonte original e adaptador.")
        self.ordem.refresh_from_db()
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Acessórios", texto_unificado)
        self.assertIn("Fonte original e adaptador.", texto_unificado)

    def test_imprimir_ordem_servico_impressao_inclui_origem_e_vinculo_garantia_quando_ativos(self):
        origem = OrdemServico.objects.create(
            cliente=self.ordem.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Origem",
            modelo_equipamento="Modelo Base",
            defeito="Base anterior",
            tipo_reparo="Fora de Garantia",
            status="concluida",
        )
        Cliente.objects.filter(pk=self.ordem.cliente_id).update(origem_cliente="google")
        OrdemServico.objects.filter(pk=self.ordem.pk).update(
            ordem_origem_garantia=origem,
            garantia_classificacao_retorno="garantia_mao_obra",
            manutencao_preventiva_meses=6,
        )
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_os_exibir_origem_cliente = True
        config.pdf_os_exibir_os_origem_garantia = True
        config.pdf_os_exibir_classificacao_retorno = True
        config.pdf_os_exibir_manutencao_preventiva = True
        config.save(
            update_fields=[
                "pdf_os_exibir_origem_cliente",
                "pdf_os_exibir_os_origem_garantia",
                "pdf_os_exibir_classificacao_retorno",
                "pdf_os_exibir_manutencao_preventiva",
            ]
        )
        self.ordem.refresh_from_db()
        self.ordem.cliente.refresh_from_db()
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Origem", texto_unificado)
        self.assertIn("Google", texto_unificado)
        self.assertIn("OS Original Garantia", texto_unificado)
        self.assertIn(origem.numero_os, texto_unificado)
        self.assertIn("Classificação Retorno", texto_unificado)
        self.assertIn("Garantia de mão de obra", texto_unificado)
        self.assertIn("Manutenção Preventiva", texto_unificado)
        self.assertIn("6 meses", texto_unificado)

    def test_imprimir_ordem_servico_impressao_cabecalho_sem_mojibake_e_com_tipo_destacado(self):
        Empresa.objects.update_or_create(
            pk=1,
            defaults={
                "nome": "ABTECH PECAS E SERVICOS",
                "cnpj": "67.966.268/0001-53",
                "endereco": "Avenida Goias, 4067, Qd. 25, Lt. 04, Sala 01",
                "telefone": "62999999999",
            },
        )
        OrdemServico.objects.filter(pk=self.ordem.pk).update(tipo_reparo="Fora de Garantia")
        self.ordem.refresh_from_db()
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("ORDEM DE SERVIÇO Nº", texto_unificado)
        self.assertIn("TIPO DA OS", texto_unificado)
        self.assertIn("Fora de Garantia", texto_unificado)
        self.assertNotIn("SERVIÃ", texto_unificado)
        self.assertNotIn("NÂº", texto_unificado)

    def test_imprimir_ordem_servico_impressao_verso_termos_tem_assinatura_do_cliente(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_os_exibir_termos = True
        config.pdf_os_exibir_assinaturas = True
        config.termos_ordem_servico = "Primeira regra. Segunda regra. Terceira regra."
        config.save(update_fields=["pdf_os_exibir_termos", "pdf_os_exibir_assinaturas", "termos_ordem_servico"])
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Declaro que li, compreendi e concordo com os termos e condições acima", texto_unificado)
        self.assertEqual(texto_unificado.count("Assinatura do cliente na abertura"), 2)
        self.assertEqual(texto_unificado.count("Assinatura do cliente na entrega"), 2)
        self.assertNotIn("Atendente:", texto_unificado)
        self.assertIn("Primeira regra.", texto_unificado)

    def test_verso_equilibrado_identifica_vias_e_formata_subtitulos(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_os_exibir_termos = True
        config.pdf_os_exibir_assinaturas = True
        config.layout_os_verso_modelo = "equilibrado"
        config.layout_os_verso_exibir_identificacao = True
        config.termos_ordem_servico_versao = "1.2 - 08/2026"
        config.termos_ordem_servico = (
            "**CONDIÇÕES GERAIS** O prazo informado é estimado. "
            "O cliente autoriza a abertura do equipamento. "
            "**GARANTIA** A garantia limita-se ao serviço executado."
        )
        config.save(
            update_fields=[
                "pdf_os_exibir_termos",
                "pdf_os_exibir_assinaturas",
                "layout_os_verso_modelo",
                "layout_os_verso_exibir_identificacao",
                "termos_ordem_servico_versao",
                "termos_ordem_servico",
            ]
        )
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(
                reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id])
            )

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertGreaterEqual(texto_unificado.count(f"<b>Nº {self.ordem.numero_os}</b>"), 2)
        self.assertGreaterEqual(texto_unificado.count("<b>Cliente:</b>"), 2)
        self.assertGreaterEqual(texto_unificado.count("<b>Termos:</b> 1.2 - 08/2026"), 2)
        self.assertGreaterEqual(texto_unificado.count("<b>CONDIÇÕES GERAIS:</b>"), 2)
        self.assertGreaterEqual(texto_unificado.count("<b>GARANTIA:</b>"), 2)
        self.assertNotIn("**CONDIÇÕES GERAIS**", texto_unificado)
        self.assertEqual(max(self._pdf_page_counts(response.content)), 2)

    def test_verso_equilibrado_pode_ocultar_identificacao_por_empresa(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.layout_os_verso_modelo = "equilibrado"
        config.layout_os_verso_exibir_identificacao = False
        config.termos_ordem_servico_versao = "VERSAO_INTERNA_2026"
        config.termos_ordem_servico = "Regra curta para validação."
        config.save(
            update_fields=[
                "layout_os_verso_modelo",
                "layout_os_verso_exibir_identificacao",
                "termos_ordem_servico_versao",
                "termos_ordem_servico",
            ]
        )
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(
                reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id])
            )

        self.assertEqual(response.status_code, 200)
        textos_meta = [texto for texto in textos_pdf if "VERSAO_INTERNA_2026" in texto]
        self.assertEqual(len(textos_meta), 2)
        self.assertTrue(all("<b>Cliente:</b>" not in texto for texto in textos_meta))

    def test_imprimir_relatorio_tecnico_resumido_oculta_valores_e_assinaturas_do_cliente(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_relatorio_modo_resumido = True
        config.save(update_fields=["pdf_relatorio_modo_resumido"])
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="peca",
            nome="Display frontal",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
        )
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Display frontal", texto_unificado)
        self.assertIn("Peças utilizadas e serviços realizados", texto_unificado)
        self.assertNotIn("R$ 120,00", texto_unificado)
        self.assertNotIn("Assinaturas do Cliente", texto_unificado)

    def test_imprimir_relatorio_tecnico_preserva_quebras_de_linha(self):
        self.ordem.relatorio_tecnico = "Primeira etapa concluída.\nSegunda etapa testada.\\nTerceira etapa aprovada."
        self.ordem.save(update_fields=["relatorio_tecnico"])
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(
                reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id])
            )

        self.assertEqual(response.status_code, 200)
        texto_relatorio = next(
            texto for texto in textos_pdf if "Primeira etapa concluída" in texto
        )
        self.assertEqual(texto_relatorio.count("<br/>"), 2)
        self.assertIn("Segunda etapa testada.<br/>Terceira etapa aprovada.", texto_relatorio)

    def test_relatorio_com_avaliacao_google_e_opcional(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.google_avaliacao_url = "https://example.com/avaliar-no-google"
        config.save(update_fields=["google_avaliacao_url"])

        textos_normal = []
        textos_avaliacao = []

        def _spy_normal(texto, *args, **kwargs):
            textos_normal.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        def _spy_avaliacao(texto, *args, **kwargs):
            textos_avaliacao.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_spy_normal):
            response_normal = self.client.get(
                reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id])
            )
        with patch(
            "ordens.view_modules.avaliacao_google_pdf.Paragraph",
            side_effect=_spy_avaliacao,
        ):
            response_avaliacao = self.client.get(
                reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
                {"avaliacao": "1"},
            )

        self.assertEqual(response_normal.status_code, 200)
        self.assertEqual(response_avaliacao.status_code, 200)
        self.assertNotIn("avalie no Google", "\n".join(textos_normal))
        texto_avaliacao = "\n".join(textos_avaliacao)
        self.assertIn("Obrigado por confiar", texto_avaliacao)
        self.assertIn("Sua opinião é muito importante para nós", texto_avaliacao)
        self.assertIn("deixe sua avaliação no", texto_avaliacao)

    def test_relatorio_profissional_coexiste_com_modelo_classico(self):
        self.ordem.relatorio_tecnico = (
            "Conector substituído.\nLimpeza técnica e testes concluídos."
        )
        self.ordem.save(update_fields=["relatorio_tecnico"])
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="peca",
            nome="Conector de alimentação",
            descricao="Componente substituído durante o reparo",
            quantidade=1,
            valor_unitario=Decimal("35.00"),
        )
        textos_profissional = []

        def _spy_profissional(texto, *args, **kwargs):
            textos_profissional.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        resposta_classica = self.client.get(
            reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id])
        )
        with patch(
            "ordens.view_modules.relatorio_profissional.Paragraph",
            side_effect=_spy_profissional,
        ):
            resposta_profissional = self.client.get(
                reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
                {"modelo": "profissional"},
            )

        self.assertEqual(resposta_classica.status_code, 200)
        self.assertEqual(resposta_profissional.status_code, 200)
        self.assertTrue(resposta_classica.content.startswith(b"%PDF"))
        self.assertTrue(resposta_profissional.content.startswith(b"%PDF"))
        self.assertNotEqual(resposta_classica.content, resposta_profissional.content)
        self.assertIn(
            "relatorio_tecnico_profissional_",
            resposta_profissional["Content-Disposition"],
        )
        texto_unificado = "\n".join(textos_profissional)
        self.assertIn("RELATÓRIO TÉCNICO", texto_unificado)
        self.assertIn("Conclusão técnica", texto_unificado)
        self.assertIn("Conector substituído.<br/>Limpeza técnica", texto_unificado)
        self.assertIn("Conector de alimentação", texto_unificado)
        self.assertNotIn("GOSTOU DO ATENDIMENTO?", texto_unificado)
        self.assertNotIn("STATUS", textos_profissional)
        self.assertNotIn("TÉCNICO", textos_profissional)
        self.assertNotIn("CONTATO", textos_profissional)

    def test_relatorio_profissional_tem_avaliacao_google_opcional(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.google_avaliacao_url = "https://example.com/avaliar-no-google"
        config.save(update_fields=["google_avaliacao_url"])
        textos_profissional = []

        def _spy_profissional(texto, *args, **kwargs):
            textos_profissional.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch(
            "ordens.view_modules.avaliacao_google_pdf.Paragraph",
            side_effect=_spy_profissional,
        ):
            resposta = self.client.get(
                reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
                {"modelo": "profissional", "avaliacao": "1"},
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.content.startswith(b"%PDF"))
        texto_unificado = "\n".join(textos_profissional)
        self.assertIn("Obrigado por confiar", texto_unificado)
        self.assertIn("Sua opinião é muito importante para nós", texto_unificado)
        self.assertIn("ESCANEIE O QR CODE", texto_unificado)

    def test_relatorio_profissional_longo_pagina_sem_erro(self):
        ServicoPeca.objects.bulk_create(
            [
                ServicoPeca(
                    ordem=self.ordem,
                    tipo="servico" if indice % 2 == 0 else "peca",
                    nome=f"Item técnico {indice:03d}",
                    descricao="Descrição de teste para validação da quebra de página.",
                    quantidade=1,
                    valor_unitario=Decimal("15.00"),
                )
                for indice in range(1, 90)
            ]
        )
        self.ordem.relatorio_tecnico = "Procedimento técnico validado. " * 700
        self.ordem.save(update_fields=["relatorio_tecnico"])

        resposta = self.client.get(
            reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
            {"modelo": "profissional"},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.content.startswith(b"%PDF"))
        self.assertTrue(any(total >= 2 for total in self._pdf_page_counts(resposta.content)))

    def test_relatorio_direto_coexiste_com_demais_modelos(self):
        self.ordem.relatorio_tecnico = "Substituição concluída.\nTestes finais aprovados."
        self.ordem.peritagem = "Gabinete com sinais leves de uso."
        self.ordem.save(update_fields=["relatorio_tecnico", "peritagem"])
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Revisão técnica",
            descricao="Limpeza e testes de funcionamento",
            quantidade=1,
            valor_unitario=Decimal("80.00"),
        )
        textos = []

        def _spy(texto, *args, **kwargs):
            textos.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.relatorio_direto.Paragraph", side_effect=_spy):
            resposta = self.client.get(
                reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
                {"modelo": "direto"},
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.content.startswith(b"%PDF"))
        self.assertIn("relatorio_tecnico_direto_", resposta["Content-Disposition"])
        texto_unificado = "\n".join(textos)
        self.assertIn("RELATÓRIO TÉCNICO", texto_unificado)
        self.assertIn("Dados do equipamento", texto_unificado)
        self.assertIn("Defeito reclamado", texto_unificado)
        self.assertIn("Peritagem", texto_unificado)
        self.assertIn("Resposta técnica", texto_unificado)
        self.assertIn("Revisão técnica", texto_unificado)
        self.assertNotIn("GOSTOU DO ATENDIMENTO?", texto_unificado)

    def test_relatorio_direto_tem_versao_google(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.google_avaliacao_url = "https://example.com/avaliar-no-google"
        config.save(update_fields=["google_avaliacao_url"])
        textos = []

        def _spy(texto, *args, **kwargs):
            textos.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.avaliacao_google_pdf.Paragraph", side_effect=_spy):
            resposta = self.client.get(
                reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
                {"modelo": "direto", "avaliacao": "1"},
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Sua opinião é muito importante para nós", "\n".join(textos))

    def test_relatorio_direto_longo_pagina_sem_erro(self):
        ServicoPeca.objects.bulk_create(
            [
                ServicoPeca(
                    ordem=self.ordem,
                    tipo="servico" if indice % 2 == 0 else "peca",
                    nome=f"Item direto {indice:03d}",
                    descricao="Descrição extensa para validação de paginação.",
                    quantidade=1,
                    valor_unitario=Decimal("12.00"),
                )
                for indice in range(1, 90)
            ]
        )
        self.ordem.relatorio_tecnico = "Procedimento técnico documentado. " * 700
        self.ordem.save(update_fields=["relatorio_tecnico"])

        resposta = self.client.get(
            reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
            {"modelo": "direto"},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.content.startswith(b"%PDF"))
        self.assertTrue(any(total >= 2 for total in self._pdf_page_counts(resposta.content)))

    def test_menu_oferece_rt_com_avaliacao_somente_quando_link_configurado(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.google_avaliacao_url = ""
        config.save(update_fields=["google_avaliacao_url"])

        resposta_sem_link = self.client.get(self.ordem.get_absolute_url())
        self.assertEqual(resposta_sem_link.status_code, 200)
        self.assertNotContains(resposta_sem_link, "Relatório Técnico + avaliação Google")

        config.google_avaliacao_url = "https://example.com/avaliar-no-google"
        config.save(update_fields=["google_avaliacao_url"])
        resposta_com_link = self.client.get(self.ordem.get_absolute_url())

        self.assertEqual(resposta_com_link.status_code, 200)
        self.assertContains(resposta_com_link, "Relatório Técnico + avaliação Google")
        self.assertContains(resposta_com_link, "?avaliacao=1")

    def test_menu_exibe_apenas_modelo_configurado_e_sua_versao_google(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.google_avaliacao_url = "https://example.com/avaliar-no-google"
        config.pdf_relatorio_modelo = "direto"
        config.save(update_fields=["google_avaliacao_url", "pdf_relatorio_modelo"])

        resposta = self.client.get(self.ordem.get_absolute_url())

        self.assertEqual(resposta.status_code, 200)
        self.assertRegex(
            resposta.content.decode(),
            r'href="[^"]+/imprimir_relatorio/\d+/"[^>]*>\s*Relatório Técnico\s*</a>',
        )
        self.assertContains(resposta, "Relatório Técnico + avaliação Google")
        self.assertContains(resposta, "Relatório técnico · Direto")
        self.assertNotContains(resposta, "modelo=profissional")
        self.assertNotContains(resposta, "modelo=direto")

    def test_relatorio_sem_parametro_usa_modelo_definido_na_configuracao(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_relatorio_modelo = "direto"
        config.save(update_fields=["pdf_relatorio_modelo"])

        resposta = self.client.get(
            reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id])
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("relatorio_tecnico_direto_", resposta["Content-Disposition"])

    def test_preview_relatorio_aplica_modelo_selecionado_antes_de_salvar(self):
        resposta = self.client.get(
            reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
            {"_preview": "1", "pdf_relatorio_modelo": "profissional"},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertIn(
            "relatorio_tecnico_profissional_",
            resposta["Content-Disposition"],
        )

    def test_relatorio_usa_modelo_configurado_na_empresa_da_os(self):
        empresa = Empresa.objects.create(nome="Empresa do RT")
        self.ordem.empresa = empresa
        self.ordem.save(update_fields=["empresa"])
        config_global = ConfiguracaoSistema.get_configuracao()
        config_global.pdf_relatorio_modelo = "classico"
        config_global.save(update_fields=["pdf_relatorio_modelo"])
        config_empresa = ConfiguracaoSistema.get_configuracao(empresa=empresa)
        config_empresa.pdf_relatorio_modelo = "direto"
        config_empresa.save(update_fields=["pdf_relatorio_modelo"])

        resposta = self.client.get(
            reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id])
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("relatorio_tecnico_direto_", resposta["Content-Disposition"])

    def test_relatorios_ocultam_assinatura_tecnico_quando_desativada(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_relatorio_exibir_assinatura_tecnico = False
        config.save(update_fields=["pdf_relatorio_exibir_assinatura_tecnico"])
        modelos = (
            ("classico", "ordens.view_modules.impressao.Paragraph"),
            ("profissional", "ordens.view_modules.relatorio_profissional.Paragraph"),
            ("direto", "ordens.view_modules.relatorio_direto.Paragraph"),
        )

        for modelo, paragraph_path in modelos:
            with self.subTest(modelo=modelo):
                textos = []

                def _spy(texto, *args, **kwargs):
                    textos.append(str(texto))
                    return reportlab_paragraph(texto, *args, **kwargs)

                params = {} if modelo == "classico" else {"modelo": modelo}
                with patch(paragraph_path, side_effect=_spy):
                    resposta = self.client.get(
                        reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
                        params,
                    )

                self.assertEqual(resposta.status_code, 200)
                texto_unificado = "\n".join(textos)
                self.assertNotIn("Assinatura do Técnico", texto_unificado)
                self.assertNotIn("Documento emitido em", texto_unificado)
                self.assertNotIn("________________________________", texto_unificado)

    def test_relatorio_sem_assinatura_mantem_avaliacao_google(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_relatorio_exibir_assinatura_tecnico = False
        config.google_avaliacao_url = "https://example.com/avaliar-no-google"
        config.save(
            update_fields=[
                "pdf_relatorio_exibir_assinatura_tecnico",
                "google_avaliacao_url",
            ]
        )
        textos = []

        def _spy(texto, *args, **kwargs):
            textos.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.avaliacao_google_pdf.Paragraph", side_effect=_spy):
            resposta = self.client.get(
                reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
                {"modelo": "direto", "avaliacao": "1"},
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Sua opinião é muito importante para nós", "\n".join(textos))

    def test_imprimir_ordem_servico_impressao_reserva_faixa_para_etiqueta(self):
        frames = []

        class FrameSpy(Frame):
            def __init__(self, x1, y1, width, height, *args, **kwargs):
                frames.append({"id": kwargs.get("id"), "y1": y1, "height": height})
                super().__init__(x1, y1, width, height, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Frame", FrameSpy):
            response = self.client.get(reverse("ordens:imprimir_ordem_servico_impressao", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        frame_top = next(frame for frame in frames if frame["id"] == "top")
        frame_bottom = next(frame for frame in frames if frame["id"] == "bottom")
        self.assertGreater(frame_top["y1"], frame_bottom["y1"] + frame_bottom["height"])
        page_height = A4[1]
        margin = 1.2 * cm
        half_height = (page_height - 2 * margin) / 2
        cut_y = margin + half_height
        label_half_height = 0.45 * cm
        min_clearance = 0.30 * cm
        self.assertGreaterEqual(frame_top["y1"], cut_y + label_half_height + min_clearance)
        self.assertGreaterEqual(cut_y - label_half_height - (frame_bottom["y1"] + frame_bottom["height"]), min_clearance)

    def test_imprimir_relatorio_tecnico_longo_gera_multiplas_paginas_com_total(self):
        ServicoPeca.objects.bulk_create(
            [
                ServicoPeca(
                    ordem=self.ordem,
                    tipo="servico" if i % 2 == 0 else "peca",
                    nome=f"Item {i:03d}",
                    descricao="Linha de teste para quebra de pagina",
                    quantidade=1,
                    valor_unitario=Decimal("15.00"),
                )
                for i in range(1, 140)
            ]
        )
        self.ordem.relatorio_tecnico = "Relatorio extenso " * 800
        self.ordem.save(update_fields=["relatorio_tecnico"])

        with patch("ordens.view_modules.impressao.make_numbered_canvas", wraps=real_make_numbered_canvas) as factory_mock:
            response = self.client.get(reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertTrue(factory_mock.called)
        self.assertTrue(any(total >= 2 for total in self._pdf_page_counts(response.content)))

    def test_imprimir_relatorio_tecnico_preview_remove_x_frame_options(self):
        response = self.client.get(
            reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]),
            {"_preview": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIsNone(response.get("X-Frame-Options"))

    def test_imprimir_relatorio_tecnico_respeita_campos_ocultos_configurados(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.pdf_relatorio_exibir_documento_cliente = False
        config.pdf_relatorio_exibir_email_cliente = False
        config.pdf_relatorio_exibir_defeito = False
        config.pdf_relatorio_exibir_numero_serie = False
        config.pdf_relatorio_exibir_peritagem = False
        config.pdf_relatorio_exibir_acessorios = False
        config.pdf_relatorio_exibir_tipo_reparo = False
        config.pdf_relatorio_exibir_servicos_pecas = False
        config.save(
            update_fields=[
                "pdf_relatorio_exibir_documento_cliente",
                "pdf_relatorio_exibir_email_cliente",
                "pdf_relatorio_exibir_defeito",
                "pdf_relatorio_exibir_numero_serie",
                "pdf_relatorio_exibir_peritagem",
                "pdf_relatorio_exibir_acessorios",
                "pdf_relatorio_exibir_tipo_reparo",
                "pdf_relatorio_exibir_servicos_pecas",
            ]
        )

        OrdemServico.objects.filter(pk=self.ordem.pk).update(
            defeito="Defeito escondido no laudo.",
            peritagem="Tela com trinca no canto superior.",
            acessorios="Carregador e capa.",
        )
        self.ordem.refresh_from_db()
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="peca",
            nome="Display frontal",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
        )
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertNotIn(self.ordem.cliente.get_documento_formatado() or self.ordem.cliente.documento or "", texto_unificado)
        self.assertNotIn("E-mail", texto_unificado)
        self.assertNotIn("Defeito", texto_unificado)
        self.assertNotIn("Defeito escondido no laudo.", texto_unificado)
        self.assertNotIn("Número de Série", texto_unificado)
        self.assertNotIn("Peritagem", texto_unificado)
        self.assertNotIn("Acessórios", texto_unificado)
        self.assertNotIn("Tipo de Reparo (OS)", texto_unificado)
        self.assertNotIn("RecepÃ§Ã£o", texto_unificado)
        self.assertNotIn("Serviços e Peças", texto_unificado)
        self.assertNotIn("Display frontal", texto_unificado)

    def test_imprimir_relatorio_tecnico_inclui_peritagem_quando_ativa(self):
        OrdemServico.objects.filter(pk=self.ordem.pk).update(peritagem="Gabinete com riscos e tampa ajustada.")
        self.ordem.refresh_from_db()
        textos_pdf = []

        def _paragraph_spy(texto, *args, **kwargs):
            textos_pdf.append(str(texto))
            return reportlab_paragraph(texto, *args, **kwargs)

        with patch("ordens.view_modules.impressao.Paragraph", side_effect=_paragraph_spy):
            response = self.client.get(reverse("ordens:imprimir_relatorio_tecnico", args=[self.ordem.id]))

        self.assertEqual(response.status_code, 200)
        texto_unificado = "\n".join(textos_pdf)
        self.assertIn("Peritagem", texto_unificado)
        self.assertIn("Gabinete com riscos e tampa ajustada.", texto_unificado)


class ImpressaoPdfUtilsTests(TestCase):
    def test_quebrar_tokens_longos_preserva_texto_e_limita_blocos(self):
        token_longo = "A" * 40
        resultado = _quebrar_tokens_longos(token_longo, tamanho_bloco=10)

        self.assertEqual(resultado.replace(" ", ""), token_longo)
        self.assertTrue(all(len(parte) <= 10 for parte in resultado.split(" ")))

    def test_draw_etiquetas_corte_usa_texto_os_sem_duplicar_prefixo(self):
        class CanvasSpy:
            def __init__(self):
                self.font_size = None
                self.textos = []

            def stringWidth(self, texto, _fonte, fonte_tamanho):
                return len(str(texto)) * (fonte_tamanho * 0.35)

            def setFillColor(self, *_args, **_kwargs):
                return None

            def setStrokeColor(self, *_args, **_kwargs):
                return None

            def setLineWidth(self, *_args, **_kwargs):
                return None

            def roundRect(self, *_args, **_kwargs):
                return None

            def setFont(self, _fonte, tamanho):
                self.font_size = tamanho

            def drawCentredString(self, x, y, texto):
                self.textos.append((x, y, texto, self.font_size))

        canv = CanvasSpy()
        tema_docs = real_get_document_theme(None)
        fonts = {"bold": "Helvetica-Bold", "regular": "Helvetica"}

        _draw_etiquetas_corte(
            canv,
            width_total=A4[0],
            y_corte=A4[1] / 2.0,
            altura_etiqueta=0.90 * cm,
            texto_os="OS-4700",
            texto_cliente="Cliente Teste",
            texto_equipamento="Celular - Modelo X",
            fonts=fonts,
            tema_docs=tema_docs,
        )

        textos_os = [texto for _x, _y, texto, size in canv.textos if size == 8.2]
        self.assertEqual(len(textos_os), 4)
        self.assertTrue(all(texto == "OS OS-4700" for texto in textos_os))


class AgendamentoOrdemServicoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente_agenda_os",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.tecnico = user_model.objects.create_user(
            username="tecnico_agenda_os",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.client.force_login(self.atendente)
        self.cliente = Cliente.objects.create(
            nome="Cliente Agenda OS",
            documento="39053344705",
            telefone="11988887777",
            email="cliente.agenda.os@teste.com",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Agenda",
            modelo_equipamento="Modelo Agenda",
            defeito="Nao carrega",
            tipo_reparo="Fora de Garantia",
            tecnico_responsavel=self.tecnico,
            manutencao_preventiva_meses=6,
            status="em_andamento",
        )

    def test_agendar_ordem_reparo_redireciona_com_os_vinculada(self):
        response = self.client.get(reverse("ordens:agendar_ordem", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 302)

        destino = urlparse(response.url)
        self.assertEqual(destino.path, reverse("agenda:criar_agendamento"))
        qs = parse_qs(destino.query)
        self.assertEqual(qs.get("ordem"), [str(self.ordem.id)])
        self.assertEqual(qs.get("cliente"), [str(self.cliente.id)])
        self.assertEqual(qs.get("tecnico"), [str(self.tecnico.id)])
        self.assertTrue((qs.get("titulo") or [""])[0].startswith("Reparo OS"))

    def test_agendar_ordem_preventiva_sem_meses_usa_padrao_e_redireciona_agenda(self):
        response = self.client.get(reverse("ordens:agendar_ordem", args=[self.ordem.id]) + "?tipo=preventiva")
        self.assertEqual(response.status_code, 302)
        destino = urlparse(response.url)
        self.assertEqual(destino.path, reverse("agenda:criar_agendamento"))
        qs = parse_qs(destino.query)
        self.assertEqual((qs.get("modo_preventiva") or [""])[0], "1")
        self.assertEqual((qs.get("preventiva_em_meses") or [""])[0], "6")

    def test_agendar_ordem_preventiva_define_titulo_e_hora_padrao(self):
        self.ordem.data_conclusao = timezone.now()
        self.ordem.save(update_fields=["data_conclusao"])

        response = self.client.get(reverse("ordens:agendar_ordem", args=[self.ordem.id]) + "?tipo=preventiva")
        self.assertEqual(response.status_code, 302)
        destino = urlparse(response.url)
        qs = parse_qs(destino.query)

        titulo = (qs.get("titulo") or [""])[0]
        self.assertIn("preventiva", titulo.lower())
        inicio = (qs.get("inicio") or [""])[0]
        self.assertTrue(bool(inicio))
        dt_inicio = datetime.fromisoformat(inicio)
        self.assertEqual(dt_inicio.hour, 9)


class GarantiaPosServicoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="garantia_operador",
            password="senha123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Garantia",
            documento="39053344705",
            telefone="11988887777",
            estado="SP",
        )
        self.tipo_reparo_garantia_servico = next(
            (valor for valor, _rotulo in OrdemServico.TIPO_REPARO_CHOICES if str(valor).lower().startswith("garantia de servi")),
            "Garantia de serviço",
        )

    def _payload_base(self):
        return {
            "tipo_equipamento": "celular",
            "marca_catalogo": "__outros__",
            "marca_manual": "Marca Garantia",
            "marca_equipamento": "",
            "modelo_equipamento": "Modelo G",
            "numero_serie_equipamento": "SER-GAR-001",
            "peritagem": "Sem avarias",
            "defeito": "Nao liga",
            "acessorios": "Carregador",
            "notas_internas": "Teste garantia pos-servico",
            "confirmar_criacao": "1",
        }

    def test_garantia_servico_exige_os_origem(self):
        payload = self._payload_base()
        payload.update(
            {
                "tipo_reparo": self.tipo_reparo_garantia_servico,
                "garantia_classificacao_retorno": "mesmo_defeito",
            }
        )
        response = self.client.post(reverse("ordens:nova_ordem_cliente", args=[self.cliente.id]), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione a OS original para vincular a garantia de serviço.")

    def test_garantia_servico_vincula_os_origem(self):
        origem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Garantia",
            modelo_equipamento="Modelo G",
            numero_serie_equipamento="SER-GAR-001",
            defeito="Falha anterior",
            tipo_reparo="Fora de Garantia",
            status="concluida",
            fechada=True,
            data_conclusao=timezone.now() - timedelta(days=7),
        )
        payload = self._payload_base()
        payload.update(
            {
                "tipo_reparo": self.tipo_reparo_garantia_servico,
                "ordem_origem_garantia": str(origem.id),
                "garantia_classificacao_retorno": "garantia_mao_obra",
            }
        )
        response = self.client.post(reverse("ordens:nova_ordem_cliente", args=[self.cliente.id]), payload)
        self.assertEqual(response.status_code, 302)
        nova = OrdemServico.objects.latest("id")
        self.assertEqual(nova.ordem_origem_garantia_id, origem.id)
        self.assertEqual(nova.garantia_classificacao_retorno, "garantia_mao_obra")
        self.assertTrue(nova.garantia_reincidencia)

    def test_abertura_detecta_possivel_reincidencia_automaticamente(self):
        anterior = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Garantia",
            modelo_equipamento="Modelo G",
            numero_serie_equipamento="SER-GAR-001",
            defeito="Falha anterior",
            tipo_reparo="Fora de Garantia",
            status="concluida",
            fechada=True,
            data_conclusao=timezone.now() - timedelta(days=20),
        )
        payload = self._payload_base()
        payload.update({"tipo_reparo": "Fora de Garantia"})
        response = self.client.post(reverse("ordens:nova_ordem_cliente", args=[self.cliente.id]), payload)
        self.assertEqual(response.status_code, 302)
        nova = OrdemServico.objects.latest("id")
        self.assertTrue(nova.garantia_reincidencia)
        alerta = nova.alertas.first()
        self.assertIsNotNone(alerta)
        self.assertIn(anterior.numero_os, alerta.mensagem)







class ConciliacaoOrdensTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="auditor_os",
            password="senha-forte-123",
            tipo_usuario="adm",
        )
        self.client.force_login(self.user)
        self.cliente = Cliente.objects.create(
            nome="Cliente Auditoria",
            documento="52998224725",
            telefone="11999999999",
            estado="SP",
        )

    def _criar_ordem(self, sufixo, status="diagnosticar", fechada=False, local="Bancada 1"):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="notebook",
            marca_equipamento="Marca",
            modelo_equipamento=f"Modelo {sufixo}",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status=status,
            local_armazenamento=local,
        )
        if fechada:
            ordem.fechada = True
            ordem.save(update_fields=["fechada"])
        return ordem

    def test_gera_conciliacao_apenas_com_ordens_abertas_do_local(self):
        self._criar_ordem("001", status="diagnosticar", local="Prateleira A")
        self._criar_ordem("002", status="em_andamento", local="Bancada 2")
        self._criar_ordem("003", status="concluida", fechada=True, local="Prateleira A")

        response = self.client.post(
            reverse("ordens:conciliacoes_ordens"),
            {"filtro_local_armazenamento": "Prateleira"},
        )

        self.assertEqual(response.status_code, 302)
        conciliacao = ConciliacaoOrdem.objects.get()
        self.assertEqual(conciliacao.itens.count(), 1)
        self.assertEqual(conciliacao.itens.first().local_armazenamento_snapshot, "Prateleira A")

    def test_conciliacao_pode_ser_finalizada_apos_conferencia(self):
        self._criar_ordem("010", status="diagnosticar", local="Bancada 1")
        conciliacao = ConciliacaoOrdem.objects.create(usuario_abertura=self.user)
        ordem = OrdemServico.objects.first()
        ConciliacaoOrdemItem.objects.create(
            conciliacao=conciliacao,
            ordem_servico=ordem,
            numero_os_snapshot=ordem.numero_os,
            cliente_snapshot=ordem.cliente.nome,
        )
        item = conciliacao.itens.first()

        response_item = self.client.post(
            reverse("ordens:conciliacao_ordem_atualizar_item", args=[item.id]),
            {"situacao": "conferido", "motivo_divergencia": "", "observacao": "OK"},
        )
        self.assertEqual(response_item.status_code, 302)

        response_fim = self.client.post(reverse("ordens:conciliacao_ordem_finalizar", args=[conciliacao.id]))
        self.assertEqual(response_fim.status_code, 302)
        conciliacao.refresh_from_db()
        self.assertEqual(conciliacao.status, "fechado")


