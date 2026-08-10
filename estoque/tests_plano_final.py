from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from configuracoes.models import Empresa, User
from estoque.models import PontoOperacional, Produto, ProdutoKitItem, UbicacaoEstoque
from estoque.services import criar_solicitacao_saida_estoque, registrar_movimentacao_estoque
from estoque.services_produto import calcular_rentabilidade_kit


class FechamentoPlanoEstoqueTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome="Empresa Homologacao Estoque",
            regime_tributario="simples",
            modo_tributario="basico",
            aliquota_comercio=Decimal("6.00"),
        )
        self.user = User.objects.create_user(
            username="homologador_estoque",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
        )
        self.ponto = PontoOperacional.objects.create(empresa=self.empresa, codigo="PO3-H", nome="Loja")
        self.ubicacao = UbicacaoEstoque.objects.create(ponto_operacional=self.ponto, codigo="A1", ativo=True)

    def _produto(self, nome, sku, custo, preco, quantidade=10):
        return Produto.objects.create(
            empresa=self.empresa,
            nome=nome,
            sku=sku,
            custo_unitario=Decimal(custo),
            preco_final=Decimal(preco),
            quantidade=quantidade,
            ponto_operacional=self.ponto,
            ubicacao_padrao=self.ubicacao,
            ativo=True,
        )

    def test_rentabilidade_kit_consolida_custo_e_capacidade(self):
        kit = self._produto("Kit limpeza", "KIT-001", "0", "100.00")
        componente_a = self._produto("Fluido", "COMP-001", "10.00", "20.00", quantidade=8)
        componente_b = self._produto("Pano", "COMP-002", "5.00", "10.00", quantidade=3)
        ProdutoKitItem.objects.create(produto_kit=kit, componente=componente_a, quantidade=2)
        ProdutoKitItem.objects.create(produto_kit=kit, componente=componente_b, quantidade=1)

        resultado = calcular_rentabilidade_kit(kit)

        self.assertEqual(resultado["custo_componentes"], Decimal("25.00"))
        self.assertEqual(resultado["quantidade_montavel"], 3)
        self.assertEqual(resultado["tributos"], Decimal("6.00"))
        self.assertEqual(resultado["lucro"], Decimal("69.00"))

    def test_api_precificacao_usa_motor_do_servidor_e_aliquota_da_empresa(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("estoque:api_simular_precificacao"),
            {
                "custo_unitario": "50.00",
                "margem_lucro": "20.00",
                "margem_minima": "10.00",
                "taxa_cartao": "2.00",
                "preco_final": "80.00",
                "modo_preco": "avancado",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["aliquota"], "6.000")
        self.assertIn("canais", payload["resultado"])

    def test_comprovante_pdf_oferta_fica_disponivel_na_empresa_correta(self):
        produto = self._produto("Capa cortesia", "CAPA-001", "12.00", "49.90", quantidade=0)
        registrar_movimentacao_estoque(
            produto=produto,
            tipo="entrada",
            quantidade=2,
            destino=self.ponto,
            destino_ubicacao_ref=self.ubicacao,
            valor_unitario_custo=Decimal("12.00"),
            observacao="Entrada para homologacao",
        )
        solicitacao = criar_solicitacao_saida_estoque(
            produto=produto,
            tipo="oferta",
            quantidade=1,
            origem=self.ponto,
            origem_ubicacao=self.ubicacao,
            finalidade="brinde_comercial",
            beneficiario_nome="Cliente fidelidade",
            observacao="Cortesia comercial documentada",
            usuario=self.user,
            aprovar_automaticamente=True,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("estoque:comprovante_solicitacao_saida", args=[solicitacao.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 3000)

    def test_perda_avaria_vencimento_e_uso_interno_baixam_pelo_custo(self):
        for indice, tipo in enumerate(("avaria", "perda", "vencimento", "uso_interno"), start=1):
            with self.subTest(tipo=tipo):
                produto = self._produto(f"Item {tipo}", f"SAIDA-{indice}", "12.00", "49.90", quantidade=0)
                registrar_movimentacao_estoque(
                    produto=produto, tipo="entrada", quantidade=2, destino=self.ponto,
                    destino_ubicacao_ref=self.ubicacao, valor_unitario_custo=Decimal("12.00"),
                    observacao="Entrada para teste de baixa",
                )
                movimento = registrar_movimentacao_estoque(
                    produto=produto, tipo=tipo, quantidade=1, origem=self.ponto,
                    origem_ubicacao=self.ubicacao, observacao=f"Motivo documentado: {tipo}", usuario=self.user,
                )
                produto.refresh_from_db()
                self.assertEqual(movimento.quantidade, -1)
                self.assertEqual(movimento.valor_unitario_custo, Decimal("12.00"))
                self.assertEqual(movimento.valor_total_custo, Decimal("12.00"))
                self.assertEqual(produto.quantidade, 1)
