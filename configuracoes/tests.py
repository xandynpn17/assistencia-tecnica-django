from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.utils import override_settings
from django.utils import timezone
from django.http import HttpResponse
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from html import unescape
import csv
import gzip
import shutil
import zipfile
from io import BytesIO, StringIO
from PIL import Image
from configuracoes.models import (
    ConfiguracaoSistema,
    Empresa,
    FornecedorGarantia,
    IntegracaoEventoLog,
    ModeloMensagem,
    LinhaAtuacaoCatalogo,
    MarcaGarantia,
    RegraSLAAlerta,
    SegmentoEmpresaCatalogo,
    SetupInicialSistema,
    TipoEquipamentoCatalogo,
)
from configuracoes.forms import ConfiguracaoSistemaForm, EmpresaForm, MarcaGarantiaForm, RegraGarantiaMarcaForm, UserForm
from configuracoes.permissions import (
    can_override_vendedor_operacao,
    has_sensitive_permission,
    require_sensitive_permission,
)
from configuracoes.services.setup_inicial import (
    garantir_catalogo_padrao,
    setup_inicial_concluido,
    sincronizar_tipos_ativos_por_linhas,
)
from django.conf import settings
from clientes.models import Cliente
from estoque.models import CategoriaProduto, Produto
from configuracoes.models import RegraGarantiaMarca, TipoEquipamentoConfig
from ordens.models import GuiaExpedicaoItem, GuiaExpedicaoParceiro, OrdemServico
from orcamentos.models import Orcamento
from configuracoes.services.sla import calcular_pendencias_sla, carregar_regras_sla
from configuracoes.services.integracoes import (
    EVENTOS_COMUNICACAO,
    emitir_evento_interno,
    registrar_evento_integracao,
)
from ordens.services.tecnicos import usuario_apto_tecnico, usuarios_tecnicos_qs


class PermissoesSensiveisHelperTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.tecnico = user_model.objects.create_user(
            username="tecnico_sensitive",
            password="senha123",
            tipo_usuario="tecnico",
        )
        self.gerente = user_model.objects.create_user(
            username="gerente_sensitive",
            password="senha123",
            tipo_usuario="gerente",
        )
        self.atendente = user_model.objects.create_user(
            username="atendente_sensitive",
            password="senha123",
            tipo_usuario="atendente",
        )

    def test_permissao_default_de_concluir_os_para_perfil_ordens(self):
        self.assertTrue(has_sensitive_permission(self.tecnico, "perm_os_concluir"))
        self.assertTrue(has_sensitive_permission(self.atendente, "perm_os_concluir"))

    def test_permissao_especifica_precisa_flag_quando_nao_ha_default(self):
        self.assertFalse(has_sensitive_permission(self.tecnico, "perm_os_editar_numero_serie"))
        self.tecnico.perm_os_editar_numero_serie = True
        self.tecnico.save(update_fields=["perm_os_editar_numero_serie"])
        self.assertTrue(has_sensitive_permission(self.tecnico, "perm_os_editar_numero_serie"))

    def test_desconto_exige_permissao_granular_para_funcionario(self):
        self.assertFalse(has_sensitive_permission(self.atendente, "perm_orcamento_aplicar_desconto"))
        self.assertFalse(has_sensitive_permission(self.atendente, "perm_caixa_aplicar_desconto"))
        self.atendente.perm_orcamento_aplicar_desconto = True
        self.atendente.perm_caixa_aplicar_desconto = True
        self.atendente.save(update_fields=["perm_orcamento_aplicar_desconto", "perm_caixa_aplicar_desconto"])
        self.assertTrue(has_sensitive_permission(self.atendente, "perm_orcamento_aplicar_desconto"))
        self.assertTrue(has_sensitive_permission(self.atendente, "perm_caixa_aplicar_desconto"))

    def test_financeiro_exige_permissoes_granulares_nas_contas(self):
        campos = [
            "perm_caixa_criar_conta_receber",
            "perm_caixa_baixar_conta_receber",
            "perm_caixa_cancelar_conta_receber",
            "perm_caixa_editar_conta_receber",
            "perm_caixa_criar_conta_pagar",
            "perm_caixa_baixar_conta_pagar",
            "perm_caixa_cancelar_conta_pagar",
            "perm_caixa_editar_conta_pagar",
        ]
        for campo in campos:
            self.assertFalse(has_sensitive_permission(self.atendente, campo))
            setattr(self.atendente, campo, True)
        self.atendente.save(update_fields=campos)
        for campo in campos:
            self.assertTrue(has_sensitive_permission(self.atendente, campo))

    def test_permissoes_granulares_de_os_continuam_exigindo_flag(self):
        campos = [
            "perm_os_editar_observacoes_internas",
            "perm_os_editar_local_armazenamento",
            "perm_os_excluir_servico_peca",
        ]
        for campo in campos:
            self.assertFalse(has_sensitive_permission(self.atendente, campo))
            setattr(self.atendente, campo, True)
        self.atendente.save(update_fields=campos)
        for campo in campos:
            self.assertTrue(has_sensitive_permission(self.atendente, campo))

    def test_orcamento_operacional_fica_liberado_para_perfil_de_ordens(self):
        campos = [
            "perm_orcamento_editar",
            "perm_orcamento_aprovar_item",
            "perm_orcamento_recusar_item",
            "perm_orcamento_migrar_item",
        ]
        for campo in campos:
            self.assertTrue(has_sensitive_permission(self.atendente, campo))

    def test_troca_vendedor_exige_permissao_ou_gestao(self):
        self.assertFalse(can_override_vendedor_operacao(self.atendente))
        self.atendente.perm_venda_mostrador_trocar_vendedor = True
        self.atendente.save(update_fields=["perm_venda_mostrador_trocar_vendedor"])
        self.assertTrue(can_override_vendedor_operacao(self.atendente))
        self.assertTrue(can_override_vendedor_operacao(self.gerente))

    def test_usuario_so_entra_como_tecnico_quando_for_tecnico_ou_marcado(self):
        self.assertTrue(usuario_apto_tecnico(self.tecnico))
        self.assertFalse(usuario_apto_tecnico(self.atendente))
        self.atendente.atua_como_tecnico = True
        self.atendente.save(update_fields=["atua_como_tecnico"])
        self.assertTrue(usuario_apto_tecnico(self.atendente))
        tecnicos_ids = set(usuarios_tecnicos_qs().values_list("id", flat=True))
        self.assertIn(self.tecnico.id, tecnicos_ids)
        self.assertIn(self.atendente.id, tecnicos_ids)

    def test_estoque_passa_a_aceitar_flags_granulares(self):
        campos = [
            "perm_estoque_cadastro_produto",
            "perm_estoque_excluir_produto",
            "perm_estoque_ajuste_manual",
            "perm_estoque_transferencia",
            "perm_estoque_inventario_finalizar",
            "perm_estoque_converter_reserva",
            "perm_estoque_cancelar_reserva",
        ]
        for campo in campos:
            self.assertFalse(has_sensitive_permission(self.atendente, campo))
            setattr(self.atendente, campo, True)
        self.atendente.save(update_fields=campos)
        for campo in campos:
            self.assertTrue(has_sensitive_permission(self.atendente, campo))

    def test_gerente_tem_acesso_sensivel_global(self):
        self.assertTrue(has_sensitive_permission(self.gerente, "perm_caixa_ver_auditoria"))
        self.assertTrue(require_sensitive_permission(self.gerente, "perm_orcamento_excluir_item"))

    def test_require_sensitive_permission_lanca_erro_quando_sem_acesso(self):
        with self.assertRaises(PermissionDenied):
            require_sensitive_permission(self.tecnico, "perm_caixa_ver_dre")


class CheckPostgresReadyCommandTests(TestCase):
    @override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}})
    @patch.dict(
        "os.environ",
        {
            "DJANGO_DB_ENGINE": "postgres",
            "DJANGO_DB_NAME": "assistencia_dev",
            "DJANGO_DB_USER": "postgres",
            "DJANGO_DB_PASSWORD": "segredo",
            "DJANGO_DB_HOST": "127.0.0.1",
            "DJANGO_DB_PORT": "5432",
        },
        clear=False,
    )
    def test_check_postgres_ready_sem_falhas_criticas(self):
        out = StringIO()
        call_command("check_postgres_ready", stdout=out)
        output = out.getvalue()
        self.assertIn("SQLite", output)
        self.assertIn("Pre-check concluido sem falhas criticas.", output)

    @override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}})
    @patch.dict("os.environ", {}, clear=True)
    def test_check_postgres_ready_strict_falha_sem_variaveis(self):
        with self.assertRaises(CommandError):
            call_command("check_postgres_ready", "--strict")


class CheckSaasReadinessCommandTests(TestCase):
    def test_check_saas_readiness_exibe_diagnostico(self):
        out = StringIO()
        call_command("check_saas_readiness", stdout=out)
        output = out.getvalue()
        self.assertIn("Tenant middleware ativo:", output)
        self.assertIn("Modelos criticos:", output)
        self.assertIn("clientes.Cliente", output)

    def test_check_tenant_data_exibe_diagnostico(self):
        out = StringIO()
        call_command("check_tenant_data", stdout=out)
        output = out.getvalue()
        self.assertIn("Diagnostico de dados por empresa", output)
        self.assertIn("ordens.OrdemServico", output)


class CheckGoLiveCommandTests(TestCase):
    @override_settings(
        DEBUG=True,
        ALLOWED_HOSTS=["127.0.0.1", "localhost"],
        CSRF_TRUSTED_ORIGINS=[],
        LOCAL_NETWORK_MODE=True,
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}},
    )
    def test_check_go_live_strict_falha_com_configuracao_insegura(self):
        with self.assertRaises(CommandError):
            call_command("check_go_live", "--strict")

    @override_settings(
        DEBUG=False,
        SECRET_KEY="segredo-local-forte-para-teste",
        ALLOWED_HOSTS=["127.0.0.1", "localhost"],
        CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:8000"],
        LOCAL_NETWORK_MODE=True,
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}},
    )
    def test_check_go_live_avisa_sobre_rede_local_limitada(self):
        out = StringIO()
        call_command("check_go_live", stdout=out)
        output = out.getvalue()
        self.assertIn("ALLOWED_HOSTS esta limitado ao proprio servidor", output)
        self.assertIn("Checklist concluido com avisos", output)


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

    def _concluir_setup_para_ui(self):
        empresa = Empresa.objects.create(nome="Empresa UI")
        garantir_catalogo_padrao()
        linha = LinhaAtuacaoCatalogo.objects.filter(segmento__codigo="assistencia_tecnica").first()
        setup = SetupInicialSistema.get_setup()
        setup.empresa = empresa
        setup.tipo_empresa = "assistencia_tecnica"
        setup.concluido = True
        setup.save()
        if linha:
            setup.linhas_atuacao.set([linha])
            sincronizar_tipos_ativos_por_linhas(LinhaAtuacaoCatalogo.objects.filter(id=linha.id))
        return setup

    def test_painel_bloqueia_atendente(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 403)

    def test_create_user_sem_numero_vendedor_gera_numero_automatico(self):
        user_model = get_user_model()
        usuario = user_model.objects.create_user(
            username="sem_numero_vendedor_auto",
            password="Senha@123",
            tipo_usuario="atendente",
        )
        self.assertIsNotNone(usuario.numero_vendedor)
        self.assertRegex(usuario.numero_vendedor, r"^\d{2}$")

    def test_create_user_usa_tres_digitos_quando_nao_ha_dois_disponiveis(self):
        user_model = get_user_model()
        for numero in range(1, 100):
            codigo = f"{numero:02d}"
            if user_model.objects.filter(numero_vendedor=codigo).exists():
                continue
            user_model.objects.create_user(
                username=f"user_vend_{codigo}",
                password="Senha@123",
                tipo_usuario="atendente",
                numero_vendedor=codigo,
            )

        usuario = user_model.objects.create_user(
            username="sem_numero_tres_digitos",
            password="Senha@123",
            tipo_usuario="tecnico",
        )
        self.assertRegex(usuario.numero_vendedor, r"^\d{3}$")

    def test_cadastro_usuario_gera_numero_vendedor_quando_campo_vazio(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("configuracoes:adicionar_usuario"),
            {
                "username": "usuario_sem_numero_form",
                "email": "auto@teste.com",
                "password": "Senha@123",
                "tipo_vinculo": "FUNCIONARIO",
                "percentual_comissao_servico": "0",
                "percentual_comissao_peca": "0",
                "is_active": "on",
                "is_staff": "on",
                "tipo_usuario": "atendente",
                "numero_vendedor": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        user_model = get_user_model()
        usuario = user_model.objects.get(username="usuario_sem_numero_form")
        self.assertTrue((usuario.numero_vendedor or "").isdigit())
        self.assertGreaterEqual(len(usuario.numero_vendedor or ""), 2)

    def test_painel_permitem_gerente(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 200)

    def test_painel_exibe_resumo_e_acoes_operacionais(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode(response.charset or "utf-8")
        self.assertIn("Visao rapida", html)
        self.assertIn("Acoes criticas", html)
        self.assertIn("Proximos passos recomendados", html)
        self.assertIn("Gerar backup", html)
        self.assertIn("Monitorar integra", html)

    @override_settings(LOCAL_RECOVERY_KEY="rec-chave-123")
    def test_painel_exibe_atalho_de_recuperacao_local_quando_habilitada(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recuperacao local")
        self.assertContains(response, reverse("configuracoes:restore_banco_publico"))

    def test_empresa_exibe_abas_da_central_operacional(self):
        self._concluir_setup_para_ui()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("configuracoes:empresa"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode(response.charset or "utf-8")
        self.assertIn("Central Operacional", html)
        self.assertIn("Empresa", html)
        self.assertIn("Ordem de Servi", html)
        self.assertIn("Sistema", html)

    def test_configuracao_os_exibe_layout_refinado(self):
        self._concluir_setup_para_ui()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("configuracoes:configuracao_os"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode(response.charset or "utf-8")
        self.assertIn("Prefixo", html)
        self.assertIn("PDFs e termos", html)
        self.assertIn("Sistema &gt; Documentos", html)

    def test_configuracao_sistema_exibe_abas_da_central_operacional(self):
        self._concluir_setup_para_ui()
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:configuracao_sistema"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode(response.charset or "utf-8")
        self.assertIn("Central Operacional", html)
        self.assertIn("central da loja", html)
        self.assertIn("Opera", html)
        self.assertIn("Fluxo da OS", html)
        self.assertIn("Documentos", html)


    def test_tipos_equipamento_exibe_central_de_catalogo(self):
        self._concluir_setup_para_ui()
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:tipos_equipamento"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Novo tipo de equipamento")

    def test_modelos_mensagem_exibe_central_de_catalogo(self):
        self._concluir_setup_para_ui()
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:modelos_mensagem"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Novo modelo manual")
        self.assertContains(response, "Eventos sem modelo")

    def test_painel_permite_funcao_extra_configuracoes(self):
        self.atendente.acesso_configuracoes_extra = True
        self.atendente.save(update_fields=["acesso_configuracoes_extra"])
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 200)

    def test_lista_usuarios_permitem_gerente(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:lista_usuarios"))
        self.assertEqual(response.status_code, 200)

    def test_lista_usuarios_permitem_admin(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("configuracoes:lista_usuarios"))
        self.assertEqual(response.status_code, 200)

    def test_gerente_pode_abrir_cadastro_usuario(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:adicionar_usuario"))
        self.assertEqual(response.status_code, 200)

    def test_cadastro_usuario_salva_funcoes_extras(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("configuracoes:adicionar_usuario"),
            {
                "username": "usuario_funcoes_extras",
                "email": "extras@teste.com",
                "password": "Senha@123",
                "tipo_vinculo": "FUNCIONARIO",
                "percentual_comissao_servico": "0",
                "percentual_comissao_peca": "0",
                "percentual_comissao_vendas": "0",
                "is_active": "on",
                "is_staff": "on",
                "tipo_usuario": "tecnico",
                "numero_vendedor": "",
                "acesso_caixa_financeiro_extra": "on",
                "acesso_configuracoes_extra": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        user_model = get_user_model()
        usuario = user_model.objects.get(username="usuario_funcoes_extras")
        self.assertTrue(usuario.acesso_caixa_financeiro_extra)
        self.assertTrue(usuario.acesso_configuracoes_extra)
        self.assertFalse(usuario.acesso_estoque_extra)

    def test_cadastro_usuario_aplica_preset_permissoes(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("configuracoes:adicionar_usuario"),
            {
                "username": "usuario_preset_caixa",
                "email": "preset@teste.com",
                "password": "Senha@123",
                "tipo_vinculo": "FUNCIONARIO",
                "percentual_comissao_servico": "0",
                "percentual_comissao_peca": "0",
                "percentual_comissao_vendas": "0",
                "is_active": "on",
                "is_staff": "on",
                "tipo_usuario": "atendente",
                "numero_vendedor": "",
                "preset_perfil": "atendente_caixa",
            },
        )
        self.assertEqual(response.status_code, 302)
        user_model = get_user_model()
        usuario = user_model.objects.get(username="usuario_preset_caixa")
        self.assertTrue(usuario.acesso_caixa_operacional_extra)
        self.assertTrue(usuario.acesso_estoque_extra)
        self.assertTrue(usuario.perm_os_concluir)
        self.assertTrue(usuario.perm_os_reabrir)

    def test_userform_limpa_flag_tecnico_quando_usuario_muda_para_atendente(self):
        usuario = get_user_model().objects.create_user(
            username="usuario_muda_funcao",
            password="Senha@123",
            tipo_usuario="tecnico",
            atua_como_tecnico=True,
        )
        form = UserForm(
            data={
                "username": usuario.username,
                "nome_completo": usuario.nome_completo,
                "email": usuario.email,
                "password": "",
                "tipo_usuario": "atendente",
                "atua_como_tecnico": "",
                "tipo_pessoa": usuario.tipo_pessoa,
                "documento_cpf_cnpj": usuario.documento_cpf_cnpj,
                "telefone": usuario.telefone,
                "endereco": usuario.endereco,
                "cargo": usuario.cargo,
                "departamento": usuario.departamento,
                "regime_contratacao": usuario.regime_contratacao,
                "tipo_vinculo": usuario.tipo_vinculo or "FUNCIONARIO",
                "percentual_comissao_servico": str(usuario.percentual_comissao_servico or "0"),
                "percentual_comissao_peca": str(usuario.percentual_comissao_peca or "0"),
                "percentual_comissao_vendas": str(usuario.percentual_comissao_vendas or "0"),
                "numero_vendedor": usuario.numero_vendedor or "",
                "is_active": "on",
            },
            instance=usuario,
        )
        self.assertTrue(form.is_valid(), form.errors)
        atualizado = form.save()
        self.assertEqual(atualizado.tipo_usuario, "atendente")
        self.assertFalse(atualizado.atua_como_tecnico)

    def test_gerente_nao_pode_criar_admin(self):
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("configuracoes:adicionar_usuario"),
            {
                "username": "novo_admin_por_gerente",
                "email": "gerente@teste.com",
                "password": "Senha@123",
                "numero_vendedor": "22",
                "tipo_vinculo": "FUNCIONARIO",
                "percentual_comissao_servico": "0",
                "percentual_comissao_peca": "0",
                "is_active": "on",
                "is_staff": "on",
                "tipo_usuario": "adm",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gerente")
        self.assertContains(response, "Administrador")

    def test_cadastro_usuario_exige_senha_forte(self):
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("configuracoes:adicionar_usuario"),
            {
                "username": "usuario_senha_fraca",
                "email": "fraco@teste.com",
                "password": "senha1234",
                "numero_vendedor": "23",
                "tipo_vinculo": "FUNCIONARIO",
                "percentual_comissao_servico": "0",
                "percentual_comissao_peca": "0",
                "is_active": "on",
                "is_staff": "on",
                "tipo_usuario": "atendente",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "letra maius")
        self.assertContains(response, "caractere especial")

    def test_backup_permite_gerente(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:backup_banco"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gerar backup oficial do ambiente")

    @override_settings(LOCAL_RECOVERY_KEY="rec-chave-123")
    def test_backup_exibe_link_de_recuperacao_local_quando_habilitada(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:backup_banco"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Abrir recuperação local")
        self.assertContains(response, reverse("configuracoes:restore_banco_publico"))

    @patch("configuracoes.view_modules.operacao.call_command")
    def test_backup_post_gera_arquivo_para_gerente(self, call_command_mock):
        self.client.force_login(self.gerente)
        response = self.client.post(reverse("configuracoes:backup_banco"), {"include_media": "1"})
        self.assertEqual(response.status_code, 302)
        call_command_mock.assert_called_once()

    def test_backup_bloqueia_atendente(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("configuracoes:backup_banco"))
        self.assertEqual(response.status_code, 403)

    @patch("configuracoes.view_modules.operacao.FileResponse")
    def test_download_backup_disponivel_para_gerente(self, file_response_mock):
        backup_dir = Path(settings.BASE_DIR) / "backups" / "backup_20990102_120000"
        self.addCleanup(lambda: shutil.rmtree(backup_dir, ignore_errors=True))
        self.addCleanup(lambda: backup_dir.with_suffix(".zip").unlink(missing_ok=True) if backup_dir.with_suffix(".zip").exists() else None)
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "database.dump").write_bytes(b"dump")
        (backup_dir / "manifest.json").write_text('{"engine": "postgresql"}', encoding="utf-8")

        def _file_response_side_effect(file_handle, *args, **kwargs):
            file_handle.close()
            return HttpResponse("ok")

        file_response_mock.side_effect = _file_response_side_effect

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:download_backup"), {"path": str(backup_dir)})
        self.assertEqual(response.status_code, 200)
        file_response_mock.assert_called_once()

    def test_setup_inicial_oferece_restore_de_backup(self):
        SetupInicialSistema.get_setup().save()
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:setup_inicial"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "backup?")
        self.assertContains(response, reverse("configuracoes:restore_banco"))

    def test_setup_inicial_fica_disponivel_sem_login_quando_base_esta_pendente(self):
        setup = SetupInicialSistema.get_setup()
        setup.concluido = False
        setup.empresa = None
        setup.tipo_empresa = ""
        setup.save()

        response = self.client.get(reverse("configuracoes:setup_inicial"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Setup inicial")

    def test_setup_inicial_sem_login_redireciona_para_login_quando_base_ja_esta_concluida(self):
        self._concluir_setup_para_ui()

        response = self.client.get(reverse("configuracoes:setup_inicial"))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("core:login"))

    @patch("configuracoes.view_modules.integracoes.consultar_cep")
    def test_busca_cep_permanece_disponivel_durante_setup_inicial(self, consultar_cep_mock):
        setup = SetupInicialSistema.get_setup()
        setup.concluido = False
        setup.save(update_fields=["concluido"])
        consultar_cep_mock.return_value = type(
            "ConsultaCepResultado",
            (),
            {
                "payload": {"logradouro": "Rua Teste", "bairro": "Centro", "cidade": "Goiania", "estado": "GO"},
                "status": 200,
            },
        )()

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:buscar_cep"), {"cep": "74000000"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["logradouro"], "Rua Teste")

    @patch("configuracoes.view_modules.integracoes.consultar_cep")
    def test_busca_cep_funciona_sem_login_durante_setup_inicial(self, consultar_cep_mock):
        setup = SetupInicialSistema.get_setup()
        setup.concluido = False
        setup.save(update_fields=["concluido"])
        consultar_cep_mock.return_value = type(
            "ConsultaCepResultado",
            (),
            {
                "payload": {"logradouro": "Rua Livre", "bairro": "Centro", "cidade": "Goiania", "estado": "GO"},
                "status": 200,
            },
        )()

        response = self.client.get(
            reverse("configuracoes:buscar_cep"),
            {"cep": "74000000"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["logradouro"], "Rua Livre")

    def test_busca_cep_ajax_sem_login_retorna_json_quando_setup_ja_foi_concluido(self):
        self._concluir_setup_para_ui()

        response = self.client.get(
            reverse("configuracoes:buscar_cep"),
            {"cep": "74000000"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["erro"], "Sessão expirada. Faça login novamente.")

    def test_setup_inicial_exibe_linhas_com_descricao(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:setup_inicial"), {"tipo_empresa": "assistencia_tecnica"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Linhas de atuacao")
        self.assertContains(response, "diagnostico mais detalhado", count=1)

    def test_restore_fica_acessivel_antes_do_setup(self):
        setup = SetupInicialSistema.get_setup()
        setup.concluido = False
        setup.save(update_fields=["concluido"])

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:restore_banco"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Setup inicial pendente")

    @override_settings(LOCAL_RECOVERY_KEY="rec-chave-123")
    def test_restore_exibe_plano_b_de_recuperacao_local_quando_habilitado(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:restore_banco"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plano B antes do login")
        self.assertContains(response, "Abrir recuperação local")

    @override_settings(LOCAL_RECOVERY_KEY="rec-chave-123")
    def test_login_exibe_link_para_recuperacao_local_quando_chave_existe(self):
        response = self.client.get(reverse("core:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("configuracoes:restore_banco_publico"))

    def test_login_exibe_atalho_de_primeira_instalacao_quando_setup_esta_pendente(self):
        setup = SetupInicialSistema.get_setup()
        setup.concluido = False
        setup.empresa = None
        setup.tipo_empresa = ""
        setup.save()

        response = self.client.get(reverse("core:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Primeira instalação do sistema")
        self.assertContains(response, reverse("configuracoes:setup_inicial"))

    @override_settings(LOCAL_NETWORK_MODE=True, LOCAL_RECOVERY_KEY="rec-chave-123")
    def test_recuperacao_local_publica_fica_disponivel_sem_login(self):
        response = self.client.get(
            reverse("configuracoes:restore_banco_publico"),
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recupera")
        self.assertContains(response, "Fallback por terminal")
        self.assertContains(response, "manage_local.ps1 restore_db")

    @override_settings(LOCAL_NETWORK_MODE=True, LOCAL_RECOVERY_KEY="")
    def test_recuperacao_local_publica_bloqueia_sem_chave(self):
        response = self.client.get(
            reverse("configuracoes:restore_banco_publico"),
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 403)

    @patch("configuracoes.view_modules.operacao.call_command")
    def test_backup_usa_diretorio_oficial_configurado(self, call_command_mock):
        self.client.force_login(self.gerente)
        config = ConfiguracaoSistema.get_configuracao()
        config.backup_diretorio_oficial = str(Path(settings.BASE_DIR) / "backups_custom")
        config.save()

        response = self.client.post(reverse("configuracoes:backup_banco"), {"include_media": "1"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(call_command_mock.call_args.kwargs["output_dir"], config.backup_diretorio_oficial)

    @patch("configuracoes.view_modules.operacao.call_command")
    def test_restore_administrativo_aceita_upload_zip(self, call_command_mock):
        self.client.force_login(self.gerente)
        arquivo = SimpleUploadedFile("backup_abgest.zip", b"PKteste", content_type="application/zip")

        response = self.client.post(
            reverse("configuracoes:restore_banco"),
            {
                "confirmar": "RESTAURAR",
                "ciente_restore": "1",
                "repair_single_tenant": "1",
                "arquivo_upload": arquivo,
            },
        )

        self.assertEqual(response.status_code, 302)
        call_command_mock.assert_called_once()
        self.assertTrue(str(call_command_mock.call_args.args[1]).lower().endswith(".zip"))

    @override_settings(LOCAL_NETWORK_MODE=True, LOCAL_RECOVERY_KEY="rec-chave-123")
    def test_recuperacao_local_publica_exibe_upload_mesmo_sem_backups_locais(self):
        backup_dir = Path(settings.BASE_DIR) / "tmp_test_backups_publico_vazio"
        config = ConfiguracaoSistema.get_configuracao()
        anterior = config.backup_diretorio_oficial
        config.backup_diretorio_oficial = str(backup_dir)
        config.save(update_fields=["backup_diretorio_oficial"])
        self.addCleanup(
            lambda: (
                setattr(config, "backup_diretorio_oficial", anterior),
                config.save(update_fields=["backup_diretorio_oficial"])
            )
        )
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        backup_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(backup_dir, ignore_errors=True) if backup_dir.exists() else None)

        response = self.client.get(
            reverse("configuracoes:restore_banco_publico"),
            REMOTE_ADDR="127.0.0.1",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="arquivo_upload"')
        self.assertContains(response, "Nenhum backup encontrado na pasta oficial")

    @override_settings(LOCAL_NETWORK_MODE=True, LOCAL_RECOVERY_KEY="rec-chave-123")
    @patch("configuracoes.view_modules.operacao.call_command")
    def test_recuperacao_local_publica_aceita_upload_zip(self, call_command_mock):
        arquivo = SimpleUploadedFile("backup_abgest.zip", b"PKteste", content_type="application/zip")

        response = self.client.post(
            reverse("configuracoes:restore_banco_publico"),
            {
                "confirmar": "RESTAURAR",
                "ciente_restore": "1",
                "recovery_key": "rec-chave-123",
                "repair_single_tenant": "1",
                "arquivo_upload": arquivo,
            },
            REMOTE_ADDR="127.0.0.1",
        )

        self.assertEqual(response.status_code, 302)
        call_command_mock.assert_called_once()
        self.assertTrue(str(call_command_mock.call_args.args[1]).lower().endswith(".zip"))

    @override_settings(LOCAL_NETWORK_MODE=True, LOCAL_RECOVERY_KEY="rec-chave-123")
    @patch("configuracoes.view_modules.operacao.call_command")
    def test_recuperacao_local_publica_exige_chave_valida(self, call_command_mock):
        backup_dir = Path(settings.BASE_DIR) / "backups" / "backup_20990101_120000"
        self.addCleanup(lambda: shutil.rmtree(backup_dir, ignore_errors=True))
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "database.dump").write_bytes(b"dump")
        (backup_dir / "manifest.json").write_text('{"engine": "postgresql"}', encoding="utf-8")

        response = self.client.post(
            reverse("configuracoes:restore_banco_publico"),
            {
                "arquivo": str(backup_dir),
                "confirmar": "RESTAURAR",
                "ciente_restore": "1",
                "recovery_key": "chave-errada",
            },
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 302)
        call_command_mock.assert_not_called()

    def test_caixa_financeiro_permite_funcao_extra(self):
        self.tecnico.acesso_caixa_financeiro_extra = True
        self.tecnico.save(update_fields=["acesso_caixa_financeiro_extra"])
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("caixa:contas_receber"))
        self.assertEqual(response.status_code, 200)

    def test_gerente_acessa_marcas_fornecedores(self):
        self._concluir_setup_para_ui()
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:marcas_fornecedores"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cadastrar Fornecedor")
        self.assertContains(response, "Cadastrar Parceiro")
        self.assertContains(response, "Fluxo recomendado")

    def test_gerente_acessa_auditoria_configuracoes(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:auditoria_configuracoes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumo da auditoria operacional")

    def test_gerente_acessa_simulador_permissoes(self):
        self.client.force_login(self.gerente)
        response = self.client.get(
            reverse("configuracoes:simulador_permissoes"),
            {"preset": "atendente_caixa"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("impactos", payload)
        self.assertTrue(any("caixa" in item.lower() for item in payload.get("impactos", [])))
        self.assertIn("resumo_risco", payload)

    def test_simulador_permissoes_considera_overrides_do_formulario(self):
        self.client.force_login(self.gerente)
        response = self.client.get(
            reverse("configuracoes:simulador_permissoes"),
            {
                "preset": "atendente_caixa",
                "perm_caixa_ver_dre": "1",
                "perm_caixa_gerir_comissoes": "1",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        resumo = payload.get("resumo_risco") or {}
        self.assertTrue(resumo.get("possui_financeiro"))
        self.assertIn(resumo.get("nivel"), {"moderado", "alto", "critico"})

    def test_gerente_acessa_contrato_webhooks(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:contrato_webhooks"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("eventos", payload)
        self.assertIn("configuracoes.alterada", payload["eventos"])

    def test_tenant_context_resolve_por_header(self):
        empresa_a = Empresa.objects.create(nome="Empresa A")
        empresa_b = Empresa.objects.create(nome="Empresa B")
        self.admin.empresa = empresa_a
        self.admin.save(update_fields=["empresa"])
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("configuracoes:painel"),
            HTTP_X_TENANT=str(empresa_b.id),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["empresa"].id, empresa_b.id)

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

    def test_gerente_pode_salvar_municipio_e_uf_do_fornecedor(self):
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Cidade")
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("configuracoes:marcas_fornecedores"),
            {
                "form_type": "fornecedor_edit",
                "fornecedor_id": fornecedor.id,
                "nome": "Fornecedor Cidade",
                "municipio": "Goiania",
                "uf": "GO",
                "modalidade_pagamento": "pix",
                "prazo_pagamento_dias": 7,
                "ativo": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        fornecedor.refresh_from_db()
        self.assertEqual(fornecedor.municipio, "Goiania")
        self.assertEqual(fornecedor.uf, "GO")

    def test_gerente_pode_salvar_procedimento_e_documentos_de_cobranca_do_fornecedor(self):
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Financeiro")
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("configuracoes:marcas_fornecedores"),
            {
                "form_type": "fornecedor_edit",
                "fornecedor_id": fornecedor.id,
                "nome": "Fornecedor Financeiro",
                "email_cobranca": "financeiro@fabricante.com",
                "portal_garantia_url": "https://portal.fabricante.com/garantia",
                "documentos_exigidos": "NF, laudo e etiqueta.",
                "procedimento_cobranca": "Abrir protocolo no portal e anexar PDF da OS.",
                "modalidade_pagamento": "pix",
                "prazo_pagamento_dias": 14,
                "ativo": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        fornecedor.refresh_from_db()
        self.assertEqual(fornecedor.email_cobranca, "financeiro@fabricante.com")
        self.assertEqual(fornecedor.portal_garantia_url, "https://portal.fabricante.com/garantia")
        self.assertIn("NF", fornecedor.documentos_exigidos)
        self.assertIn("protocolo", fornecedor.procedimento_cobranca)

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

    def test_gerente_crud_item_mao_obra_na_edicao_da_marca(self):
        marca = MarcaGarantia.objects.create(nome="Marca Regra", valor_mao_obra_garantia=10, ativo=True)
        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()

        response_add = self.client.post(
            reverse("configuracoes:marcas_fornecedores"),
            {
                "form_type": "regra_add",
                "marca_id": marca.id,
                "tipo_produto": "secador",
                "valor_mao_obra": "20.00",
                "valor_mao_obra_tecnico": "8.00",
                "modalidade_pagamento": "pix",
                "prazo_pagamento_dias": 30,
                "inicio_vigencia": hoje,
                "fim_vigencia": "",
                "ativo": "on",
            },
        )
        self.assertEqual(response_add.status_code, 302)
        regra = RegraGarantiaMarca.objects.get(marca=marca, tipo_produto="secador")
        self.assertEqual(str(regra.valor_mao_obra), "20.00")
        self.assertEqual(str(regra.valor_mao_obra_tecnico), "8.00")

        response_edit = self.client.post(
            reverse("configuracoes:marcas_fornecedores"),
            {
                "form_type": "regra_edit",
                "marca_id": marca.id,
                "regra_id": regra.id,
                "tipo_produto": "secador",
                "valor_mao_obra": "50.00",
                "valor_mao_obra_tecnico": "25.00",
                "modalidade_pagamento": "pix",
                "prazo_pagamento_dias": 30,
                "inicio_vigencia": hoje,
                "fim_vigencia": "",
                "ativo": "on",
            },
        )
        self.assertEqual(response_edit.status_code, 302)
        regra.refresh_from_db()
        self.assertEqual(str(regra.valor_mao_obra), "50.00")
        self.assertEqual(str(regra.valor_mao_obra_tecnico), "25.00")

        response_delete = self.client.post(
            reverse("configuracoes:marcas_fornecedores"),
            {
                "form_type": "regra_delete",
                "marca_id": marca.id,
                "regra_id": regra.id,
            },
        )
        self.assertEqual(response_delete.status_code, 302)
        self.assertFalse(RegraGarantiaMarca.objects.filter(id=regra.id).exists())

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

    def test_consulta_de_marca_exibe_procedimento_operacional(self):
        fornecedor = FornecedorGarantia.objects.create(
            nome="Fornecedor Procedimento",
            municipio="Sao Paulo",
            uf="SP",
            email_cobranca="faturamento@fornecedor.com",
            portal_garantia_url="https://portal.fornecedor.com",
            documentos_exigidos="NF e laudo tecnico",
            procedimento_cobranca="Abrir protocolo e anexar os comprovantes.",
            modalidade_pagamento="boleto",
            prazo_pagamento_dias=28,
        )
        MarcaGarantia.objects.create(
            nome="Marca Procedimento",
            fornecedor=fornecedor,
            parceira_garantia=True,
            procedimentos="Abrir portal, anexar NF e faturar mao de obra no fechamento.",
            ativo=True,
        )
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:marcas_fornecedores"), {"qm": "Marca Procedimento"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ver procedimento da marca")
        self.assertContains(response, "Abrir portal, anexar NF e faturar mao de obra no fechamento.")
        self.assertContains(response, "Sao Paulo / SP")
        self.assertContains(response, "faturamento@fornecedor.com")
        self.assertContains(response, "NF e laudo tecnico")
        self.assertContains(response, "Abrir protocolo e anexar os comprovantes.")

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

    def test_tecnico_pode_buscar_cep(self):
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("configuracoes:buscar_cep"), {"cep": "123"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("CEP", response.json().get("erro", ""))

    def test_atendente_e_tecnico_acessam_cep_sem_bloqueio_de_permissao(self):
        for usuario in (self.atendente, self.tecnico):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                response = self.client.get(reverse("configuracoes:buscar_cep"), {"cep": "123"})
                self.assertNotEqual(response.status_code, 403)
                self.assertEqual(response.status_code, 400)

    def test_todos_tipos_de_usuario_podem_acessar_fluxo_criacao_os_e_cep(self):
        cliente = Cliente.objects.create(
            nome="Cliente Permissao OS",
            documento="52998224725",
            telefone="11999990000",
            estado="SP",
        )
        user_model = get_user_model()
        usuarios_por_tipo = {
            "adm": self.admin,
            "gerente": self.gerente,
            "atendente": self.atendente,
            "tecnico": self.tecnico,
        }
        for tipo_usuario, _ in user_model.TIPO_CHOICES:
            usuario = usuarios_por_tipo.get(tipo_usuario)
            if usuario is None:
                usuario = user_model.objects.create_user(
                    username=f"{tipo_usuario}_criacao_os",
                    password="senha123",
                    tipo_usuario=tipo_usuario,
                )
                usuarios_por_tipo[tipo_usuario] = usuario

            with self.subTest(tipo_usuario=tipo_usuario):
                self.client.force_login(usuario)
                self.assertEqual(
                    self.client.get(reverse("ordens:verificar_cliente_os")).status_code,
                    200,
                )
                self.assertEqual(
                    self.client.get(reverse("ordens:selecionar_cliente_os")).status_code,
                    200,
                )
                self.assertEqual(
                    self.client.get(reverse("ordens:nova_ordem_cliente", args=[cliente.id])).status_code,
                    200,
                )
                response_cep = self.client.get(reverse("configuracoes:buscar_cep"), {"cep": "123"})
                self.assertEqual(response_cep.status_code, 400)
                self.assertIn("CEP", response_cep.json().get("erro", ""))


class EmpresaFormLogoTests(TestCase):
    @staticmethod
    def _arquivo_imagem(nome="logo.png", tamanho=(900, 450), color=(24, 72, 128, 255)):
        buffer = BytesIO()
        Image.new("RGBA", tamanho, color).save(buffer, format="PNG")
        return SimpleUploadedFile(nome, buffer.getvalue(), content_type="image/png")

    def test_form_processa_logo_e_logo_pdf_com_tamanho_padrao(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                form = EmpresaForm(
                    data={
                        "nome": "Empresa QA",
                        "cnpj": "",
                        "endereco": "",
                        "telefone": "",
                        "email": "",
                        "regime_tributario": "simples",
                        "anexo_simples": "I",
                        "modo_tributario": "basico",
                        "aliquota_comercio": "0",
                        "aliquota_servico": "0",
                        "icms": "0",
                        "ipi": "0",
                        "pis": "0",
                        "cofins": "0",
                        "logo_zoom": "1.4",
                        "logo_focus_x": "0.5",
                        "logo_focus_y": "0.5",
                        "logo_pdf_zoom": "1.2",
                        "logo_pdf_focus_x": "0.5",
                        "logo_pdf_focus_y": "0.5",
                    },
                    files={
                        "logo": self._arquivo_imagem("sistema.png", tamanho=(1000, 500)),
                        "logo_pdf": self._arquivo_imagem("pdf.png", tamanho=(1200, 600)),
                    },
                )

                self.assertTrue(form.is_valid(), form.errors)
                empresa = form.save()

                with Image.open(empresa.logo.path) as logo_sistema:
                    self.assertEqual(logo_sistema.size, (640, 320))
                with Image.open(empresa.logo_pdf.path) as logo_pdf:
                    self.assertEqual(logo_pdf.size, (960, 440))

    def test_form_rejeita_formato_nao_suportado(self):
        form = EmpresaForm(
            data={
                "nome": "Empresa QA",
                "regime_tributario": "simples",
                "anexo_simples": "I",
                "modo_tributario": "basico",
                "aliquota_comercio": "0",
                "aliquota_servico": "0",
                "icms": "0",
                "ipi": "0",
                "pis": "0",
                "cofins": "0",
            },
            files={
                "logo": SimpleUploadedFile("logo.svg", b"<svg></svg>", content_type="image/svg+xml"),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)

    def test_form_remove_logo_atual_sem_novo_upload(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(MEDIA_ROOT=tmp_dir):
                empresa = Empresa.objects.create(nome="Empresa Remocao")
                empresa.logo = self._arquivo_imagem("sistema.png")
                empresa.logo_pdf = self._arquivo_imagem("pdf.png")
                empresa.save(update_fields=["logo", "logo_pdf"])

                caminho_logo = empresa.logo.path
                caminho_logo_pdf = empresa.logo_pdf.path

                form = EmpresaForm(
                    data={
                        "nome": "Empresa Remocao",
                        "cnpj": "",
                        "endereco": "",
                        "telefone": "",
                        "email": "",
                        "regime_tributario": "simples",
                        "anexo_simples": "I",
                        "modo_tributario": "basico",
                        "aliquota_comercio": "0",
                        "aliquota_servico": "0",
                        "icms": "0",
                        "ipi": "0",
                        "pis": "0",
                        "cofins": "0",
                        "remover_logo": "on",
                        "remover_logo_pdf": "on",
                    },
                    instance=empresa,
                )

                self.assertTrue(form.is_valid(), form.errors)
                empresa = form.save()
                empresa.refresh_from_db()

                self.assertFalse(bool(empresa.logo))
                self.assertFalse(bool(empresa.logo_pdf))
                self.assertFalse(Path(caminho_logo).exists())
                self.assertFalse(Path(caminho_logo_pdf).exists())
                if empresa.logo:
                    empresa.logo.close()
                if empresa.logo_pdf:
                    empresa.logo_pdf.close()


class ConfiguracaoSistemaFormTests(TestCase):
    def _base_data(self):
        config = ConfiguracaoSistema.get_configuracao()
        form = ConfiguracaoSistemaForm(instance=config)
        data = {}
        for nome in form.fields:
            valor = form.initial.get(nome)
            if valor is None:
                valor = ""
            data[nome] = valor
        return data

    def test_form_rejeita_termos_ordem_servico_acima_do_limite(self):
        data = self._base_data()
        data["condicoes_orcamento"] = "Ok"
        data["termos_ordem_servico"] = "A" * 1801
        form = ConfiguracaoSistemaForm(
            data=data,
            instance=ConfiguracaoSistema.get_configuracao(),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("termos_ordem_servico", form.errors)

    def test_form_rejeita_condicoes_orcamento_acima_do_limite(self):
        data = self._base_data()
        data["condicoes_orcamento"] = "B" * 501
        data["termos_ordem_servico"] = "Texto curto"
        form = ConfiguracaoSistemaForm(
            data=data,
            instance=ConfiguracaoSistema.get_configuracao(),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("condicoes_orcamento", form.errors)


class ComandosConfiguracoesTests(TestCase):
    def test_preencher_numero_vendedor_preenche_usuarios_sem_numero(self):
        user_model = get_user_model()
        usuario_sem_numero = user_model.objects.create_user(
            username="usuario_sem_numero_cmd",
            password="Senha@123",
            tipo_usuario="atendente",
            numero_vendedor="31",
        )
        user_model.objects.filter(id=usuario_sem_numero.id).update(numero_vendedor="")

        usuario_com_numero = user_model.objects.create_user(
            username="usuario_com_numero_cmd",
            password="Senha@123",
            tipo_usuario="tecnico",
            numero_vendedor="77",
        )

        call_command("preencher_numero_vendedor")

        usuario_sem_numero.refresh_from_db()
        usuario_com_numero.refresh_from_db()
        self.assertRegex(usuario_sem_numero.numero_vendedor or "", r"^\d{2,}$")
        self.assertEqual(usuario_com_numero.numero_vendedor, "77")

    def test_preencher_numero_vendedor_dry_run_nao_persiste(self):
        user_model = get_user_model()
        usuario = user_model.objects.create_user(
            username="usuario_sem_numero_dry_run",
            password="Senha@123",
            tipo_usuario="atendente",
            numero_vendedor="32",
        )
        user_model.objects.filter(id=usuario.id).update(numero_vendedor="")

        saida = StringIO()
        call_command("preencher_numero_vendedor", "--dry-run", stdout=saida)

        usuario.refresh_from_db()
        self.assertEqual(usuario.numero_vendedor or "", "")
        self.assertIn("DRY-RUN", saida.getvalue())

    def test_backup_db_gera_arquivo_gzip(self):
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "dev.sqlite3"
            db_path.write_bytes(b"sqlite-dev-content")
            output_dir = Path(tmp_dir) / "backups"
            with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(db_path)}}):
                call_command("backup_db", output_dir=str(output_dir), gzip=True)
            files = list(output_dir.glob("backup_*.zip"))
            self.assertEqual(len(files), 1)
            with zipfile.ZipFile(files[0], "r") as zipf:
                nomes = zipf.namelist()
            self.assertTrue(any(nome.endswith("manifest.json") for nome in nomes))
            self.assertTrue(any(nome.endswith("database.sqlite3.gz") for nome in nomes))

    def test_backup_db_postgres_gera_dump_manifesto_e_media(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            output_dir = base_dir / "backups"
            media_root = base_dir / "media"
            media_root.mkdir()
            (media_root / "logo.txt").write_text("arquivo-media", encoding="utf-8")
            pg_dump = base_dir / "pg_dump.exe"
            pg_dump.write_text("", encoding="utf-8")
            db_settings = {
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "assistencia_dev",
                    "USER": "alexandre",
                    "PASSWORD": "senha",
                    "HOST": "127.0.0.1",
                    "PORT": "5433",
                    "OPTIONS": {"sslmode": "prefer"},
                }
            }
            with override_settings(DATABASES=db_settings, MEDIA_ROOT=media_root):
                with patch("configuracoes.management.commands.backup_db.subprocess.run") as run_mock:
                    def _mock_pg_dump(*args, **kwargs):
                        backup_dirs = [item for item in output_dir.glob("backup_*") if item.is_dir()]
                        if backup_dirs:
                            (backup_dirs[0] / "database.dump").write_bytes(b"dump")
                        return None
                    run_mock.side_effect = _mock_pg_dump
                    call_command(
                        "backup_db",
                        output_dir=str(output_dir),
                        include_media=True,
                        pg_dump=str(pg_dump),
                    )

            run_mock.assert_called_once()
            backup_dirs = [item for item in output_dir.glob("backup_*") if item.is_dir()]
            backup_zips = list(output_dir.glob("backup_*.zip"))
            self.assertEqual(len(backup_dirs), 1)
            self.assertEqual(len(backup_zips), 1)
            self.assertTrue((backup_dirs[0] / "manifest.json").exists())
            self.assertTrue((backup_dirs[0] / "media.zip").exists())
            with zipfile.ZipFile(backup_zips[0], "r") as zipf:
                nomes = zipf.namelist()
            self.assertTrue(any(nome.endswith("database.dump") for nome in nomes))
            self.assertTrue(any(nome.endswith("manifest.json") for nome in nomes))

    def test_restore_db_exige_force(self):
        with TemporaryDirectory() as tmp_dir:
            backup_path = Path(tmp_dir) / "origem.sqlite3"
            backup_path.write_bytes(b"sqlite-origem")
            target_path = Path(tmp_dir) / "destino.sqlite3"
            with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(target_path)}}):
                with self.assertRaises(CommandError):
                    call_command("restore_db", str(backup_path))

    def test_restore_db_por_gzip(self):
        with TemporaryDirectory() as tmp_dir:
            payload = b"sqlite-restaurado"
            backup_path = Path(tmp_dir) / "origem.sqlite3.gz"
            with gzip.open(backup_path, "wb") as fp:
                fp.write(payload)
            target_path = Path(tmp_dir) / "destino.sqlite3"
            with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(target_path)}}):
                call_command("restore_db", str(backup_path), force=True)
            self.assertTrue(target_path.exists())
            self.assertEqual(target_path.read_bytes(), payload)

    def test_restore_db_postgres_executa_pg_restore_e_restaura_media(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            backup_dir = base_dir / "backup_20260519_230000"
            backup_dir.mkdir()
            (backup_dir / "database.dump").write_bytes(b"dump")
            with zipfile.ZipFile(backup_dir / "media.zip", "w") as zipf:
                zipf.writestr("logos/logo.txt", "logo-restaurada")
            media_root = base_dir / "media"
            pg_restore = base_dir / "pg_restore.exe"
            pg_restore.write_text("", encoding="utf-8")
            db_settings = {
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "assistencia_dev",
                    "USER": "alexandre",
                    "PASSWORD": "senha",
                    "HOST": "127.0.0.1",
                    "PORT": "5433",
                    "OPTIONS": {"sslmode": "prefer"},
                }
            }
            with override_settings(DATABASES=db_settings, MEDIA_ROOT=media_root):
                with patch("configuracoes.management.commands.restore_db.subprocess.run") as run_mock:
                    call_command(
                        "restore_db",
                        str(backup_dir),
                        force=True,
                        restore_media=True,
                        pg_restore=str(pg_restore),
                    )

            run_mock.assert_called_once()
            self.assertEqual((media_root / "logos" / "logo.txt").read_text(encoding="utf-8"), "logo-restaurada")

    def test_repair_single_tenant_data_associa_registros_sem_empresa(self):
        empresa = Empresa.objects.create(nome="Empresa Local")
        setup = SetupInicialSistema.get_setup()
        setup.empresa = empresa
        setup.save(update_fields=["empresa"])

        cliente = Cliente.objects.create(nome="Cliente legado")
        ordem = OrdemServico.objects.create(
            cliente=cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
        )
        orcamento = Orcamento.objects.create(cliente=cliente, ordem_servico=ordem)
        produto = Produto.objects.create(nome="Peca legada")

        saida = StringIO()
        call_command("repair_single_tenant_data", "--force", stdout=saida)

        cliente.refresh_from_db()
        ordem.refresh_from_db()
        orcamento.refresh_from_db()
        produto.refresh_from_db()
        self.assertEqual(cliente.empresa, empresa)
        self.assertEqual(ordem.empresa, empresa)
        self.assertEqual(orcamento.empresa, empresa)
        self.assertEqual(produto.empresa, empresa)
        self.assertIn("Registros associados com sucesso", saida.getvalue())

    def test_import_shoficina_dry_run_nao_grava(self):
        with TemporaryDirectory() as tmp_dir:
            clientes_csv = Path(tmp_dir) / "clientes.csv"
            with clientes_csv.open("w", encoding="utf-8", newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=["nome", "documento", "telefone"])
                writer.writeheader()
                writer.writerow({"nome": "Cliente Teste", "documento": "52998224725", "telefone": "11999990000"})
            call_command("import_shoficina_csv", clientes=str(clientes_csv), dry_run=True)
            self.assertEqual(Cliente.objects.count(), 0)

    def test_import_shoficina_importa_produto_e_ignora_documento_invalido(self):
        with TemporaryDirectory() as tmp_dir:
            clientes_csv = Path(tmp_dir) / "clientes.csv"
            produtos_csv = Path(tmp_dir) / "produtos.csv"
            with clientes_csv.open("w", encoding="utf-8", newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=["nome", "documento", "telefone"])
                writer.writeheader()
                writer.writerow({"nome": "Doc Invalido", "documento": "1234", "telefone": "11911112222"})
            with produtos_csv.open("w", encoding="utf-8", newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=["nome", "ean", "preco_venda", "quantidade"])
                writer.writeheader()
                writer.writerow({"nome": "Tela iPhone", "ean": "7890001112223", "preco_venda": "1.234,56", "quantidade": "2"})
            call_command("import_shoficina_csv", clientes=str(clientes_csv), produtos=str(produtos_csv))
            self.assertEqual(Cliente.objects.count(), 1)
            self.assertIsNone(Cliente.objects.first().documento)
            produto = Produto.objects.get(ean="7890001112223")
            self.assertEqual(str(produto.preco_final), "1234.56")
            self.assertEqual(produto.quantidade, 2)

    def test_gerar_base_teste_cria_clientes_e_produtos(self):
        call_command("gerar_base_teste", prefixo="SEEDCMD", clientes=6, produtos=8, limpar=True)

        self.assertEqual(Cliente.objects.filter(nome__startswith="SEEDCMD - ").count(), 6)
        self.assertEqual(Produto.objects.filter(nome__startswith="SEEDCMD - ").count(), 8)
        self.assertGreaterEqual(CategoriaProduto.objects.filter(nome__startswith="SEEDCMD - ").count(), 1)

    def test_gerar_base_teste_permite_somente_limpeza(self):
        call_command("gerar_base_teste", prefixo="SEEDLIMPA", clientes=2, produtos=2, limpar=True)
        self.assertEqual(Cliente.objects.filter(nome__startswith="SEEDLIMPA - ").count(), 2)
        self.assertEqual(Produto.objects.filter(nome__startswith="SEEDLIMPA - ").count(), 2)

        call_command("gerar_base_teste", prefixo="SEEDLIMPA", clientes=0, produtos=0, limpar=True)
        self.assertEqual(Cliente.objects.filter(nome__startswith="SEEDLIMPA - ").count(), 0)
        self.assertEqual(Produto.objects.filter(nome__startswith="SEEDLIMPA - ").count(), 0)


class GarantiaTiposEquipamentoTests(TestCase):
    def test_regra_form_usa_tipos_configurados_da_os(self):
        TipoEquipamentoConfig.objects.update_or_create(
            codigo="secador",
            defaults={"nome": "Secador", "ativo": True},
        )
        TipoEquipamentoConfig.objects.update_or_create(
            codigo="alisador",
            defaults={"nome": "Alisador", "ativo": True},
        )
        form = RegraGarantiaMarcaForm()
        choices = dict(form.fields["tipo_produto"].choices)
        self.assertIn("secador", choices)
        self.assertIn("alisador", choices)

    def test_tipo_produto_label_prioriza_configuracao(self):
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Label")
        marca = MarcaGarantia.objects.create(nome="Marca Label", fornecedor=fornecedor, valor_mao_obra_garantia=0)
        TipoEquipamentoConfig.objects.update_or_create(
            codigo="secador",
            defaults={"nome": "Secador Profissional", "ativo": True},
        )
        regra = RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="secador",
            valor_mao_obra="20.00",
            modalidade_pagamento="pix",
            prazo_pagamento_dias=30,
        )
        self.assertEqual(regra.tipo_produto_label, "Secador Profissional")


class PreviewDocumentoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="admin_preview_pdf",
            password="senha123",
            tipo_usuario="adm",
        )
        self.client.force_login(self.admin)
        self.cliente = Cliente.objects.create(
            nome="Cliente Preview",
            documento="39053344705",
            telefone="11999998888",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Preview",
            modelo_equipamento="Modelo Preview",
            defeito="Teste preview",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        self.orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)

    def test_preview_documento_repassa_preview_e_layout_para_pdf(self):
        response = self.client.get(
            reverse("configuracoes:preview_documento"),
            {
                "tipo": "orcamento",
                "orcamento_id": str(self.orcamento.id),
                "_preview": "1",
                "layout_documentos_preset": "executivo",
                "layout_documentos_cor": "pb",
                "layout_os_exibir_etiqueta_corte": "0",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(response.get("X-Frame-Options"))

        destino = urlparse(response["Location"])
        self.assertEqual(destino.path, reverse("orcamentos:imprimir_orcamento", args=[self.orcamento.id]))
        qs = parse_qs(destino.query)
        self.assertEqual(qs.get("_preview"), ["1"])
        self.assertEqual(qs.get("layout_documentos_preset"), ["executivo"])
        self.assertEqual(qs.get("layout_documentos_cor"), ["pb"])
        self.assertEqual(qs.get("layout_os_exibir_etiqueta_corte"), ["0"])

    def test_configuracao_sistema_renderiza_preview_sem_mojibake(self):
        response = self.client.get(reverse("configuracoes:configuracao_sistema"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("charset=utf-8", response.get("Content-Type", "").lower())
        html = response.content.decode(response.charset or "utf-8")
        texto = unescape(html)
        self.assertIn("Pré-visualização dos Layouts", texto)
        self.assertNotIn("Pr\u00c3\u00a9-visualiza\u00c3\u00a7\u00c3\u00a3o dos Layouts", texto)

    def test_preview_documento_sem_dados_reais_retorna_pdf_mock(self):
        OrdemServico.objects.all().delete()
        Orcamento.objects.all().delete()

        response = self.client.get(
            reverse("configuracoes:preview_documento"),
            {"tipo": "orcamento", "_preview": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIsNone(response.get("X-Frame-Options"))

    def test_sidebar_oculta_setup_inicial_quando_setup_ja_foi_concluido(self):
        garantir_catalogo_padrao()
        empresa = Empresa.objects.create(nome="Empresa Preview")
        linha = LinhaAtuacaoCatalogo.objects.filter(segmento__codigo="assistencia_tecnica").first()
        setup = SetupInicialSistema.get_setup()
        setup.empresa = empresa
        setup.tipo_empresa = "assistencia_tecnica"
        setup.concluido = True
        setup.save()
        if linha:
            setup.linhas_atuacao.set([linha])
            sincronizar_tipos_ativos_por_linhas(LinhaAtuacaoCatalogo.objects.filter(id=linha.id))
        self.client.force_login(self.admin)
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode(response.charset or "utf-8")
        self.assertNotIn("Setup Inicial", html)
        self.assertIn("Revisar assistente inicial", html)

    def test_painel_exibe_bloco_de_proximos_passos(self):
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Proximos passos recomendados")
        self.assertContains(response, "Concluir setup inicial")
        self.assertContains(response, "Validar ordem de servico")

    def test_painel_renderiza_css_do_bloco_styles(self):
        response = self.client.get(reverse("configuracoes:painel"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode(response.charset or "utf-8")
        self.assertIn(".panel-summary {", html)
        self.assertIn(".config-topline {", html)

class SetupInicialSyncCompatTests(TestCase):
    def test_sync_reaproveita_tipo_existente_com_mesmo_nome_e_codigo_legado(self):
        garantir_catalogo_padrao()
        linha = LinhaAtuacaoCatalogo.objects.filter(codigo="informatica").first()
        self.assertIsNotNone(linha)
        tipo_catalogo = TipoEquipamentoCatalogo.objects.filter(linha=linha).order_by("id").first()
        self.assertIsNotNone(tipo_catalogo)
        registro_existente = TipoEquipamentoConfig.objects.filter(nome=tipo_catalogo.nome).first()
        self.assertIsNotNone(registro_existente)
        registro_existente.codigo = "codigo_legado"
        registro_existente.ativo = False
        registro_existente.ordem = 999
        registro_existente.save(update_fields=["codigo", "ativo", "ordem"])

        sincronizar_tipos_ativos_por_linhas(LinhaAtuacaoCatalogo.objects.filter(id=linha.id))

        registro = TipoEquipamentoConfig.objects.get(nome=tipo_catalogo.nome)
        self.assertEqual(registro.codigo, tipo_catalogo.codigo)
        self.assertTrue(registro.ativo)


class RegrasSLATests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.gerente = user_model.objects.create_user(
            username="gerente_sla",
            password="senha123",
            tipo_usuario="gerente",
        )
        self.client.force_login(self.gerente)
        self.cliente = Cliente.objects.create(
            nome="Cliente SLA",
            documento="39053344705",
            telefone="11999998888",
            estado="SP",
        )

    def _criar_ordem(self, numero_sufixo):
        return OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca SLA",
            modelo_equipamento=f"Modelo {numero_sufixo}",
            defeito="Teste SLA",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )

    def test_tela_regras_sla_carrega_com_seed_padrao(self):
        response = self.client.get(reverse("configuracoes:regras_sla"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RegraSLAAlerta.objects.count(), 5)

    def test_calculo_identifica_os_sem_movimentacao(self):
        ordem = self._criar_ordem("SemMov")
        OrdemServico.objects.filter(id=ordem.id).update(data_abertura=timezone.now() - timedelta(days=4))
        pendencias = calcular_pendencias_sla()
        self.assertTrue(any(p.codigo_regra == "os_sem_movimentacao" and p.ordem_id == ordem.id for p in pendencias))

    def test_calculo_identifica_parceiro_externo_atrasado(self):
        ordem = self._criar_ordem("Parceiro")
        guia = GuiaExpedicaoParceiro.objects.create(parceiro_nome="Assistência Parceira", expedida_por=self.gerente)
        item = GuiaExpedicaoItem.objects.create(guia=guia, ordem_servico=ordem, status="expedida")
        GuiaExpedicaoParceiro.objects.filter(id=guia.id).update(expedida_em=timezone.now() - timedelta(days=7))
        pendencias = calcular_pendencias_sla()
        self.assertTrue(any(p.codigo_regra == "parceiro_externo_atrasado" and p.guia_item_id == item.id for p in pendencias))

    def test_painel_sla_permite_filtro_por_regra(self):
        carregar_regras_sla()
        response = self.client.get(reverse("configuracoes:painel_sla"), {"regra": "os_sem_movimentacao"})
        self.assertEqual(response.status_code, 200)


class GarantiaReincidenciaPainelTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.gerente = user_model.objects.create_user(
            username="gerente_garantia_painel",
            password="senha123",
            tipo_usuario="gerente",
        )
        self.tecnico = user_model.objects.create_user(
            username="tecnico_garantia_painel",
            password="senha123",
            tipo_usuario="tecnico",
        )
        self.client.force_login(self.gerente)
        self.cliente = Cliente.objects.create(
            nome="Cliente Garantia",
            documento="39053344705",
            telefone="11999998888",
            estado="SP",
        )

    def test_painel_reincidencias_exibe_resumo(self):
        origem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca X",
            modelo_equipamento="Modelo X",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="concluida",
            fechada=True,
            tecnico_responsavel=self.tecnico,
            data_conclusao=timezone.now() - timedelta(days=5),
        )
        OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca X",
            modelo_equipamento="Modelo X",
            defeito="Nao liga novamente",
            tipo_reparo="Garantia de servico",
            status="diagnosticar",
            tecnico_responsavel=self.tecnico,
            ordem_origem_garantia=origem,
            garantia_reincidencia=True,
            garantia_classificacao_retorno="mesmo_defeito",
        )

        response = self.client.get(reverse("configuracoes:painel_reincidencias"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Garantia e Reincidencias")
        self.assertContains(response, "Total de retornos")


class IntegracoesLogsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.gerente = user_model.objects.create_user(
            username="gerente_integracoes",
            password="senha123",
            tipo_usuario="gerente",
        )
        self.client.force_login(self.gerente)

    def test_registra_evento_integracao_manual(self):
        registrar_evento_integracao(
            canal="email",
            evento="notificacao.orcamento",
            status="sucesso",
            destino="cliente@dominio.com",
            payload={"ordem": "OS0001"},
            resposta="enviado",
        )
        self.assertEqual(IntegracaoEventoLog.objects.count(), 1)

    @patch.dict("os.environ", {"WEBHOOK_INTERNO_URL": ""}, clear=False)
    def test_emitir_evento_interno_gera_log_quando_endpoint_ausente(self):
        resultado = emitir_evento_interno("configuracoes.alterada", {"origem": "teste"})
        self.assertFalse(resultado["enviado"])
        self.assertTrue(IntegracaoEventoLog.objects.filter(canal="webhook", evento="configuracoes.alterada").exists())

    def test_tela_logs_integracoes(self):
        IntegracaoEventoLog.objects.create(canal="sistema", evento="notificacao.manual", status="sucesso")
        response = self.client.get(reverse("configuracoes:logs_integracoes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "notificacao.manual")

    def test_popular_modelos_por_evento(self):
        response = self.client.post(
            reverse("configuracoes:modelos_mensagem"),
            {"form_type": "popular_eventos"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        total_eventos = len(EVENTOS_COMUNICACAO)
        self.assertGreaterEqual(
            ModeloMensagem.objects.exclude(evento_chave="").count(),
            total_eventos,
        )

