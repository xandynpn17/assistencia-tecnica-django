from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import Caixa
from caixa.models import CustoFixoMensal
from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema, Empresa
from estoque.forms import MovimentacaoEstoqueForm, ProdutoForm
from estoque.models import (
    EstoqueEvento,
    ConfiguracaoRateioCustoFixo,
    InventarioEstoque,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ProdutoHistorico,
    ProdutoEquivalente,
    ProdutoPrecoTabela,
    RateioCustoFixoCompetencia,
    ReservaEstoque,
    SaldoEstoquePonto,
    TabelaPreco,
    VendaRapidaEstoque,
)
from ordens.models import LinhaTrabalho, OrdemServico, ServicoPeca


class ConsultaArtigosTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="estoque_tester",
            password="senha-forte-123",
            tipo_usuario="atendente",
            perm_estoque_cadastro_produto=True,
            perm_estoque_excluir_produto=True,
            perm_estoque_ajuste_manual=True,
            perm_estoque_transferencia=True,
            perm_estoque_inventario_finalizar=True,
            perm_estoque_converter_reserva=True,
            perm_estoque_cancelar_reserva=True,
        )
        self.tecnico = user_model.objects.create_user(
            username="estoque_tecnico",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.client.force_login(self.user)
        self.vendedor_numero = self.user.numero_vendedor

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
        self.assertContains(response, "Finalizar venda e gerar guia")
        self.assertContains(response, "F4")
        self.assertContains(response, "Match exato por EAN/SKU")
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

    def test_buscar_produto_sem_termo_minimo_retorna_vazio(self):
        response = self.client.get(reverse("estoque:buscar_produto"), {"q": "a"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_buscar_produto_filtra_por_tipo(self):
        Produto.objects.create(
            nome="Servico premium",
            sku="SKU-SVC-PREMIUM",
            ean="7890001112333",
            tipo_item="servico",
            preco_final=Decimal("99.00"),
            preco=Decimal("99.00"),
            quantidade=0,
            ponto_operacional=self.ponto_loja,
            ativo=True,
        )
        response_peca = self.client.get(reverse("estoque:buscar_produto"), {"q": "Tela", "tipo": "peca"})
        self.assertEqual(response_peca.status_code, 200)
        self.assertTrue(all(item["tipo_item"] != "servico" for item in response_peca.json()))

        response_servico = self.client.get(reverse("estoque:buscar_produto"), {"q": "Servico", "tipo": "servico"})
        self.assertEqual(response_servico.status_code, 200)
        self.assertTrue(all(item["tipo_item"] == "servico" for item in response_servico.json()))

    def test_lista_produtos_com_paginacao(self):
        for i in range(40):
            Produto.objects.create(
                nome=f"Produto Extra {i}",
                sku=f"SKU-EXTRA-{i:03d}",
                ean=f"7899991000{i:03d}"[-13:],
                preco_final=Decimal("10.00"),
                preco=Decimal("10.00"),
                quantidade=1,
                ponto_operacional=self.ponto_loja,
                ativo=True,
            )
        response = self.client.get(reverse("estoque:lista_produtos"), {"tipo": "produtos", "page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["produtos_page"].number, 2)

    def test_lista_produtos_filtra_por_busca_e_atalho(self):
        Produto.objects.create(
            nome="Bateria sem saldo",
            sku="SKU-BAT-000",
            ean="7899991110001",
            preco_final=Decimal("12.00"),
            preco=Decimal("12.00"),
            quantidade=0,
            estoque_minimo=1,
            ponto_operacional=self.ponto_loja,
            ativo=True,
        )
        response = self.client.get(
            reverse("estoque:lista_produtos"),
            {"q": "Bateria", "quick": "sem_saldo"},
        )
        self.assertEqual(response.status_code, 200)
        produtos = list(response.context["produtos"])
        self.assertEqual(len(produtos), 1)
        self.assertEqual(produtos[0].nome, "Bateria sem saldo")
        self.assertEqual(response.context["quick"], "sem_saldo")

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
            nome="Motor Generico",
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
                "funcionario_numero": self.vendedor_numero,
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
        self.assertIn("vendedor", response.json()["erro"])

    def test_venda_rapida_bloqueia_numero_vendedor_inexistente(self):
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": "88",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Numero de vendedor nao encontrado", response.json()["erro"])

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
                "funcionario_numero": self.vendedor_numero,
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
                "funcionario_numero": self.vendedor_numero,
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
        self.assertIn("Data de validade", response.json()["erro"])

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
            "nome": "Produto EAN invalido",
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
        self.assertIn("13", str(form.errors["ean"]))

    def test_produto_form_servico_rejeita_estoque_positivo(self):
        form = ProdutoForm(
            data={
                "nome": "Servico com estoque",
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
        self.assertIn("negativa", response.json()["erro"])

    def test_inventario_finalizar_sem_itens_rejeita(self):
        resp_ini = self.client.post(reverse("estoque:api_inventario_iniciar"), {"ponto_id": self.ponto_loja.id})
        inventario_id = resp_ini.json()["inventario_id"]
        response = self.client.post(reverse("estoque:api_inventario_finalizar", args=[inventario_id]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("sem itens", response.json()["erro"])

    def test_inventario_finalizar_exige_permissao_granular(self):
        user_model = get_user_model()
        operador = user_model.objects.create_user(
            username="estoque_sem_perm_inventario",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(operador)
        resp_ini = self.client.post(reverse("estoque:api_inventario_iniciar"), {"ponto_id": self.ponto_loja.id})
        inventario_id = resp_ini.json()["inventario_id"]
        self.client.post(
            reverse("estoque:api_inventario_adicionar_item", args=[inventario_id]),
            {"produto_id": self.produto.id, "quantidade_contada": 2},
        )
        response = self.client.post(reverse("estoque:api_inventario_finalizar", args=[inventario_id]))
        self.assertEqual(response.status_code, 403)

    def test_converter_reserva_exige_permissao_granular(self):
        reserva = ReservaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente Reserva",
            telefone_contato="910000000",
            valido_ate=timezone.localdate() + timedelta(days=2),
            status="ativa",
            usuario=self.user,
        )
        user_model = get_user_model()
        operador = user_model.objects.create_user(
            username="estoque_sem_perm_reserva",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(operador)
        response = self.client.post(reverse("estoque:api_converter_reserva", args=[reserva.codigo_reserva]))
        self.assertEqual(response.status_code, 403)

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

    def test_tecnico_pode_criar_reserva(self):
        self.client.force_login(self.tecnico)
        response = self.client.post(
            reverse("estoque:api_criar_reserva"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "nome": "Cliente Tecnico",
                "telefone": "910000000",
                "quantidade": 1,
                "valido_ate": (timezone.localdate() + timedelta(days=2)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["codigo_reserva"].startswith("RES-"))

    def test_restrito_sem_perm_nao_pode_excluir_produto(self):
        user_model = get_user_model()
        operador = user_model.objects.create_user(
            username="estoque_sem_perm_excluir",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(operador)
        response = self.client.post(reverse("estoque:excluir_produto", args=[self.produto.id]))
        self.assertEqual(response.status_code, 403)

    def test_restrito_sem_perm_nao_pode_transferencia_ou_reposicao(self):
        user_model = get_user_model()
        operador = user_model.objects.create_user(
            username="estoque_sem_perm_transfer",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(operador)
        response_transfer = self.client.get(reverse("estoque:transferir_estoque"))
        self.assertEqual(response_transfer.status_code, 403)
        response_reposicao = self.client.get(reverse("estoque:reposicao_estoque"))
        self.assertEqual(response_reposicao.status_code, 403)

    def test_restrito_sem_perm_nao_pode_cancelar_reserva(self):
        reserva = ReservaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente Reserva",
            telefone_contato="910000001",
            valido_ate=timezone.localdate() + timedelta(days=2),
            status="ativa",
            usuario=self.user,
        )
        user_model = get_user_model()
        operador = user_model.objects.create_user(
            username="estoque_sem_perm_cancelar_reserva",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(operador)
        response = self.client.post(
            reverse("estoque:api_cancelar_reserva", args=[reserva.codigo_reserva]),
            {"motivo": "teste"},
        )
        self.assertEqual(response.status_code, 403)

    def test_auditoria_estoque_filtra_evento_para_gerente(self):
        gerente = get_user_model().objects.create_user(
            username="gerente_auditoria_estoque",
            password="senha-forte-123",
            tipo_usuario="gerente",
        )
        EstoqueEvento.objects.create(
            evento="reserva_criada",
            usuario=self.user,
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            dados={"origem": "teste"},
        )
        EstoqueEvento.objects.create(
            evento="inventario_finalizado",
            usuario=self.user,
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=2,
            dados={"origem": "teste"},
        )

        self.client.force_login(gerente)
        response = self.client.get(
            reverse("estoque:auditoria_estoque"),
            {"evento": "reserva_criada", "q": "reserva_criada"},
        )
        self.assertEqual(response.status_code, 200)
        eventos_page = response.context["eventos_page"]
        self.assertGreaterEqual(eventos_page.paginator.count, 1)
        self.assertTrue(all(evt.evento == "reserva_criada" for evt in eventos_page.object_list))

    def test_eventos_operacionais_estoque_sao_persistidos_nominalmente(self):
        self.client.force_login(self.user)

        response_venda = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": self.vendedor_numero,
            },
        )
        self.assertEqual(response_venda.status_code, 200)

        response_reserva = self.client.post(
            reverse("estoque:api_criar_reserva"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "nome": "Cliente Reserva 1",
                "telefone": "910000002",
                "quantidade": 1,
                "valido_ate": (timezone.localdate() + timedelta(days=2)).isoformat(),
            },
        )
        self.assertEqual(response_reserva.status_code, 200)
        codigo_reserva = response_reserva.json()["codigo_reserva"]

        reserva_expirar = ReservaEstoque.objects.create(
            codigo_reserva="RES-EXP-EVT1",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente Expirar",
            telefone_contato="910000003",
            valido_ate=timezone.localdate() - timedelta(days=1),
            status="ativa",
            usuario=self.user,
        )
        self.assertIsNotNone(reserva_expirar.id)
        response_expirar = self.client.post(reverse("estoque:api_expirar_reservas"))
        self.assertEqual(response_expirar.status_code, 200)

        response_converter = self.client.post(reverse("estoque:api_converter_reserva", args=[codigo_reserva]))
        self.assertEqual(response_converter.status_code, 200)

        response_cancelar = self.client.post(
            reverse("estoque:api_cancelar_reserva", args=[codigo_reserva]),
            {"motivo": "cancelamento para teste"},
        )
        self.assertEqual(response_cancelar.status_code, 200)

        response_transferir = self.client.post(
            reverse("estoque:transferir_estoque"),
            {
                "produto_id": self.produto.id,
                "origem_id": self.ponto_loja.id,
                "destino_id": self.ponto_avaria.id,
                "quantidade": 1,
            },
        )
        self.assertEqual(response_transferir.status_code, 302)

        resp_ini = self.client.post(reverse("estoque:api_inventario_iniciar"), {"ponto_id": self.ponto_loja.id})
        self.assertEqual(resp_ini.status_code, 200)
        inventario_id = resp_ini.json()["inventario_id"]
        resp_item = self.client.post(
            reverse("estoque:api_inventario_adicionar_item", args=[inventario_id]),
            {"produto_id": self.produto.id, "quantidade_contada": 2},
        )
        self.assertEqual(resp_item.status_code, 200)
        resp_fim = self.client.post(reverse("estoque:api_inventario_finalizar", args=[inventario_id]))
        self.assertEqual(resp_fim.status_code, 200)

        eventos_esperados = [
            "venda_pre_reserva_criada",
            "reserva_criada",
            "reservas_expiradas_execucao",
            "reserva_convertida",
            "reserva_cancelada",
            "transferencia_estoque",
            "inventario_finalizado",
        ]
        for nome_evento in eventos_esperados:
            self.assertTrue(
                EstoqueEvento.objects.filter(evento=nome_evento).exists(),
                msg=f"Evento esperado nao encontrado: {nome_evento}",
            )

    def test_venda_rapida_cria_pre_reserva_sem_baixa_imediata(self):
        saldo_inicial = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja).quantidade
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": self.vendedor_numero,
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
                "funcionario_numero": self.vendedor_numero,
            },
        )
        self.assertEqual(response_item.status_code, 200)
        cesto_codigo = response_item.json()["cesto_codigo"]
        response_guia = self.client.post(reverse("estoque:api_cesto_finalizar"), {"cesto_codigo": cesto_codigo})
        self.assertEqual(response_guia.status_code, 200)
        data = response_guia.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["guia"].startswith("GUIA-"))

        response_pagina = self.client.get(reverse("estoque:guia_pagamento", args=[data["guia"]]))
        self.assertEqual(response_pagina.status_code, 200)
        self.assertContains(response_pagina, "Ir para Caixa")
        self.assertContains(response_pagina, "Imprimir guia")

    def test_guia_pagamento_continua_disponivel_apos_finalizacao_da_venda(self):
        venda = VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-VENDIDA-01",
            guia_pagamento="GUIA-VENDIDA-01",
            status="vendida",
            usuario=self.user,
            concluido_em=timezone.now(),
        )
        response = self.client.get(reverse("estoque:guia_pagamento", args=[venda.guia_pagamento]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GUIA-VENDIDA-01")
        self.assertContains(response, self.produto.nome)

    def test_api_guia_status_retorna_pendente(self):
        venda = VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-GUIA-PEND-01",
            guia_pagamento="GUIA-PENDENTE-01",
            status="pre_reserva",
            usuario=self.user,
        )
        response = self.client.get(reverse("estoque:api_guia_status", args=[venda.guia_pagamento]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "pendente")
        self.assertTrue(payload["pode_ir_caixa"])
        self.assertEqual(payload["itens_pre_reserva"], 1)
        self.assertEqual(payload["itens_total"], 1)

    def test_api_guia_status_retorna_divergente_quando_misto(self):
        codigo = "GUIA-DIVERGENTE-01"
        VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-GUIA-DIV-01",
            guia_pagamento=codigo,
            status="pre_reserva",
            usuario=self.user,
        )
        VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-GUIA-DIV-01",
            guia_pagamento=codigo,
            status="vendida",
            usuario=self.user,
            concluido_em=timezone.now(),
        )

        response = self.client.get(reverse("estoque:api_guia_status", args=[codigo]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "divergente")
        self.assertEqual(payload["itens_pre_reserva"], 1)
        self.assertEqual(payload["itens_vendida"], 1)

    def test_api_guias_recentes_respeita_ordem_e_limite(self):
        VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-GUIA-OLD-01",
            guia_pagamento="GUIA-OLD-01",
            status="pre_reserva",
            usuario=self.user,
        )
        VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-GUIA-NEW-01",
            guia_pagamento="GUIA-NEW-01",
            status="vendida",
            usuario=self.user,
            concluido_em=timezone.now(),
        )

        response = self.client.get(reverse("estoque:api_guias_recentes"), {"limit": 1})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["guias"]), 1)
        self.assertEqual(payload["guias"][0]["guia"], "GUIA-NEW-01")
        self.assertIn("caixa_url", payload["guias"][0])
        self.assertIn("guia_url", payload["guias"][0])

    def test_venda_rapida_rejeita_cesto_ja_finalizado(self):
        response_item = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": self.vendedor_numero,
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
                "funcionario_numero": self.vendedor_numero,
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
                "funcionario_numero": self.vendedor_numero,
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
                "funcionario_numero": self.vendedor_numero,
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
            funcionario_numero=self.vendedor_numero,
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
                "funcionario_numero": self.vendedor_numero,
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
                "funcionario_numero": self.vendedor_numero,
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

    def test_reposicao_inteligente_filtra_por_faltante_compra(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=1)
        saldo_loja = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo_loja.quantidade = 0
        saldo_loja.save(update_fields=["quantidade"])
        self.produto.estoque_minimo = 5
        self.produto.save(update_fields=["estoque_minimo"])
        response = self.client.get(reverse("estoque:reposicao_estoque"), {"quick": "faltante_compra"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Faltante compra")
        self.assertContains(response, self.produto.nome)

    def test_transferir_estoque_exibe_artigo_selecionado_e_saldos_por_ponto(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=7)
        response = self.client.get(
            reverse("estoque:transferir_estoque"),
            {"q": "Tela", "produto_id": self.produto.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["produto_selecionado"], self.produto)
        self.assertContains(response, "Artigo selecionado")
        self.assertContains(response, "PO2 - Armazem")
        self.assertContains(response, "PO3 - Loja")

    def test_movimentacoes_com_paginacao(self):
        for i in range(65):
            MovimentacaoEstoque.objects.create(
                produto=self.produto,
                tipo="ajuste",
                quantidade=1,
                origem=self.ponto_loja,
                observacao=f"Ajuste {i}",
                usuario=self.user,
            )
        response = self.client.get(reverse("estoque:movimentacoes"), {"page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["movimentacoes_page"].number, 2)

    def test_movimentacoes_filtra_por_busca_periodo_e_exporta_csv(self):
        MovimentacaoEstoque.objects.create(
            produto=self.produto,
            tipo="transferencia",
            quantidade=2,
            origem=self.ponto_loja,
            observacao="Transfere motor principal",
            usuario=self.user,
        )
        response = self.client.get(
            reverse("estoque:movimentacoes"),
            {
                "q": "motor",
                "data_inicio": timezone.localdate().isoformat(),
                "data_fim": timezone.localdate().isoformat(),
                "export": "csv",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("Tela A10", response.content.decode("utf-8"))

    def test_reservas_clientes_com_paginacao(self):
        for i in range(50):
            ReservaEstoque.objects.create(
                codigo_reserva=f"RES-PAG-{i:04d}",
                produto=self.produto,
                ponto_operacional=self.ponto_loja,
                quantidade=1,
                nome_contato=f"Cliente {i}",
                valido_ate=timezone.localdate() + timedelta(days=5),
                status="ativa",
                usuario=self.user,
            )
        response = self.client.get(reverse("estoque:reservas_clientes"), {"page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["reservas_page"].number, 2)

    def test_reservas_clientes_exibe_atendente_e_tecnico_da_os_vinculada(self):
        ordem = OrdemServico.objects.create(
            cliente=Cliente.objects.create(
                nome="Cliente Reserva OS",
                documento="39053344705",
                telefone="11912345678",
                estado="SP",
            ),
            tipo_equipamento="celular",
            marca_equipamento="Marca Reserva",
            modelo_equipamento="Modelo Reserva",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
            tecnico_responsavel=self.tecnico,
        )
        LinhaTrabalho.objects.create(
            ordem=ordem,
            usuario=self.user,
            status="criada",
            descricao="Ordem criada",
            tipo_evento="manual",
        )
        ReservaEstoque.objects.create(
            codigo_reserva="RES-OS-0001",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente Reserva",
            valido_ate=timezone.localdate() + timedelta(days=5),
            status="ativa",
            usuario=self.user,
            ordem_servico=ordem,
        )

        response = self.client.get(reverse("estoque:reservas_clientes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Atendente")
        self.assertContains(response, "Tec.:")
        self.assertContains(response, self.user.username)
        self.assertContains(response, self.tecnico.username)

    def test_associar_reserva_ordem_aceita_numero_os(self):
        ordem = OrdemServico.objects.create(
            cliente=Cliente.objects.create(
                nome="Cliente Numero OS",
                documento="11144477735",
                telefone="11912345679",
                estado="SP",
            ),
            tipo_equipamento="celular",
            marca_equipamento="Marca Numero",
            modelo_equipamento="Modelo Numero",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
        )
        reserva = ReservaEstoque.objects.create(
            codigo_reserva="RES-NUM-0001",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente Numero",
            valido_ate=timezone.localdate() + timedelta(days=5),
            status="ativa",
            usuario=self.user,
        )
        response = self.client.post(
            reverse("estoque:associar_reserva_ordem", args=[reserva.codigo_reserva]),
            {"ordem_id": ordem.numero_os},
        )
        self.assertEqual(response.status_code, 302)
        reserva.refresh_from_db()
        self.assertEqual(reserva.ordem_servico, ordem)

    def test_reservas_clientes_filtra_sem_os(self):
        ReservaEstoque.objects.create(
            codigo_reserva="RES-SEM-0001",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente Sem OS",
            valido_ate=timezone.localdate() + timedelta(days=5),
            status="ativa",
            usuario=self.user,
        )
        ordem = OrdemServico.objects.create(
            cliente=Cliente.objects.create(
                nome="Cliente Com OS",
                documento="93541134780",
                telefone="11912345670",
                estado="SP",
            ),
            tipo_equipamento="celular",
            marca_equipamento="Marca Com OS",
            modelo_equipamento="Modelo Com OS",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
        )
        ReservaEstoque.objects.create(
            codigo_reserva="RES-COM-0001",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente Com OS",
            valido_ate=timezone.localdate() + timedelta(days=5),
            status="ativa",
            usuario=self.user,
            ordem_servico=ordem,
        )
        response = self.client.get(reverse("estoque:reservas_clientes"), {"quick": "sem_os"})
        self.assertEqual(response.status_code, 200)
        reservas = list(response.context["reservas"])
        self.assertEqual(len(reservas), 1)
        self.assertEqual(reservas[0].codigo_reserva, "RES-SEM-0001")

    def test_limpeza_pre_reservas_antigas_via_web(self):
        venda_antiga = VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-99990001",
            status="pre_reserva",
            usuario=self.user,
        )
        VendaRapidaEstoque.objects.filter(id=venda_antiga.id).update(
            criado_em=timezone.now() - timedelta(days=2)
        )
        response = self.client.post(reverse("estoque:limpar_pre_reservas_antigas_web"), {"dias": 1})
        self.assertEqual(response.status_code, 302)
        venda_antiga.refresh_from_db()
        self.assertEqual(venda_antiga.status, "cancelada")

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
                observacao__icontains="Invent",
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


class LimpezaPreReservasCommandTests(TestCase):
    def test_limpar_pre_reservas_antigas_comando(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username="estoque_pre_reserva_cleanup",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)
        produto = Produto.objects.create(
            nome="Peca cleanup",
            ean="7891234500999",
            sku="SKU-CLEAN-01",
            preco_final=Decimal("20.00"),
            preco=Decimal("20.00"),
            quantidade=3,
            ponto_operacional=ponto,
            ativo=True,
        )
        antiga = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("20.00"),
            funcionario_numero=user.numero_vendedor,
            cesto_codigo="CES-CLEAN-01",
            status="pre_reserva",
            usuario=user,
        )
        VendaRapidaEstoque.objects.filter(id=antiga.id).update(criado_em=timezone.now() - timedelta(days=3))
        recente = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("20.00"),
            funcionario_numero=user.numero_vendedor,
            cesto_codigo="CES-CLEAN-02",
            status="pre_reserva",
            usuario=user,
        )

        call_command("limpar_pre_reservas_antigas", dias=1)

        antiga.refresh_from_db()
        recente.refresh_from_db()
        self.assertEqual(antiga.status, "cancelada")
        self.assertEqual(recente.status, "pre_reserva")


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
        self.assertIn("Diverg", out.getvalue())

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


class EstruturaProdutoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="estoque_estrutura",
            password="senha-forte-123",
            tipo_usuario="atendente",
            perm_estoque_cadastro_produto=True,
        )
        self.client.force_login(self.user)
        self.ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)
        self.produto = Produto.objects.create(
            nome="Motor Principal",
            ean="7895550000011",
            sku="SKU-MOTOR-01",
            preco_final=Decimal("100.00"),
            preco=Decimal("100.00"),
            quantidade=8,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        self.equivalente = Produto.objects.create(
            nome="Motor Alternativo",
            ean="7895550000012",
            sku="SKU-MOTOR-02",
            preco_final=Decimal("95.00"),
            preco=Decimal("95.00"),
            quantidade=5,
            ponto_operacional=self.ponto,
            ativo=True,
        )

    def test_tabelas_preco_cria_tabela(self):
        response = self.client.post(
            reverse("estoque:tabelas_preco"),
            {"nome": "Atacado", "margem_extra": "5.00", "ativo": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TabelaPreco.objects.filter(nome="Atacado").exists())

    def test_estrutura_produto_adiciona_equivalente(self):
        response = self.client.post(
            reverse("estoque:estrutura_produto", args=[self.produto.id]),
            {
                "acao": "adicionar_equivalente",
                "equivalente": str(self.equivalente.id),
                "observacao": "Compativel",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ProdutoEquivalente.objects.filter(produto=self.produto, equivalente=self.equivalente).exists()
        )

    def test_estrutura_produto_adiciona_preco_tabela(self):
        tabela = TabelaPreco.objects.create(nome="Balcao", margem_extra=Decimal("2.00"), ativo=True)
        response = self.client.post(
            reverse("estoque:estrutura_produto", args=[self.produto.id]),
            {
                "acao": "adicionar_preco_tabela",
                "tabela": str(tabela.id),
                "preco": "110.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ProdutoPrecoTabela.objects.filter(produto=self.produto, tabela=tabela, preco=Decimal("110.00")).exists()
        )


class ProdutoCadastroAprimoradoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="estoque_cadastro_aprimorado",
            password="senha-forte-123",
            tipo_usuario="atendente",
            perm_estoque_cadastro_produto=True,
        )
        self.client.force_login(self.user)
        self.ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)

    def _payload_produto(self, **overrides):
        payload = {
            "nome": "Produto Cadastro Aprimorado",
            "tipo_item": "produto",
            "modo_preco": "avancado",
            "custo_unitario": "50.00",
            "preco_final": "90.00",
            "quantidade": "0",
            "estoque_minimo": "1",
            "estoque_inicial": "3",
            "custo_entrada_inicial": "40.00",
            "ponto_operacional": str(self.ponto.id),
            "data_entrada": timezone.localdate().isoformat(),
            "ativo": "on",
            "permite_os": "on",
            "margem_lucro": "20.00",
            "margem_minima": "10.00",
        }
        payload.update(overrides)
        return payload

    def test_criar_produto_com_estoque_inicial_gera_movimento_e_historico(self):
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(nome="Produto com Entrada Inicial"),
        )
        self.assertEqual(response.status_code, 302)

        produto = Produto.objects.get(nome="Produto com Entrada Inicial")
        self.assertEqual(produto.quantidade, 3)
        self.assertTrue(
            MovimentacaoEstoque.objects.filter(
                produto=produto,
                tipo="entrada",
                quantidade=3,
            ).exists()
        )
        self.assertTrue(
            ProdutoHistorico.objects.filter(
                produto=produto,
                acao="CRIACAO",
            ).exists()
        )

    def test_criar_produto_exige_permissao_granular(self):
        user_model = get_user_model()
        operador = user_model.objects.create_user(
            username="estoque_sem_perm_cadastro",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(operador)
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(nome="Produto Bloqueado"),
        )
        self.assertEqual(response.status_code, 403)

    def test_form_produto_exibe_abas_operacionais(self):
        response = self.client.get(reverse("estoque:criar_produto"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Essencial")
        self.assertContains(response, "Estoque e venda")
        self.assertContains(response, "Preco e rateio")
        self.assertContains(response, "Observacoes")

    def test_form_rejeita_preco_abaixo_minimo_sem_confirmacao(self):
        form = ProdutoForm(
            data=self._payload_produto(
                nome="Produto Minimo",
                custo_unitario="100.00",
                preco_final="100.00",
                margem_minima="50.00",
                estoque_inicial="0",
            )
        )
        self.assertFalse(form.is_valid())
        self.assertIn("preco_final", form.errors)

        form_ok = ProdutoForm(
            data=self._payload_produto(
                nome="Produto Minimo Confirmado",
                custo_unitario="100.00",
                preco_final="100.00",
                margem_minima="50.00",
                estoque_inicial="0",
                permitir_preco_abaixo_minimo="on",
            )
        )
        self.assertTrue(form_ok.is_valid())

    def test_duplicar_produto_redireciona_para_criacao(self):
        produto = Produto.objects.create(
            nome="Produto Base Duplicacao",
            ean="7897770000001",
            sku="SKU-DUP-0001",
            preco_final=Decimal("55.00"),
            preco=Decimal("55.00"),
            quantidade=1,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        response = self.client.get(reverse("estoque:duplicar_produto", args=[produto.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"duplicar={produto.id}", response.url)

    def test_importar_produtos_csv_cria_produto_e_historico(self):
        csv_content = "\n".join(
            [
                "nome,sku,ean,tipo_item,categoria,marca,fornecedor,custo_unitario,preco_final,estoque_minimo,estoque_inicial",
                "Produto Importado,SKU-IMP-01,7894440000001,produto,Eletronico,,,30.00,60.00,1,2",
            ]
        )
        arquivo_validar = SimpleUploadedFile(
            "produtos.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )
        response_validar = self.client.post(
            reverse("estoque:importar_produtos"),
            {"arquivo": arquivo_validar, "acao": "validar"},
        )
        self.assertEqual(response_validar.status_code, 200)
        self.assertContains(response_validar, "Pre-visualizacao")

        arquivo_importar = SimpleUploadedFile(
            "produtos.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )
        response_importar = self.client.post(
            reverse("estoque:importar_produtos"),
            {"arquivo": arquivo_importar, "acao": "importar"},
        )
        self.assertEqual(response_importar.status_code, 302)
        produto = Produto.objects.get(nome="Produto Importado")
        self.assertEqual(produto.quantidade, 2)
        self.assertTrue(
            ProdutoHistorico.objects.filter(produto=produto, acao="IMPORTACAO").exists()
        )

    def test_produto_calcula_rateio_custo_fixo_unitario(self):
        CustoFixoMensal.objects.create(
            competencia=timezone.localdate().replace(day=1),
            descricao="Aluguel",
            categoria="Infraestrutura",
            valor_previsto=Decimal("300.00"),
            valor_pago=Decimal("0.00"),
            ativo=True,
        )
        produto_base = Produto.objects.create(
            nome="Produto Base Rateio",
            ean="7894440000002",
            sku="SKU-RATEIO-BASE",
            custo_unitario=Decimal("10.00"),
            preco_final=Decimal("20.00"),
            preco=Decimal("20.00"),
            quantidade=1,
            previsao_venda_mensal=30,
            incluir_rateio_custo_fixo=True,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        produto = Produto.objects.create(
            nome="Produto Rateado",
            ean="7894440000003",
            sku="SKU-RATEIO-01",
            custo_unitario=Decimal("10.00"),
            preco_final=Decimal("20.00"),
            preco=Decimal("20.00"),
            quantidade=1,
            previsao_venda_mensal=30,
            incluir_rateio_custo_fixo=True,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        produto_base.refresh_from_db()
        produto.refresh_from_db()
        self.assertEqual(produto_base.custo_rateio_fixo.quantize(Decimal("0.01")), Decimal("5.00"))
        self.assertEqual(produto.custo_rateio_fixo.quantize(Decimal("0.01")), Decimal("5.00"))

    def test_preco_sugerido_considera_rateio_custo_fixo(self):
        CustoFixoMensal.objects.create(
            competencia=timezone.localdate().replace(day=1),
            descricao="Internet",
            categoria="Infraestrutura",
            valor_previsto=Decimal("100.00"),
            valor_pago=Decimal("0.00"),
            ativo=True,
        )
        produto = Produto.objects.create(
            nome="Produto Preco Rateado",
            ean="7894440000004",
            sku="SKU-RATEIO-02",
            custo_unitario=Decimal("50.00"),
            margem_lucro=Decimal("20.00"),
            modo_preco="simples",
            preco_final=Decimal("0.00"),
            quantidade=1,
            previsao_venda_mensal=10,
            incluir_rateio_custo_fixo=True,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        produto.refresh_from_db()
        self.assertEqual(produto.custo_rateio_fixo.quantize(Decimal("0.01")), Decimal("10.00"))
        self.assertEqual(produto.preco_sugerido.quantize(Decimal("0.01")), Decimal("72.00"))

    def test_alteracao_custo_fixo_recalcula_produtos_rateados(self):
        custo_fixo = CustoFixoMensal.objects.create(
            competencia=timezone.localdate().replace(day=1),
            descricao="Infraestrutura",
            categoria="Infraestrutura",
            valor_previsto=Decimal("100.00"),
            valor_pago=Decimal("0.00"),
            ativo=True,
        )
        produto = Produto.objects.create(
            nome="Produto Recalculo Rateio",
            ean="7894440000005",
            sku="SKU-RATEIO-03",
            custo_unitario=Decimal("20.00"),
            preco_final=Decimal("40.00"),
            preco=Decimal("40.00"),
            quantidade=1,
            previsao_venda_mensal=10,
            incluir_rateio_custo_fixo=True,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        produto.refresh_from_db()
        self.assertEqual(produto.custo_rateio_fixo.quantize(Decimal("0.01")), Decimal("10.00"))

        custo_fixo.valor_previsto = Decimal("200.00")
        custo_fixo.save()
        produto.refresh_from_db()
        self.assertEqual(produto.custo_rateio_fixo.quantize(Decimal("0.01")), Decimal("20.00"))

    def test_rateio_por_faturamento_previsto(self):
        configuracao = ConfiguracaoRateioCustoFixo.get_solo()
        configuracao.criterio_rateio = ConfiguracaoRateioCustoFixo.CRITERIO_FATURAMENTO
        configuracao.save()

        CustoFixoMensal.objects.create(
            competencia=timezone.localdate().replace(day=1),
            descricao="Equipe",
            categoria="Operacao",
            valor_previsto=Decimal("90.00"),
            valor_pago=Decimal("0.00"),
            ativo=True,
        )
        produto_a = Produto.objects.create(
            nome="Produto Faturamento A",
            ean="7894440000006",
            sku="SKU-RATEIO-04",
            custo_unitario=Decimal("10.00"),
            preco_final=Decimal("30.00"),
            preco=Decimal("30.00"),
            quantidade=1,
            previsao_venda_mensal=3,
            incluir_rateio_custo_fixo=True,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        produto_b = Produto.objects.create(
            nome="Produto Faturamento B",
            ean="7894440000007",
            sku="SKU-RATEIO-05",
            custo_unitario=Decimal("10.00"),
            preco_final=Decimal("15.00"),
            preco=Decimal("15.00"),
            quantidade=1,
            previsao_venda_mensal=3,
            incluir_rateio_custo_fixo=True,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        produto_a.refresh_from_db()
        produto_b.refresh_from_db()
        self.assertEqual(produto_a.custo_rateio_fixo.quantize(Decimal("0.01")), Decimal("20.00"))
        self.assertEqual(produto_b.custo_rateio_fixo.quantize(Decimal("0.01")), Decimal("10.00"))

    def test_indicadores_exibem_painel_rateio(self):
        response = self.client.get(reverse("estoque:indicadores_estoque"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumo do Rateio Atual")
        self.assertContains(response, "Configuracao do Rateio")
        self.assertContains(response, "Evolucao Previsto x Realizado")

    def test_gerar_snapshot_rateio_pelo_dashboard(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        CustoFixoMensal.objects.create(
            competencia=timezone.localdate().replace(day=1),
            descricao="Infra",
            categoria="Operacao",
            valor_previsto=Decimal("120.00"),
            valor_pago=Decimal("0.00"),
            ativo=True,
        )
        produto = Produto.objects.create(
            nome="Produto Snapshot Rateio",
            ean="7894440000008",
            sku="SKU-RATEIO-06",
            custo_unitario=Decimal("10.00"),
            preco_final=Decimal("25.00"),
            preco=Decimal("25.00"),
            quantidade=1,
            previsao_venda_mensal=6,
            incluir_rateio_custo_fixo=True,
            ponto_operacional=self.ponto,
            ativo=True,
        )
        VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=self.ponto,
            quantidade=2,
            valor_unitario=Decimal("25.00"),
            valor_total=Decimal("50.00"),
            funcionario_numero=self.user.numero_vendedor,
            status="vendida",
            usuario=self.user,
            concluido_em=timezone.now(),
        )
        response = self.client.post(
            reverse("estoque:indicadores_estoque"),
            {
                "acao_rateio": "gerar_snapshot",
                "competencia": timezone.localdate().replace(day=1).isoformat(),
                "observacao": "Fechamento de teste",
            },
        )
        self.assertEqual(response.status_code, 302)
        snapshot = RateioCustoFixoCompetencia.objects.get(competencia=timezone.localdate().replace(day=1))
        self.assertEqual(snapshot.total_produtos, 1)
        item_snapshot = snapshot.itens.get(produto=produto)
        self.assertEqual(item_snapshot.quantidade_realizada, 2)
        self.assertEqual(item_snapshot.faturamento_realizado.quantize(Decimal("0.01")), Decimal("50.00"))

        detalhe = self.client.get(reverse("estoque:detalhe_rateio_competencia", args=[snapshot.id]))
        self.assertEqual(detalhe.status_code, 200)
        self.assertContains(detalhe, "Produto Snapshot Rateio")

        exportacao = self.client.get(reverse("estoque:exportar_rateio_competencia", args=[snapshot.id]))
        self.assertEqual(exportacao.status_code, 200)
        self.assertIn("text/csv", exportacao["Content-Type"])
        self.assertContains(exportacao, "Produto Snapshot Rateio")

        exportacao_excel = self.client.get(reverse("estoque:exportar_rateio_competencia_excel", args=[snapshot.id]))
        self.assertEqual(exportacao_excel.status_code, 200)
        self.assertIn("application/vnd.ms-excel", exportacao_excel["Content-Type"])
        self.assertContains(exportacao_excel, "Produto Snapshot Rateio")

