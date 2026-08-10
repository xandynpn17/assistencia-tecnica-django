from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from caixa.models import Caixa, FormaPagamento, Pagamento
from configuracoes.models import Empresa

from estoque.models import Produto

from .models import ConfiguracaoFiscal, DocumentoFiscal, FaixaTributaria, PerfilTributario, RegraTributaria, TributoParametrizado
from .services_prontidao import diagnosticar_prontidao_precificacao
from .services_tributacao import calcular_estimativa_tributaria, simular_impacto_precificacao, simular_transicao_tributaria


class FiscalViewsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.empresa = Empresa.objects.create(nome="Empresa Fiscal A")
        self.outra_empresa = Empresa.objects.create(nome="Empresa Fiscal B")
        self.gerente = user_model.objects.create_user(
            username="gerente_fiscal",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
        )
        self.atendente = user_model.objects.create_user(
            username="atendente_fiscal",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
        )

    def test_gerente_cria_documento_na_fila_da_empresa(self):
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("fiscal:novo_documento_fiscal"),
            {
                "tipo": "NFE",
                "origem": "MANUAL",
                "origem_referencia": "TESTE-001",
                "valor_total": "150.00",
                "xml_envio": "<xml/>",
            },
        )
        self.assertEqual(response.status_code, 302)
        documento = DocumentoFiscal.objects.get()
        self.assertEqual(documento.status, "fila")
        self.assertEqual(documento.empresa, self.empresa)
        self.assertEqual(documento.criado_por_id, self.gerente.id)

    def test_processar_fila_bloqueia_nfe_sem_simular_autorizacao(self):
        self.client.force_login(self.gerente)
        config = ConfiguracaoFiscal.get_solo(self.empresa)
        documento = DocumentoFiscal.objects.create(
            empresa=self.empresa,
            tipo="NFE",
            origem="MANUAL",
            origem_referencia="OS-10",
            status="fila",
            valor_total=Decimal("220.00"),
        )

        response = self.client.post(reverse("fiscal:processar_fila_fiscal"))
        self.assertEqual(response.status_code, 302)

        documento.refresh_from_db()
        config.refresh_from_db()
        self.assertEqual(documento.status, "rejeitada")
        self.assertIsNone(documento.numero)
        self.assertFalse(documento.chave_acesso)
        self.assertFalse(documento.protocolo_autorizacao)
        self.assertIn("Nenhum documento foi transmitido", documento.mensagem_retorno)
        self.assertEqual(config.proximo_numero_nfe, 1)

    def test_processar_fila_bloqueia_nfse_sem_integracao_real(self):
        self.client.force_login(self.gerente)
        documento = DocumentoFiscal.objects.create(
            empresa=self.empresa,
            tipo="NFSE",
            origem="MANUAL",
            origem_referencia="OS-11",
            status="fila",
            valor_total=Decimal("90.00"),
        )

        response = self.client.post(reverse("fiscal:processar_fila_fiscal"))
        self.assertEqual(response.status_code, 302)

        documento.refresh_from_db()
        self.assertEqual(documento.status, "rejeitada")
        self.assertIn("integração fiscal real", documento.mensagem_retorno)

    def test_modelo_bloqueia_autorizacao_manual_sem_provedor(self):
        documento = DocumentoFiscal(
            empresa=self.empresa, tipo="NFE", origem="MANUAL", status="autorizada", valor_total=Decimal("10.00"),
        )
        with self.assertRaisesMessage(ValidationError, "não pode ser definido manualmente"):
            documento.save()

        documento.status = "rascunho"
        documento.save()
        with self.assertRaisesMessage(ValidationError, "integração real"):
            documento.marcar_autorizada(numero=1, serie=1, chave_acesso="x", protocolo="y")

    def test_painel_e_processamento_isolam_documentos_por_empresa(self):
        documento_empresa = DocumentoFiscal.objects.create(
            empresa=self.empresa,
            tipo="NFE",
            origem="MANUAL",
            origem_referencia="EMPRESA-A",
            status="fila",
            valor_total=Decimal("10.00"),
        )
        documento_outra_empresa = DocumentoFiscal.objects.create(
            empresa=self.outra_empresa,
            tipo="NFE",
            origem="MANUAL",
            origem_referencia="EMPRESA-B",
            status="fila",
            valor_total=Decimal("20.00"),
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("fiscal:painel_fiscal"))
        self.assertContains(response, "EMPRESA-A")
        self.assertNotContains(response, "EMPRESA-B")
        self.client.post(reverse("fiscal:processar_fila_fiscal"))

        documento_empresa.refresh_from_db()
        documento_outra_empresa.refresh_from_db()
        self.assertEqual(documento_empresa.status, "rejeitada")
        self.assertEqual(documento_outra_empresa.status, "fila")

    def test_senha_certificado_nao_e_persistida(self):
        config = ConfiguracaoFiscal(empresa=self.empresa, senha_certificado="segredo-nao-persistir")
        config.save()
        config.refresh_from_db()
        self.assertEqual(config.senha_certificado, "")

    def test_atendente_sem_acesso_ao_painel_fiscal(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("fiscal:painel_fiscal"))
        self.assertEqual(response.status_code, 403)

    def test_gerente_acessa_motor_tributario_da_empresa(self):
        PerfilTributario.objects.create(
            empresa=self.outra_empresa, nome="Perfil que não pode vazar", regime="simples",
            inicio_vigencia=date(2026, 1, 1),
        )
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("fiscal:motor_tributario"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Motor tributário gerencial")
        self.assertNotContains(response, "Perfil que não pode vazar")


class MotorTributarioGerencialTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome="Empresa Motor Fiscal", regime_tributario="simples", modo_tributario="basico",
            aliquota_comercio=Decimal("6.00"), aliquota_servico=Decimal("8.00"),
        )
        self.perfil = PerfilTributario.objects.create(
            empresa=self.empresa, nome="Simples 2026", regime="simples", inicio_vigencia=date(2026, 1, 1),
            status="homologado", rbt12=Decimal("360000.00"), folha_12=Decimal("108000.00"),
        )

    def regra(self, **kwargs):
        defaults = {
            "perfil": self.perfil, "codigo": "REGRA", "nome": "Regra de teste", "tipo_item": "produto",
            "finalidade": "revenda", "anexo_simples": "I", "inicio_vigencia": date(2026, 1, 1),
            "status": "homologado", "aliquota_estimativa": Decimal("9.00"),
        }
        defaults.update(kwargs)
        return RegraTributaria.objects.create(**defaults)

    def test_diagnostico_aponta_regra_e_classificacao_pendentes_por_empresa(self):
        Produto.objects.create(empresa=self.empresa, nome="Produto sem classificaÃ§Ã£o", tipo_item="produto")
        outra = Empresa.objects.create(nome="Outra empresa diagnÃ³stico")
        Produto.objects.create(empresa=outra, nome="NÃ£o pode entrar na contagem", tipo_item="produto")

        diagnostico = diagnosticar_prontidao_precificacao(empresa=self.empresa)
        itens = {item["codigo"]: item for item in diagnostico["itens"]}

        self.assertFalse(diagnostico["pronto"])
        self.assertEqual(itens["regra_produto"]["nivel"], "critico")
        self.assertEqual(itens["classificacao_produtos"]["quantidade"], 1)
        self.assertEqual(itens["perfil_homologado"]["nivel"], "ok")
        self.assertEqual(itens["rbt12"]["nivel"], "ok")

    def test_simples_calcula_aliquota_efetiva_por_rbt12_e_faixa(self):
        regra = self.regra()
        FaixaTributaria.objects.create(
            regra=regra, anexo="I", nome="Faixa configurada", receita_inicial=Decimal("180000.01"),
            receita_final=Decimal("360000.00"), aliquota_nominal=Decimal("7.30"), parcela_deduzir=Decimal("5940.00"),
        )
        resultado = calcular_estimativa_tributaria(
            empresa=self.empresa, valor=Decimal("1000.00"), tipo_item="produto", data_referencia=date(2026, 8, 5),
        )
        self.assertEqual(resultado["aliquota_efetiva"], Decimal("5.6500"))
        self.assertEqual(resultado["valor_imposto"], Decimal("56.50"))
        self.assertEqual(resultado["regra_codigo"], "REGRA")
        self.assertTrue(resultado["homologado"])
        self.assertEqual(resultado["memoria"]["formula"], "((RBT12 x aliquota_nominal) - parcela_deduzir) / RBT12")

    def test_produto_e_servico_usam_regras_separadas_com_fator_r(self):
        produto = self.regra(codigo="COMERCIO")
        FaixaTributaria.objects.create(regra=produto, anexo="I", nome="Comércio", receita_inicial=0, aliquota_nominal=Decimal("6.00"))
        servico = self.regra(
            codigo="SERVICO", tipo_item="servico", finalidade="prestacao", anexo_simples="",
            aplicar_fator_r=True, anexo_fator_r_atendido="III", anexo_fator_r_nao_atendido="V",
        )
        FaixaTributaria.objects.create(regra=servico, anexo="III", nome="Serviço III", receita_inicial=0, aliquota_nominal=Decimal("8.00"))
        FaixaTributaria.objects.create(regra=servico, anexo="V", nome="Serviço V", receita_inicial=0, aliquota_nominal=Decimal("15.50"))

        calculo_produto = calcular_estimativa_tributaria(empresa=self.empresa, tipo_item="produto")
        calculo_servico = calcular_estimativa_tributaria(empresa=self.empresa, tipo_item="servico")
        self.assertEqual(calculo_produto["anexo"], "I")
        self.assertEqual(calculo_servico["anexo"], "III")
        self.assertEqual(calculo_servico["fator_r"], Decimal("0.3"))
        self.assertNotEqual(calculo_produto["regra_id"], calculo_servico["regra_id"])

    def test_regra_rascunho_calcula_com_alerta_sem_fingir_homologacao(self):
        self.perfil.status = "rascunho"
        self.perfil.save(update_fields=["status"])
        self.regra(status="rascunho", aliquota_estimativa=Decimal("7.25"))
        resultado = calcular_estimativa_tributaria(empresa=self.empresa, tipo_item="produto")
        self.assertEqual(resultado["aliquota_efetiva"], Decimal("7.2500"))
        self.assertFalse(resultado["homologado"])
        self.assertTrue(resultado["alertas"])

    def test_lucro_presumido_usa_estimativa_parametrizada_e_memoria(self):
        empresa = Empresa.objects.create(nome="Empresa Presumido", regime_tributario="presun")
        perfil = PerfilTributario.objects.create(
            empresa=empresa, nome="Presumido 2026", regime="presun", inicio_vigencia=date(2026, 1, 1), status="homologado",
        )
        RegraTributaria.objects.create(
            perfil=perfil, codigo="PRES-COM", nome="Comércio presumido", tipo_item="produto", finalidade="revenda",
            aliquota_estimativa=Decimal("11.33"), componentes={"IRPJ_CSLL": "3.08", "PIS_COFINS": "3.65", "ICMS": "4.60"},
            inicio_vigencia=date(2026, 1, 1), status="homologado",
        )
        resultado = calcular_estimativa_tributaria(empresa=empresa, valor=Decimal("200.00"), tipo_item="produto")
        self.assertEqual(resultado["aliquota_efetiva"], Decimal("11.3300"))
        self.assertEqual(resultado["valor_imposto"], Decimal("22.66"))
        self.assertEqual(resultado["memoria"]["regime"], "presun")

    def test_precificacao_guarda_regra_e_preserva_preco_final(self):
        regra = self.regra(aliquota_estimativa=Decimal("6.00"))
        produto = Produto.objects.create(
            empresa=self.empresa, nome="Produto tributado", ncm="39269090", regra_tributaria=regra,
            custo_unitario=Decimal("20.00"), margem_lucro=Decimal("30.00"), preco_final=Decimal("99.00"),
        )
        self.assertEqual(produto.preco_final, Decimal("99.00"))
        self.assertEqual(produto.precificacao_snapshot["tributacao"]["regra_id"], regra.id)
        self.assertEqual(produto.precificacao_snapshot["tributacao"]["regra_codigo"], "REGRA")

    def test_pagamento_congela_memoria_da_regra_aplicada(self):
        regra = self.regra(aliquota_estimativa=Decimal("6.00"))
        caixa = Caixa.objects.create(empresa=self.empresa, aberto=True, saldo_inicial=0)
        forma = FormaPagamento.objects.create(
            empresa=self.empresa, nome="PIX memória fiscal", codigo="pix-memoria-fiscal", taxa_percentual=0,
        )
        pagamento = Pagamento.objects.create(
            empresa=self.empresa, caixa=caixa, forma_pagamento=forma, metodo=forma.codigo, valor=Decimal("100.00"),
        )
        pagamento.refresh_from_db()
        memoria = pagamento.encargos_gerenciais_snapshot["memorias_tributarias"][0]
        self.assertEqual(pagamento.impostos_estimados, Decimal("6.00"))
        self.assertEqual(memoria["regra_id"], regra.id)
        self.assertEqual(memoria["regra_codigo"], "REGRA")
        regra.aliquota_estimativa = Decimal("12.00")
        with self.assertRaisesMessage(ValidationError, "imutável"):
            regra.save(update_fields=["aliquota_estimativa"])
        pagamento.refresh_from_db()
        self.assertEqual(pagamento.impostos_estimados, Decimal("6.00"))
        self.assertEqual(pagamento.encargos_gerenciais_snapshot["memorias_tributarias"][0]["aliquota_efetiva"], "6.0000")

    def test_tributos_da_reforma_entram_apenas_na_vigencia_configurada(self):
        regra = self.regra(aliquota_estimativa=Decimal("10.00"))
        TributoParametrizado.objects.create(
            regra=regra, codigo="IBS", nome="IBS transição", inicio_vigencia=date(2027, 1, 1),
            aliquota=Decimal("2.00"), percentual_base=Decimal("100.00"), impacto="adicionar", destino="Destino",
        )
        TributoParametrizado.objects.create(
            regra=regra, codigo="CBS", nome="CBS transição", inicio_vigencia=date(2027, 1, 1),
            aliquota=Decimal("3.00"), percentual_base=Decimal("100.00"), percentual_credito=Decimal("50.00"), impacto="adicionar",
        )
        cenarios = simular_transicao_tributaria(
            empresa=self.empresa, valor=Decimal("100.00"), tipo_item="produto",
            datas=[date(2026, 12, 31), date(2027, 1, 1)],
        )
        self.assertEqual(cenarios[0]["aliquota_efetiva"], Decimal("10.0000"))
        self.assertEqual(cenarios[1]["aliquota_efetiva"], Decimal("13.5000"))
        self.assertEqual(cenarios[1]["valor_imposto"], Decimal("13.50"))
        self.assertEqual(len(cenarios[1]["memoria"]["tributos_parametrizados"]), 2)

    def test_tributo_substituto_troca_base_principal_sem_apagar_historico(self):
        regra = self.regra(aliquota_estimativa=Decimal("10.00"))
        TributoParametrizado.objects.create(
            regra=regra, codigo="NOVO", nome="Regime substituto", inicio_vigencia=date(2028, 1, 1),
            aliquota=Decimal("8.00"), impacto="substituir", natureza="débito",
        )
        antes = calcular_estimativa_tributaria(empresa=self.empresa, tipo_item="produto", data_referencia=date(2027, 12, 31))
        depois = calcular_estimativa_tributaria(empresa=self.empresa, tipo_item="produto", data_referencia=date(2028, 1, 1))
        self.assertEqual(antes["aliquota_efetiva"], Decimal("10.0000"))
        self.assertEqual(depois["aliquota_efetiva"], Decimal("8.0000"))
        self.assertTrue(depois["memoria"]["aliquota_principal_substituida"])

    def test_simulador_mostra_impacto_da_transicao_no_preco_e_na_margem(self):
        regra = self.regra(aliquota_estimativa=Decimal("6.00"))
        TributoParametrizado.objects.create(
            regra=regra, codigo="CBS", nome="CBS futura", inicio_vigencia=date(2027, 1, 1),
            aliquota=Decimal("4.00"), impacto="adicionar",
        )
        cenarios = simular_impacto_precificacao(
            empresa=self.empresa, custo_base=Decimal("50.00"), margem_alvo=Decimal("30.00"),
            taxa_recebimento=Decimal("2.00"), tipo_item="produto", preco_atual=Decimal("80.00"),
            datas=[date(2026, 12, 31), date(2027, 1, 1)],
        )
        self.assertGreater(cenarios[1]["preco_sugerido"], cenarios[0]["preco_sugerido"])
        self.assertLess(cenarios[1]["resultado_preco_atual"]["lucro"], cenarios[0]["resultado_preco_atual"]["lucro"])

    def test_produto_nao_aceita_regra_de_outra_empresa(self):
        regra = self.regra()
        outra = Empresa.objects.create(nome="Outra empresa fiscal")
        with self.assertRaisesMessage(ValidationError, "outra empresa"):
            Produto.objects.create(empresa=outra, nome="Produto inválido", regra_tributaria=regra)

    def test_cfop_e_condicao_do_destinatario_selecionam_regra_especifica(self):
        self.regra(codigo="GERAL", prioridade=100, aliquota_estimativa=Decimal("6.00"))
        especifica = self.regra(
            codigo="INTERNA-CONTRIB", prioridade=1, cfop="5102", cst_csosn="102",
            codigo_beneficio="BENEF-1", natureza_operacao="Venda de mercadoria",
            destinatario_contribuinte="sim", aliquota_estimativa=Decimal("7.00"),
        )
        resultado = calcular_estimativa_tributaria(
            empresa=self.empresa, tipo_item="produto", cfop="5102", destinatario_contribuinte=True,
        )
        self.assertEqual(resultado["regra_id"], especifica.id)
        self.assertEqual(resultado["memoria"]["cfop"], "5102")
        self.assertEqual(resultado["memoria"]["cst_csosn"], "102")
        self.assertEqual(resultado["memoria"]["codigo_beneficio"], "BENEF-1")

    def test_produto_fabricado_usa_regra_de_industrializacao(self):
        regra = self.regra(
            codigo="FABRICADO", tipo_item="industrializado", finalidade="industrializacao",
            anexo_simples="II", aliquota_estimativa=Decimal("8.50"),
        )
        produto = Produto.objects.create(
            empresa=self.empresa, nome="Item fabricado", tipo_item="fabricado", regra_tributaria=regra,
            custo_unitario=Decimal("20.00"), preco_final=Decimal("40.00"),
        )
        resultado = calcular_estimativa_tributaria(
            empresa=self.empresa, tipo_item=produto.tipo_item, produto=produto, valor=Decimal("40.00"),
        )
        self.assertEqual(resultado["regra_id"], regra.id)
        self.assertEqual(resultado["memoria"]["tipo_item"], "industrializado")
        self.assertEqual(resultado["memoria"]["finalidade"], "industrializacao")
        self.assertEqual(resultado["anexo"], "II")
        self.assertEqual(produto.precificacao_snapshot["tributacao"]["tipo_item"], "industrializado")
        self.assertEqual(produto.precificacao_snapshot["tributacao"]["finalidade"], "industrializacao")
        self.assertEqual(produto.precificacao_snapshot["tributacao"]["anexo"], "II")

    def test_regra_vinculada_nao_vaza_para_oferta_ou_perda(self):
        regra_revenda = self.regra(codigo="REVENDA", prioridade=1, aliquota_estimativa=Decimal("6.00"))
        regra_oferta = self.regra(
            codigo="OFERTA", finalidade="oferta", prioridade=2, aliquota_estimativa=Decimal("1.00")
        )
        regra_perda = self.regra(
            codigo="PERDA", finalidade="perda", prioridade=3, aliquota_estimativa=Decimal("0.00")
        )
        produto = Produto.objects.create(
            empresa=self.empresa, nome="Mercadoria com regra base", regra_tributaria=regra_revenda,
            custo_unitario=Decimal("10.00"), preco_final=Decimal("20.00"),
        )
        oferta = calcular_estimativa_tributaria(
            empresa=self.empresa, produto=produto, tipo_item="produto", finalidade="oferta",
        )
        perda = calcular_estimativa_tributaria(
            empresa=self.empresa, produto=produto, tipo_item="produto", finalidade="perda",
        )
        self.assertEqual(oferta["regra_id"], regra_oferta.id)
        self.assertEqual(perda["regra_id"], regra_perda.id)

    def test_tratamentos_especiais_ficam_identificados_na_memoria(self):
        for indice, tratamento in enumerate(("normal", "monofasico", "st", "isento"), start=1):
            with self.subTest(tratamento=tratamento):
                regra = self.regra(
                    codigo=f"TRAT-{indice}", tratamento=tratamento, ncm_prefixo=f"{indice}",
                    prioridade=indice, aliquota_estimativa=Decimal("4.00"),
                )
                produto = Produto.objects.create(
                    empresa=self.empresa, nome=f"Produto {tratamento}", ncm=f"{indice}2345678",
                    custo_unitario=Decimal("10.00"), preco_final=Decimal("20.00"),
                )
                resultado = calcular_estimativa_tributaria(
                    empresa=self.empresa, produto=produto, tipo_item="produto",
                )
                self.assertEqual(resultado["regra_id"], regra.id)
                self.assertEqual(resultado["memoria"]["tratamento"], tratamento)
