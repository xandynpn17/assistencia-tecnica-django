from django.test import TestCase
from django.urls import reverse

from caixa.models import CategoriaFinanceira, CentroCusto
from configuracoes.models import Empresa, User
from estoque.models import CategoriaProduto, PontoOperacional


class DREFiltrosGerenciaisTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa DRE Filtros")
        self.user = User.objects.create_user(
            username="gestor_dre_filtros",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
            perm_caixa_ver_dre=True,
        )
        self.ponto = PontoOperacional.objects.create(empresa=self.empresa, codigo="DRE1", nome="Loja DRE")
        self.categoria_produto = CategoriaProduto.objects.create(empresa=self.empresa, nome="Acessorios")
        self.categoria_financeira = CategoriaFinanceira.objects.create(empresa=self.empresa, nome="Marketing", tipo="saida")
        self.centro = CentroCusto.objects.create(empresa=self.empresa, nome="Comercial")
        self.client.force_login(self.user)

    def test_todos_os_filtros_gerenciais_sao_aplicaveis_em_conjunto(self):
        response = self.client.get(
            reverse("caixa:dre"),
            {
                "ponto": self.ponto.id,
                "categoria_produto": self.categoria_produto.id,
                "categoria_financeira": self.categoria_financeira.id,
                "centro_custo": self.centro.id,
                "motivo_estoque": "oferta",
                "campanha": "Fidelizacao",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filtros_gerenciais_ativos"])
        self.assertFalse(response.context["periodo_fechavel"])
