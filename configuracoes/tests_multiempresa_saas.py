from django.test import TestCase

from caixa.models import CategoriaFinanceira, CentroCusto, FormaPagamento
from configuracoes.models import ConfiguracaoOrdemServico, ConfiguracaoSistema, Empresa, User, UsuarioEmpresa
from configuracoes.permissions import has_sensitive_permission, is_management_user
from configuracoes.services.onboarding_empresa import provisionar_empresa
from configuracoes.services.tenant_runtime import definir_empresa_runtime, restaurar_empresa_runtime
from estoque.models import PontoOperacional


class PreparacaoSaasTests(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(nome="Tenant A")
        self.user = User.objects.create_user(
            username="admin_tenant",
            password="senha-forte-123",
            tipo_usuario="adm",
            empresa=self.empresa_a,
        )

    def test_configuracoes_sao_independentes_por_empresa(self):
        empresa_b = Empresa.objects.create(nome="Tenant B")
        config_a = ConfiguracaoSistema.get_configuracao(empresa=self.empresa_a)
        config_b = ConfiguracaoSistema.get_configuracao(empresa=empresa_b)
        os_a = ConfiguracaoOrdemServico.get_configuracao(empresa=self.empresa_a)
        os_b = ConfiguracaoOrdemServico.get_configuracao(empresa=empresa_b)
        config_a.ddd_padrao = "21"
        config_a.save(update_fields=["ddd_padrao"])

        self.assertNotEqual(config_a.pk, config_b.pk)
        self.assertNotEqual(os_a.pk, os_b.pk)
        self.assertNotEqual(os_a.prefixo_os, os_b.prefixo_os)
        self.assertNotEqual(config_b.ddd_padrao, "21")

    def test_perfil_e_permissao_podem_variar_por_empresa(self):
        vinculo = UsuarioEmpresa.objects.get(usuario=self.user, empresa=self.empresa_a)
        vinculo.tipo_usuario = "tecnico"
        vinculo.permissoes = {"perm_estoque_oferta": False, "perm_estoque_cedencia": True}
        vinculo.save()
        self.user._tenant_tipo_usuario = vinculo.tipo_usuario
        self.user._tenant_permissoes = vinculo.permissoes

        self.assertFalse(is_management_user(self.user))
        self.assertFalse(has_sensitive_permission(self.user, "perm_estoque_oferta"))
        self.assertTrue(has_sensitive_permission(self.user, "perm_estoque_cedencia"))

    def test_onboarding_cria_estrutura_operacional_isolada(self):
        empresa_b = Empresa(nome="Tenant Provisionado")
        provisionar_empresa(empresa=empresa_b, usuario_admin=self.user)

        self.assertTrue(UsuarioEmpresa.objects.filter(usuario=self.user, empresa=empresa_b, ativo=True).exists())
        self.assertGreaterEqual(PontoOperacional.objects.filter(empresa=empresa_b).count(), 2)
        self.assertGreaterEqual(FormaPagamento.objects.filter(empresa=empresa_b).count(), 5)
        self.assertGreaterEqual(CentroCusto.objects.filter(empresa=empresa_b).count(), 4)
        self.assertGreaterEqual(CategoriaFinanceira.objects.filter(empresa=empresa_b).count(), 8)

    def test_contexto_runtime_resolve_configuracao_da_empresa_ativa(self):
        token = definir_empresa_runtime(self.empresa_a)
        try:
            config = ConfiguracaoSistema.get_configuracao()
        finally:
            restaurar_empresa_runtime(token)
        self.assertEqual(config.empresa, self.empresa_a)
