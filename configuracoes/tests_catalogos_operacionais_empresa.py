from django.db import IntegrityError, transaction
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import reverse

from caixa.forms import BaixaContaReceberForm, FormaPagamentoForm, PagamentoForm, PagamentoContaPagarForm
from caixa.models import FormaPagamento
from configuracoes.forms import ParceiroExpedicaoForm, RegraGarantiaMarcaForm, TipoEquipamentoConfigForm
from configuracoes.models import (
    Empresa,
    ConfiguracaoAuditoria,
    LinhaAtuacaoCatalogo,
    ParceiroExpedicao,
    SegmentoEmpresaCatalogo,
    TipoEquipamentoCatalogo,
    TipoEquipamentoConfig,
    User,
    UsuarioEmpresa,
)
from configuracoes.services.setup_inicial import sincronizar_tipos_ativos_por_linhas
from configuracoes.services.tenant import resolve_tenant_context
from estoque.forms import ProdutoForm
from estoque.models import ServicoReferencia
from ordens.forms import ExpedicaoParceiroForm, OrdemServicoForm


class CatalogosOperacionaisPorEmpresaTests(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(nome="Empresa A")
        self.empresa_b = Empresa.objects.create(nome="Empresa B")

    def test_mesmos_nomes_e_codigos_sao_permitidos_em_empresas_distintas(self):
        FormaPagamento.objects.create(
            empresa=self.empresa_a, nome="PIX", codigo="pix", tipo="avista"
        )
        FormaPagamento.objects.create(
            empresa=self.empresa_b, nome="PIX", codigo="pix", tipo="avista"
        )
        TipoEquipamentoConfig.objects.create(
            empresa=self.empresa_a, nome="Notebook", codigo="notebook"
        )
        TipoEquipamentoConfig.objects.create(
            empresa=self.empresa_b, nome="Notebook", codigo="notebook"
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            FormaPagamento.objects.create(
                empresa=self.empresa_a, nome="PIX alternativo", codigo="pix", tipo="avista"
            )

    def test_formularios_exibem_apenas_empresa_atual_e_legado(self):
        tipo_a = TipoEquipamentoConfig.objects.create(
            empresa=self.empresa_a, nome="Tipo A", codigo="tipo_a"
        )
        tipo_b = TipoEquipamentoConfig.objects.create(
            empresa=self.empresa_b, nome="Tipo B", codigo="tipo_b"
        )
        tipo_legado = TipoEquipamentoConfig.objects.create(nome="Tipo legado", codigo="tipo_legado")
        parceiro_a = ParceiroExpedicao.objects.create(empresa=self.empresa_a, nome="Parceiro A")
        parceiro_b = ParceiroExpedicao.objects.create(empresa=self.empresa_b, nome="Parceiro B")
        parceiro_legado = ParceiroExpedicao.objects.create(nome="Parceiro legado")
        servico_a = ServicoReferencia.objects.create(empresa=self.empresa_a, nome="Servico A")
        servico_b = ServicoReferencia.objects.create(empresa=self.empresa_b, nome="Servico B")
        servico_legado = ServicoReferencia.objects.create(nome="Servico legado")
        forma_a = FormaPagamento.objects.create(
            empresa=self.empresa_a, nome="Forma A", codigo="forma-a"
        )
        forma_b = FormaPagamento.objects.create(
            empresa=self.empresa_b, nome="Forma B", codigo="forma-b"
        )
        forma_legada = FormaPagamento.objects.create(nome="Forma legada", codigo="forma-legada")

        ordem_form = OrdemServicoForm(empresa=self.empresa_a)
        codigos_tipo = {codigo for codigo, _ in ordem_form.fields["tipo_equipamento"].choices}
        self.assertIn(tipo_a.codigo, codigos_tipo)
        self.assertIn(tipo_legado.codigo, codigos_tipo)
        self.assertNotIn(tipo_b.codigo, codigos_tipo)

        expedicao_form = ExpedicaoParceiroForm(empresa=self.empresa_a)
        parceiros_ids = {valor for valor, _ in expedicao_form.fields["parceiro_config"].choices}
        self.assertIn(str(parceiro_a.id), parceiros_ids)
        self.assertIn(str(parceiro_legado.id), parceiros_ids)
        self.assertNotIn(str(parceiro_b.id), parceiros_ids)

        produto_form = ProdutoForm(empresa=self.empresa_a)
        servicos_ids = set(produto_form.fields["servicos_compativeis"].queryset.values_list("id", flat=True))
        self.assertEqual(servicos_ids, {servico_a.id, servico_legado.id})

        for form in (
            PagamentoForm(empresa=self.empresa_a),
            BaixaContaReceberForm(empresa=self.empresa_a),
            PagamentoContaPagarForm(empresa=self.empresa_a),
        ):
            formas_ids = set(form.fields["forma_pagamento"].queryset.values_list("id", flat=True))
            self.assertIn(forma_a.id, formas_ids)
            self.assertIn(forma_legada.id, formas_ids)
            self.assertNotIn(forma_b.id, formas_ids)

    def test_formularios_de_cadastro_atribuem_empresa(self):
        parceiro_form = ParceiroExpedicaoForm(
            {"nome": "Transportadora", "ativo": True}, empresa=self.empresa_a
        )
        self.assertTrue(parceiro_form.is_valid(), parceiro_form.errors)
        self.assertEqual(parceiro_form.save().empresa, self.empresa_a)

        tipo_form = TipoEquipamentoConfigForm(
            {"nome": "Console", "ativo": True}, empresa=self.empresa_a
        )
        self.assertTrue(tipo_form.is_valid(), tipo_form.errors)
        self.assertEqual(tipo_form.save().empresa, self.empresa_a)

        forma_form = FormaPagamentoForm(
            {
                "nome": "Dinheiro",
                "codigo": "dinheiro",
                "tipo": "avista",
                "parcelas_padrao": "1",
                "taxa_percentual": "0",
                "dias_recebimento": "0",
                "ativa": True,
            },
            empresa=self.empresa_a,
        )
        self.assertTrue(forma_form.is_valid(), forma_form.errors)
        self.assertEqual(forma_form.save().empresa, self.empresa_a)

    def test_sincronizacao_de_tipos_nao_remove_dados_de_outra_empresa(self):
        segmento = SegmentoEmpresaCatalogo.objects.create(codigo="teste", nome="Teste")
        linha = LinhaAtuacaoCatalogo.objects.create(
            segmento=segmento, codigo="linha_teste", nome="Linha teste"
        )
        tipo = TipoEquipamentoCatalogo.objects.create(
            linha=linha, codigo="equipamento_teste", nome="Equipamento teste"
        )
        linhas = LinhaAtuacaoCatalogo.objects.filter(pk=linha.pk)

        sincronizar_tipos_ativos_por_linhas(linhas, empresa=self.empresa_a)
        sincronizar_tipos_ativos_por_linhas(linhas, empresa=self.empresa_b)
        self.assertTrue(
            TipoEquipamentoConfig.objects.filter(empresa=self.empresa_a, codigo=tipo.codigo).exists()
        )
        self.assertTrue(
            TipoEquipamentoConfig.objects.filter(empresa=self.empresa_b, codigo=tipo.codigo).exists()
        )

        sincronizar_tipos_ativos_por_linhas(LinhaAtuacaoCatalogo.objects.none(), empresa=self.empresa_a)
        self.assertFalse(TipoEquipamentoConfig.objects.filter(empresa=self.empresa_a).exists())
        self.assertTrue(
            TipoEquipamentoConfig.objects.filter(empresa=self.empresa_b, codigo=tipo.codigo).exists()
        )

    def test_usuario_nao_troca_de_empresa_por_parametro_tenant(self):
        usuario = User.objects.create_user(
            username="usuario_empresa_a", password="teste", empresa=self.empresa_a
        )
        request = RequestFactory().get("/dashboard/", {"tenant": self.empresa_b.id})
        request.user = usuario

        contexto = resolve_tenant_context(request)

        self.assertEqual(contexto.empresa, self.empresa_a)
        self.assertEqual(contexto.source, "user")

    def test_tenant_publico_continua_disponivel_sem_usuario_autenticado(self):
        request = RequestFactory().get("/os/confirmar/", {"tenant": self.empresa_b.id})
        request.user = AnonymousUser()

        contexto = resolve_tenant_context(request)

        self.assertEqual(contexto.empresa, self.empresa_b)
        self.assertEqual(contexto.source, "query")

    def test_usuario_com_vinculo_ativo_pode_usar_empresa_da_sessao(self):
        usuario = User.objects.create_user(
            username="usuario_multiempresa", password="teste", empresa=self.empresa_a
        )
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.empresa_b, ativo=True)
        request = RequestFactory().get("/dashboard/")
        request.user = usuario
        request.session = {"empresa_ativa_id": self.empresa_b.id}

        contexto = resolve_tenant_context(request)

        self.assertEqual(contexto.empresa, self.empresa_b)
        self.assertEqual(contexto.source, "session")

    def test_troca_empresa_exige_vinculo_e_registra_auditoria(self):
        usuario = User.objects.create_user(
            username="usuario_seletor", password="teste", empresa=self.empresa_a
        )
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.empresa_b, ativo=True)
        self.client.force_login(usuario)

        response = self.client.post(
            reverse("configuracoes:trocar_empresa"),
            {"empresa_id": self.empresa_b.id, "next": "/"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["empresa_ativa_id"], self.empresa_b.id)
        self.assertTrue(
            ConfiguracaoAuditoria.objects.filter(
                usuario=usuario,
                acao="empresa_ativa_alterada",
                alvo=f"empresa:{self.empresa_b.id}",
            ).exists()
        )

        vinculo = UsuarioEmpresa.objects.get(usuario=usuario, empresa=self.empresa_b)
        vinculo.ativo = False
        vinculo.save(update_fields=["ativo"])
        self.client.post(
            reverse("configuracoes:trocar_empresa"),
            {"empresa_id": self.empresa_b.id, "next": "/"},
        )
        self.assertEqual(self.client.session["empresa_ativa_id"], self.empresa_b.id)
        request = RequestFactory().get("/dashboard/")
        request.user = usuario
        request.session = {"empresa_ativa_id": self.empresa_b.id}
        self.assertEqual(resolve_tenant_context(request).empresa, self.empresa_a)
