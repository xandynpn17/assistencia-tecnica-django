from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import (
    AuditoriaGarantia,
    Caixa,
    ComissaoItemOrcamento,
    ContaReceber,
    FaixaPremioMeta,
    LancamentoCaixa,
    Pagamento,
    PremioColaboradorCompetencia,
    RegraComissaoTecnico,
    RegraPremioMeta,
)
from clientes.models import Cliente
from configuracoes.models import FornecedorGarantia, MarcaGarantia, RegraGarantiaMarca
from estoque.models import MovimentacaoEstoque, PontoOperacional, Produto, SaldoEstoquePonto, VendaRapidaEstoque
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.models import OrdemServico, ServicoPeca


class CaixaPermissoesTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente_caixa",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.gerente = user_model.objects.create_user(
            username="gerente_caixa",
            password="senha-forte-123",
            tipo_usuario="gerente",
        )
        self.superuser = user_model.objects.create_superuser(
            username="root_caixa",
            password="senha-forte-123",
            email="root@caixa.com",
        )
        Caixa.objects.create(aberto=True, saldo_inicial=0)
        self.cliente = Cliente.objects.create(
            nome="Cliente Caixa",
            documento="52998224725",
            telefone="11999998888",
            estado="SP",
        )
        self.tecnico = user_model.objects.create_user(
            username="tecnico_caixa",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="pronto_contactado",
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Mao de obra",
            quantidade=1,
            valor_unitario="100.00",
        )

    def test_atendente_sem_acesso_ao_dashboard_financeiro(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:dashboard_caixa"))
        self.assertEqual(response.status_code, 403)

    def test_atendente_sem_acesso_a_relatorios(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:relatorios"))
        self.assertEqual(response.status_code, 403)

    def test_atendente_com_acesso_a_registro_pagamento(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:registrar_pagamento"))
        self.assertEqual(response.status_code, 200)

    def test_atendente_com_acesso_a_abrir_e_fechar_caixa(self):
        self.client.force_login(self.atendente)
        response_abrir = self.client.get(reverse("caixa:abrir_caixa"))
        response_fechar = self.client.get(reverse("caixa:fechar_caixa"))
        self.assertEqual(response_abrir.status_code, 200)
        self.assertEqual(response_fechar.status_code, 200)

    def test_gerente_com_acesso_ao_dashboard_financeiro(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:dashboard_caixa"))
        self.assertEqual(response.status_code, 200)

    def test_superuser_com_acesso_a_relatorios(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("caixa:relatorios"))
        self.assertEqual(response.status_code, 200)

    def test_gerente_cria_conta_receber(self):
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("caixa:criar_conta_receber"),
            {
                "ordem_servico": self.ordem.id,
                "descricao": "OS teste",
                "cliente_nome": self.cliente.nome,
                "valor_original": "120.00",
                "vencimento": "2030-01-01",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ContaReceber.objects.exists())

    def test_atendente_sem_acesso_a_dre_e_comissoes(self):
        self.client.force_login(self.atendente)
        resp_dre = self.client.get(reverse("caixa:dre"))
        resp_comissao = self.client.get(reverse("caixa:comissoes_tecnicos"))
        self.assertEqual(resp_dre.status_code, 403)
        self.assertEqual(resp_comissao.status_code, 403)

    def test_gerente_com_acesso_a_dre_e_fluxo(self):
        self.client.force_login(self.gerente)
        resp_dre = self.client.get(reverse("caixa:dre"))
        resp_fluxo = self.client.get(reverse("caixa:fluxo_projetado"))
        self.assertEqual(resp_dre.status_code, 200)
        self.assertEqual(resp_fluxo.status_code, 200)

    def test_baixa_parcial_conta_receber(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="OS teste",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="100.00",
            vencimento="2030-01-01",
            status="aberta",
        )
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("caixa:detalhe_conta_receber", args=[conta.id]),
            {
                "valor": "40.00",
                "desconto": "0.00",
                "juros": "0.00",
                "referencia": "REC-1",
                "observacao": "",
                "metodo": "pix",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(str(conta.valor_aberto), "60.00")
        self.assertEqual(conta.status, "parcial")

    def test_finalizar_pre_reserva_no_caixa_da_baixa_no_estoque(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja")
        produto = Produto.objects.create(
            nome="Bateria X",
            ean="7899991110002",
            preco_final=Decimal("50.00"),
            preco=Decimal("50.00"),
            quantidade=5,
            ponto_operacional=ponto,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=5)
        venda = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=2,
            valor_unitario=Decimal("50.00"),
            valor_total=Decimal("100.00"),
            funcionario_numero="F01",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?venda={venda.id}",
            {"valor": "100.00", "metodo": "pix", "referencia": "PDV-1"},
        )
        self.assertEqual(response.status_code, 302)
        venda.refresh_from_db()
        self.assertEqual(venda.status, "vendida")
        saldo = SaldoEstoquePonto.objects.get(produto=produto, ponto_operacional=ponto)
        self.assertEqual(saldo.quantidade, 3)
        self.assertTrue(MovimentacaoEstoque.objects.filter(produto=produto, tipo="venda").exists())

    def test_finalizar_guia_no_caixa_da_baixa_em_todos_itens(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        produto = Produto.objects.create(
            nome="Conector C",
            ean="7899991110003",
            preco_final=Decimal("20.00"),
            preco=Decimal("20.00"),
            quantidade=10,
            ponto_operacional=ponto,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=10)
        venda1 = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=2,
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("40.00"),
            funcionario_numero="12",
            cesto_codigo="CES-12345678",
            guia_pagamento="GUIA-12345678",
            status="pre_reserva",
            usuario=self.atendente,
        )
        venda2 = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("20.00"),
            valor_total=Decimal("20.00"),
            funcionario_numero="12",
            cesto_codigo="CES-12345678",
            guia_pagamento="GUIA-12345678",
            status="pre_reserva",
            usuario=self.atendente,
        )
        response = self.client.post(
            reverse("caixa:registrar_pagamento") + "?guia=GUIA-12345678",
            {"valor": "60.00", "metodo": "pix", "referencia": "PDV-GUIA"},
        )
        self.assertEqual(response.status_code, 302)
        venda1.refresh_from_db()
        venda2.refresh_from_db()
        self.assertEqual(venda1.status, "vendida")
        self.assertEqual(venda2.status, "vendida")
        saldo = SaldoEstoquePonto.objects.get(produto=produto, ponto_operacional=ponto)
        self.assertEqual(saldo.quantidade, 7)

    def test_recalcular_comissao_item_antecipado(self):
        self.client.force_login(self.gerente)
        tecnico = get_user_model().objects.create_user(
            username="tecnico_com_item",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("5.00"),
            ativo=True,
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico tecnico",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("200.00"),
            origem="manual",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        response = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_antecipado"})
        self.assertEqual(response.status_code, 302)
        comissao = ComissaoItemOrcamento.objects.get(item_orcamento=item, modo_pagamento="antecipado")
        self.assertEqual(str(comissao.valor_comissao), "20.00")

    def test_recalcular_comissao_item_fechamento_exige_os_fechada(self):
        self.client.force_login(self.gerente)
        tecnico = get_user_model().objects.create_user(
            username="tecnico_com_fechamento",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("5.00"),
            ativo=True,
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Peca X",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="estoque",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        response = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_fechamento"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ComissaoItemOrcamento.objects.filter(modo_pagamento="fechamento").exists())

        self.ordem.fechada = True
        self.ordem.save(update_fields=["fechada"])
        response2 = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_fechamento"})
        self.assertEqual(response2.status_code, 302)
        self.assertTrue(ComissaoItemOrcamento.objects.filter(modo_pagamento="fechamento").exists())

    def test_recalcular_premios_por_meta_cria_registros_para_tecnicos(self):
        self.client.force_login(self.gerente)
        regra = RegraPremioMeta.objects.create(
            nome="Meta Margem Loja",
            metrica="margem_loja",
            meta_alvo=Decimal("1000.00"),
            publico="tecnico",
            ativo=True,
        )
        FaixaPremioMeta.objects.create(regra=regra, meta_minima=Decimal("0.00"), meta_maxima=Decimal("999.99"), premio_valor=Decimal("0.00"), ordem=1)
        FaixaPremioMeta.objects.create(regra=regra, meta_minima=Decimal("1000.00"), meta_maxima=None, premio_valor=Decimal("200.00"), ordem=2)
        caixa = Caixa.objects.filter(aberto=True).first()
        Pagamento.objects.create(caixa=caixa, ordem_servico=self.ordem, valor=Decimal("1500.00"), metodo="pix")
        LancamentoCaixa.objects.create(caixa=caixa, descricao="Despesa", valor=Decimal("200.00"), tipo="saida", usuario=self.gerente)

        response = self.client.post(reverse("caixa:premios_meta"), {"action": "recalcular_premios"})
        self.assertEqual(response.status_code, 302)
        premio = PremioColaboradorCompetencia.objects.filter(colaborador=self.tecnico, regra=regra).first()
        self.assertIsNotNone(premio)
        self.assertEqual(str(premio.premio_valor), "200.00")

    def test_meu_desempenho_disponivel_para_tecnico(self):
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("caixa:meu_desempenho"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Corrida de Atingimento")

    def test_pagamento_os_garantia_sugere_metodo_e_valor_da_marca(self):
        self.client.force_login(self.atendente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fabricante A")
        marca = MarcaGarantia.objects.create(
            nome="Marca",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("180.00"),
            parceira_garantia=True,
            ativo=True,
        )
        ordem_garantia = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca",
            marca_garantia=marca,
            modelo_equipamento="Modelo G",
            defeito="Teste garantia",
            tipo_reparo="Garantia",
            status="diagnosticar",
        )
        response = self.client.get(reverse("caixa:registrar_pagamento") + f"?os={ordem_garantia.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OS de garantia detectada")
        self.assertEqual(response.context["form"].initial.get("metodo"), "garantia_fabricante")
        self.assertEqual(response.context["form"].initial.get("valor"), Decimal("180.00"))

    def test_pagamento_garantia_fabricante_baixa_conta_receber_garantia(self):
        self.client.force_login(self.atendente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fabricante Conta")
        marca = MarcaGarantia.objects.create(
            nome="Marca Conta",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("120.00"),
            parceira_garantia=True,
            ativo=True,
        )
        ordem_garantia = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Conta",
            marca_garantia=marca,
            modelo_equipamento="Modelo C",
            defeito="Teste",
            tipo_reparo="Garantia",
            status="concluida",
            fechada=True,
        )
        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={ordem_garantia.id}",
            {"valor": "120.00", "metodo": "garantia_fabricante", "referencia": "GAR-120"},
        )
        self.assertEqual(response.status_code, 302)
        conta = ContaReceber.objects.filter(ordem_servico=ordem_garantia, descricao__icontains="Garantia fabricante").first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.status, "paga")
        self.assertEqual(str(conta.valor_aberto), "0.00")

    def test_pagamento_garantia_fabricante_bloqueado_para_marca_nao_parceira(self):
        self.client.force_login(self.atendente)
        MarcaGarantia.objects.create(
            nome="Marca Nao Parceira",
            valor_mao_obra_garantia=Decimal("90.00"),
            parceira_garantia=False,
            ativo=True,
        )
        ordem_garantia = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Nao Parceira",
            modelo_equipamento="Modelo X",
            defeito="Nao liga",
            tipo_reparo="Garantia",
            status="diagnosticar",
        )
        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={ordem_garantia.id}",
            {"valor": "90.00", "metodo": "garantia_fabricante", "referencia": "GAR-NAO"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("metodo", response.context["form"].errors)
        self.assertFalse(Pagamento.objects.filter(referencia="GAR-NAO").exists())

    def test_relatorio_garantias_fabricante_disponivel_para_gerente(self):
        self.client.force_login(self.gerente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Rel")
        marca = MarcaGarantia.objects.create(
            nome="Marca Rel",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("120.00"),
            parceira_garantia=True,
            ativo=True,
        )
        auditoria = AuditoriaGarantia.objects.create(
            ordem_servico=self.ordem,
            fornecedor=fornecedor,
            marca=marca,
            valor_previsto_fabricante=Decimal("120.00"),
            comissao_prevista_tecnica=Decimal("0.00"),
            status_faturamento="pendente",
        )
        response = self.client.get(reverse("caixa:garantias_fabricante"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ordem.numero_os)

        response_post = self.client.post(
            reverse("caixa:garantias_fabricante"),
            {
                "auditoria_id": auditoria.id,
                "status_faturamento": "enviado",
                "referencia_faturamento": "FAT-001",
                "observacoes": "Envio mensal",
            },
        )
        self.assertEqual(response_post.status_code, 302)
        auditoria.refresh_from_db()
        self.assertEqual(auditoria.status_faturamento, "enviado")
        self.assertEqual(auditoria.referencia_faturamento, "FAT-001")

    def test_garantias_fabricante_status_pago_da_baixa_na_conta(self):
        self.client.force_login(self.gerente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Baixa")
        marca = MarcaGarantia.objects.create(
            nome="Marca Baixa",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("130.00"),
            parceira_garantia=True,
            ativo=True,
        )
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Baixa",
            marca_garantia=marca,
            modelo_equipamento="Modelo B",
            defeito="Teste",
            tipo_reparo="Garantia",
            status="concluida",
            fechada=True,
        )
        auditoria = AuditoriaGarantia.objects.create(
            ordem_servico=ordem,
            fornecedor=fornecedor,
            marca=marca,
            valor_previsto_fabricante=Decimal("130.00"),
            comissao_prevista_tecnica=Decimal("30.00"),
            status_faturamento="pendente",
        )
        self.client.post(
            reverse("caixa:garantias_fabricante"),
            {
                "auditoria_id": auditoria.id,
                "status_faturamento": "pago",
                "referencia_faturamento": "FAT-BAIXA-001",
                "observacoes": "Pago no fechamento mensal",
            },
        )
        conta = ContaReceber.objects.filter(ordem_servico=ordem, descricao__icontains="Garantia fabricante").first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.status, "paga")
        self.assertEqual(str(conta.valor_aberto), "0.00")

    def test_relatorio_garantias_exporta_csv_com_resumo_mensal(self):
        self.client.force_login(self.gerente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor CSV")
        marca = MarcaGarantia.objects.create(
            nome="Marca CSV",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("150.00"),
            parceira_garantia=True,
            ativo=True,
        )
        AuditoriaGarantia.objects.create(
            ordem_servico=self.ordem,
            fornecedor=fornecedor,
            marca=marca,
            valor_previsto_fabricante=Decimal("150.00"),
            comissao_prevista_tecnica=Decimal("50.00"),
            status_faturamento="pendente",
        )
        hoje = timezone.localdate()
        response = self.client.get(
            reverse("caixa:garantias_fabricante") + f"?mes={hoje.month}&ano={hoje.year}&export=csv"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        conteudo = response.content.decode("utf-8")
        self.assertIn("Fornecedor", conteudo)
        self.assertIn("Fornecedor CSV", conteudo)
        self.assertIn("Marca CSV", conteudo)

    def test_pagamento_os_garantia_prioriza_regra_por_tipo_produto(self):
        self.client.force_login(self.atendente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fabricante B")
        marca = MarcaGarantia.objects.create(
            nome="Marca B",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("180.00"),
            parceira_garantia=True,
            ativo=True,
        )
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("230.00"),
            modalidade_pagamento="faturado",
            prazo_pagamento_dias=45,
            ativo=True,
        )
        ordem_garantia = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca B",
            marca_garantia=marca,
            modelo_equipamento="Modelo G",
            defeito="Teste garantia",
            tipo_reparo="Garantia",
            status="diagnosticar",
        )
        response = self.client.get(reverse("caixa:registrar_pagamento") + f"?os={ordem_garantia.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial.get("valor"), Decimal("230.00"))

    def test_comissao_item_garantia_bloqueada_por_padrao(self):
        self.client.force_login(self.gerente)
        tecnico = get_user_model().objects.create_user(
            username="tecnico_garantia_sem_comissao",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.ordem.tipo_reparo = "Garantia"
        self.ordem.save(update_fields=["tipo_reparo"])
        RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("5.00"),
            comissionar_garantia=False,
            ativo=True,
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico garantia",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("200.00"),
            origem="manual",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        response = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_antecipado"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ComissaoItemOrcamento.objects.exists())
