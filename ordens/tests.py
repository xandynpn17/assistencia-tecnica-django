from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import Caixa, Pagamento
from caixa.models import AuditoriaGarantia
from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema
from configuracoes.models import FornecedorGarantia, MarcaGarantia, ModeloMensagem
from estoque.models import PontoOperacional, Produto, ReservaEstoque, SaldoEstoquePonto
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.forms import LinhaTrabalhoForm
from ordens.models import OrdemServico, LinhaTrabalho, NotificacaoCliente, ServicoPeca


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
        response = self.client.post(
            url,
            {
                "tipo_equipamento": "celular",
                "marca_equipamento": "Marca A",
                "modelo_equipamento": "Modelo B",
                "numero_serie_equipamento": "SN-123",
                "defeito": "Nao liga",
                "acessorios": "Cabo",
                "tipo_reparo": "Fora de Garantia",
                "status": "concluida",
                "peritagem": "Sem danos visiveis",
            },
        )
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

    def test_resumo_ordem_exibe_dados_principais(self):
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca A",
            modelo_equipamento="Modelo B",
            numero_serie_equipamento="SN-ABC",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        response = self.client.get(reverse("ordens:resumo_ordem", args=[ordem.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.cliente.nome)
        self.assertContains(response, ordem.marca_equipamento)
        self.assertContains(response, ordem.modelo_equipamento)

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
                "numero_nota_fiscal": "NF-12345",
                "status": "diagnosticar",
                "peritagem": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        ordem = OrdemServico.objects.latest("id")
        self.assertEqual(ordem.marca_equipamento, "Marca Nova")

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
                "status": "diagnosticar",
                "peritagem": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "informe o numero da nota fiscal")


class LinhaTrabalhoFormTests(TestCase):
    def test_status_criada_nao_aparece_para_selecao_manual(self):
        form = LinhaTrabalhoForm()
        valores = [valor for valor, _ in form.fields["status"].choices if valor]
        self.assertNotIn("criada", valores)


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
                "marca_equipamento": "Marca T",
                "modelo_equipamento": "Modelo Z",
                "numero_serie_equipamento": "SN-999",
                "defeito": "Nao liga",
                "acessorios": "Capa",
                "tipo_reparo": "Fora de Garantia",
                "status": "concluida",
                "peritagem": "",
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

    def test_finalizar_com_opcao_ir_caixa_redireciona_para_pagamento(self):
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
        self.assertIn(reverse("caixa:registrar_pagamento"), response_finalizar.url)
        self.assertIn(f"os={ordem.id}", response_finalizar.url)

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
                descricao__icontains="Numero de serie alterado",
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
            {"nome": "Novo item", "quantidade": 1, "valor_unitario": "10.00", "origem": "manual"},
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
            {"status": "orcamentado", "descricao": "Equipamento orcamentado"},
        )

        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "orcamentado")
        self.assertTrue(LinhaTrabalho.objects.filter(ordem=self.ordem, status="orcamentado").exists())
        self.assertFalse(
            LinhaTrabalho.objects.filter(
                ordem=self.ordem,
                tipo_evento="automatico",
                descricao__startswith="Status alterado de",
            ).exists()
        )

    def test_status_bancada_atualiza_os_com_mesmo_status(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(url, {"status": "bancada", "descricao": "Bancada"})
        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "bancada")
        self.assertTrue(LinhaTrabalho.objects.filter(ordem=self.ordem, status="bancada").exists())

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

    def test_concluida_sem_campos_obrigatorios_nao_quebra_adicao_da_linha(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(url, {"status": "concluida", "descricao": "Tentativa de conclusao"})
        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "diagnosticar")
        self.assertTrue(LinhaTrabalho.objects.filter(ordem=self.ordem, status="concluida").exists())


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
        response = self.client.get(
            reverse("ordens:portal_cliente"),
            {"codigo": self.ordem.codigo_portal, "cpf": self.cliente.documento},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ordem.numero_os)

    def test_portal_cliente_documento_invalido_bloqueia(self):
        response = self.client.get(
            reverse("ordens:portal_cliente"),
            {"codigo": self.ordem.codigo_portal, "cpf": "00000000000"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CPF nao confere")

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
                descricao__icontains="Orcamento enviado por WhatsApp",
            ).exists()
        )


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
        self.produto = Produto.objects.create(
            nome="Display",
            sku="DSP-01",
            ean="7894561230001",
            preco_final=100,
            preco=100,
            quantidade=5,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=self.ponto, quantidade=5)
        self.reserva = ReservaEstoque.objects.create(
            codigo_reserva="RES-OS0001",
            produto=self.produto,
            ponto_operacional=self.ponto,
            quantidade=2,
            nome_contato=self.cliente.nome,
            valido_ate=timezone.localdate() + timedelta(days=2),
            status="ativa",
            ordem_servico=self.ordem,
            usuario=self.user,
        )

    def test_fechamento_os_consume_reservas(self):
        response = self.client.get(reverse("ordens:toggle_fechamento_os", args=[self.ordem.id]))
        self.assertEqual(response.status_code, 302)
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.status, "convertida")
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto)
        self.assertEqual(saldo.quantidade, 3)

    def test_reabertura_os_devolve_reservas(self):
        self.client.get(reverse("ordens:toggle_fechamento_os", args=[self.ordem.id]))
        self.ordem.refresh_from_db()
        self.assertTrue(self.ordem.fechada)

        response = self.client.get(reverse("ordens:toggle_fechamento_os", args=[self.ordem.id]))
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

    def test_busca_por_sn_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "sn:ABC"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        if "redirect" in payload:
            self.assertIn(f"/ordens/{self.ordem.id}/detalhes/", payload["redirect"])
        else:
            self.assertTrue(payload["resultados"])
            self.assertEqual(payload["resultados"][0]["id"], self.ordem.id)

    def test_busca_por_cpf_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "cpf:390.533.447-05"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        if "redirect" in payload:
            self.assertIn(f"/ordens/{self.ordem.id}/detalhes/", payload["redirect"])
        else:
            self.assertTrue(payload["resultados"])
            self.assertEqual(payload["resultados"][0]["id"], self.ordem.id)

    def test_busca_sem_prefixo_por_cpf_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "390.533.447-05"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        if "redirect" in payload:
            self.assertIn(f"/ordens/{self.ordem.id}/detalhes/", payload["redirect"])
        else:
            self.assertTrue(payload["resultados"])
            self.assertEqual(payload["resultados"][0]["id"], self.ordem.id)

    def test_busca_sem_prefixo_por_telefone_retorna_resultado(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "(11) 93333-4444"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        if "redirect" in payload:
            self.assertIn(f"/ordens/{self.ordem.id}/detalhes/", payload["redirect"])
        else:
            self.assertTrue(payload["resultados"])
            self.assertEqual(payload["resultados"][0]["id"], self.ordem.id)


class FluxoCriticoE2ETests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_e2e",
            password="senha-forte-123",
            tipo_usuario="atendente",
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
        resp_fechar = self.client.get(reverse("ordens:toggle_fechamento_os", args=[ordem.id]))
        self.assertEqual(resp_fechar.status_code, 302)
        ordem.refresh_from_db()
        self.assertTrue(ordem.fechada)
        self.assertEqual(ordem.status, "concluida")

        # 6) caixa: registrar pagamento da OS
        resp_pag = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={ordem.id}",
            {"valor": "150.00", "metodo": "pix", "referencia": "E2E-001"},
        )
        self.assertEqual(resp_pag.status_code, 302)
        self.assertTrue(Pagamento.objects.filter(ordem_servico=ordem, referencia="E2E-001").exists())


class OSConfirmadaBloqueioEdicaoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="atendente_confirmada",
            password="senha-forte-123",
            tipo_usuario="atendente",
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
