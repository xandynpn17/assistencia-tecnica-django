from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import Caixa
from configuracoes.models import Empresa
from estoque.forms import MovimentacaoEstoqueForm
from estoque.models import MovimentacaoEstoque, PontoOperacional, Produto, ReservaEstoque, SaldoEstoquePonto


class ConsultaArtigosTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="estoque_tester",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.tecnico = user_model.objects.create_user(
            username="estoque_tecnico",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.client.force_login(self.user)

        self.ponto_loja = PontoOperacional.objects.create(codigo="PO3", nome="Loja")
        self.ponto_avaria = PontoOperacional.objects.create(codigo="AVARIA", nome="Avariados")
        self.produto = Produto.objects.create(
            nome="Tela A10",
            sku="SKU-TELA-A10",
            ean="7890001112223",
            descricao="Peca de reposicao",
            preco_final=Decimal("150.00"),
            preco=Decimal("150.00"),
            quantidade=10,
            estoque_minimo=1,
            ponto_operacional=self.ponto_loja,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=self.ponto_loja, quantidade=8)
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=self.ponto_avaria, quantidade=2)
        Caixa.objects.create(aberto=True, saldo_inicial=0)
        Empresa.objects.create(
            nome="Empresa Teste",
            regime_tributario="simples",
            modo_tributario="basico",
            aliquota_comercio=6,
            aliquota_servico=8,
        )

    def test_pagina_consulta_artigos(self):
        response = self.client.get(reverse("estoque:consulta_artigos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Consulta de Artigos")

    def test_busca_por_sku(self):
        response = self.client.get(reverse("estoque:api_consulta_artigos"), {"q": "SKU-TELA-A10"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["resultados"]), 1)

    def test_venda_bloqueada_para_ponto_nao_permitido(self):
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_avaria.id,
                "quantidade": 1,
                "funcionario_numero": "12",
                "metodo": "pix",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Venda permitida", response.json()["erro"])

    def test_venda_exige_numero_vendedor_com_2_digitos(self):
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": "9",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Numero de vendedor invalido", response.json()["erro"])

    def test_cria_reserva_com_codigo(self):
        response = self.client.post(
            reverse("estoque:api_criar_reserva"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "nome": "Cliente Teste",
                "telefone": "11999998888",
                "valido_ate": (timezone.localdate() + timedelta(days=2)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["codigo_reserva"].startswith("RES-"))

    def test_produto_sem_ean_gera_codigo_13_digitos_e_po3(self):
        produto = Produto.objects.create(
            nome="Conector USB",
            sku="SKU-USB-01",
            descricao="Peca",
            preco_final=Decimal("20.00"),
            preco=Decimal("20.00"),
            quantidade=1,
            ativo=True,
        )
        self.assertEqual(len(produto.ean), 13)
        self.assertEqual(produto.ponto_operacional.codigo, "PO3")

    def test_transferencia_po3_para_po2_exige_ubicacao(self):
        po3, _ = PontoOperacional.objects.get_or_create(codigo="PO3", defaults={"nome": "Loja"})
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        form = MovimentacaoEstoqueForm(
            data={
                "produto": self.produto.id,
                "tipo": "transferencia",
                "quantidade": 1,
                "origem": po3.id,
                "destino": po2.id,
                "destino_ubicacao": "",
                "observacao": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("destino_ubicacao", form.errors)

    def test_expirar_reservas_vencidas(self):
        ReservaEstoque.objects.create(
            codigo_reserva="RES-EXPIRA1",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente",
            valido_ate=timezone.localdate() - timedelta(days=1),
            status="ativa",
            usuario=self.user,
        )
        response = self.client.post(reverse("estoque:api_expirar_reservas"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reservas_expiradas"], 1)
        self.assertEqual(ReservaEstoque.objects.get(codigo_reserva="RES-EXPIRA1").status, "expirada")

    def test_converter_e_cancelar_reserva_movimenta_saldo(self):
        reserva = ReservaEstoque.objects.create(
            codigo_reserva="RES-CYCLE1",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=2,
            nome_contato="Cliente",
            valido_ate=timezone.localdate() + timedelta(days=3),
            status="ativa",
            usuario=self.user,
        )
        saldo_inicial = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja).quantidade
        resp_conv = self.client.post(reverse("estoque:api_converter_reserva", args=[reserva.codigo_reserva]))
        self.assertEqual(resp_conv.status_code, 200)
        saldo_convertida = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja).quantidade
        self.assertEqual(saldo_convertida, saldo_inicial - 2)
        self.assertTrue(MovimentacaoEstoque.objects.filter(observacao__icontains="RES-CYCLE1").exists())

        resp_cancel = self.client.post(reverse("estoque:api_cancelar_reserva", args=[reserva.codigo_reserva]), {"motivo": "teste"})
        self.assertEqual(resp_cancel.status_code, 200)
        saldo_final = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja).quantidade
        self.assertEqual(saldo_final, saldo_inicial)

    def test_inventario_finalizar_aplica_ajuste(self):
        resp_ini = self.client.post(reverse("estoque:api_inventario_iniciar"), {"ponto_id": self.ponto_loja.id})
        self.assertEqual(resp_ini.status_code, 200)
        inventario_id = resp_ini.json()["inventario_id"]
        resp_item = self.client.post(
            reverse("estoque:api_inventario_adicionar_item", args=[inventario_id]),
            {"produto_id": self.produto.id, "quantidade_contada": 10},
        )
        self.assertEqual(resp_item.status_code, 200)
        resp_fim = self.client.post(reverse("estoque:api_inventario_finalizar", args=[inventario_id]))
        self.assertEqual(resp_fim.status_code, 200)
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        self.assertEqual(saldo.quantidade, 10)

    def test_alertas_estoque_minimo(self):
        self.produto.estoque_minimo = 10
        self.produto.save(update_fields=["estoque_minimo"])
        response = self.client.get(reverse("estoque:api_alertas_estoque"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(item["id"] == self.produto.id for item in response.json()["resultados"]))

    def test_tecnico_nao_pode_venda_rapida(self):
        self.client.force_login(self.tecnico)
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": "F123",
                "metodo": "pix",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_venda_rapida_cria_pre_reserva_sem_baixa_imediata(self):
        saldo_inicial = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja).quantidade
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": "12",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        venda_id = data["venda_id"]
        self.assertTrue(data["cesto_codigo"].startswith("CES-"))
        from estoque.models import VendaRapidaEstoque

        venda = VendaRapidaEstoque.objects.get(id=venda_id)
        self.assertEqual(venda.status, "pre_reserva")
        saldo_final = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja).quantidade
        self.assertEqual(saldo_final, saldo_inicial)

    def test_finalizar_cesto_gera_guia(self):
        response_item = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": "12",
            },
        )
        self.assertEqual(response_item.status_code, 200)
        cesto_codigo = response_item.json()["cesto_codigo"]
        response_guia = self.client.post(reverse("estoque:api_cesto_finalizar"), {"cesto_codigo": cesto_codigo})
        self.assertEqual(response_guia.status_code, 200)
        data = response_guia.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["guia"].startswith("GUIA-"))

    def test_preco_sugerido_simples_comercio(self):
        p = Produto.objects.create(
            nome="Mouse USB",
            ean="7891110002223",
            custo_unitario=Decimal("100.00"),
            custo_operacional=Decimal("0.00"),
            margem_lucro=Decimal("20.00"),
            taxa_cartao=Decimal("2.00"),
            tipo_item="produto",
            preco_final=Decimal("0.00"),
            ativo=True,
            ponto_operacional=self.ponto_loja,
        )
        # 100 / (1 - 0.06 - 0.02 - 0.20) = 138.888...
        self.assertAlmostEqual(float(p.preco_sugerido), 138.89, places=2)

    def test_preco_sugerido_override_manual(self):
        p = Produto.objects.create(
            nome="Servico Labor",
            ean="7891110002224",
            custo_unitario=Decimal("100.00"),
            custo_operacional=Decimal("0.00"),
            margem_lucro=Decimal("10.00"),
            taxa_cartao=Decimal("0.00"),
            tipo_item="servico",
            usar_aliquota_manual=True,
            aliquota_manual=Decimal("5.00"),
            preco_final=Decimal("0.00"),
            ativo=True,
            ponto_operacional=self.ponto_loja,
        )
        # 100 / (1 - 0.05 - 0.10) = 117.647...
        self.assertAlmostEqual(float(p.preco_sugerido), 117.65, places=2)

    def test_venda_rapida_permite_pre_reserva_com_saldo_insuficiente(self):
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo.quantidade = 0
        saldo.save(update_fields=["quantidade"])
        self.produto.quantidade = 0
        self.produto.save(update_fields=["quantidade"])

        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 3,
                "funcionario_numero": "12",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_reposicao_inteligente_tela(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=5)
        self.produto.estoque_minimo = 10
        self.produto.save(update_fields=["estoque_minimo"])
        response = self.client.get(reverse("estoque:reposicao_estoque"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reposicao Inteligente")

    def test_reposicao_inteligente_post_transfere_po2_para_po3(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=7)
        saldo_loja = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo_loja.quantidade = 1
        saldo_loja.save(update_fields=["quantidade"])
        response = self.client.post(
            reverse("estoque:reposicao_estoque"),
            {"produto_id": self.produto.id, "quantidade": 3},
        )
        self.assertEqual(response.status_code, 302)
        s2 = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=po2)
        s3 = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        self.assertEqual(s2.quantidade, 4)
        self.assertEqual(s3.quantidade, 4)

    def test_indicadores_estoque_tela(self):
        response = self.client.get(reverse("estoque:indicadores_estoque"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Indicadores de Estoque")
