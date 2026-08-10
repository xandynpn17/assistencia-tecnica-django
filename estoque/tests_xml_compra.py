import io
import zipfile
from datetime import timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from caixa.models import ContaPagar
from configuracoes.models import Empresa, FornecedorGarantia, MarcaGarantia
from estoque.models import CategoriaProduto, DocumentoFiscalConferencia, DocumentoLoteImportacao, EntradaMercadoria, ItemEntradaMercadoria, ItemImportacaoXML, LoteImportacaoCompra, MovimentacaoEstoque, ParcelaEntradaMercadoria, PontoOperacional, Produto, ProdutoFornecedor, ProdutoHistorico, SaldoEstoquePonto, UbicacaoEstoque
from estoque.services import receber_entrada_mercadoria
from estoque.services_documentos_fiscais import confirmar_documento_conferencia, importar_documento_conferencia
from estoque.services_xml import confirmar_fornecedor_xml, importar_documentos_compra, importar_xml_compra, resolver_item_xml, resolver_itens_xml_em_massa, resolver_lote_importacao, salvar_rascunhos_produtos_xml


def xml_nfe(*, chave, destinatario="11222333000181", emitente="11444777000161", gtin="7891234567895", codigo="ABC-1", status="100", quantidade="2.0000", parcelas=None):
    cobranca = ""
    if parcelas:
        duplicatas = "".join(
            f"<dup><nDup>{numero}</nDup><dVenc>{vencimento}</dVenc><vDup>{valor}</vDup></dup>"
            for numero, vencimento, valor in parcelas
        )
        cobranca = f"<cobr><fat><nFat>123</nFat><vOrig>24.00</vOrig><vLiq>24.00</vLiq></fat>{duplicatas}</cobr>"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe{chave}" versao="4.00">
<ide><mod>55</mod><nNF>123</nNF><serie>1</serie><dhEmi>2026-08-05T10:00:00-03:00</dhEmi></ide>
<emit><CNPJ>{emitente}</CNPJ><xNome>Fornecedor XML Ltda</xNome><xFant>Fornecedor XML</xFant><IE>123456789</IE><enderEmit><xLgr>Rua das Capas</xLgr><nro>100</nro><xBairro>Centro</xBairro><xMun>São Paulo</xMun><UF>SP</UF><CEP>01001000</CEP></enderEmit></emit>
<dest><CNPJ>{destinatario}</CNPJ><xNome>Empresa Destino</xNome></dest>
<det nItem="1"><prod><cProd>{codigo}</cProd><cEAN>{gtin}</cEAN><xProd>Capa protetora XML</xProd><NCM>39269090</NCM><CEST>0100100</CEST><CFOP>5102</CFOP><uCom>UN</uCom><qCom>{quantidade}</qCom><vUnCom>10.000000</vUnCom><vProd>20.00</vProd><vDesc>1.00</vDesc></prod><imposto><ICMS><ICMS00><vICMS>3.60</vICMS><vICMSST>0</vICMSST></ICMS00></ICMS><IPI><IPITrib><vIPI>0</vIPI></IPITrib></IPI><PIS><PISAliq><vPIS>0.33</vPIS></PISAliq></PIS><COFINS><COFINSAliq><vCOFINS>1.52</vCOFINS></COFINSAliq></COFINS></imposto></det>
<total><ICMSTot><vProd>20.00</vProd><vFrete>5.00</vFrete><vSeg>0</vSeg><vOutro>0</vOutro><vDesc>1.00</vDesc><vNF>24.00</vNF></ICMSTot></total>
{cobranca}
</infNFe></NFe><protNFe><infProt><cStat>{status}</cStat><chNFe>{chave}</chNFe></infProt></protNFe></nfeProc>'''.encode()


class ImportacaoXMLCompraTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media = TemporaryDirectory()
        cls._override = override_settings(MEDIA_ROOT=cls._media.name)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        cls._media.cleanup()

    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa XML", cnpj="11.222.333/0001-81")
        self.usuario = get_user_model().objects.create_user(username="estoque_xml", password="senha-forte", tipo_usuario="gerente", empresa=self.empresa)
        self.ponto = PontoOperacional.objects.create(empresa=self.empresa, codigo="LOJA", nome="Loja")
        self.ubicacao = UbicacaoEstoque.objects.create(ponto_operacional=self.ponto, codigo="A1")
        self.categoria = CategoriaProduto.objects.create(empresa=self.empresa, nome="Produtos XML")
        self.chave = "35260811444777000161550010000001231000001237"

    def importar(self, **kwargs):
        return importar_xml_compra(
            empresa=self.empresa, arquivo=xml_nfe(chave=self.chave, **kwargs), ponto_operacional=self.ponto,
            ubicacao=self.ubicacao, usuario=self.usuario, gerar_conta_pagar=True,
            vencimento_conta_pagar=timezone.localdate() + timedelta(days=30),
        )

    def test_importa_como_rascunho_e_nao_duplica(self):
        produto = Produto.objects.create(empresa=self.empresa, nome="Capa existente", ean="7891234567895", quantidade=0)
        entrada, criada = self.importar()
        repetida, criada_novamente = self.importar()
        item = entrada.itens_xml.get()

        self.assertTrue(criada)
        self.assertFalse(criada_novamente)
        self.assertEqual(repetida.pk, entrada.pk)
        self.assertEqual(item.produto, produto)
        self.assertEqual(item.correspondencia, "gtin")
        self.assertEqual(item.nivel_correspondencia, "exato")
        self.assertEqual(entrada.status, "rascunho")
        self.assertEqual(EntradaMercadoria.objects.count(), 1)
        self.assertEqual(ItemEntradaMercadoria.objects.count(), 0)
        self.assertEqual(MovimentacaoEstoque.objects.count(), 0)
        self.assertEqual(ContaPagar.objects.count(), 0)
        self.assertEqual(FornecedorGarantia.objects.get().cnpj_normalizado, "11444777000161")
        self.assertEqual(FornecedorGarantia.objects.get().municipio, "São Paulo")
        self.assertEqual(FornecedorGarantia.objects.get().cep, "01001000")

    def test_importa_lote_zip_de_xml_sem_movimentar_estoque(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pacote:
            pacote.writestr("notas/compra-123.xml", xml_nfe(chave=self.chave))
        arquivo = SimpleUploadedFile("notas.zip", buffer.getvalue(), content_type="application/zip")
        resultados = importar_documentos_compra(
            empresa=self.empresa,
            arquivo=arquivo,
            ponto_operacional=self.ponto,
            ubicacao=self.ubicacao,
            usuario=self.usuario,
            gerar_conta_pagar=True,
            vencimento_conta_pagar=timezone.localdate() + timedelta(days=30),
        )
        self.assertEqual(len(resultados), 1)
        entrada, criada = resultados[0]
        self.assertTrue(criada)
        self.assertEqual(entrada.status, "rascunho")
        self.assertEqual(entrada.itens_xml.count(), 1)
        lote = LoteImportacaoCompra.objects.get()
        self.assertEqual(lote.total_documentos, 1)
        self.assertEqual(lote.documentos.get().entrada, entrada)
        self.assertEqual(lote.status, "em_revisao")
        self.assertEqual(ItemEntradaMercadoria.objects.count(), 0)
        self.assertEqual(MovimentacaoEstoque.objects.count(), 0)
        resolver_item_xml(
            item=entrada.itens_xml.get(), usuario=self.usuario, criar_produto=True,
            dados_produto={"categoria": self.categoria},
        )
        confirmar_fornecedor_xml(entrada=entrada, usuario=self.usuario)
        receber_entrada_mercadoria(entrada, usuario=self.usuario)
        lote.refresh_from_db()
        self.assertEqual(lote.status, "concluido")

    def test_rejeita_xml_destinado_a_outra_empresa(self):
        with self.assertRaisesMessage(ValidationError, "outro CNPJ"):
            self.importar(destinatario="99888777000166")
        self.assertEqual(EntradaMercadoria.objects.count(), 0)

    def test_rejeita_nfe_sem_autorizacao(self):
        with self.assertRaisesMessage(ValidationError, "protocolo de autorização"):
            self.importar(status="110")
        self.assertEqual(EntradaMercadoria.objects.count(), 0)

    def test_rejeita_emitente_incompativel_com_chave(self):
        with self.assertRaisesMessage(ValidationError, "emitente não corresponde"):
            self.importar(emitente="11222333000181")
        self.assertEqual(EntradaMercadoria.objects.count(), 0)

    def test_rejeita_item_com_quantidade_invalida_sem_criar_rascunho(self):
        with self.assertRaisesMessage(ValidationError, "quantidade inválida"):
            self.importar(quantidade="0.0000")
        self.assertEqual(EntradaMercadoria.objects.count(), 0)

    def test_correspondencia_por_codigo_fornecedor_e_pendencia_bloqueiam_recebimento(self):
        fornecedor = FornecedorGarantia.objects.create(empresa=self.empresa, nome="Fornecedor cadastrado", cnpj="11.444.777/0001-61")
        produto = Produto.objects.create(empresa=self.empresa, nome="Produto pelo código")
        ProdutoFornecedor.objects.create(produto=produto, fornecedor_config=fornecedor, codigo_fornecedor="ABC-1")
        entrada, _ = self.importar(gtin="SEM GTIN")
        item = entrada.itens_xml.get()
        self.assertEqual(item.produto, produto)
        self.assertEqual(item.correspondencia, "codigo_fornecedor")
        self.assertEqual(item.nivel_correspondencia, "exato")
        with self.assertRaisesMessage(ValueError, "revisão tributária"):
            receber_entrada_mercadoria(entrada, usuario=self.usuario)
        self.assertEqual(MovimentacaoEstoque.objects.count(), 0)

    def test_conflito_entre_gtin_e_codigo_fornecedor_exige_decisao_humana(self):
        fornecedor = FornecedorGarantia.objects.create(
            empresa=self.empresa, nome="Fornecedor XML", cnpj="11.444.777/0001-61"
        )
        produto_gtin = Produto.objects.create(
            empresa=self.empresa, nome="Produto do GTIN", ean="7891234567895", ncm="39269090"
        )
        produto_codigo = Produto.objects.create(
            empresa=self.empresa, nome="Produto do codigo", ncm="39269090"
        )
        ProdutoFornecedor.objects.create(
            produto=produto_codigo, fornecedor_config=fornecedor, codigo_fornecedor="ABC-1"
        )
        entrada, _ = self.importar()
        item = entrada.itens_xml.get()

        self.assertIsNone(item.produto)
        self.assertEqual(item.nivel_correspondencia, "conflito")
        self.assertEqual(
            {candidato["produto_id"] for candidato in item.candidatos_correspondencia},
            {produto_gtin.pk, produto_codigo.pk},
        )
        categoria = CategoriaProduto.objects.create(empresa=self.empresa, nome="Conflitos XML")
        with self.assertRaisesMessage(ValidationError, "resolvidos individualmente"):
            resolver_itens_xml_em_massa(
                entrada=entrada, usuario=self.usuario, item_ids=[item.pk], categoria=categoria
            )

    def test_descricao_e_ncm_geram_sugestao_provavel_sem_associacao_automatica(self):
        candidato = Produto.objects.create(
            empresa=self.empresa, nome="Capa protetora XML", ncm="39269090"
        )
        entrada, _ = self.importar(gtin="SEM GTIN", codigo="SEM-MAPA")
        item = entrada.itens_xml.get()

        self.assertIsNone(item.produto)
        self.assertEqual(item.nivel_correspondencia, "provavel")
        self.assertEqual(item.candidatos_correspondencia[0]["produto_id"], candidato.pk)

    def test_produto_novo_revisao_recebimento_e_conta_pagar_sao_atomicos(self):
        entrada, _ = self.importar(gtin="SEM GTIN", codigo="NOVO-9")
        item = entrada.itens_xml.get()
        self.assertIsNone(item.produto)
        resolver_item_xml(
            item=item, usuario=self.usuario, criar_produto=True,
            impostos_custo_total=Decimal("2.00"), tributos_recuperaveis_total=Decimal("0.00"),
            dados_produto={"categoria": self.categoria},
        )
        with self.assertRaisesMessage(ValueError, "Confirme o fornecedor"):
            receber_entrada_mercadoria(entrada, usuario=self.usuario)
        confirmar_fornecedor_xml(entrada=entrada, usuario=self.usuario)
        resultado = receber_entrada_mercadoria(entrada, usuario=self.usuario)
        entrada.refresh_from_db()
        item.refresh_from_db()

        self.assertEqual(resultado["itens"], 1)
        self.assertEqual(entrada.status, "recebida")
        self.assertIsNotNone(entrada.conta_pagar_id)
        self.assertEqual(entrada.conta_pagar.valor_total, Decimal("24.00"))
        self.assertEqual(ItemEntradaMercadoria.objects.count(), 1)
        item_entrada = ItemEntradaMercadoria.objects.get()
        self.assertEqual(item_entrada.frete_rateado_unitario, Decimal("2.50"))
        self.assertEqual(item_entrada.desconto_unitario, Decimal("0.50"))
        self.assertEqual(item_entrada.custo_entrada_unitario, Decimal("13.00"))
        self.assertEqual(MovimentacaoEstoque.objects.filter(origem_tipo="entrada_mercadoria").count(), 1)
        self.assertTrue(ProdutoHistorico.objects.filter(produto=item.produto, acao="IMPORTACAO", dados_depois__chave_nfe=self.chave).exists())
        self.assertEqual(SaldoEstoquePonto.objects.get(produto=item.produto, ponto_operacional=self.ponto).quantidade, 2)
        with self.assertRaisesMessage(ValueError, "Somente entradas"):
            receber_entrada_mercadoria(entrada, usuario=self.usuario)
        self.assertEqual(ContaPagar.objects.count(), 1)
        self.assertEqual(MovimentacaoEstoque.objects.count(), 1)

    def test_revisao_em_massa_preserva_existente_e_cria_desconhecido_com_custo_rateado(self):
        entrada, _ = self.importar(gtin="SEM GTIN", codigo="NOVO-MASSA")
        novo_xml = entrada.itens_xml.get()
        existente = Produto.objects.create(
            empresa=self.empresa, nome="Produto existente", custo_unitario=Decimal("7.00"),
            custo_medio=Decimal("7.00"), preco_final=Decimal("50.00"), quantidade=3,
        )
        correspondente = ItemImportacaoXML.objects.create(
            entrada=entrada, numero_item=2, codigo_fornecedor="EXIST-2", gtin="",
            descricao="Produto jÃ¡ cadastrado", ncm="39269090", cfop="5102", unidade="UN",
            quantidade=Decimal("1.0000"), valor_unitario=Decimal("20.000000"),
            valor_produtos=Decimal("20.00"), produto=existente, correspondencia="codigo_fornecedor",
        )
        categoria = CategoriaProduto.objects.create(
            empresa=self.empresa, nome="AcessÃ³rios XML", margem_padrao=Decimal("35.00")
        )
        marca = MarcaGarantia.objects.create(empresa=self.empresa, nome="Marca XML")

        resultado = resolver_itens_xml_em_massa(
            entrada=entrada, usuario=self.usuario, item_ids=[novo_xml.pk, correspondente.pk],
            categoria=categoria, marca=marca, ajustes={novo_xml.pk: {"nome": "Capa criada em massa", "preco_final": 0}},
        )
        novo_xml.refresh_from_db()
        correspondente.refresh_from_db()
        existente.refresh_from_db()
        criado = novo_xml.produto

        self.assertEqual(resultado["confirmados"], 2)
        self.assertEqual(resultado["criados"], 1)
        self.assertTrue(novo_xml.resolvido)
        self.assertTrue(correspondente.resolvido)
        self.assertEqual(criado.nome, "Capa criada em massa")
        self.assertEqual(criado.categoria_config, categoria)
        self.assertEqual(criado.marca, marca)
        # Frete de R$ 5,00 rateado pela proporÃ§Ã£o dos itens (20/40), menos desconto do item.
        self.assertEqual(criado.custo_unitario, Decimal("10.75"))
        self.assertGreater(criado.preco_final, Decimal("0.00"))
        self.assertEqual(existente.custo_unitario, Decimal("7.00"))
        self.assertEqual(existente.preco_final, Decimal("50.00"))
        self.assertTrue(
            ProdutoHistorico.objects.filter(produto=criado, acao="IMPORTACAO", dados_depois__entrada_id=entrada.pk).exists()
        )

        repeticao = resolver_itens_xml_em_massa(
            entrada=entrada, usuario=self.usuario, item_ids=[novo_xml.pk, correspondente.pk], categoria=categoria,
        )
        self.assertEqual(repeticao["confirmados"], 0)
        self.assertEqual(Produto.objects.filter(nome="Capa criada em massa").count(), 1)

    def test_revisao_em_massa_falha_inteira_sem_categoria_para_produto_novo(self):
        entrada, _ = self.importar(gtin="SEM GTIN", codigo="NOVO-SEM-CATEGORIA")
        item = entrada.itens_xml.get()
        with self.assertRaisesMessage(ValidationError, "categoria"):
            resolver_itens_xml_em_massa(
                entrada=entrada, usuario=self.usuario, item_ids=[item.pk], categoria=None,
            )
        item.refresh_from_db()
        self.assertFalse(item.resolvido)
        self.assertFalse(Produto.objects.filter(nome=item.descricao).exists())

    def test_central_do_lote_resolve_varias_notas_e_atualiza_existente_seletivamente(self):
        fornecedor = FornecedorGarantia.objects.create(empresa=self.empresa, nome="Fornecedor lote")
        entrada_a = EntradaMercadoria.objects.create(
            empresa=self.empresa, fornecedor_config=fornecedor, documento_numero="A-1", importada_xml=True,
            ponto_operacional=self.ponto, ubicacao=self.ubicacao, usuario=self.usuario,
        )
        entrada_b = EntradaMercadoria.objects.create(
            empresa=self.empresa, fornecedor_config=fornecedor, documento_numero="B-1", importada_xml=True,
            ponto_operacional=self.ponto, ubicacao=self.ubicacao, usuario=self.usuario,
        )
        lote = LoteImportacaoCompra.objects.create(
            empresa=self.empresa, origem="zip_xml", arquivo_nome="duas-notas.zip", arquivo_sha256="a" * 64,
            total_documentos=2, documentos_novos=2, criado_por=self.usuario,
        )
        DocumentoLoteImportacao.objects.create(lote=lote, entrada=entrada_a, criada_na_importacao=True)
        DocumentoLoteImportacao.objects.create(lote=lote, entrada=entrada_b, criada_na_importacao=True)
        existente = Produto.objects.create(
            empresa=self.empresa, nome="Capa antiga", ncm="00000000", preco_final=Decimal("40.00")
        )
        item_existente = ItemImportacaoXML.objects.create(
            entrada=entrada_a, numero_item=1, descricao="Capa atualizada", ncm="39269090", cfop="5102",
            unidade="UN", quantidade=1, valor_unitario=10, valor_produtos=10,
            produto=existente, correspondencia="gtin", nivel_correspondencia="exato",
        )
        item_novo = ItemImportacaoXML.objects.create(
            entrada=entrada_b, numero_item=1, descricao="Produto novo segunda nota", ncm="39269090",
            unidade="UN", quantidade=1, valor_unitario=20, valor_produtos=20,
            nivel_correspondencia="novo",
        )
        categoria = CategoriaProduto.objects.create(empresa=self.empresa, nome="Lote central", margem_padrao=30)

        resultado = resolver_lote_importacao(
            lote=lote, usuario=self.usuario, item_ids=[item_existente.pk, item_novo.pk], categoria=categoria,
            ajustes={item_novo.pk: {"nome": "Produto lote criado", "preco_final": Decimal("0")}},
            atualizacoes={item_existente.pk: {
                "campos": ["nome", "ncm", "preco_final"],
                "valores": {"preco_final": Decimal("55.00")},
            }},
        )
        existente.refresh_from_db()
        item_existente.refresh_from_db()
        item_novo.refresh_from_db()
        self.assertEqual(resultado["confirmados"], 2)
        self.assertEqual(resultado["criados"], 1)
        self.assertEqual(resultado["atualizados"], 1)
        self.assertEqual(existente.nome, "Capa atualizada")
        self.assertEqual(existente.ncm, "39269090")
        self.assertEqual(existente.preco_final, Decimal("55.00"))
        self.assertTrue(item_existente.resolvido)
        self.assertEqual(item_novo.produto.nome, "Produto lote criado")
        self.assertTrue(ProdutoHistorico.objects.filter(produto=existente, dados_depois__campos_atualizados__isnull=False).exists())
        self.client.force_login(self.usuario)
        response = self.client.get(reverse("estoque:detalhe_lote_importacao", args=[lote.pk]), {"situacao": "todos"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Central do lote")
        exportacao = self.client.get(reverse("estoque:detalhe_lote_importacao", args=[lote.pk]), {"situacao": "todos", "export": "csv"})
        self.assertEqual(exportacao.status_code, 200)
        self.assertIn("text/csv", exportacao["Content-Type"])

    def test_revisao_em_massa_suporta_volume_de_200_itens_sem_duplicar(self):
        fornecedor = FornecedorGarantia.objects.create(empresa=self.empresa, nome="Fornecedor volume")
        entrada = EntradaMercadoria.objects.create(
            empresa=self.empresa, fornecedor_config=fornecedor, documento_numero="VOL-200", importada_xml=True,
            ponto_operacional=self.ponto, ubicacao=self.ubicacao, usuario=self.usuario,
        )
        itens = ItemImportacaoXML.objects.bulk_create([
            ItemImportacaoXML(
                entrada=entrada, numero_item=indice, descricao=f"Produto volume {indice}",
                gtin=f"7890000{indice:06d}", ncm="39269090", unidade="UN", quantidade=1,
                valor_unitario=Decimal("10.00"), valor_produtos=Decimal("10.00"), nivel_correspondencia="novo",
            ) for indice in range(1, 201)
        ])
        categoria = CategoriaProduto.objects.create(empresa=self.empresa, nome="Volume", margem_padrao=25)
        resultado = resolver_itens_xml_em_massa(
            entrada=entrada, usuario=self.usuario, item_ids=[item.pk for item in itens], categoria=categoria,
        )
        self.assertEqual(resultado["criados"], 200)
        self.assertEqual(Produto.objects.filter(empresa=self.empresa, categoria_config=categoria).count(), 200)
        repeticao = resolver_itens_xml_em_massa(
            entrada=entrada, usuario=self.usuario, item_ids=[item.pk for item in itens], categoria=categoria,
        )
        self.assertEqual(repeticao["criados"], 0)

    def test_gtin_pode_existir_em_empresas_diferentes_sem_vazamento(self):
        Produto.objects.create(empresa=self.empresa, nome="Produto A", ean="7891234567895")
        empresa_b = Empresa.objects.create(nome="Empresa B XML", cnpj="99.888.777/0001-66")
        produto_b = Produto.objects.create(empresa=empresa_b, nome="Produto B", ean="7891234567895")
        self.assertNotEqual(produto_b.empresa, self.empresa)
        entrada, _ = self.importar()
        self.assertEqual(entrada.itens_xml.get().produto.empresa, self.empresa)

    def test_pre_cadastro_persiste_sem_criar_produto_e_so_promove_na_aprovacao(self):
        entrada, _ = self.importar(gtin="SEM GTIN", codigo="RASCUNHO-1")
        item = entrada.itens_xml.get()
        quantidade_antes = Produto.objects.count()

        resultado = salvar_rascunhos_produtos_xml(
            entrada=entrada,
            usuario=self.usuario,
            item_ids=[item.pk],
            ajustes={
                item.pk: {
                    "nome": "Capa revisada no pré-cadastro",
                    "tipo_item": "peca",
                    "categoria": self.categoria,
                    "marca": None,
                    "ncm": "39269090",
                    "margem_lucro": Decimal("30.00"),
                    "margem_minima": Decimal("10.00"),
                    "preco_final": Decimal("49.90"),
                }
            },
        )
        item.refresh_from_db()
        self.assertEqual(resultado, {"salvos": 1, "prontos": 1})
        self.assertEqual(Produto.objects.count(), quantidade_antes)
        self.assertEqual(item.status_pre_cadastro, "pronto")
        self.assertEqual(item.nome_proposto, "Capa revisada no pré-cadastro")
        self.assertEqual(item.categoria_proposta, self.categoria)

        resolver_itens_xml_em_massa(
            entrada=entrada, usuario=self.usuario, item_ids=[item.pk]
        )
        item.refresh_from_db()
        self.assertEqual(item.status_pre_cadastro, "aprovado")
        self.assertEqual(item.produto.nome, "Capa revisada no pré-cadastro")
        self.assertEqual(item.produto.categoria_config, self.categoria)
        self.assertEqual(item.produto.preco_final, Decimal("49.90"))

    def test_sugere_marca_e_categoria_por_historico_auditavel_do_ncm(self):
        categoria = CategoriaProduto.objects.create(empresa=self.empresa, nome="Capas e proteções")
        marca = MarcaGarantia.objects.create(empresa=self.empresa, nome="Protec")
        Produto.objects.create(
            empresa=self.empresa, nome="Capa histórica", ncm="39269090",
            categoria_config=categoria, categoria=categoria.nome, marca=marca,
        )
        entrada, _ = self.importar(gtin="SEM GTIN", codigo="SUGESTAO-1")
        item = entrada.itens_xml.get()

        self.assertEqual(item.categoria_proposta, categoria)
        self.assertEqual(item.marca_proposta, marca)
        self.assertIn(item.sugestoes_cadastro["categoria"]["confianca"], {"alta", "media"})
        self.assertIn("NCM", item.sugestoes_cadastro["categoria"]["motivo"])
        self.assertEqual(item.status_pre_cadastro, "pronto")

    def test_recebimento_recalcula_custos_sem_alterar_preco_final(self):
        produto = Produto.objects.create(
            empresa=self.empresa, nome="Capa com preço definido", ean="7891234567895",
            quantidade=10, custo_unitario=Decimal("10.00"), custo_medio=Decimal("10.00"),
            preco_final=Decimal("100.00"), margem_lucro=Decimal("30.00"),
        )
        versao_anterior = produto.precificacao_versao
        entrada, _ = self.importar()
        item = entrada.itens_xml.get()
        resolver_item_xml(
            item=item, usuario=self.usuario, produto=produto,
            impostos_custo_total=Decimal("2.00"), tributos_recuperaveis_total=Decimal("0.00"),
        )
        confirmar_fornecedor_xml(entrada=entrada, usuario=self.usuario)
        receber_entrada_mercadoria(entrada, usuario=self.usuario)
        produto.refresh_from_db()

        self.assertEqual(produto.quantidade, 12)
        self.assertEqual(produto.custo_medio, Decimal("10.50"))
        self.assertEqual(produto.custo_unitario, Decimal("13.00"))
        self.assertEqual(produto.preco_final, Decimal("100.00"))
        self.assertGreater(produto.precificacao_versao, versao_anterior)

    def test_duplicatas_xml_geram_multiplas_contas_a_pagar(self):
        entrada, _ = self.importar(
            gtin="SEM GTIN",
            codigo="PARCELADO-1",
            parcelas=[("001", "2026-09-10", "10.00"), ("002", "2026-10-10", "14.00")],
        )
        self.assertEqual(entrada.parcelas_financeiras.count(), 2)
        item = entrada.itens_xml.get()
        resolver_item_xml(
            item=item, usuario=self.usuario, criar_produto=True,
            dados_produto={"categoria": self.categoria},
        )
        confirmar_fornecedor_xml(entrada=entrada, usuario=self.usuario)
        receber_entrada_mercadoria(entrada, usuario=self.usuario)
        entrada.refresh_from_db()
        parcelas = list(ParcelaEntradaMercadoria.objects.filter(entrada=entrada).order_by("numero"))
        self.assertEqual(ContaPagar.objects.filter(parcela_entrada_mercadoria__entrada=entrada).count(), 2)
        self.assertEqual([parcela.conta_pagar.valor_total for parcela in parcelas], [Decimal("10.00"), Decimal("14.00")])
        self.assertEqual(entrada.conta_pagar_id, parcelas[0].conta_pagar_id)


class DocumentosFiscaisConferenciaTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media = TemporaryDirectory()
        cls._override = override_settings(MEDIA_ROOT=cls._media.name)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        cls._media.cleanup()

    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa documentos", cnpj="11.222.333/0001-81")
        self.usuario = get_user_model().objects.create_user(
            username="documentos_fiscais", password="senha", tipo_usuario="gerente", empresa=self.empresa
        )

    def arquivo(self, nome, conteudo):
        return SimpleUploadedFile(nome, conteudo.encode("utf-8"), content_type="application/xml")

    def test_cte_autorizado_e_armazenado_somente_para_conferencia(self):
        chave = "35260811444777000161570010000001231000001234"
        xml = f"""<cteProc><CTe><infCte Id="CTe{chave}"><ide><mod>57</mod><nCT>123</nCT><dhEmi>2026-08-06T10:00:00-03:00</dhEmi></ide><emit><CNPJ>11444777000161</CNPJ></emit><rem><CNPJ>11222333000181</CNPJ></rem><vPrest><vTPrest>55.90</vTPrest></vPrest></infCte></CTe><protCTe><infProt><cStat>100</cStat><chCTe>{chave}</chCTe></infProt></protCTe></cteProc>"""
        documento, criado = importar_documento_conferencia(
            empresa=self.empresa, tipo="cte", arquivo=self.arquivo("frete.xml", xml), usuario=self.usuario
        )
        self.assertTrue(criado)
        self.assertEqual(documento.valor_total, Decimal("55.90"))
        self.assertEqual(documento.status, "conferir")
        self.assertEqual(MovimentacaoEstoque.objects.count(), 0)
        confirmar_documento_conferencia(documento=documento, usuario=self.usuario)
        documento.refresh_from_db()
        self.assertEqual(documento.status, "conferido")

    def test_nfse_e_sped_sao_idempotentes_e_nao_criam_produtos(self):
        nfse = """<CompNfse><Nfse><InfNfse><Numero>900</Numero><CodigoVerificacao>ABC</CodigoVerificacao><DataEmissao>2026-08-06</DataEmissao><PrestadorServico><Cnpj>11444777000161</Cnpj></PrestadorServico><TomadorServico><Cnpj>11222333000181</Cnpj></TomadorServico><Servico><Valores><ValorServicos>120.00</ValorServicos></Valores></Servico></InfNfse></Nfse></CompNfse>"""
        documento, criado = importar_documento_conferencia(
            empresa=self.empresa, tipo="nfse", arquivo=self.arquivo("servico.xml", nfse), usuario=self.usuario
        )
        repetido, criado_novamente = importar_documento_conferencia(
            empresa=self.empresa, tipo="nfse", arquivo=self.arquivo("servico.xml", nfse), usuario=self.usuario
        )
        self.assertTrue(criado)
        self.assertFalse(criado_novamente)
        self.assertEqual(documento.pk, repetido.pk)
        sped = "|0000|017|0|01012026|31012026|EMPRESA DOCUMENTOS|11222333000181|SP|123|3550308|||A|1|\n|0001|0|\n|9999|3|"
        sped_doc, _ = importar_documento_conferencia(
            empresa=self.empresa, tipo="sped",
            arquivo=SimpleUploadedFile("efd.txt", sped.encode("utf-8"), content_type="text/plain"),
            usuario=self.usuario,
        )
        self.assertEqual(sped_doc.resumo["registros"], 3)
        self.assertEqual(DocumentoFiscalConferencia.objects.count(), 2)
        self.assertEqual(Produto.objects.count(), 0)
