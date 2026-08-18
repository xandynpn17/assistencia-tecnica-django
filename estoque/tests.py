from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import Caixa
from caixa.models import CategoriaFinanceira, CentroCusto, CustoFixoMensal, FormaPagamento, Pagamento
from clientes.models import Cliente
from configuracoes.forms import MarcaGarantiaForm
from configuracoes.models import ConfiguracaoSistema, Empresa, FornecedorGarantia, MarcaGarantia
from estoque.forms import MovimentacaoEstoqueForm, ProdutoForm
from estoque.models import (
    AtendimentoPosVendaBalcao,
    CategoriaProduto,
    EntradaMercadoria,
    EstoqueCamadaCusto,
    EstoqueEvento,
    EstoqueLote,
    EstoqueSerie,
    ExecucaoAuditoriaEstoque,
    ConfiguracaoRateioCustoFixo,
    InventarioEstoque,
    ItemEntradaMercadoria,
    ItemInventarioEstoque,
    MapeamentoImportacaoProduto,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ProdutoHistorico,
    ProdutoEquivalente,
    ProdutoFornecedor,
    ProdutoKitItem,
    ProdutoPrecoTabela,
    RateioCustoFixoCompetencia,
    ReservaEstoque,
    SaldoEstoquePonto,
    SaldoEstoqueUbicacao,
    SolicitacaoSaidaEstoque,
    TabelaPreco,
    UbicacaoEstoque,
    VendaRapidaEstoque,
)
from estoque.services_inventario_operacional import finalizar_inventario_operacional
from ordens.models import LinhaTrabalho, OrdemServico, ServicoPeca


class ConsultaArtigosTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.empresa = Empresa.objects.create(
            nome="Empresa Teste",
            regime_tributario="simples",
            modo_tributario="basico",
            aliquota_comercio=6,
            aliquota_servico=8,
        )
        self.user = user_model.objects.create_user(
            username="estoque_tester",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
            perm_estoque_cadastro_produto=True,
            perm_estoque_excluir_produto=True,
            perm_estoque_ajuste_manual=True,
            perm_estoque_avaria=True,
            perm_estoque_oferta=True,
            perm_estoque_cedencia=True,
            perm_estoque_transferencia=True,
            perm_estoque_inventario_finalizar=True,
            perm_estoque_converter_reserva=True,
            perm_estoque_cancelar_reserva=True,
        )
        self.tecnico = user_model.objects.create_user(
            username="estoque_tecnico",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            empresa=self.empresa,
        )
        self.client.force_login(self.user)
        self.vendedor_numero = self.user.numero_vendedor

        self.ponto_loja = PontoOperacional.objects.create(codigo="PO3", nome="Loja")
        self.ponto_avaria = PontoOperacional.objects.create(codigo="AVARIA", nome="Avariados")
        self.ubicacao_loja = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto_loja,
            codigo="A1",
            descricao="Prateleira loja",
            ativo=True,
        )
        self.ubicacao_avaria = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto_avaria,
            codigo="AV-01",
            descricao="Area tecnica",
            ativo=True,
        )
        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Tela A10",
            sku="SKU-TELA-A10",
            ean="7890001112223",
            descricao="Peca de reposicao",
            preco_final=Decimal("150.00"),
            preco=Decimal("150.00"),
            quantidade=10,
            estoque_minimo=1,
            ponto_operacional=self.ponto_loja,
            ubicacao_padrao=self.ubicacao_loja,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=self.ponto_loja, quantidade=8)
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=self.ponto_avaria, quantidade=2)
        SaldoEstoqueUbicacao.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            ubicacao=self.ubicacao_loja,
            quantidade=8,
        )
        SaldoEstoqueUbicacao.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_avaria,
            ubicacao=self.ubicacao_avaria,
            quantidade=2,
        )
        Caixa.objects.create(aberto=True, saldo_inicial=0)
        ConfiguracaoSistema.get_configuracao()

    def test_pagina_consulta_artigos(self):
        response = self.client.get(reverse("estoque:consulta_artigos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1. Buscar artigo")
        self.assertContains(response, "Finalizar venda e gerar guia")
        self.assertContains(response, "F4")
        self.assertContains(response, "Se houver um unico match exato por EAN, SKU ou ID")
        self.assertContains(response, "2. Montar e fechar cesto")
        self.assertContains(response, "Cestos em aberto")
        self.assertContains(response, "Estado do caixa")
        self.assertContains(response, "Artigo em foco")
        self.assertTrue(response.context["pode_venda_mostrador"])
        self.assertContains(response, "Numero do vendedor")

    def test_consulta_artigos_faz_fallback_de_vendedores_quando_empresa_nao_bate(self):
        user_model = get_user_model()
        vendedor_sem_empresa = user_model.objects.create_user(
            username="vendedor_solto",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=None,
            numero_vendedor="77",
        )
        user_model.objects.filter(id=self.user.id).update(empresa=None)
        self.user.refresh_from_db()
        self.client.force_login(self.user)

        response = self.client.get(reverse("estoque:consulta_artigos"))

        self.assertEqual(response.status_code, 200)
        vendedores = response.context["vendedores_disponiveis"]
        numeros = {item["numero_vendedor"] for item in vendedores}
        self.assertIn(vendedor_sem_empresa.numero_vendedor, numeros)
        self.assertIn(self.user.numero_vendedor, numeros)

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
                empresa=self.empresa,
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

    def test_lista_produtos_nao_carrega_tudo_por_padrao(self):
        response = self.client.get(reverse("estoque:lista_produtos"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["carregar"])
        self.assertIsNone(response.context["produtos_page"])
        self.assertContains(response, "Carregar lista")

    def test_lista_produtos_filtra_por_busca_e_atalho(self):
        Produto.objects.create(
            empresa=self.empresa,
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

    def test_lista_produtos_filtra_itens_sem_estrutura(self):
        produto_sem_estrutura = Produto.objects.create(
            empresa=self.empresa,
            nome="Produto sem estrutura",
            sku="SKU-SEM-ESTRUTURA",
            ean="7899991110099",
            preco_final=Decimal("18.00"),
            preco=Decimal("18.00"),
            quantidade=2,
            estoque_minimo=1,
            ponto_operacional=self.ponto_loja,
            ubicacao_padrao=None,
            ativo=True,
        )
        response = self.client.get(
            reverse("estoque:lista_produtos"),
            {"quick": "sem_estrutura"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sem estrutura")
        produtos = list(response.context["produtos"])
        self.assertTrue(any(item.id == produto_sem_estrutura.id for item in produtos))
        self.assertEqual(response.context["resumo"]["sem_estrutura"], 1)

    def test_lista_produtos_exibe_saldo_disponivel_e_reservado(self):
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Produto com reserva",
            sku="SKU-RES-001",
            ean="7899991110198",
            preco_final=Decimal("22.00"),
            preco=Decimal("22.00"),
            quantidade=5,
            estoque_minimo=1,
            ponto_operacional=self.ponto_loja,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(
            produto=produto,
            ponto_operacional=self.ponto_loja,
            quantidade=5,
        )
        ReservaEstoque.objects.create(
            produto=produto,
            ponto_operacional=self.ponto_loja,
            quantidade=2,
            nome_contato="Cliente teste",
            valido_ate=timezone.localdate() + timedelta(days=2),
            status="ativa",
        )

        response = self.client.get(
            reverse("estoque:lista_produtos"),
            {"q": "Produto com reserva", "carregar": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Disponivel: 3")
        self.assertContains(response, "Reservado: 2")

    def test_busca_por_modelo_compativel(self):
        self.produto.modelos_compativeis = "A10, A20, A30"
        self.produto.save(update_fields=["modelos_compativeis"])
        response = self.client.get(reverse("estoque:api_consulta_artigos"), {"q": "A20"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["resultados"]), 1)

    def test_sugestao_ranking_por_historico(self):
        produto_hist = Produto.objects.create(
            empresa=self.empresa,
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
            empresa=self.empresa,
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
            empresa=self.empresa,
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

    def test_venda_rapida_respeita_pontos_configurados_para_mostrador(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.estoque_venda_mostrador_codigos = "AVARIA"
        config.save(update_fields=["estoque_venda_mostrador_codigos"])

        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_avaria.id,
                "quantidade": 1,
                "funcionario_numero": self.vendedor_numero,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_venda_exige_numero_vendedor_com_2_digitos(self):
        gerente = get_user_model().objects.create_user(
            username="gerente_validador_vendedor",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
        )
        self.client.force_login(gerente)
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
        gerente = get_user_model().objects.create_user(
            username="gerente_vendedor_inexistente",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
        )
        self.client.force_login(gerente)
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
        ponto = PontoOperacional.objects.create(codigo="PO-TST-EAN", nome="Teste EAN")
        ubicacao = UbicacaoEstoque.objects.create(ponto_operacional=ponto, codigo="A-01", descricao="Teste", ativo=True)
        form = ProdutoForm(
            data={
                "nome": "Produto EAN invalido",
                "ean": "1234",
                "tipo_item": "produto",
                "modo_preco": "avancado",
                "preco_final": "10.00",
                "quantidade": "1",
                "estoque_minimo": "0",
                "ponto_operacional": str(ponto.id),
                "ubicacao_padrao": str(ubicacao.id),
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
        ubicacao_po3 = UbicacaoEstoque.objects.create(ponto_operacional=po3, codigo="B1", descricao="Origem", ativo=True)
        form = MovimentacaoEstoqueForm(
            data={
                "produto": self.produto.id,
                "tipo": "transferencia",
                "quantidade": 1,
                "origem": po3.id,
                "origem_ubicacao": ubicacao_po3.id,
                "destino": po2.id,
                "destino_ubicacao": "",
                "observacao": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("destino_ubicacao_ref", form.errors)

    def test_transferencia_exige_quantidade_positiva(self):
        po3, _ = PontoOperacional.objects.get_or_create(codigo="PO3", defaults={"nome": "Loja"})
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        ubicacao_po3 = UbicacaoEstoque.objects.create(ponto_operacional=po3, codigo="B2", descricao="Origem", ativo=True)
        ubicacao_po2 = UbicacaoEstoque.objects.create(ponto_operacional=po2, codigo="A1", descricao="Destino", ativo=True)
        form = MovimentacaoEstoqueForm(
            data={
                "produto": self.produto.id,
                "tipo": "transferencia",
                "quantidade": 0,
                "origem": po3.id,
                "origem_ubicacao": ubicacao_po3.id,
                "destino": po2.id,
                "destino_ubicacao_ref": ubicacao_po2.id,
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

    def test_inventario_iniciar_por_ubicacao_permite_recortes_diferentes_no_mesmo_ponto(self):
        outra_ubicacao = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto_loja,
            codigo="A2",
            descricao="Prateleira secundária",
            ativo=True,
        )
        InventarioEstoque.objects.create(
            ponto_operacional=self.ponto_loja,
            ubicacao=self.ubicacao_loja,
            status="aberto",
            observacao="Inventario A1",
            usuario=self.user,
        )
        response = self.client.post(
            reverse("estoque:api_inventario_iniciar"),
            {"ponto_id": self.ponto_loja.id, "ubicacao_id": outra_ubicacao.id},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["escopo"]["ubicacao_id"], outra_ubicacao.id)

    def test_inventario_item_por_ubicacao_usa_saldo_da_ubicacao(self):
        outra_ubicacao = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto_loja,
            codigo="A2",
            descricao="Prateleira secundária",
            ativo=True,
        )
        SaldoEstoqueUbicacao.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            ubicacao=outra_ubicacao,
            quantidade=3,
        )
        resp_ini = self.client.post(
            reverse("estoque:api_inventario_iniciar"),
            {"ponto_id": self.ponto_loja.id, "ubicacao_id": outra_ubicacao.id},
        )
        self.assertEqual(resp_ini.status_code, 200)
        inventario_id = resp_ini.json()["inventario_id"]
        resp_item = self.client.post(
            reverse("estoque:api_inventario_adicionar_item", args=[inventario_id]),
            {"produto_id": self.produto.id, "quantidade_contada": 5},
        )
        self.assertEqual(resp_item.status_code, 200)
        item = ItemInventarioEstoque.objects.get(inventario_id=inventario_id, produto=self.produto, ubicacao=outra_ubicacao)
        self.assertEqual(item.quantidade_sistema, 3)
        self.assertEqual(item.ajuste, 2)

    def test_inventario_finalizar_por_ubicacao_ajusta_saldo_da_ubicacao(self):
        outra_ubicacao = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto_loja,
            codigo="A2",
            descricao="Prateleira secundária",
            ativo=True,
        )
        SaldoEstoqueUbicacao.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            ubicacao=outra_ubicacao,
            quantidade=3,
        )
        resp_ini = self.client.post(
            reverse("estoque:api_inventario_iniciar"),
            {"ponto_id": self.ponto_loja.id, "ubicacao_id": outra_ubicacao.id},
        )
        inventario_id = resp_ini.json()["inventario_id"]
        self.client.post(
            reverse("estoque:api_inventario_adicionar_item", args=[inventario_id]),
            {"produto_id": self.produto.id, "quantidade_contada": 5, "observacao": "Contagem A2"},
        )
        resp_fim = self.client.post(reverse("estoque:api_inventario_finalizar", args=[inventario_id]))
        self.assertEqual(resp_fim.status_code, 200)
        saldo_ubicacao = SaldoEstoqueUbicacao.objects.get(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            ubicacao=outra_ubicacao,
        )
        self.assertEqual(saldo_ubicacao.quantidade, 5)

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
            empresa=self.empresa,
            acesso_estoque_extra=True,
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
                "destino_ubicacao_id": self.ubicacao_avaria.id,
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

    def test_venda_rapida_bloqueia_troca_manual_de_vendedor_para_operacao_comum(self):
        outro_usuario = get_user_model().objects.create_user(
            username="vendedor_extra_balcao",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
        )
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": outro_usuario.numero_vendedor,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("proprio numero de vendedor", response.json()["erro"])

    def test_excluir_produto_inativa_e_preserva_historico(self):
        movimento = MovimentacaoEstoque.objects.create(
            produto=self.produto,
            tipo="ajuste",
            quantidade=1,
            origem=self.ponto_loja,
            origem_ubicacao=self.ubicacao_loja,
            observacao="Historico a preservar",
        )

        response = self.client.post(reverse("estoque:excluir_produto", args=[self.produto.id]))

        self.assertEqual(response.status_code, 302)
        self.produto.refresh_from_db()
        self.assertFalse(self.produto.ativo)
        self.assertTrue(MovimentacaoEstoque.objects.filter(pk=movimento.pk).exists())

    def test_movimentacao_manual_nao_aceita_produto_de_outra_empresa(self):
        outra_empresa = Empresa.objects.create(nome="Empresa isolada")
        produto_alheio = Produto.objects.create(
            empresa=outra_empresa,
            nome="Produto de outra empresa",
            tipo_item="produto",
            quantidade=1,
            preco_final=10,
            preco=10,
        )

        response = self.client.post(
            reverse("estoque:registrar_movimentacao"),
            {
                "produto": produto_alheio.pk,
                "tipo": "ajuste",
                "quantidade": 1,
                "destino": self.ponto_loja.pk,
                "destino_ubicacao_ref": self.ubicacao_loja.pk,
                "observacao": "Tentativa cruzada",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MovimentacaoEstoque.objects.filter(produto=produto_alheio).exists())

    def test_oferta_exige_permissao_especifica(self):
        self.user.perm_estoque_oferta = False
        self.user.save(update_fields=["perm_estoque_oferta"])

        response = self.client.post(
            reverse("estoque:registrar_movimentacao"),
            {
                "produto": self.produto.pk,
                "tipo": "oferta",
                "quantidade": 1,
                "origem": self.ponto_loja.pk,
                "origem_ubicacao": self.ubicacao_loja.pk,
                "finalidade": "brinde_comercial",
                "beneficiario_nome": "Cliente sem autorização",
                "observacao": "Brinde sem autorizacao",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_gerente_pode_trocar_vendedor_com_rastro_operacional(self):
        user_model = get_user_model()
        gerente = user_model.objects.create_user(
            username="gerente_balcao",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
        )
        vendedor = user_model.objects.create_user(
            username="vendedor_balcao_override",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
        )
        self.client.force_login(gerente)
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": vendedor.numero_vendedor,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            EstoqueEvento.objects.filter(
                evento="venda_pre_reserva_troca_vendedor",
                usuario=gerente,
            ).exists()
        )

    def test_operador_com_permissao_explicita_pode_trocar_vendedor(self):
        user_model = get_user_model()
        operador = user_model.objects.create_user(
            username="operador_balcao",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
            perm_venda_mostrador_trocar_vendedor=True,
        )
        vendedor = user_model.objects.create_user(
            username="vendedor_balcao_permitido",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
        )
        self.client.force_login(operador)
        response = self.client.post(
            reverse("estoque:api_venda_rapida"),
            {
                "produto_id": self.produto.id,
                "ponto_id": self.ponto_loja.id,
                "quantidade": 1,
                "funcionario_numero": vendedor.numero_vendedor,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            EstoqueEvento.objects.filter(
                evento="venda_pre_reserva_troca_vendedor",
                usuario=operador,
            ).exists()
        )

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

    def test_guia_pagamento_exibe_codigo_de_barras_da_guia(self):
        venda = VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-GUIA-BAR-01",
            guia_pagamento="GUIA-BAR-01",
            status="pre_reserva",
            usuario=self.user,
        )

        response = self.client.get(reverse("estoque:guia_pagamento", args=[venda.guia_pagamento]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Código de barras da guia")
        self.assertContains(response, "GUIA-BAR-01")
        self.assertContains(response, "<svg", html=False)

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

    def test_api_cestos_abertos_lista_resumos_disponiveis(self):
        VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=2,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("300.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-ABERTO-01",
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
            cesto_codigo="CES-ABERTO-01",
            status="pre_reserva",
            usuario=self.user,
        )

        response = self.client.get(reverse("estoque:api_cestos_abertos"), {"limit": 5})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["cestos"]), 1)
        resumo = payload["cestos"][0]
        self.assertEqual(resumo["cesto_codigo"], "CES-ABERTO-01")
        self.assertEqual(resumo["itens_total"], 2)
        self.assertEqual(resumo["quantidade_total"], 3)
        self.assertEqual(Decimal(str(resumo["valor_total"])), Decimal("450.00"))
        self.assertEqual(resumo["operador"], self.user.username)
        self.assertIsNotNone(resumo["criado_em"])
        self.assertIn("tempo_parado_minutos", resumo)

    def test_painel_venda_mostrador_exibe_indicadores_operacionais(self):
        VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-PAINEL-01",
            guia_pagamento="GUIA-PAINEL-01",
            status="vendida",
            usuario=self.user,
            concluido_em=timezone.now(),
        )
        VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-PAINEL-02",
            guia_pagamento="GUIA-PEND-PAINEL-01",
            status="pre_reserva",
            usuario=self.user,
        )

        response = self.client.get(reverse("estoque:painel_venda_mostrador"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Painel da venda a mostrador")
        self.assertContains(response, "Top produtos")
        self.assertContains(response, "Top operadores")
        self.assertContains(response, "GUIA-PEND-PAINEL-01")

    def test_pos_venda_balcao_cria_e_conclui_atendimento(self):
        forma = FormaPagamento.objects.create(nome="PIX POS", codigo="pix_pos", tipo="avista", ativa=True)
        pagamento = Pagamento.objects.create(
            caixa=Caixa.objects.first(),
            valor=Decimal("150.00"),
            forma_pagamento=forma,
            metodo="pix_pos",
            cliente_nome="Cliente POS",
            cliente_telefone="62999990000",
        )
        self.produto.garantia_peca_dias = 90
        self.produto.save(update_fields=["garantia_peca_dias"])
        venda = VendaRapidaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            valor_total=Decimal("150.00"),
            funcionario_numero=self.vendedor_numero,
            cesto_codigo="CES-POS-01",
            guia_pagamento="GUIA-POS-01",
            status="vendida",
            usuario=self.user,
            pagamento=pagamento,
            concluido_em=timezone.now(),
        )

        response_get = self.client.get(reverse("estoque:pos_venda_balcao"), {"q": "GUIA-POS-01"})
        self.assertEqual(response_get.status_code, 200)
        self.assertContains(response_get, "Pos-venda de balcao")
        self.assertContains(response_get, "Cliente POS")
        self.assertContains(response_get, "Abrir guia")
        self.assertContains(response_get, "Talao")

        response_post = self.client.post(
            reverse("estoque:pos_venda_balcao"),
            {
                "acao": "criar_atendimento",
                "venda_id": venda.id,
                "tipo": "garantia",
                "motivo": "Teste de garantia",
                "observacao": "Cliente relatou falha intermitente.",
                "q": "GUIA-POS-01",
            },
            follow=True,
        )
        self.assertEqual(response_post.status_code, 200)
        atendimento = AtendimentoPosVendaBalcao.objects.get(venda=venda)
        self.assertEqual(atendimento.tipo, "garantia")
        self.assertEqual(atendimento.cliente_nome_snapshot, "Cliente POS")

        response_concluir = self.client.post(
            reverse("estoque:pos_venda_balcao"),
            {
                "acao": "concluir_atendimento",
                "atendimento_id": atendimento.id,
                "observacao_conclusao": "Atendimento encerrado com orientacao.",
                "q": "GUIA-POS-01",
            },
            follow=True,
        )
        self.assertEqual(response_concluir.status_code, 200)
        atendimento.refresh_from_db()
        self.assertEqual(atendimento.status, "concluido")

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
            empresa=self.empresa,
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
        UbicacaoEstoque.objects.create(ponto_operacional=po2, codigo="PO2-A1", descricao="Armazem", ativo=True)
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

    def test_reposicao_inteligente_respeita_pontos_configurados(self):
        cfg = ConfiguracaoSistema.get_configuracao()
        cfg.estoque_reposicao_origem_codigo = "EST"
        cfg.estoque_reposicao_destino_codigo = "LOJ"
        cfg.save(
            update_fields=[
                "estoque_reposicao_origem_codigo",
                "estoque_reposicao_destino_codigo",
                "data_atualizacao",
            ]
        )
        ponto_origem = PontoOperacional.objects.create(codigo="EST", nome="Estoque Central")
        ponto_destino = PontoOperacional.objects.create(codigo="LOJ", nome="Loja Front")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=ponto_origem, quantidade=5)
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=ponto_destino, quantidade=0)

        response = self.client.get(reverse("estoque:reposicao_estoque"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ponto_origem"].codigo, "EST")
        self.assertEqual(response.context["ponto_destino"].codigo, "LOJ")

    def test_inventario_iniciar_persiste_empresa(self):
        response = self.client.post(
            reverse("estoque:api_inventario_iniciar"),
            {"ponto_id": self.ponto_loja.id, "observacao": "Inventario teste"},
        )
        self.assertEqual(response.status_code, 200)
        inventario = InventarioEstoque.objects.get(id=response.json()["inventario_id"])
        self.assertEqual(inventario.empresa, self.empresa)

    def test_inventario_operacional_permita_contagem_cega_e_aprovacao(self):
        response = self.client.post(
            reverse("estoque:inventarios_estoque"),
            {
                "ponto_id": self.ponto_loja.id,
                "observacao": "Cego",
                "modo_contagem_cega": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        inventario = InventarioEstoque.objects.latest("id")
        self.assertTrue(inventario.modo_contagem_cega)
        self.assertTrue(inventario.exige_aprovacao_divergencia)
        self.assertEqual(inventario.itens.first().quantidade_contada, 0)

        detalhe = self.client.get(reverse("estoque:inventario_estoque_detalhe", args=[inventario.id]))
        self.assertEqual(detalhe.status_code, 200)
        self.assertFalse(detalhe.context["mostrar_quantidade_sistema"])
        self.assertContains(detalhe, "Oculto")

    def test_inventario_operacional_permita_dupla_conferencia(self):
        response = self.client.post(
            reverse("estoque:inventarios_estoque"),
            {
                "ponto_id": self.ponto_loja.id,
                "observacao": "Dupla",
                "exige_dupla_conferencia": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        inventario = InventarioEstoque.objects.latest("id")
        self.assertTrue(inventario.exige_dupla_conferencia)

    def test_inventario_operacional_bloqueia_finalizar_divergencia_sem_aprovacao(self):
        response = self.client.post(
            reverse("estoque:inventarios_estoque"),
            {
                "ponto_id": self.ponto_loja.id,
                "observacao": "Divergencia pendente",
            },
        )
        self.assertEqual(response.status_code, 302)
        inventario = InventarioEstoque.objects.latest("id")
        item = inventario.itens.first()
        self.client.post(
            reverse("estoque:inventario_estoque_atualizar_item", args=[item.id]),
            {
                "quantidade_contada": max(int(item.quantidade_sistema or 0) + 1, 1),
                "motivo_divergencia": "sobra",
                "observacao": "Teste",
            },
        )
        inventario.refresh_from_db()
        with self.assertRaisesMessage(ValueError, "Ainda existem divergencias sem aprovacao."):
            finalizar_inventario_operacional(inventario, usuario=self.user)

    def test_inventario_operacional_bloqueia_finalizar_divergencia_sem_recontagem(self):
        response = self.client.post(
            reverse("estoque:inventarios_estoque"),
            {
                "ponto_id": self.ponto_loja.id,
                "observacao": "Recontagem obrigatoria",
                "exige_dupla_conferencia": "1",
                "dispensar_aprovacao_divergencia": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        inventario = InventarioEstoque.objects.latest("id")
        item = inventario.itens.first()
        self.client.post(
            reverse("estoque:inventario_estoque_atualizar_item", args=[item.id]),
            {
                "quantidade_contada": max(int(item.quantidade_sistema or 0) + 1, 1),
                "motivo_divergencia": "sobra",
                "observacao": "Teste recontagem",
            },
        )
        inventario.refresh_from_db()
        with self.assertRaisesMessage(ValueError, "Ainda existem divergencias sem recontagem."):
            finalizar_inventario_operacional(inventario, usuario=self.user)

    def test_inventario_operacional_recontagem_permite_finalizar_sem_aprovacao_quando_dispensada(self):
        response = self.client.post(
            reverse("estoque:inventarios_estoque"),
            {
                "ponto_id": self.ponto_loja.id,
                "observacao": "Recontagem final",
                "exige_dupla_conferencia": "1",
                "dispensar_aprovacao_divergencia": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        inventario = InventarioEstoque.objects.latest("id")
        item = inventario.itens.first()
        self.client.post(
            reverse("estoque:inventario_estoque_atualizar_item", args=[item.id]),
            {
                "quantidade_contada": max(int(item.quantidade_sistema or 0) + 1, 1),
                "motivo_divergencia": "sobra",
                "observacao": "Teste recontagem",
            },
        )
        self.client.post(
            reverse("estoque:inventario_estoque_recontar_item", args=[item.id]),
            {"quantidade_recontada": max(int(item.quantidade_sistema or 0) + 1, 1)},
        )
        inventario.refresh_from_db()
        resumo = finalizar_inventario_operacional(inventario, usuario=self.user)
        self.assertIn("divergencias", resumo)
        item.refresh_from_db()
        self.assertEqual(item.quantidade_recontada, max(int(item.quantidade_sistema or 0) + 1, 1))

    def test_inventario_operacional_aprovar_divergencia_permite_finalizar(self):
        response = self.client.post(
            reverse("estoque:inventarios_estoque"),
            {
                "ponto_id": self.ponto_loja.id,
                "observacao": "Aprovar e fechar",
            },
        )
        self.assertEqual(response.status_code, 302)
        inventario = InventarioEstoque.objects.latest("id")
        item = inventario.itens.first()
        self.client.post(
            reverse("estoque:inventario_estoque_atualizar_item", args=[item.id]),
            {
                "quantidade_contada": max(int(item.quantidade_sistema or 0) + 1, 1),
                "motivo_divergencia": "sobra",
                "observacao": "Teste",
            },
        )
        self.client.post(reverse("estoque:inventario_estoque_aprovar_divergencia", args=[item.id]))
        inventario.refresh_from_db()
        resumo = finalizar_inventario_operacional(inventario, usuario=self.user)
        self.assertIn("divergencias", resumo)
        inventario.refresh_from_db()
        self.assertEqual(inventario.status, "fechado")

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

    def test_reposicao_inteligente_exibe_fornecedor_preferencial_e_custo_estimado(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=1)
        saldo_loja = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo_loja.quantidade = 0
        saldo_loja.save(update_fields=["quantidade"])
        self.produto.estoque_minimo = 4
        self.produto.save(update_fields=["estoque_minimo"])
        ProdutoFornecedor.objects.create(
            produto=self.produto,
            fornecedor_manual="Fornecedor Alfa",
            codigo_fornecedor="ALF-001",
            custo_referencia=Decimal("12.50"),
            prazo_medio_dias=3,
            preferencial=True,
        )

        response = self.client.get(reverse("estoque:reposicao_estoque"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fornecedor Alfa")
        self.assertContains(response, "ALF-001")
        self.assertContains(response, "R$ 37,50")

    def test_reposicao_inteligente_considera_reservas_ativas_como_demanda(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=2)
        saldo_loja = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo_loja.quantidade = 0
        saldo_loja.save(update_fields=["quantidade"])
        self.produto.estoque_minimo = 1
        self.produto.save(update_fields=["estoque_minimo"])
        ReservaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=5,
            nome_contato="Cliente Reserva",
            valido_ate=timezone.localdate() + timedelta(days=3),
            status="ativa",
            usuario=self.user,
        )

        response = self.client.get(reverse("estoque:reposicao_estoque"), {"quick": "com_reserva"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demanda puxada por reservas")
        linha = next(l for l in response.context["linhas"] if l["produto"].id == self.produto.id)
        self.assertEqual(linha["reservas_ativas"], 5)
        self.assertEqual(linha["demanda_base"], 5)
        self.assertEqual(linha["sugestao"], 5)
        self.assertEqual(linha["pode_repor"], 2)
        self.assertEqual(linha["faltante_compra"], 3)

    def test_reposicao_inteligente_considera_giro_real_na_demanda(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=1)
        saldo_loja = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo_loja.quantidade = 0
        saldo_loja.save(update_fields=["quantidade"])
        self.produto.estoque_minimo = 1
        self.produto.save(update_fields=["estoque_minimo"])
        ProdutoFornecedor.objects.create(
            produto=self.produto,
            fornecedor_manual="Fornecedor Giro",
            prazo_medio_dias=10,
            preferencial=True,
        )
        MovimentacaoEstoque.objects.create(
            produto=self.produto,
            tipo="venda",
            quantidade=-9,
            origem=self.ponto_loja,
            usuario=self.user,
        )

        response = self.client.get(reverse("estoque:reposicao_estoque"), {"quick": "giro_ativo"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demanda puxada por giro real")
        linha = next(l for l in response.context["linhas"] if l["produto"].id == self.produto.id)
        self.assertEqual(linha["demanda_giro"], 3)
        self.assertEqual(linha["demanda_base"], 3)
        self.assertEqual(linha["sugestao"], 3)
        self.assertEqual(linha["pode_repor"], 1)
        self.assertEqual(linha["faltante_compra"], 2)

    def test_reposicao_inteligente_considera_os_pendentes_sem_duplicar_reserva(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=1)
        saldo_loja = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo_loja.quantidade = 0
        saldo_loja.save(update_fields=["quantidade"])
        self.produto.estoque_minimo = 1
        self.produto.save(update_fields=["estoque_minimo"])
        cliente = Cliente.objects.create(
            nome="Cliente OS",
            documento="52998224725",
            telefone="11999990000",
        )
        ordem = OrdemServico.objects.create(
            empresa=self.empresa,
            cliente=cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca X",
            modelo_equipamento="Modelo Y",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="autorizado",
        )
        ServicoPeca.objects.create(
            ordem=ordem,
            produto_estoque=self.produto,
            ponto_operacional_reserva=self.ponto_loja,
            tipo="peca",
            nome="Tela A10",
            quantidade=4,
            valor_unitario=Decimal("50.00"),
        )
        ReservaEstoque.objects.create(
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=2,
            nome_contato="Cliente OS",
            valido_ate=timezone.localdate() + timedelta(days=3),
            status="ativa",
            usuario=self.user,
            ordem_servico=ordem,
        )

        response = self.client.get(reverse("estoque:reposicao_estoque"), {"quick": "os_pendentes"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demanda puxada por OS pendentes")
        linha = next(l for l in response.context["linhas"] if l["produto"].id == self.produto.id)
        self.assertEqual(linha["reservas_os"], 2)
        self.assertEqual(linha["os_pendentes"], 4)
        self.assertEqual(linha["os_pendentes_sem_reserva"], 2)
        self.assertEqual(linha["demanda_base"], 4)
        self.assertEqual(linha["sugestao"], 4)
        self.assertEqual(linha["pode_repor"], 1)
        self.assertEqual(linha["faltante_compra"], 3)

    def test_reposicao_inteligente_exporta_csv_com_fornecedor(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=0)
        saldo_loja = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo_loja.quantidade = 0
        saldo_loja.save(update_fields=["quantidade"])
        self.produto.estoque_minimo = 3
        self.produto.save(update_fields=["estoque_minimo"])
        ProdutoFornecedor.objects.create(
            produto=self.produto,
            fornecedor_manual="Fornecedor CSV",
            custo_referencia=Decimal("7.00"),
            preferencial=True,
        )

        response = self.client.get(reverse("estoque:reposicao_estoque"), {"export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        body = response.content.decode("utf-8")
        self.assertIn("Fornecedor CSV", body)
        self.assertIn("valor_estimado_compra", body)

    def test_reposicao_gera_entrada_rascunho_por_fornecedor(self):
        po2 = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=po2, quantidade=0)
        saldo_loja = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_loja)
        saldo_loja.quantidade = 0
        saldo_loja.save(update_fields=["quantidade"])
        self.produto.estoque_minimo = 3
        self.produto.save(update_fields=["estoque_minimo"])
        ProdutoFornecedor.objects.create(
            produto=self.produto,
            fornecedor_manual="Fornecedor Compra",
            custo_referencia=Decimal("9.50"),
            preferencial=True,
        )

        response = self.client.post(
            reverse("estoque:reposicao_estoque"),
            {
                "acao": "gerar_entrada_compra",
                "fornecedor_manual": "Fornecedor Compra",
                "itens_compra": f"{self.produto.id}:3",
            },
        )
        self.assertEqual(response.status_code, 302)
        entrada = EntradaMercadoria.objects.get(fornecedor_manual="Fornecedor Compra")
        self.assertEqual(entrada.status, "rascunho")
        self.assertEqual(entrada.ponto_operacional, self.ponto_loja)
        item = entrada.itens.get()
        self.assertEqual(item.produto, self.produto)
        self.assertEqual(item.quantidade, 3)
        self.assertEqual(item.custo_unitario, Decimal("9.50"))

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

    def test_movimentacoes_exibe_leitura_operacional_e_rota_fisica(self):
        MovimentacaoEstoque.objects.create(
            produto=self.produto,
            tipo="transferencia",
            quantidade=2,
            origem=self.ponto_loja,
            destino=self.ponto_avaria,
            origem_ubicacao=self.ubicacao_loja,
            destino_ubicacao_ref=self.ubicacao_avaria,
            observacao="Transferencia de teste",
            usuario=self.user,
        )
        response = self.client.get(reverse("estoque:movimentacoes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Como ler esta tela")
        self.assertContains(response, "Origem fisica")
        self.assertContains(response, "Destino fisico")
        self.assertContains(response, self.ubicacao_loja.codigo)
        self.assertContains(response, self.ubicacao_avaria.codigo)

    def test_movimentacoes_quick_filter_ajustes(self):
        MovimentacaoEstoque.objects.create(
            produto=self.produto,
            tipo="ajuste",
            quantidade=1,
            origem=self.ponto_loja,
            observacao="Ajuste rapido",
            usuario=self.user,
        )
        MovimentacaoEstoque.objects.create(
            produto=self.produto,
            tipo="transferencia",
            quantidade=1,
            origem=self.ponto_loja,
            destino=self.ponto_avaria,
            observacao="Transferencia paralela",
            usuario=self.user,
        )
        response = self.client.get(reverse("estoque:movimentacoes"), {"quick": "ajustes"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tipo_filtro"], "ajuste")
        self.assertContains(response, "Ajuste rapido")
        self.assertNotContains(response, "Transferencia paralela")

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
            empresa=self.empresa,
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

    def test_reservas_clientes_exibe_ubicacao_e_resumo_operacional(self):
        ReservaEstoque.objects.create(
            codigo_reserva="RES-UBI-0001",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            ubicacao=self.ubicacao_loja,
            quantidade=1,
            nome_contato="Cliente Ubi",
            valido_ate=timezone.localdate() + timedelta(days=1),
            status="ativa",
            usuario=self.user,
        )
        response = self.client.get(reverse("estoque:reservas_clientes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Expiram em 48h")
        self.assertContains(response, self.ubicacao_loja.codigo)
        self.assertEqual(response.context["resumo"]["expiram_curto"], 1)

    def test_reservas_clientes_filtra_por_ponto_operacional(self):
        ponto_secundario = PontoOperacional.objects.create(codigo="PO2", nome="Armazem", ativo=True)
        ReservaEstoque.objects.create(
            codigo_reserva="RES-PO3-0001",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente Loja",
            valido_ate=timezone.localdate() + timedelta(days=3),
            status="ativa",
            usuario=self.user,
        )
        ReservaEstoque.objects.create(
            codigo_reserva="RES-PO2-0001",
            produto=self.produto,
            ponto_operacional=ponto_secundario,
            quantidade=1,
            nome_contato="Cliente Armazem",
            valido_ate=timezone.localdate() + timedelta(days=3),
            status="ativa",
            usuario=self.user,
        )

        response = self.client.get(reverse("estoque:reservas_clientes"), {"ponto": ponto_secundario.id})

        self.assertEqual(response.status_code, 200)
        reservas = list(response.context["reservas"])
        self.assertEqual(len(reservas), 1)
        self.assertEqual(reservas[0].codigo_reserva, "RES-PO2-0001")
        self.assertEqual(response.context["ponto_filtro"], str(ponto_secundario.id))

    def test_reservas_clientes_exibe_orientacao_operacional_por_ponto(self):
        response = self.client.get(reverse("estoque:reservas_clientes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Como usar esta tela")
        self.assertContains(response, "disponibilidade real por bancada ou loja")

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
        self.assertContains(response, "Ruptura por ponto")
        self.assertContains(response, "Valor por ponto operacional")
        self.assertContains(response, "Impacto de avarias")
        self.assertContains(response, "Giro e cobertura (30 dias)")
        self.assertContains(response, "Curva ABC por valor em custo")
        self.assertContains(response, "Ruptura prevista por cobertura")
        self.assertContains(response, "Pressao de margem")

    def test_relatorio_divergencias_estoque_exibe_estrutura_fisica(self):
        produto_sem_estrutura = Produto.objects.create(
            empresa=self.empresa,
            nome="Produto Solto",
            sku="SKU-SOLTO-01",
            ean="7890001112456",
            preco_final=Decimal("35.00"),
            preco=Decimal("35.00"),
            quantidade=2,
            ativo=True,
        )
        ReservaEstoque.objects.create(
            codigo_reserva="RES-SEM-UBI",
            produto=self.produto,
            ponto_operacional=self.ponto_loja,
            quantidade=1,
            nome_contato="Cliente sem estrutura",
            valido_ate=timezone.localdate() + timedelta(days=2),
            status="ativa",
            usuario=self.user,
        )
        response = self.client.get(reverse("estoque:relatorio_divergencias"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Itens sem estrutura fisica")
        self.assertContains(response, produto_sem_estrutura.nome)
        self.assertContains(response, "Reservas ativas sem ubicacao valida")

    def test_movimentacao_form_preenche_destino_ubicacao_a_partir_da_referencia(self):
        form = MovimentacaoEstoqueForm(
            data={
                "produto": self.produto.id,
                "tipo": "entrada",
                "quantidade": 3,
                "destino": self.ponto_loja.id,
                "destino_ubicacao_ref": self.ubicacao_loja.id,
                "destino_ubicacao": "",
                "observacao": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn(self.ubicacao_loja.codigo, form.cleaned_data["destino_ubicacao"])


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

    def test_monitoramento_persiste_execucao_limpa_por_empresa(self):
        empresa = Empresa.objects.create(nome="Empresa auditoria limpa")
        out = StringIO()

        call_command("monitorar_estoque", empresa=empresa.id, origem="agendada", stdout=out)

        execucao = ExecucaoAuditoriaEstoque.objects.get(empresa=empresa)
        self.assertEqual(execucao.status, "ok")
        self.assertEqual(execucao.total_divergencias, 0)
        self.assertIn("Monitoramento concluido", out.getvalue())

    def test_monitoramento_grava_divergencia_antes_de_retornar_falha(self):
        empresa = Empresa.objects.create(nome="Empresa auditoria divergente")
        ponto = PontoOperacional.objects.create(codigo="AUD1", nome="Auditoria", ativo=True)
        produto = Produto.objects.create(
            empresa=empresa,
            nome="Produto monitorado",
            ean="7891234500099",
            sku="SKU-AUD-MON",
            preco_final=Decimal("10.00"),
            preco=Decimal("10.00"),
            quantidade=1,
            ponto_operacional=ponto,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=-1)

        with self.assertRaises(CommandError):
            call_command("monitorar_estoque", empresa=empresa.id, falhar_se_divergir=True)

        execucao = ExecucaoAuditoriaEstoque.objects.get(empresa=empresa)
        self.assertEqual(execucao.status, "divergencia")
        self.assertGreater(execucao.total_divergencias, 0)
        self.assertTrue(execucao.detalhes["saldos_negativos"])


class EstruturaProdutoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.empresa = Empresa.objects.create(
            nome="Empresa Estrutura",
            regime_tributario="simples",
            modo_tributario="basico",
        )
        self.user = user_model.objects.create_user(
            username="estoque_estrutura",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
            perm_estoque_cadastro_produto=True,
        )
        self.client.force_login(self.user)
        self.ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)
        self.ubicacao = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto,
            codigo="A1",
            descricao="Prateleira principal",
            ativo=True,
        )
        self.produto = Produto.objects.create(
            empresa=self.empresa,
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
            empresa=self.empresa,
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

    def test_estrutura_produto_adiciona_fornecedor_relacionado(self):
        response = self.client.post(
            reverse("estoque:estrutura_produto", args=[self.produto.id]),
            {
                "acao": "adicionar_fornecedor",
                "fornecedor_manual": "Distribuidor Centro",
                "codigo_fornecedor": "DIST-001",
                "custo_referencia": "42.50",
                "prazo_medio_dias": "5",
                "preferencial": "on",
                "ativo": "on",
                "observacao": "Entrega semanal",
            },
        )
        self.assertEqual(response.status_code, 302)
        rel = ProdutoFornecedor.objects.get(produto=self.produto, fornecedor_manual="Distribuidor Centro")
        self.assertEqual(rel.codigo_fornecedor, "DIST-001")
        self.assertEqual(rel.custo_referencia, Decimal("42.50"))
        self.assertTrue(rel.preferencial)

    def test_estrutura_produto_exibe_comparativo_fornecedores(self):
        ProdutoFornecedor.objects.create(
            produto=self.produto,
            fornecedor_manual="Fornecedor A",
            custo_referencia=Decimal("40.00"),
            prazo_medio_dias=4,
            preferencial=True,
            ativo=True,
        )
        ProdutoFornecedor.objects.create(
            produto=self.produto,
            fornecedor_manual="Fornecedor B",
            custo_referencia=Decimal("35.00"),
            prazo_medio_dias=7,
            ativo=True,
        )
        response = self.client.get(reverse("estoque:estrutura_produto", args=[self.produto.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Melhor custo cadastrado")
        self.assertContains(response, "Vs melhor custo")
        self.assertContains(response, "Fornecedor A")
        self.assertContains(response, "Fornecedor B")
        self.assertContains(response, "Negociar / comprar")

    def test_estrutura_produto_exibe_resumo_de_recompra_com_link_pre_preenchido(self):
        fornecedor = ProdutoFornecedor.objects.create(
            produto=self.produto,
            fornecedor_manual="Fornecedor Economia",
            custo_referencia=Decimal("33.00"),
            prazo_medio_dias=3,
            ativo=True,
        )
        response = self.client.get(reverse("estoque:estrutura_produto", args=[self.produto.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recompra")
        self.assertContains(response, "Abrir entrada pre-preenchida")
        self.assertContains(response, fornecedor.fornecedor_nome)
        self.assertContains(response, f"produto={self.produto.id}")


class ProdutoCadastroAprimoradoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.empresa = Empresa.objects.create(
            nome="Empresa Cadastro",
            regime_tributario="simples",
            modo_tributario="basico",
            aliquota_comercio=Decimal("6.00"),
            aliquota_servico=Decimal("8.00"),
        )
        self.user = user_model.objects.create_user(
            username="estoque_cadastro_aprimorado",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
            perm_estoque_cadastro_produto=True,
        )
        self.client.force_login(self.user)
        self.ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)
        self.ubicacao = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto,
            codigo="A1",
            descricao="Prateleira principal",
            ativo=True,
        )

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
            "ubicacao_padrao": str(self.ubicacao.id),
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
        self.assertIn("carregar=1", response.url)
        self.assertIn("q=Produto+com+Entrada+Inicial", response.url)

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
        self.assertEqual(produto.ubicacao_padrao_id, self.ubicacao.id)

    def test_criar_produto_aceita_margens_maiores_que_dez_porcento(self):
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(
                nome="Produto com margem alta válida",
                margem_lucro="75.00",
                margem_minima="40.00",
                preco_final="300.00",
            ),
        )

        self.assertEqual(response.status_code, 302)
        produto = Produto.objects.get(nome="Produto com margem alta válida")
        self.assertEqual(produto.margem_lucro, Decimal("75.00"))
        self.assertEqual(produto.margem_minima, Decimal("40.00"))

    def test_margem_inviavel_informa_capacidade_disponivel(self):
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(
                nome="Produto com margem inviável",
                margem_lucro="95.00",
                margem_minima="95.00",
                preco_final="300.00",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "deve ser menor que 94")
        self.assertFalse(Produto.objects.filter(nome="Produto com margem inviável").exists())

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
        self.assertContains(response, "Metodo de custo")
        self.assertContains(response, "Compra x Venda")
        self.assertContains(response, "Nova categoria")
        self.assertContains(response, "Criar aqui")
        self.assertContains(response, "Nao encontrei")
        self.assertContains(response, "Fluxo recomendado para cadastrar sem erro")
        self.assertContains(response, "Valor estimado da entrada inicial")
        self.assertContains(response, "modelos_compativeis")
        self.assertContains(response, "Relacione esta peca aos servicos em que ela costuma ser usada.")
        self.assertContains(response, "Presets operacionais")
        self.assertContains(response, "Balcao tecnico")
        self.assertContains(response, "Marketplace")
        self.assertContains(response, "Simulador por forma de pagamento")
        self.assertContains(response, "Recebe R$ 0,00")
        self.assertContains(response, "Minimo R$ 0,00")
        self.assertContains(response, "Modo rapido")
        self.assertContains(response, "Modo avancado")
        self.assertContains(response, "Modo rapido ativo")
        self.assertContains(response, "sistema reaproveita")
        self.assertContains(response, "custo medio ponderado")
        self.assertContains(response, "Marca identifica o fabricante")
        self.assertContains(response, "categoria classifica")
        self.assertContains(response, "Como o sistema usa esta estrutura")
        self.assertContains(response, "Salvar e estruturar")
        self.assertContains(response, "Mapa rapido desta aba")
        self.assertContains(response, "Custos de compra em R$")
        self.assertContains(response, "Politica em %")
        self.assertContains(response, "Outra marca / fabricante")
        self.assertContains(response, "Calculo automatico")

    def test_form_produto_garante_pontos_operacionais_em_base_nova(self):
        PontoOperacional.objects.all().delete()
        UbicacaoEstoque.objects.all().delete()

        form = ProdutoForm()

        opcoes = list(form.fields["ponto_operacional"].queryset.values_list("codigo", flat=True))
        self.assertIn("PO2", opcoes)
        self.assertIn("PO3", opcoes)
        self.assertTrue(
            UbicacaoEstoque.objects.filter(
                ponto_operacional__codigo="PO2",
                codigo="A1",
            ).exists()
        )
        self.assertTrue(
            UbicacaoEstoque.objects.filter(
                ponto_operacional__codigo="PO3",
                codigo="A1",
            ).exists()
        )

    def test_criar_produto_com_categoria_manual_cria_categoria_no_catalogo(self):
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(
                nome="Produto Categoria Manual",
                categoria="Cabos especiais",
                categoria_config="",
            ),
        )
        self.assertEqual(response.status_code, 302)
        produto = Produto.objects.get(nome="Produto Categoria Manual")
        categoria = CategoriaProduto.objects.get(nome="Cabos especiais")
        self.assertEqual(produto.categoria_config_id, categoria.id)
        self.assertEqual(produto.categoria, "Cabos especiais")

    def test_criar_produto_com_marca_manual_cria_e_vincula_catalogo(self):
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(
                nome="Produto Marca Manual",
                marca="",
                marca_manual="Fabricante Especial",
            ),
        )
        self.assertEqual(response.status_code, 302)
        produto = Produto.objects.get(nome="Produto Marca Manual")
        self.assertEqual(produto.marca.nome, "Fabricante Especial")
        self.assertEqual(MarcaGarantia.objects.filter(nome__iexact="Fabricante Especial").count(), 1)

    def test_marca_manual_reaproveita_marca_inativa_sem_duplicar(self):
        marca = MarcaGarantia.objects.create(nome="Marca Reutilizada", ativo=False)
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(
                nome="Produto Marca Reutilizada",
                marca="",
                marca_manual="  marca reutilizada  ",
            ),
        )
        self.assertEqual(response.status_code, 302)
        marca.refresh_from_db()
        produto = Produto.objects.get(nome="Produto Marca Reutilizada")
        self.assertTrue(marca.ativo)
        self.assertEqual(produto.marca_id, marca.id)
        self.assertEqual(MarcaGarantia.objects.filter(nome__iexact="Marca Reutilizada").count(), 1)

    def test_simples_calcula_tributo_da_empresa_automaticamente(self):
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Produto Simples Automatico",
            modo_preco="simples",
            custo_unitario=Decimal("100.00"),
            custo_operacional=Decimal("0.00"),
            margem_lucro=Decimal("20.00"),
            margem_minima=Decimal("10.00"),
            taxa_cartao=Decimal("2.00"),
            preco_final=Decimal("0.00"),
            preco=Decimal("0.00"),
            ponto_operacional=self.ponto,
            ubicacao_padrao=self.ubicacao,
            ativo=True,
        )
        self.assertEqual(produto._aliquota_percentual(), Decimal("6.00"))
        self.assertEqual(produto.preco_sugerido.quantize(Decimal("0.01")), Decimal("130.43"))
        self.assertEqual(produto.preco_minimo.quantize(Decimal("0.01")), Decimal("121.95"))
        self.assertEqual(produto.precificacao_versao, 1)
        self.assertEqual(produto.precificacao_snapshot["regime_tributario"], "simples")
        self.assertEqual(produto.precificacao_snapshot["origem_aliquota"], "empresa")
        self.assertEqual(Decimal(produto.precificacao_snapshot["aliquota_efetiva"]), Decimal("6.000"))

        self.empresa.aliquota_comercio = Decimal("8.00")
        self.empresa.save(update_fields=["aliquota_comercio"])
        produto.save(update_fields=["nome"])
        produto.refresh_from_db()

        self.assertEqual(produto.precificacao_versao, 2)
        self.assertEqual(Decimal(produto.precificacao_snapshot["aliquota_efetiva"]), Decimal("8.000"))
        self.assertEqual(produto.preco_sugerido, Decimal("133.33"))

    def test_previa_precificacao_considera_classificacao_ainda_nao_salva(self):
        from fiscal.models import PerfilTributario, RegraTributaria

        perfil = PerfilTributario.objects.create(
            empresa=self.empresa,
            nome="Perfil para previa",
            regime="simples",
            inicio_vigencia=timezone.localdate(),
            status="homologado",
            rbt12=Decimal("100000.00"),
        )
        RegraTributaria.objects.create(
            perfil=perfil,
            codigo="GERAL-PREVIA",
            nome="Regra geral",
            tipo_item="produto",
            finalidade="revenda",
            aliquota_estimativa=Decimal("6.00"),
            prioridade=100,
            inicio_vigencia=timezone.localdate(),
            status="homologado",
        )
        especifica = RegraTributaria.objects.create(
            perfil=perfil,
            codigo="NCM-PREVIA",
            nome="Regra específica por NCM",
            tipo_item="produto",
            finalidade="revenda",
            ncm_prefixo="8517",
            aliquota_estimativa=Decimal("9.00"),
            prioridade=1,
            inicio_vigencia=timezone.localdate(),
            status="homologado",
        )

        response = self.client.post(
            reverse("estoque:api_simular_precificacao"),
            data={
                "tipo_item": "produto",
                "ncm": "8517.13.00",
                "custo_unitario": "100.00",
                "margem_lucro": "20.00",
                "margem_minima": "10.00",
                "modo_preco": "avancado",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["tributacao"]["regra_codigo"], especifica.codigo)
        self.assertEqual(Decimal(payload["aliquota"]), Decimal("9.000"))

    def test_criar_produto_com_ubicacao_texto_cria_ubicacao_no_ponto(self):
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(
                nome="Produto com nova ubicacao",
                ubicacao_padrao="",
                ubicacao_padrao_texto="Bancada 02",
            ),
        )

        self.assertEqual(response.status_code, 302)
        produto = Produto.objects.get(nome="Produto com nova ubicacao")
        self.assertEqual(produto.localizacao, "Bancada 02")
        self.assertIsNotNone(produto.ubicacao_padrao_id)
        self.assertEqual(produto.ubicacao_padrao.ponto_operacional_id, self.ponto.id)
        self.assertEqual(produto.ubicacao_padrao.codigo, "BANCADA 02")

    def test_criar_produto_com_save_and_structure_redireciona_para_estrutura(self):
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(
                nome="Produto com estrutura guiada",
                _save_and_structure="1",
            ),
        )

        self.assertEqual(response.status_code, 302)
        produto = Produto.objects.get(nome="Produto com estrutura guiada")
        self.assertEqual(
            response.url,
            reverse("estoque:estrutura_produto", args=[produto.id]),
        )

    def test_pagina_categorias_produto_salva_categoria(self):
        response = self.client.post(
            reverse("estoque:categorias_produto"),
            data={
                "nome": "Fontes",
                "margem_padrao": "35.00",
                "ordem": "5",
                "ativo": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CategoriaProduto.objects.filter(nome="Fontes", margem_padrao=Decimal("35.00")).exists())

    def test_pagina_categorias_produto_exibe_total_de_produtos_vinculados(self):
        categoria = CategoriaProduto.objects.create(nome="Cabos", margem_padrao=Decimal("12.00"), ativo=True)
        Produto.objects.create(
            empresa=self.empresa,
            nome="Cabo HDMI",
            ean="7897771234567",
            sku="SKU-CABO-HDMI",
            categoria_config=categoria,
            categoria=categoria.nome,
            preco_final=Decimal("30.00"),
            preco=Decimal("30.00"),
            quantidade=2,
            ponto_operacional=self.ponto,
            ubicacao_padrao=self.ubicacao,
            ativo=True,
        )
        response = self.client.get(reverse("estoque:categorias_produto"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 ativos")

    def test_api_categoria_produto_criar_cadastra_e_retorna_categoria(self):
        response = self.client.post(
            reverse("estoque:api_categoria_produto_criar"),
            data={"nome": "Conectores", "margem_padrao": "18.50"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["criada"])
        self.assertEqual(payload["categoria"]["nome"], "Conectores")
        self.assertTrue(CategoriaProduto.objects.filter(nome="Conectores", margem_padrao=Decimal("18.50")).exists())

    def test_api_categoria_produto_criar_reaproveita_existente_sem_duplicar(self):
        categoria = CategoriaProduto.objects.create(nome="Cabos", margem_padrao=Decimal("12.00"), ativo=True)
        response = self.client.post(
            reverse("estoque:api_categoria_produto_criar"),
            data={"nome": " cabos  ", "margem_padrao": "25.00"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["criada"])
        self.assertEqual(payload["categoria"]["id"], categoria.id)
        self.assertEqual(CategoriaProduto.objects.filter(nome__iexact="Cabos").count(), 1)

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
                justificativa_preco_abaixo_minimo="Campanha promocional planejada.",
            )
        )
        self.assertTrue(form_ok.is_valid())

    def test_form_exige_ubicacao_padrao_para_item_fisico(self):
        form = ProdutoForm(
            data=self._payload_produto(
                nome="Produto Sem Ubicacao",
                ubicacao_padrao="",
            )
        )
        self.assertFalse(form.is_valid())
        self.assertIn("ubicacao_padrao", form.errors)

    def test_form_rejeita_ean_duplicado_com_mensagem_clara(self):
        Produto.objects.create(
            empresa=self.empresa,
            nome="Produto EAN Base",
            ean="7891234567890",
            sku="SKU-EAN-BASE",
            preco_final=Decimal("10.00"),
            preco=Decimal("10.00"),
            quantidade=1,
            ponto_operacional=self.ponto,
            ubicacao_padrao=self.ubicacao,
            ativo=True,
        )
        response = self.client.post(
            reverse("estoque:criar_produto"),
            data=self._payload_produto(
                nome="Produto EAN Duplicado",
                ean="7891234567890",
                estoque_inicial="0",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ja existe um produto cadastrado com este EAN.")

    def test_editar_produto_exibe_historico_da_ultima_compra_na_precificacao(self):
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Produto com Historico Compra",
            ean="7891234567001",
            sku="SKU-HIST-COMPRA",
            preco_final=Decimal("80.00"),
            preco=Decimal("80.00"),
            quantidade=1,
            ponto_operacional=self.ponto,
            ubicacao_padrao=self.ubicacao,
            ativo=True,
        )
        entrada = EntradaMercadoria.objects.create(
            empresa=self.empresa,
            fornecedor_manual="Fornecedor Historico",
            documento_numero="NF-HIST-01",
            data_emissao=timezone.localdate(),
            data_entrada=timezone.localdate(),
            ponto_operacional=self.ponto,
            ubicacao=self.ubicacao,
            status="recebida",
            usuario=self.user,
        )
        ItemEntradaMercadoria.objects.create(
            entrada=entrada,
            produto=produto,
            quantidade=2,
            custo_unitario=Decimal("25.00"),
            impostos_entrada_unitario=Decimal("1.00"),
            frete_rateado_unitario=Decimal("0.50"),
            outras_despesas_rateadas_unitario=Decimal("0.25"),
            desconto_unitario=Decimal("0.00"),
        )

        response = self.client.get(reverse("estoque:editar_produto", args=[produto.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ultimo custo de entrada")
        self.assertContains(response, "Compras recentes deste item")
        self.assertContains(response, "Fornecedor Historico")
        self.assertContains(response, "NF-HIST-01")
        self.assertContains(response, "26,75")

    def test_form_aceita_data_entrada_no_dia_do_sistema(self):
        form = ProdutoForm(
            data=self._payload_produto(
                nome="Produto Data Atual",
                ean="7891234567891",
                estoque_inicial="0",
                data_entrada=date.today().isoformat(),
            )
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_duplicar_produto_redireciona_para_criacao(self):
        produto = Produto.objects.create(
            empresa=self.empresa,
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
            {
                "arquivo": arquivo_validar,
                "acao": "validar",
                "ponto_operacional_padrao": str(self.ponto.id),
                "ubicacao_padrao_importacao": str(self.ubicacao.id),
            },
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
            {
                "arquivo": arquivo_importar,
                "acao": "importar",
                "ponto_operacional_padrao": str(self.ponto.id),
                "ubicacao_padrao_importacao": str(self.ubicacao.id),
            },
        )
        self.assertEqual(response_importar.status_code, 302)
        produto = Produto.objects.get(nome="Produto Importado")
        self.assertEqual(produto.quantidade, 2)
        self.assertEqual(produto.ponto_operacional_id, self.ponto.id)
        self.assertEqual(produto.ubicacao_padrao_id, self.ubicacao.id)
        self.assertTrue(
            ProdutoHistorico.objects.filter(produto=produto, acao="IMPORTACAO").exists()
        )

    def test_baixar_modelo_importacao_inclui_custos_e_classificacao_fiscal(self):
        response = self.client.get(reverse("estoque:modelo_importacao_produtos"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("modelo_importacao_produtos.csv", response["Content-Disposition"])
        conteudo = response.content.decode("utf-8-sig")
        self.assertIn("custo_frete", conteudo)
        self.assertIn("margem_lucro", conteudo)
        self.assertIn("ncm", conteudo)
        self.assertIn("cst_csosn", conteudo)

    def test_mapeamento_de_planilha_e_salvo_por_fornecedor_e_reutilizado(self):
        fornecedor = FornecedorGarantia.objects.create(
            empresa=self.empresa, nome="Fornecedor planilha", fornecedor_comercial=True
        )
        conteudo = "Descricao do item;Custo compra;Classificacao;Preco\nCapa mapeada;18.50;39269090;0\n"
        response = self.client.post(
            reverse("estoque:importar_produtos"),
            {
                "arquivo": SimpleUploadedFile("catalogo.csv", conteudo.encode("utf-8"), content_type="text/csv"),
                "acao": "validar", "ponto_operacional_padrao": str(self.ponto.id),
                "ubicacao_padrao_importacao": str(self.ubicacao.id),
                "fornecedor_mapeamento": str(fornecedor.id), "salvar_mapeamento": "1",
                "nome_mapeamento": "Catalogo padrao",
                "mapeamento_colunas": "nome=Descricao do item;custo_unitario=Custo compra;ncm=Classificacao;preco_final=Preco",
            },
        )
        self.assertEqual(response.status_code, 200)
        mapa = MapeamentoImportacaoProduto.objects.get(empresa=self.empresa, fornecedor=fornecedor)
        self.assertEqual(mapa.mapeamento["nome"], "Descricao do item")

        response = self.client.post(
            reverse("estoque:importar_produtos"),
            {
                "arquivo": SimpleUploadedFile("catalogo.csv", conteudo.encode("utf-8"), content_type="text/csv"),
                "acao": "importar", "ponto_operacional_padrao": str(self.ponto.id),
                "ubicacao_padrao_importacao": str(self.ubicacao.id), "mapeamento_salvo": str(mapa.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        produto = Produto.objects.get(nome="Capa mapeada")
        self.assertEqual(produto.ncm, "39269090")
        self.assertEqual(produto.fornecedor_config, fornecedor)

    def test_importar_produtos_rejeita_ponto_invalido_no_arquivo(self):
        csv_content = "\n".join(
            [
                "nome,sku,ean,tipo_item,categoria,custo_unitario,preco_final,estoque_minimo,estoque_inicial,ponto_operacional,ubicacao",
                "Produto Sem Estrutura,SKU-IMP-02,7894440000003,produto,Eletronico,30.00,60.00,1,2,PONTO-X,A1",
            ]
        )
        arquivo_validar = SimpleUploadedFile(
            "produtos_sem_estrutura.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )
        response_validar = self.client.post(
            reverse("estoque:importar_produtos"),
            {"arquivo": arquivo_validar, "acao": "validar", "ponto_operacional_padrao": "", "ubicacao_padrao_importacao": ""},
        )
        self.assertEqual(response_validar.status_code, 200)
        self.assertContains(response_validar, "Ponto operacional da linha nao encontrado")
        self.assertFalse(Produto.objects.filter(nome="Produto Sem Estrutura").exists())

    def test_importar_planilha_fiscal_aplica_custos_classificacao_e_preco_automatico(self):
        csv_content = "\n".join(
            [
                "nome,sku,ean,tipo_item,categoria,custo_unitario,custo_frete,custo_impostos,margem_lucro,preco_final,ncm,cest,cfop,cst_csosn,origem_mercadoria,unidade_comercial,estoque_inicial",
                "Capa Fiscal Lote,SKU-FISC-01,7894440000099,produto,Acessorios,20.00,2.00,1.00,35.00,0,39269090,0100100,5102,102,0,UN,0",
            ]
        )
        arquivo = SimpleUploadedFile("produtos_fiscais.csv", csv_content.encode("utf-8"), content_type="text/csv")
        response = self.client.post(
            reverse("estoque:importar_produtos"),
            {
                "arquivo": arquivo,
                "acao": "importar",
                "ponto_operacional_padrao": str(self.ponto.id),
                "ubicacao_padrao_importacao": str(self.ubicacao.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        produto = Produto.objects.get(nome="Capa Fiscal Lote")
        self.assertEqual(produto.ncm, "39269090")
        self.assertEqual(produto.cest, "0100100")
        self.assertEqual(produto.cfop_padrao, "5102")
        self.assertEqual(produto.cst_csosn, "102")
        self.assertEqual(produto.custo_frete, Decimal("2.00"))
        self.assertEqual(produto.custo_impostos, Decimal("1.00"))
        self.assertEqual(produto.margem_lucro, Decimal("35.00"))
        self.assertGreater(produto.preco_final, Decimal("23.00"))
        self.assertTrue(produto.precificacao_snapshot)

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
            empresa=self.empresa,
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
            empresa=self.empresa,
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
            empresa=self.empresa,
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
            empresa=self.empresa,
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
            empresa=self.empresa,
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
            empresa=self.empresa,
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


class PoliticaCustoEstoqueTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome="Empresa Custo",
            regime_tributario="simples",
            modo_tributario="basico",
        )
        self.ponto_origem = PontoOperacional.objects.create(codigo="PC3", nome="Loja custo")
        self.ponto_destino = PontoOperacional.objects.create(codigo="PC2", nome="Armazem custo")
        self.ubicacao_origem = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto_origem,
            codigo="A1",
            descricao="Prateleira 1",
            ativo=True,
        )
        self.ubicacao_destino = UbicacaoEstoque.objects.create(
            ponto_operacional=self.ponto_destino,
            codigo="B1",
            descricao="Caixa destino",
            ativo=True,
        )
        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Produto Camadas",
            ean="7899998887776",
            sku="SKU-CAMADAS-01",
            tipo_item="produto",
            custo_unitario=Decimal("0.00"),
            custo_medio=Decimal("0.00"),
            preco_final=Decimal("100.00"),
            preco=Decimal("100.00"),
            quantidade=0,
            ponto_operacional=self.ponto_origem,
            ubicacao_padrao=self.ubicacao_origem,
            ativo=True,
        )
        self.config = ConfiguracaoSistema.get_configuracao()

    def _registrar_entrada(self, quantidade, custo):
        from estoque.services import registrar_movimentacao_estoque

        return registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="entrada",
            quantidade=quantidade,
            destino=self.ponto_origem,
            destino_ubicacao_ref=self.ubicacao_origem,
            valor_unitario_custo=Decimal(str(custo)),
            observacao="Entrada teste",
        )

    def test_pmp_consume_pelo_custo_medio(self):
        from estoque.services import registrar_movimentacao_estoque

        self.config.estoque_metodo_custo = ConfiguracaoSistema.ESTOQUE_METODO_CUSTO_PMP
        self.config.save(update_fields=["estoque_metodo_custo", "data_atualizacao"])

        self._registrar_entrada(2, "10.00")
        self._registrar_entrada(2, "30.00")

        movimento = registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="venda",
            quantidade=2,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            observacao="Saida PMP",
        )

        self.assertEqual(movimento.valor_unitario_custo, Decimal("20.00"))
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_origem)
        self.assertEqual(saldo.quantidade, 2)

    def test_peps_consume_primeira_camada(self):
        from estoque.services import registrar_movimentacao_estoque

        self.config.estoque_metodo_custo = ConfiguracaoSistema.ESTOQUE_METODO_CUSTO_PEPS
        self.config.save(update_fields=["estoque_metodo_custo", "data_atualizacao"])

        self._registrar_entrada(2, "10.00")
        self._registrar_entrada(2, "30.00")

        movimento = registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="venda",
            quantidade=2,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            observacao="Saida PEPS",
        )

        self.assertEqual(movimento.valor_unitario_custo, Decimal("10.00"))
        camadas = list(
            EstoqueCamadaCusto.objects.filter(produto=self.produto, ubicacao=self.ubicacao_origem).order_by("criado_em", "id")
        )
        self.assertEqual(camadas[0].quantidade_saldo, 0)
        self.assertEqual(camadas[1].quantidade_saldo, 2)

    def test_transferencia_replica_camada_no_destino(self):
        from estoque.services import registrar_movimentacao_estoque

        self.config.estoque_metodo_custo = ConfiguracaoSistema.ESTOQUE_METODO_CUSTO_PEPS
        self.config.save(update_fields=["estoque_metodo_custo", "data_atualizacao"])

        self._registrar_entrada(3, "18.00")
        registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="transferencia",
            quantidade=1,
            origem=self.ponto_origem,
            destino=self.ponto_destino,
            origem_ubicacao=self.ubicacao_origem,
            destino_ubicacao_ref=self.ubicacao_destino,
            observacao="Transferencia teste",
        )

        camada_destino = EstoqueCamadaCusto.objects.filter(
            produto=self.produto,
            ponto_operacional=self.ponto_destino,
            ubicacao=self.ubicacao_destino,
        ).first()
        self.assertIsNotNone(camada_destino)
        self.assertEqual(camada_destino.quantidade_saldo, 1)
        self.assertEqual(camada_destino.custo_unitario, Decimal("18.00"))

    def test_oferta_baixa_estoque_pelo_custo_sem_movimentar_caixa(self):
        from estoque.services import registrar_movimentacao_estoque

        self._registrar_entrada(3, "12.00")
        pagamentos_antes = Pagamento.objects.count()

        movimento = registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="oferta",
            quantidade=1,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            observacao="Brinde para cliente da campanha de fidelizacao",
        )

        self.assertEqual(movimento.quantidade, -1)
        self.assertEqual(movimento.valor_unitario_custo, Decimal("12.00"))
        saldo = SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_origem)
        self.assertEqual(saldo.quantidade, 2)
        self.assertEqual(Pagamento.objects.count(), pagamentos_antes)

    def test_cedencia_baixa_estoque_e_exige_justificativa(self):
        from estoque.services import registrar_movimentacao_estoque

        self._registrar_entrada(2, "15.00")
        with self.assertRaisesMessage(ValueError, "motivo ou beneficiario"):
            registrar_movimentacao_estoque(
                produto=self.produto,
                tipo="cedencia",
                quantidade=1,
                origem=self.ponto_origem,
                origem_ubicacao=self.ubicacao_origem,
                observacao="",
            )

        movimento = registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="cedencia",
            quantidade=1,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            observacao="Cedida ao laboratorio interno para testes",
        )
        self.assertEqual(movimento.quantidade, -1)

    def test_form_oferta_exige_quantidade_positiva_e_observacao(self):
        form = MovimentacaoEstoqueForm(
            data={
                "produto": self.produto.id,
                "tipo": "oferta",
                "quantidade": -1,
                "origem": self.ponto_origem.id,
                "origem_ubicacao": self.ubicacao_origem.id,
                "observacao": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("quantidade", form.errors)
        self.assertIn("observacao", form.errors)

    def test_avaria_recebe_quantidade_positiva_e_grava_baixa_com_custo(self):
        from estoque.services import registrar_movimentacao_estoque

        self._registrar_entrada(3, "11.50")
        movimento = registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="avaria",
            quantidade=1,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            observacao="Quebra durante manuseio",
        )

        self.assertEqual(movimento.quantidade, -1)
        self.assertEqual(movimento.valor_total_custo, Decimal("11.50"))
        self.assertEqual(
            SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_origem).quantidade,
            2,
        )

    def test_oferta_nao_consume_saldo_reservado(self):
        from estoque.services import criar_reserva_estoque, registrar_movimentacao_estoque, saldo_disponivel

        self._registrar_entrada(3, "10.00")
        criar_reserva_estoque(
            produto=self.produto,
            ponto_operacional=self.ponto_origem,
            ubicacao=self.ubicacao_origem,
            quantidade=2,
            nome_contato="Cliente reservado",
            valido_ate=timezone.localdate() + timedelta(days=1),
        )
        self.assertEqual(saldo_disponivel(self.produto, self.ponto_origem, self.ubicacao_origem), 1)

        with self.assertRaisesMessage(ValueError, "Disponivel apos reservas: 1"):
            registrar_movimentacao_estoque(
                produto=self.produto,
                tipo="oferta",
                quantidade=2,
                origem=self.ponto_origem,
                origem_ubicacao=self.ubicacao_origem,
                observacao="Oferta indevida",
            )

    def test_oferta_acima_da_alcada_fica_pendente_sem_baixar_estoque(self):
        from estoque.services import criar_solicitacao_saida_estoque

        self._registrar_entrada(3, "20.00")
        self.empresa.limite_oferta_sem_aprovacao = Decimal("5.00")
        self.empresa.save(update_fields=["limite_oferta_sem_aprovacao"])
        solicitante = get_user_model().objects.create_user(
            username="solicitante_oferta",
            password="senha-forte-123",
            empresa=self.empresa,
            tipo_usuario="atendente",
        )

        solicitacao = criar_solicitacao_saida_estoque(
            produto=self.produto,
            tipo="oferta",
            quantidade=1,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            finalidade="brinde_comercial",
            beneficiario_nome="Cliente campanha",
            campanha="Lançamento",
            observacao="Brinde autorizado por campanha",
            usuario=solicitante,
        )

        self.assertEqual(solicitacao.status, "pendente")
        self.assertTrue(solicitacao.exige_aprovacao)
        self.assertIsNone(solicitacao.movimento_id)
        self.assertEqual(
            SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_origem).quantidade,
            3,
        )

    def test_gerente_aprova_solicitacao_e_baixa_pelo_custo(self):
        from estoque.services import criar_solicitacao_saida_estoque, executar_solicitacao_saida_estoque

        self._registrar_entrada(2, "18.00")
        self.empresa.limite_cedencia_sem_aprovacao = Decimal("1.00")
        self.empresa.save(update_fields=["limite_cedencia_sem_aprovacao"])
        solicitante = get_user_model().objects.create_user(
            username="solicitante_cedencia",
            password="senha-forte-123",
            empresa=self.empresa,
            tipo_usuario="atendente",
        )
        gerente = get_user_model().objects.create_user(
            username="gerente_cedencia",
            password="senha-forte-123",
            empresa=self.empresa,
            tipo_usuario="gerente",
        )
        solicitacao = criar_solicitacao_saida_estoque(
            produto=self.produto,
            tipo="cedencia",
            quantidade=1,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            finalidade="uso_interno",
            beneficiario_nome="Laboratório",
            observacao="Teste interno",
            usuario=solicitante,
        )

        solicitacao = executar_solicitacao_saida_estoque(solicitacao, aprovador=gerente)

        self.assertEqual(solicitacao.status, "executada")
        self.assertEqual(solicitacao.valor_total_custo, Decimal("18.00"))
        self.assertEqual(solicitacao.movimento.quantidade, -1)
        self.assertEqual(solicitacao.movimento.origem_tipo, "solicitacao_saida")
        self.assertEqual(solicitacao.aprovado_por, gerente)

    def test_rejeicao_preserva_saldo_e_motivo(self):
        from estoque.services import criar_solicitacao_saida_estoque, rejeitar_solicitacao_saida_estoque

        self._registrar_entrada(1, "12.00")
        self.empresa.limite_oferta_sem_aprovacao = Decimal("0.00")
        self.empresa.save(update_fields=["limite_oferta_sem_aprovacao"])
        solicitante = get_user_model().objects.create_user(
            username="solicitante_rejeicao",
            password="senha-forte-123",
            empresa=self.empresa,
            tipo_usuario="atendente",
        )
        gerente = get_user_model().objects.create_user(
            username="gerente_rejeicao",
            password="senha-forte-123",
            empresa=self.empresa,
            tipo_usuario="gerente",
        )
        solicitacao = criar_solicitacao_saida_estoque(
            produto=self.produto,
            tipo="oferta",
            quantidade=1,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            finalidade="doacao",
            beneficiario_nome="Entidade",
            observacao="Solicitação de doação",
            usuario=solicitante,
        )

        rejeitar_solicitacao_saida_estoque(solicitacao, usuario=gerente, motivo="Fora da política comercial")
        solicitacao.refresh_from_db()

        self.assertEqual(solicitacao.status, "rejeitada")
        self.assertEqual(solicitacao.motivo_rejeicao, "Fora da política comercial")
        self.assertIsNone(solicitacao.movimento_id)
        self.assertEqual(
            SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_origem).quantidade,
            1,
        )

    def test_cedencia_temporaria_devolvida_recompoe_quantidade_e_custo(self):
        from estoque.services import criar_solicitacao_saida_estoque, devolver_cedencia_estoque

        self._registrar_entrada(2, "16.00")
        gerente = get_user_model().objects.create_user(
            username="gerente_retorno_cedencia",
            password="senha-forte-123",
            empresa=self.empresa,
            tipo_usuario="gerente",
        )
        solicitacao = criar_solicitacao_saida_estoque(
            produto=self.produto,
            tipo="cedencia",
            quantidade=1,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            finalidade="cedencia_temporaria",
            beneficiario_nome="Equipe de demonstração",
            observacao="Uso em evento",
            usuario=gerente,
            aprovar_automaticamente=True,
        )

        solicitacao = devolver_cedencia_estoque(
            solicitacao,
            usuario=gerente,
            observacao="Item devolvido em bom estado",
        )

        self.assertEqual(solicitacao.status, "devolvida")
        self.assertEqual(solicitacao.movimento_retorno.quantidade, 1)
        self.assertEqual(solicitacao.movimento_retorno.valor_unitario_custo, Decimal("16.00"))
        self.assertEqual(
            SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_origem).quantidade,
            2,
        )

    def test_auditoria_detecta_reserva_lote_e_serie_inconsistentes(self):
        from estoque.services import diagnosticar_inconsistencias_estoque

        self._registrar_entrada(1, "10.00")
        self.produto.controla_lote = True
        self.produto.controla_serie = True
        self.produto.save(update_fields=["controla_lote", "controla_serie"])
        ReservaEstoque.objects.create(
            codigo_reserva="RES-AUDIT01",
            produto=self.produto,
            ponto_operacional=self.ponto_origem,
            ubicacao=self.ubicacao_origem,
            quantidade=2,
            nome_contato="Reserva inconsistente",
            valido_ate=timezone.localdate() + timedelta(days=1),
            status="ativa",
        )

        diagnostico = diagnosticar_inconsistencias_estoque(empresa=self.empresa)

        self.assertEqual(len(diagnostico["reservas_excedentes"]), 1)
        self.assertEqual(diagnostico["reservas_excedentes"][0]["excesso"], 1)
        self.assertEqual(len(diagnostico["divergencias_lotes"]), 1)
        self.assertEqual(len(diagnostico["divergencias_series"]), 1)

    def test_chave_idempotencia_impede_baixa_duplicada(self):
        from estoque.services import registrar_movimentacao_estoque

        self._registrar_entrada(3, "9.00")
        parametros = {
            "produto": self.produto,
            "tipo": "oferta",
            "quantidade": 1,
            "origem": self.ponto_origem,
            "origem_ubicacao": self.ubicacao_origem,
            "observacao": "Brinde idempotente",
            "chave_idempotencia": "campanha:2026:cliente-1",
        }
        primeiro = registrar_movimentacao_estoque(**parametros)
        segundo = registrar_movimentacao_estoque(**parametros)

        self.assertEqual(primeiro.pk, segundo.pk)
        self.assertEqual(MovimentacaoEstoque.objects.filter(chave_idempotencia=parametros["chave_idempotencia"]).count(), 1)
        self.assertEqual(
            SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_origem).quantidade,
            2,
        )

    def test_estorno_formal_restaura_saida_e_fica_vinculado(self):
        from estoque.services import estornar_movimentacao_estoque, registrar_movimentacao_estoque

        self._registrar_entrada(2, "14.00")
        saida = registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="cedencia",
            quantidade=1,
            origem=self.ponto_origem,
            origem_ubicacao=self.ubicacao_origem,
            observacao="Uso interno",
        )
        estorno = estornar_movimentacao_estoque(saida, motivo="Cedencia lancada em duplicidade")

        self.assertEqual(estorno.movimento_estornado_id, saida.pk)
        self.assertEqual(estorno.valor_total_custo, Decimal("14.00"))
        self.assertEqual(
            SaldoEstoquePonto.objects.get(produto=self.produto, ponto_operacional=self.ponto_origem).quantidade,
            2,
        )

    def test_tabela_de_preco_e_aplicada_e_fica_registrada_no_cesto(self):
        from estoque.services import criar_item_cesto_venda_rapida

        self._registrar_entrada(2, "10.00")
        tabela = TabelaPreco.objects.create(empresa=self.empresa, nome="Atacado")
        ProdutoPrecoTabela.objects.create(produto=self.produto, tabela=tabela, preco=Decimal("77.00"))
        self.config.estoque_venda_mostrador_codigos = self.ponto_origem.codigo
        self.config.save(update_fields=["estoque_venda_mostrador_codigos", "data_atualizacao"])
        vendedor = get_user_model().objects.create_user(
            username="vendedor_tabela_preco",
            password="senha-forte-123",
            empresa=self.empresa,
            tipo_usuario="atendente",
        )

        resultado = criar_item_cesto_venda_rapida(
            produto=self.produto,
            ponto_operacional=self.ponto_origem,
            quantidade=1,
            funcionario_numero=vendedor.numero_vendedor,
            tabela_preco=tabela,
        )

        self.assertEqual(resultado["venda"].valor_unitario, Decimal("77.00"))
        self.assertEqual(resultado["venda"].tabela_preco_nome, "Atacado")

    def test_pre_reserva_de_kit_compromete_saldo_dos_componentes(self):
        from estoque.services import componentes_fisicos_venda, saldo_disponivel

        self._registrar_entrada(5, "8.00")
        kit = Produto.objects.create(
            empresa=self.empresa,
            nome="Kit duas pecas",
            tipo_item="produto",
            preco_final=Decimal("40.00"),
            preco=Decimal("40.00"),
            ponto_operacional=self.ponto_origem,
        )
        ProdutoKitItem.objects.create(produto_kit=kit, componente=self.produto, quantidade=2)
        VendaRapidaEstoque.objects.create(
            produto=kit,
            ponto_operacional=self.ponto_origem,
            quantidade=2,
            valor_unitario=Decimal("40.00"),
            valor_total=Decimal("80.00"),
            funcionario_numero="99",
            status="pre_reserva",
        )

        self.assertEqual(componentes_fisicos_venda(kit, 2), [(self.produto, 4)])
        self.assertEqual(saldo_disponivel(self.produto, self.ponto_origem), 1)

    def test_pre_reserva_preserva_composicao_historica_do_kit(self):
        from estoque.services import componentes_fisicos_item_venda, criar_item_cesto_venda_rapida, saldo_disponivel

        self._registrar_entrada(5, "8.00")
        kit = Produto.objects.create(
            empresa=self.empresa,
            nome="Kit com snapshot",
            tipo_item="produto",
            preco_final=Decimal("40.00"),
            preco=Decimal("40.00"),
            ponto_operacional=self.ponto_origem,
        )
        item_kit = ProdutoKitItem.objects.create(produto_kit=kit, componente=self.produto, quantidade=2)
        self.config.estoque_venda_mostrador_codigos = self.ponto_origem.codigo
        self.config.save(update_fields=["estoque_venda_mostrador_codigos", "data_atualizacao"])
        vendedor = get_user_model().objects.create_user(
            username="vendedor_snapshot_kit",
            password="senha-forte-123",
            empresa=self.empresa,
            tipo_usuario="atendente",
        )
        venda = criar_item_cesto_venda_rapida(
            produto=kit,
            ponto_operacional=self.ponto_origem,
            quantidade=2,
            funcionario_numero=vendedor.numero_vendedor,
            usuario=vendedor,
        )["venda"]

        item_kit.quantidade = 1
        item_kit.save(update_fields=["quantidade"])

        self.assertEqual(componentes_fisicos_item_venda(venda), [(self.produto, 4)])
        self.assertEqual(venda.composicao_kit_snapshot[0]["produto_id"], self.produto.pk)
        self.assertEqual(saldo_disponivel(self.produto, self.ponto_origem), 1)

    def test_kit_rejeita_componente_inativo_e_kit_aninhado(self):
        componente_inativo = Produto.objects.create(
            empresa=self.empresa,
            nome="Componente inativo",
            tipo_item="produto",
            preco_final=Decimal("10.00"),
            preco=Decimal("10.00"),
            ativo=False,
        )
        kit_interno = Produto.objects.create(
            empresa=self.empresa,
            nome="Kit interno",
            tipo_item="produto",
            preco_final=Decimal("20.00"),
            preco=Decimal("20.00"),
        )
        ProdutoKitItem.objects.create(produto_kit=kit_interno, componente=self.produto, quantidade=1)
        kit_externo = Produto.objects.create(
            empresa=self.empresa,
            nome="Kit externo",
            tipo_item="produto",
            preco_final=Decimal("30.00"),
            preco=Decimal("30.00"),
        )

        with self.assertRaisesMessage(ValidationError, "componente inativo"):
            ProdutoKitItem(produto_kit=kit_externo, componente=componente_inativo, quantidade=1).full_clean()
        with self.assertRaisesMessage(ValidationError, "Kits aninhados"):
            ProdutoKitItem(produto_kit=kit_externo, componente=kit_interno, quantidade=1).full_clean()


class EntradaMercadoriaTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.empresa = Empresa.objects.create(nome="Empresa Entrada", regime_tributario="simples", modo_tributario="basico")
        self.user = user_model.objects.create_user(
            username="usuario_entrada_mercadoria",
            password="senha-forte-123",
            tipo_usuario="adm",
            empresa=self.empresa,
            perm_estoque_cadastro_produto=True,
        )
        self.client.force_login(self.user)
        self.ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja", ativo=True)
        self.ubicacao = UbicacaoEstoque.objects.create(ponto_operacional=self.ponto, codigo="A1", descricao="Principal", ativo=True)
        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Produto Entrada",
            ean="7894561234567",
            sku="SKU-ENT-01",
            preco_final=Decimal("30.00"),
            preco=Decimal("30.00"),
            quantidade=0,
            ponto_operacional=self.ponto,
            ubicacao_padrao=self.ubicacao,
            ativo=True,
        )

    def _payload_entrada(self):
        return {
            "fornecedor_manual": "Fornecedor Teste",
            "documento_numero": "NF-1001",
            "serie_documento": "1",
            "data_emissao": timezone.localdate().isoformat(),
            "data_entrada": timezone.localdate().isoformat(),
            "ponto_operacional": str(self.ponto.id),
            "ubicacao": str(self.ubicacao.id),
            "frete_total": "10.00",
            "seguro_total": "0.00",
            "outras_despesas_total": "5.00",
            "desconto_total": "0.00",
            "observacao": "Reposicao semanal",
            "itens-TOTAL_FORMS": "5",
            "itens-INITIAL_FORMS": "0",
            "itens-MIN_NUM_FORMS": "1",
            "itens-MAX_NUM_FORMS": "1000",
            "itens-0-produto": str(self.produto.id),
            "itens-0-quantidade": "4",
            "itens-0-custo_unitario": "12.00",
            "itens-0-impostos_entrada_unitario": "1.00",
            "itens-0-frete_rateado_unitario": "0.50",
            "itens-0-outras_despesas_rateadas_unitario": "0.25",
            "itens-0-desconto_unitario": "0.00",
            "itens-0-observacao": "",
            "itens-1-produto": "",
            "itens-1-quantidade": "",
            "itens-1-custo_unitario": "",
            "itens-1-impostos_entrada_unitario": "",
            "itens-1-frete_rateado_unitario": "",
            "itens-1-outras_despesas_rateadas_unitario": "",
            "itens-1-desconto_unitario": "",
            "itens-1-observacao": "",
            "itens-2-produto": "",
            "itens-2-quantidade": "",
            "itens-2-custo_unitario": "",
            "itens-2-impostos_entrada_unitario": "",
            "itens-2-frete_rateado_unitario": "",
            "itens-2-outras_despesas_rateadas_unitario": "",
            "itens-2-desconto_unitario": "",
            "itens-2-observacao": "",
            "itens-3-produto": "",
            "itens-3-quantidade": "",
            "itens-3-custo_unitario": "",
            "itens-3-impostos_entrada_unitario": "",
            "itens-3-frete_rateado_unitario": "",
            "itens-3-outras_despesas_rateadas_unitario": "",
            "itens-3-desconto_unitario": "",
            "itens-3-observacao": "",
            "itens-4-produto": "",
            "itens-4-quantidade": "",
            "itens-4-custo_unitario": "",
            "itens-4-impostos_entrada_unitario": "",
            "itens-4-frete_rateado_unitario": "",
            "itens-4-outras_despesas_rateadas_unitario": "",
            "itens-4-desconto_unitario": "",
            "itens-4-observacao": "",
        }

    def test_form_entrada_mercadoria_exibe_orientacao_de_custo(self):
        response = self.client.get(reverse("estoque:nova_entrada_mercadoria"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Como pensar esta entrada")
        self.assertContains(response, "Destino fisico")
        self.assertContains(response, "Ponto de entrada")
        self.assertContains(response, "Ubicacao de destino")
        self.assertContains(response, "Imposto recuperavel nao deve inflar o PMP")
        self.assertContains(response, "Impostos que compoem custo")

    def test_lista_entradas_exibe_resumo_operacional_e_paginacao(self):
        for i in range(22):
            EntradaMercadoria.objects.create(
                empresa=self.empresa,
                fornecedor_manual=f"Fornecedor {i}",
                documento_numero=f"NF-PAG-{i:03d}",
                ponto_operacional=self.ponto,
                ubicacao=self.ubicacao,
            )

        response = self.client.get(reverse("estoque:entradas_mercadoria"), {"page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Carteira de recebimento")
        self.assertContains(response, "Como usar esta tela")
        self.assertContains(response, "Resultado atual")
        self.assertEqual(response.context["entradas_page"].number, 2)

    def test_detalhe_entrada_exibe_leitura_operacional_e_bloqueio_pos_recebimento(self):
        self.client.post(reverse("estoque:nova_entrada_mercadoria"), data=self._payload_entrada())
        entrada = EntradaMercadoria.objects.get(documento_numero="NF-1001")
        self.client.post(reverse("estoque:receber_entrada_mercadoria", args=[entrada.id]))

        response = self.client.get(reverse("estoque:detalhe_entrada_mercadoria", args=[entrada.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Leitura operacional desta entrada")
        self.assertContains(response, "Entrada consolidada.")
        self.assertContains(response, "Total geral")

    def test_nova_entrada_mercadoria_pre_preenche_produto_fornecedor_e_destino(self):
        response = self.client.get(
            reverse("estoque:nova_entrada_mercadoria"),
            {
                "produto": self.produto.id,
                "fornecedor_manual": "Fornecedor Recompra",
                "ponto": self.ponto.id,
                "ubicacao": self.ubicacao.id,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recompra iniciada a partir do produto")
        form = response.context["form"]
        formset = response.context["formset"]
        self.assertEqual(form.initial.get("fornecedor_manual"), "Fornecedor Recompra")
        self.assertEqual(str(form.initial.get("ponto_operacional")), str(self.ponto.id))
        self.assertEqual(str(form.initial.get("ubicacao")), str(self.ubicacao.id))
        self.assertEqual(str(formset.forms[0].initial.get("produto")), str(self.produto.id))

    def test_criar_e_receber_entrada_mercadoria_movimenta_estoque(self):
        response = self.client.post(reverse("estoque:nova_entrada_mercadoria"), data=self._payload_entrada())
        self.assertEqual(response.status_code, 302)

        entrada = EntradaMercadoria.objects.get(documento_numero="NF-1001")
        self.assertEqual(entrada.status, "rascunho")
        item = ItemEntradaMercadoria.objects.get(entrada=entrada)
        self.assertEqual(item.custo_entrada_unitario, Decimal("13.75"))

        response_receber = self.client.post(reverse("estoque:receber_entrada_mercadoria", args=[entrada.id]))
        self.assertEqual(response_receber.status_code, 302)

        entrada.refresh_from_db()
        self.produto.refresh_from_db()
        self.assertEqual(entrada.status, "recebida")
        self.assertEqual(self.produto.quantidade, 4)
        self.assertTrue(
            MovimentacaoEstoque.objects.filter(
                produto=self.produto,
                tipo="entrada",
                destino=self.ponto,
                destino_ubicacao_ref=self.ubicacao,
            ).exists()
        )

    def test_entrada_mercadoria_aplica_rateio_automatico_quando_itens_nao_tem_rateio_manual(self):
        payload = self._payload_entrada()
        payload["itens-0-frete_rateado_unitario"] = "0.00"
        payload["itens-0-outras_despesas_rateadas_unitario"] = "0.00"
        response = self.client.post(reverse("estoque:nova_entrada_mercadoria"), data=payload)
        self.assertEqual(response.status_code, 302)

        entrada = EntradaMercadoria.objects.get(documento_numero="NF-1001")
        item = ItemEntradaMercadoria.objects.get(entrada=entrada)

        self.assertTrue(entrada.usar_rateio_automatico)
        self.assertEqual(item.rateio_automatico_unitario, Decimal("3.75"))
        self.assertEqual(item.custo_entrada_unitario, Decimal("16.75"))

    def test_editar_entrada_em_rascunho_atualiza_itens(self):
        response = self.client.post(reverse("estoque:nova_entrada_mercadoria"), data=self._payload_entrada())
        self.assertEqual(response.status_code, 302)
        entrada = EntradaMercadoria.objects.get(documento_numero="NF-1001")
        payload = self._payload_entrada()
        payload["documento_numero"] = "NF-1001-REV"
        payload["itens-0-quantidade"] = "6"

        response = self.client.post(reverse("estoque:editar_entrada_mercadoria", args=[entrada.id]), data=payload)
        self.assertEqual(response.status_code, 302)
        entrada.refresh_from_db()
        self.assertEqual(entrada.documento_numero, "NF-1001-REV")
        self.assertEqual(entrada.itens.get().quantidade, 6)

    def test_cancelar_rascunho_nao_movimenta_estoque(self):
        self.client.post(reverse("estoque:nova_entrada_mercadoria"), data=self._payload_entrada())
        entrada = EntradaMercadoria.objects.get(documento_numero="NF-1001")

        response = self.client.post(
            reverse("estoque:cancelar_entrada_mercadoria", args=[entrada.id]),
            {"motivo": "Documento emitido incorretamente"},
        )

        self.assertEqual(response.status_code, 302)
        entrada.refresh_from_db()
        self.produto.refresh_from_db()
        self.assertEqual(entrada.status, "cancelada")
        self.assertIn("Documento emitido incorretamente", entrada.observacao)
        self.assertEqual(self.produto.quantidade, 0)
        self.assertFalse(MovimentacaoEstoque.objects.filter(produto=self.produto).exists())

    def test_entrada_recebida_nao_pode_ser_cancelada(self):
        self.client.post(reverse("estoque:nova_entrada_mercadoria"), data=self._payload_entrada())
        entrada = EntradaMercadoria.objects.get(documento_numero="NF-1001")
        self.client.post(reverse("estoque:receber_entrada_mercadoria", args=[entrada.id]))

        response = self.client.post(reverse("estoque:cancelar_entrada_mercadoria", args=[entrada.id]))

        self.assertEqual(response.status_code, 302)
        entrada.refresh_from_db()
        self.produto.refresh_from_db()
        self.assertEqual(entrada.status, "recebida")
        self.assertEqual(self.produto.quantidade, 4)

    def test_produto_controlado_exige_lote_e_series_na_entrada(self):
        self.produto.controla_lote = True
        self.produto.controla_serie = True
        self.produto.save(update_fields=["controla_lote", "controla_serie"])
        payload = self._payload_entrada()

        response = self.client.post(reverse("estoque:nova_entrada_mercadoria"), data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Este produto exige identificacao do lote")
        self.assertContains(response, "Informe exatamente 4 numero(s) de serie")

    def test_receber_entrada_controlada_registra_lote_e_series(self):
        self.produto.controla_lote = True
        self.produto.controla_serie = True
        self.produto.save(update_fields=["controla_lote", "controla_serie"])
        payload = self._payload_entrada()
        payload["itens-0-lote_codigo"] = "LOTE-2026-A"
        payload["itens-0-lote_validade"] = (timezone.localdate() + timedelta(days=180)).isoformat()
        payload["itens-0-numeros_serie"] = "SER-001\nSER-002\nSER-003\nSER-004"

        response = self.client.post(reverse("estoque:nova_entrada_mercadoria"), data=payload)
        self.assertEqual(response.status_code, 302)
        entrada = EntradaMercadoria.objects.get(documento_numero="NF-1001")
        response = self.client.post(reverse("estoque:receber_entrada_mercadoria", args=[entrada.id]))
        self.assertEqual(response.status_code, 302)

        lote = EstoqueLote.objects.get(produto=self.produto, codigo="LOTE-2026-A")
        self.assertEqual(lote.quantidade_disponivel, 4)
        self.assertEqual(lote.ponto_operacional, self.ponto)
        self.assertEqual(
            set(EstoqueSerie.objects.filter(produto=self.produto).values_list("numero", flat=True)),
            {"SER-001", "SER-002", "SER-003", "SER-004"},
        )

    def test_saida_e_devolucao_mantem_lote_e_series_consistentes(self):
        from estoque.services import registrar_movimentacao_estoque

        self.produto.controla_lote = True
        self.produto.controla_serie = True
        self.produto.save(update_fields=["controla_lote", "controla_serie"])
        payload = self._payload_entrada()
        payload["itens-0-lote_codigo"] = "LOTE-SAIDA"
        payload["itens-0-numeros_serie"] = "SER-A\nSER-B\nSER-C\nSER-D"
        self.client.post(reverse("estoque:nova_entrada_mercadoria"), data=payload)
        entrada = EntradaMercadoria.objects.get(documento_numero="NF-1001")
        self.client.post(reverse("estoque:receber_entrada_mercadoria", args=[entrada.id]))

        registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="venda",
            quantidade=1,
            origem=self.ponto,
            origem_ubicacao=self.ubicacao,
            usuario=self.user,
            observacao="Venda rastreada",
        )
        lote = EstoqueLote.objects.get(produto=self.produto, codigo="LOTE-SAIDA")
        self.assertEqual(lote.quantidade_disponivel, 3)
        self.assertEqual(
            EstoqueSerie.objects.filter(produto=self.produto, status=EstoqueSerie.STATUS_BAIXADA).count(),
            1,
        )

        registrar_movimentacao_estoque(
            produto=self.produto,
            tipo="devolucao_reserva",
            quantidade=1,
            destino=self.ponto,
            destino_ubicacao_ref=self.ubicacao,
            usuario=self.user,
            observacao="Devolucao rastreada",
        )
        lote.refresh_from_db()
        self.assertEqual(lote.quantidade_disponivel, 4)
        self.assertEqual(
            EstoqueSerie.objects.filter(produto=self.produto, status=EstoqueSerie.STATUS_DISPONIVEL).count(),
            4,
        )


class InventarioOperacionalViewsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="estoque_auditor",
            password="senha-forte-123",
            tipo_usuario="gerente",
            perm_estoque_inventario_finalizar=True,
            perm_estoque_transferencia=True,
        )
        self.client.force_login(self.user)
        self.empresa = Empresa.objects.create(nome="Empresa Estoque")
        self.user.empresa = self.empresa
        self.user.save(update_fields=["empresa"])
        self.ponto = PontoOperacional.objects.create(codigo="PO9", nome="Loja Auditoria")
        self.ubicacao = UbicacaoEstoque.objects.create(ponto_operacional=self.ponto, codigo="A1", descricao="Prateleira A1")
        self.categoria = CategoriaProduto.objects.create(nome="Cabos")
        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Cabo HDMI",
            tipo_item="produto",
            categoria_config=self.categoria,
            categoria="Cabos",
            quantidade=5,
            custo_unitario=10,
            custo_medio=10,
            preco_final=25,
            preco=25,
            margem_lucro=30,
            ponto_operacional=self.ponto,
            ubicacao_padrao=self.ubicacao,
            localizacao="A1",
        )
        SaldoEstoquePonto.objects.create(produto=self.produto, ponto_operacional=self.ponto, quantidade=5)
        SaldoEstoqueUbicacao.objects.create(produto=self.produto, ponto_operacional=self.ponto, ubicacao=self.ubicacao, quantidade=5)

    def test_gera_inventario_operacional_com_snapshot(self):
        response = self.client.post(
            reverse("estoque:inventarios_estoque"),
            {"ponto_id": self.ponto.id, "ubicacao_id": self.ubicacao.id, "categoria_id": self.categoria.id},
        )
        self.assertEqual(response.status_code, 302)
        inventario = InventarioEstoque.objects.get()
        item = inventario.itens.get()
        self.assertEqual(inventario.numero[:4], "INV-")
        self.assertEqual(item.nome_snapshot, "Cabo HDMI")
        self.assertEqual(item.quantidade_sistema, 5)
        self.assertEqual(item.ubicacao_snapshot, "A1")

    def test_finaliza_inventario_operacional_apos_conferencia(self):
        inventario = InventarioEstoque.objects.create(
            empresa=self.empresa,
            usuario=self.user,
            ponto_operacional=self.ponto,
            ubicacao=self.ubicacao,
        )
        item = ItemInventarioEstoque.objects.create(
            inventario=inventario,
            produto=self.produto,
            ubicacao=self.ubicacao,
            quantidade_sistema=5,
            quantidade_contada=5,
            ajuste=0,
            nome_snapshot="Cabo HDMI",
            ean_snapshot="",
        )
        response_item = self.client.post(
            reverse("estoque:inventario_estoque_atualizar_item", args=[item.id]),
            {"quantidade_contada": 5, "motivo_divergencia": "", "observacao": "OK"},
        )
        self.assertEqual(response_item.status_code, 302)
        response_fim = self.client.post(reverse("estoque:inventario_estoque_finalizar", args=[inventario.id]))
        self.assertEqual(response_fim.status_code, 302)
        inventario.refresh_from_db()
        self.assertEqual(inventario.status, "fechado")

    def test_lista_inventarios_exibe_filtros_operacionais(self):
        ponto_secundario = PontoOperacional.objects.create(codigo="PO2", nome="Deposito")
        categoria_secundaria = CategoriaProduto.objects.create(nome="Baterias")
        InventarioEstoque.objects.create(
            empresa=self.empresa,
            usuario=self.user,
            ponto_operacional=self.ponto,
            categoria=self.categoria,
            status="aberto",
        )
        InventarioEstoque.objects.create(
            empresa=self.empresa,
            usuario=self.user,
            ponto_operacional=ponto_secundario,
            categoria=categoria_secundaria,
            status="fechado",
        )

        response = self.client.get(
            reverse("estoque:inventarios_estoque"),
            {"status": "fechado", "ponto": ponto_secundario.id, "categoria": categoria_secundaria.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Como usar esta area")
        inventarios = list(response.context["inventarios"])
        self.assertEqual(len(inventarios), 1)
        self.assertEqual(inventarios[0].ponto_operacional_id, ponto_secundario.id)
        self.assertEqual(response.context["ponto_filtro"], str(ponto_secundario.id))
        self.assertEqual(response.context["categoria_filtro"], str(categoria_secundaria.id))


class CatalogosMultiempresaEstoqueTests(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(nome="Empresa Catalogo A")
        self.empresa_b = Empresa.objects.create(nome="Empresa Catalogo B")

    def test_nomes_e_codigos_podem_se_repetir_em_empresas_diferentes(self):
        for empresa in (self.empresa_a, self.empresa_b):
            PontoOperacional.objects.create(empresa=empresa, codigo="PO3", nome="Loja")
            CategoriaProduto.objects.create(empresa=empresa, nome="Acessorios")
            CategoriaFinanceira.objects.create(empresa=empresa, nome="Compras", tipo="saida")
            CentroCusto.objects.create(empresa=empresa, nome="Operacional")
            fornecedor = FornecedorGarantia.objects.create(empresa=empresa, nome="Fabricante")
            MarcaGarantia.objects.create(empresa=empresa, nome="Marca X", fornecedor=fornecedor)

        self.assertEqual(PontoOperacional.objects.filter(codigo="PO3").count(), 2)
        self.assertEqual(CategoriaProduto.objects.filter(nome="Acessorios").count(), 2)
        self.assertEqual(CategoriaFinanceira.objects.filter(nome="Compras", tipo="saida").count(), 2)
        self.assertEqual(CentroCusto.objects.filter(nome="Operacional").count(), 2)
        self.assertEqual(FornecedorGarantia.objects.filter(nome="Fabricante").count(), 2)
        self.assertEqual(MarcaGarantia.objects.filter(nome="Marca X").count(), 2)

    def test_duplicidade_na_mesma_empresa_e_bloqueada(self):
        CategoriaFinanceira.objects.create(empresa=self.empresa_a, nome="Compras", tipo="saida")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CategoriaFinanceira.objects.create(empresa=self.empresa_a, nome="Compras", tipo="saida")

    def test_formulario_produto_nao_aceita_catalogo_de_outra_empresa(self):
        categoria_a = CategoriaProduto.objects.create(empresa=self.empresa_a, nome="Categoria A")
        categoria_b = CategoriaProduto.objects.create(empresa=self.empresa_b, nome="Categoria B")
        fornecedor_a = FornecedorGarantia.objects.create(empresa=self.empresa_a, nome="Fornecedor A")
        fornecedor_b = FornecedorGarantia.objects.create(empresa=self.empresa_b, nome="Fornecedor B")
        marca_a = MarcaGarantia.objects.create(empresa=self.empresa_a, nome="Marca A", fornecedor=fornecedor_a)
        marca_b = MarcaGarantia.objects.create(empresa=self.empresa_b, nome="Marca B", fornecedor=fornecedor_b)

        form = ProdutoForm(empresa=self.empresa_a)

        self.assertIn(categoria_a, form.fields["categoria_config"].queryset)
        self.assertNotIn(categoria_b, form.fields["categoria_config"].queryset)
        self.assertIn(fornecedor_a, form.fields["fornecedor_config"].queryset)
        self.assertNotIn(fornecedor_b, form.fields["fornecedor_config"].queryset)
        self.assertIn(marca_a, form.fields["marca"].queryset)
        self.assertNotIn(marca_b, form.fields["marca"].queryset)

    def test_marca_nao_pode_vincular_fornecedor_de_outra_empresa(self):
        fornecedor_b = FornecedorGarantia.objects.create(empresa=self.empresa_b, nome="Fornecedor B")
        form = MarcaGarantiaForm(
            data={
                "nome": "Marca A",
                "fornecedor": fornecedor_b.id,
                "parceira_garantia": "",
                "procedimentos": "",
                "ativo": "on",
            },
            empresa=self.empresa_a,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("fornecedor", form.errors)

