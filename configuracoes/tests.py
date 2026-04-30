from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.utils import override_settings
from django.utils import timezone
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from tempfile import TemporaryDirectory
from html import unescape
import csv
import gzip
from io import BytesIO, StringIO
from PIL import Image
from configuracoes.models import ConfiguracaoSistema, Empresa, FornecedorGarantia, MarcaGarantia
from configuracoes.forms import ConfiguracaoSistemaForm, EmpresaForm, MarcaGarantiaForm, RegraGarantiaMarcaForm
from configuracoes.permissions import has_sensitive_permission, require_sensitive_permission
from django.conf import settings
from clientes.models import Cliente
from estoque.models import CategoriaProduto, Produto
from configuracoes.models import RegraGarantiaMarca, TipoEquipamentoConfig
from ordens.models import OrdemServico
from orcamentos.models import Orcamento


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
            "perm_caixa_criar_conta_pagar",
            "perm_caixa_baixar_conta_pagar",
            "perm_caixa_cancelar_conta_pagar",
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
        self.assertContains(response, "Gerente não pode criar usuário Administrador.")

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
        self.assertContains(response, "A senha deve conter ao menos uma letra maiuscula.")
        self.assertContains(response, "A senha deve conter ao menos um caractere especial.")

    def test_backup_permite_gerente(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("configuracoes:backup_banco"))
        self.assertEqual(response.status_code, 302)
        backup_dir = Path(settings.BASE_DIR) / "backups"
        self.assertTrue(backup_dir.exists())

    def test_backup_bloqueia_atendente(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("configuracoes:backup_banco"))
        self.assertEqual(response.status_code, 403)

    def test_caixa_financeiro_permite_funcao_extra(self):
        self.tecnico.acesso_caixa_financeiro_extra = True
        self.tecnico.save(update_fields=["acesso_caixa_financeiro_extra"])
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("caixa:contas_receber"))
        self.assertEqual(response.status_code, 200)

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
            files = list(output_dir.glob("db_*.sqlite3.gz"))
            self.assertEqual(len(files), 1)

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
        self.assertNotIn("PrÃ©-visualizaÃ§Ã£o dos Layouts", texto)
