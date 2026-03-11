from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import Caixa
from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema, Empresa
from estoque.forms import MovimentacaoEstoqueForm, ProdutoForm
from estoque.models import (
    InventarioEstoque,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ReservaEstoque,
    SaldoEstoquePonto,
    VendaRapidaEstoque,
)
from ordens.models import OrdemServico, ServicoPeca


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
        ConfiguracaoSistema.get_configuracao()

    def test_pagina_consulta_artigos(self):
        response = self.client.get(reverse("estoque:consulta_artigos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Consulta de Artigos")
        self.assertTrue(response.context["pode_venda_mostrador"])

    def test_busca_por_sku(self):
        response = self.client.get(reverse("estoque:api_consulta_artigos"), {"q": "SKU-TELA-A10"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["resultados"]), 1)

    def test_consulta_artigos_sem_termo_retorna_vazio(self):
        response = self.client.get(reverse("estoque:api_consulta_artigos"), {"q": ""})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["resultados"], [])

    def test_buscar_produtos_redireciona_para_consulta_artigos(self):
        response = self.client.get(reverse("estoque:buscar_produtos"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("estoque:consulta_artigos"))

    def test_busca_por_modelo_compativel(self):
        self.produto.modelos_compativeis = "A10, A20, A30"
        self.produto.save(update_fields=["modelos_compativeis"])
        response = self.client.get(reverse("estoque:api_consulta_artigos"), {"q": "A20"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["resultados"]), 1)

    def test_sugestao_ranking_por_historico(self):
        produto_hist = Produto.objects.create(
            nome="Motor Turbo X",
            sku="SKU-MOTOR-TURBO",
            ean="7894561230001",
            descricao="Motor para secador",
            preco_final=Decimal("120.00"),
            preco=Decimal("120.00"),
            quantidade=5,
            estoque_minimo=1,
            ponto_operacional=self.ponto_loja,
            modelos_compativeis="SEC-9000",
            permite_os=True,
            ativo=True,
        )
        Produto.objects.create(
            nome="Motor Genérico",
            sku="SKU-MOTOR-GEN",
            ean="7894561230002",
            descricao="Motor similar",
            preco_final=Decimal("110.00"),
            preco=Decimal("110.00"),
            quantidade=5,
            estoque_minimo=1,
            ponto_operacional=self.ponto_loja,
            modelos_compativeis="SEC-9000",
            permite_os=True,
            ativo=True,
        )
        cliente = Cliente.objects.create(
            nome="Cliente Historico",
            documento="52998224725",
            telefone="11999998888",
        )
        ordem = OrdemServico.objects.create(
            cliente=cliente,
            tipo_equipamento="secador",
            marca_equipamento="Marca X",
            modelo_equipamento="SEC-9000",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
        )
        ServicoPeca.objects.create(
            ordem=ordem,
            tipo="peca",
            nome=produto_hist.nome,
            quantidade=1,
            valor_unitario=Decimal("120.00"),
        )

        response = self.client.get(
            reverse("estoque:api_sugerir_pecas_os"),
            {"modelo": "SEC-9000"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["resultados"]
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]["id"], produto_hist.id)
        self.assertGreaterEqual(data[0].get("frequencia_historica", 0), 1)

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
        self.assertIn("Número de vendedor inválido", response.json()["erro"])

    def test_venda_rapida_bloqueia_item_servico(self):
        servico = Produto.objects.create(
            nome="Servico Diagnostico",
            sku="SKU-SVC-01",
            ean="7890001112299",
            tipo_item="servico",
            permite_os=True,
            preco_final=Decimal("50.00"),
            preco=Decimal("50.00"),
            quantidade=0,
            ponto_operacional=self.ponto_loja,
            ativo=True,
        )
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": servico.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": "12",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_venda_rapida_bloqueia_produto_nao_vendavel(self):
        produto_bloqueado = Produto.objects.create(
            nome="Peca Bloqueada",
            sku="SKU-BLOQ-01",
            ean="7890001112288",
            is_servico=False,
            permite_os=False,
            preco_final=Decimal("30.00"),
            preco=Decimal("30.00"),
            quantidade=2,
            ponto_operacional=self.ponto_loja,
            ativo=True,
        )
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": produto_bloqueado.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": "12",
            },
        )
        self.assertEqual(response.status_code, 404)

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

    def test_cria_reserva_rejeita_data_invalida(self):
        response = self.client.post(
            reverse("estoque:api_criar_reserva"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "nome": "Cliente Teste",
                "telefone": "11999998888",
                "valido_ate": "31/12/2030",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Data de validade inválida", response.json()["erro"])

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

    def test_produto_sem_sku_gera_codigo(self):
        produto = Produto.objects.create(
            nome="Resistencia X",
            descricao="Peca",
            preco_final=Decimal("25.00"),
            preco=Decimal("25.00"),
            quantidade=1,
            ativo=True,
        )
        self.assertTrue((produto.sku or "").startswith("SKU-"))

    def test_produto_form_rejeita_ean_com_tamanho_invalido(self):
        form = ProdutoForm(
            data={
                "nome": "Produto EAN inválido",
                "ean": "1234",
                "tipo_item": "produto",
                "modo_preco": "avancado",
                "preco_final": "10.00",
                "quantidade": "1",
                "estoque_minimo": "0",
                "data_entrada": timezone.localdate().isoformat(),
                "ativo": "on",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("ean", form.errors)
        self.assertIn("13 dígitos", str(form.errors["ean"]))

    def test_produto_form_servico_rejeita_estoque_positivo(self):
        form = ProdutoForm(
            data={
                "nome": "Serviço com estoque",
                "tipo_item": "servico",
                "modo_preco": "avancado",
                "preco_final": "50.00",
                "quantidade": "2",
                "estoque_minimo": "1",
                "data_entrada": timezone.localdate().isoformat(),
                "ativo": "on",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("quantidade", form.errors)
        self.assertIn("estoque_minimo", form.errors)

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

    def test_transferencia_exige_quantidade_positiva(self):
        po3, _ = PontoOperacional.objects.get_or_create(codigo="PO3", defaults={"nome": "Loja"})
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        form = MovimentacaoEstoqueForm(
            data={
                "produto": self.produto.id,
                "tipo": "transferencia",
                "quantidade": 0,
                "origem": po3.id,
                "destino": po2.id,
                "destino_ubicacao": "A1",
                "observacao": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("quantidade", form.errors)

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
        data = resp_fim.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["resumo"]["itens_ajustados"], 1)
        self.assertEqual(data["resumo"]["unidades_ajustadas"], 2)
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        self.assertEqual(saldo.quantidade, 10)

    def test_inventario_iniciar_bloqueia_quando_ja_existe_aberto_no_ponto(self):
        aberto = InventarioEstoque.objects.create(
            ponto_operacional=self.ponto_loja,
            status="aberto",
            observacao="Aberto manualmente",
            usuario=self.user,
        )
        response = self.client.post(reverse("estoque:api_inventario_iniciar"), {"ponto_id": self.ponto_loja.id})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(response.json()["inventario_id"], aberto.id)

    def test_inventario_item_rejeita_quantidade_negativa(self):
        resp_ini = self.client.post(reverse("estoque:api_inventario_iniciar"), {"ponto_id": self.ponto_loja.id})
        inventario_id = resp_ini.json()["inventario_id"]
        response = self.client.post(
            reverse("estoque:api_inventario_adicionar_item", args=[inventario_id]),
            {"produto_id": self.produto.id, "quantidade_contada": -1},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("não pode ser negativa", response.json()["erro"])

    def test_inventario_finalizar_sem_itens_rejeita(self):
        resp_ini = self.client.post(reverse("estoque:api_inventario_iniciar"), {"ponto_id": self.ponto_loja.id})
        inventario_id = resp_ini.json()["inventario_id"]
        response = self.client.post(reverse("estoque:api_inventario_finalizar", args=[inventario_id]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("sem itens", response.json()["erro"])

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

    def test_venda_rapida_rejeita_cesto_ja_finalizado(self):
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

        response_novo_item = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": "12",
                "cesto_codigo": cesto_codigo,
            },
        )
        self.assertEqual(response_novo_item.status_code, 409)
        self.assertIn("ja foi finalizado", response_novo_item.json()["erro"])

    def test_remover_item_cesto_cancela_pre_reserva(self):
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
        venda_id = response_item.json()["venda_id"]
        cesto_codigo = response_item.json()["cesto_codigo"]

        response_remove = self.client.post(
            reverse("estoque:api_cesto_item_remover", args=[venda_id]),
            {"cesto_codigo": cesto_codigo},
        )
        self.assertEqual(response_remove.status_code, 200)
        data = response_remove.json()
        self.assertEqual(data["total"], 0.0)
        self.assertEqual(data["itens"], [])
        self.assertEqual(VendaRapidaEstoque.objects.get(id=venda_id).status, "cancelada")

    def test_finalizar_cesto_atribui_guia_para_item_sem_guia_no_mesmo_cesto(self):
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
        guia = response_guia.json()["guia"]

        venda_extra = VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero="12",
            cesto_codigo=cesto_codigo,
            status="pre_reserva",
            usuario=self.user,
        )
        response_guia_2 = self.client.post(reverse("estoque:api_cesto_finalizar"), {"cesto_codigo": cesto_codigo})
        self.assertEqual(response_guia_2.status_code, 200)
        venda_extra.refresh_from_db()
        self.assertEqual(venda_extra.guia_pagamento, guia)

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

    def test_preco_sugerido_modo_simples(self):
        p = Produto.objects.create(
            nome="Motor Simples",
            ean="7891110002299",
            custo_unitario=Decimal("100.00"),
            custo_operacional=Decimal("10.00"),
            margem_lucro=Decimal("100.00"),
            modo_preco="simples",
            preco_final=Decimal("0.00"),
            ativo=True,
            ponto_operacional=self.ponto_loja,
        )
        self.assertAlmostEqual(float(p.preco_sugerido), 220.0, places=2)

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

    def test_venda_rapida_bloqueia_pre_reserva_sem_saldo_quando_regra_ativa(self):
        cfg = ConfiguracaoSistema.get_configuracao()
        cfg.estoque_pre_reserva_exige_saldo = True
        cfg.save(update_fields=["estoque_pre_reserva_exige_saldo", "data_atualizacao"])

        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo.quantidade = 0
        saldo.save(update_fields=["quantidade"])

        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": "12",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Saldo insuficiente", response.json()["erro"])

    def test_movimentacao_ajuste_exige_observacao(self):
        po3 = self.ponto_loja
        form = MovimentacaoEstoqueForm(
            data={
                "produto": self.produto.id,
                "tipo": "ajuste",
                "quantidade": 1,
                "origem": po3.id,
                "destino": "",
                "destino_ubicacao": "",
                "observacao": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("observacao", form.errors)

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


class InventarioCiclicoCommandTests(TestCase):
    def test_gera_inventario_para_pontos_ativos_sem_inventario_aberto(self):
        po3 = PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Estoque", ativo=True)
        InventarioEstoque.objects.create(ponto_operacional=po2, status="aberto")
        cfg = ConfiguracaoSistema.get_configuracao()
        cfg.inventario_ciclico_dias = 15
        cfg.save(update_fields=["inventario_ciclico_dias", "data_atualizacao"])

        call_command("gerar_inventario_ciclico", force=True)

        self.assertTrue(
            InventarioEstoque.objects.filter(
                ponto_operacional=po3,
                status="aberto",
                observacao__icontains="Inventário cíclico automático",
            ).exists()
        )
        self.assertEqual(
            InventarioEstoque.objects.filter(ponto_operacional=po2, status="aberto").count(),
            1,
        )
        cfg.refresh_from_db()
        self.assertEqual(cfg.inventario_ultima_execucao, timezone.localdate())

    def test_nao_executa_antes_da_proxima_janela_sem_force(self):
        PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)
        cfg = ConfiguracaoSistema.get_configuracao()
        cfg.inventario_ciclico_dias = 30
        cfg.inventario_ultima_execucao = timezone.localdate()
        cfg.save(update_fields=["inventario_ciclico_dias", "inventario_ultima_execucao", "data_atualizacao"])

        call_command("gerar_inventario_ciclico")

        self.assertEqual(InventarioEstoque.objects.count(), 0)


class AuditoriaEstoqueCommandTests(TestCase):
    def test_auditar_estoque_detecta_divergencia_e_corrige_total(self):
        po3 = PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)
        produto = Produto.objects.create(
            nome="Placa Controle",
            ean="7891234500001",
            sku="SKU-AUD-01",
            preco_final=Decimal("90.00"),
            preco=Decimal("90.00"),
            quantidade=10,
            ponto_operacional=po3,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=po3, quantidade=3)

        out = StringIO()
        call_command("auditar_estoque", stdout=out)
        produto.refresh_from_db()
        self.assertEqual(produto.quantidade, 10)
        self.assertIn("Divergências de total: 1", out.getvalue())

        out_fix = StringIO()
        call_command("auditar_estoque", corrigir_totais=True, stdout=out_fix)
        produto.refresh_from_db()
        self.assertEqual(produto.quantidade, 3)
        self.assertIn("Totais reconciliados: 1", out_fix.getvalue())

    def test_auditar_estoque_pode_falhar_quando_existe_divergencia(self):
        po3 = PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)
        produto = Produto.objects.create(
            nome="Capacitor",
            ean="7891234500002",
            sku="SKU-AUD-02",
            preco_final=Decimal("10.00"),
            preco=Decimal("10.00"),
            quantidade=1,
            ponto_operacional=po3,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=po3, quantidade=-1)

        with self.assertRaises(CommandError):
            call_command("auditar_estoque", falhar_se_divergir=True)
