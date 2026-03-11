from decimal import Decimal
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import (
    AuditoriaGarantia,
    Caixa,
    Comissao,
    ComissaoItemOrcamento,
    ContaPagar,
    ContaReceber,
    FaixaPremioMeta,
    LancamentoCaixa,
    Pagamento,
    PremioColaboradorCompetencia,
    RegraComissaoTecnico,
    RegraPremioMeta,
)
from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema, FornecedorGarantia, MarcaGarantia, RegraGarantiaMarca
from estoque.models import MovimentacaoEstoque, PontoOperacional, Produto, SaldoEstoquePonto, VendaRapidaEstoque
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.models import OrdemServico, ServicoPeca
from caixa.services.comissao_status import ComissaoStatusError, aplicar_acao_comissao
from caixa.services.comissoes import cancelar_comissoes_por_ordem, processar_evento_servico_finalizado


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

    def test_bloqueia_finalizacao_pre_reserva_com_valor_divergente(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO4", nome="Loja 4")
        produto = Produto.objects.create(
            nome="Tela Y",
            ean="7899991110004",
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
            funcionario_numero="F04",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?venda={venda.id}",
            {"valor": "90.00", "metodo": "pix", "referencia": "PDV-ERR"},
        )
        self.assertEqual(response.status_code, 200)
        venda.refresh_from_db()
        self.assertEqual(venda.status, "pre_reserva")
        saldo = SaldoEstoquePonto.objects.get(produto=produto, ponto_operacional=ponto)
        self.assertEqual(saldo.quantidade, 5)
        self.assertFalse(MovimentacaoEstoque.objects.filter(produto=produto, tipo="venda").exists())

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

    def test_finalizar_guia_permita_saldo_negativo(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO3X", nome="Loja Aux")
        produto = Produto.objects.create(
            nome="Fonte Y",
            ean="7899991110099",
            preco_final=Decimal("30.00"),
            preco=Decimal("30.00"),
            quantidade=0,
            ponto_operacional=ponto,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=0)
        venda = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=2,
            valor_unitario=Decimal("30.00"),
            valor_total=Decimal("60.00"),
            funcionario_numero="12",
            status="pre_reserva",
            usuario=self.atendente,
        )
        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?venda={venda.id}",
            {"valor": "60.00", "metodo": "pix", "referencia": "PDV-NEG"},
        )
        self.assertEqual(response.status_code, 302)
        venda.refresh_from_db()
        self.assertEqual(venda.status, "vendida")
        saldo = SaldoEstoquePonto.objects.get(produto=produto, ponto_operacional=ponto)
        self.assertEqual(saldo.quantidade, -2)

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
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
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
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
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

    def test_comissao_item_pronto_contactado_pode_exigir_pagamento(self):
        self.client.force_login(self.gerente)
        tecnico = get_user_model().objects.create_user(
            username="tecnico_exige_pagamento",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("5.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=True,
            ativo=True,
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico sem pgto",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )

        response = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_antecipado"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ComissaoItemOrcamento.objects.filter(item_orcamento=item).exists())

        caixa = Caixa.objects.filter(aberto=True).first()
        Pagamento.objects.create(caixa=caixa, ordem_servico=self.ordem, valor=Decimal("120.00"), metodo="pix")
        response2 = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_antecipado"})
        self.assertEqual(response2.status_code, 302)
        self.assertTrue(ComissaoItemOrcamento.objects.filter(item_orcamento=item).exists())

    def test_comissao_item_entregue_pago_exige_status_concluida(self):
        self.client.force_login(self.gerente)
        tecnico = get_user_model().objects.create_user(
            username="tecnico_status_concluida",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("5.00"),
            momento_liberacao="entregue_pago",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico entrega",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )

        response = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_antecipado"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ComissaoItemOrcamento.objects.filter(item_orcamento=item).exists())

        self.ordem.status = "concluida"
        self.ordem.save(update_fields=["status"])
        response2 = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_antecipado"})
        self.assertEqual(response2.status_code, 302)
        self.assertTrue(ComissaoItemOrcamento.objects.filter(item_orcamento=item).exists())

    def test_comissao_item_considera_status_pronto_contactar(self):
        self.client.force_login(self.gerente)
        tecnico = get_user_model().objects.create_user(
            username="tecnico_pronto_contactar",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )
        self.ordem.status = "pronto_contactar"
        self.ordem.save(update_fields=["status"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico pronto contactar",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        response = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_antecipado"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ComissaoItemOrcamento.objects.filter(item_orcamento=item).exists())

    def test_motor_novo_nao_gera_sem_relatorio_tecnico(self):
        self.client.force_login(self.gerente)
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_sem_relatorio",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("12.00"),
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico sem relatorio",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        response = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Comissao.objects.filter(item_orcamento=item).exists())

    def test_motor_novo_gera_comissao_servico_e_eh_idempotente(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_servico",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("15.00"),
        )
        self.ordem.relatorio_tecnico = "Relatorio aprovado"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico principal",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("200.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        total_primeira = Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").count()
        self.assertEqual(total_primeira, 1)

        criadas = processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO")
        self.assertEqual(criadas, 0)
        total_final = Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").count()
        self.assertEqual(total_final, 1)

    def test_motor_novo_usa_regra_quando_percentual_usuario_esta_zero(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_regra_fallback",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("0.00"),
        )
        RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            ativo=True,
        )
        self.ordem.relatorio_tecnico = "Relatorio com fallback de regra"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico com fallback",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        comissao = Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").first()
        self.assertIsNotNone(comissao)
        self.assertEqual(str(comissao.percentual), "10.00")
        self.assertEqual(str(comissao.valor_comissao), "10.00")

    def test_motor_novo_prioriza_servicos_pecas_migrados_para_calculo(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_prioridade_sp",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("10.00"),
        )
        self.ordem.relatorio_tecnico = "Relatorio pronto para prioridade"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico base",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("80.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=item,
            tipo="servico",
            nome="Servico migrado",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            tecnico_responsavel=tecnico,
        )

        processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO")
        comissao = Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").first()
        self.assertIsNotNone(comissao)
        self.assertEqual(str(comissao.valor_base), "120.00")
        self.assertEqual(str(comissao.valor_comissao), "12.00")

    def test_motor_novo_recalcula_por_tipo_servico_sem_gerar_peca(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_tipos",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("10.00"),
            percentual_comissao_peca=Decimal("5.00"),
        )
        self.ordem.relatorio_tecnico = "Relatorio para filtro por tipo"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        produto = Produto.objects.create(
            nome="Peca Tipo Filtro",
            ean="7894561230999",
            preco_final=Decimal("50.00"),
            quantidade=5,
            permite_comissao_peca=True,
            percentual_comissao_peca=Decimal("8.00"),
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="Servico tipo filtro",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            tecnico_responsavel=tecnico,
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="peca",
            nome=produto.nome,
            quantidade=1,
            valor_unitario=Decimal("50.00"),
            tecnico_responsavel=tecnico,
        )

        processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO", tipos={"servico"})
        tipos_gerados = set(Comissao.objects.values_list("tipo", flat=True))
        self.assertIn("SERVICO", tipos_gerados)
        self.assertNotIn("PECA", tipos_gerados)

    def test_motor_novo_gera_comissao_peca_e_bonus_produto(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_peca",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_peca=Decimal("3.00"),
        )
        self.ordem.relatorio_tecnico = "Relatorio final"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        produto = Produto.objects.create(
            nome="Placa Principal",
            ean="7894561230001",
            preco_final=Decimal("300.00"),
            quantidade=5,
            permite_comissao_peca=True,
            percentual_comissao_peca=Decimal("10.00"),
            bonus_venda=Decimal("7.00"),
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome=produto.nome,
            ean=produto.ean,
            descricao="Troca de peca",
            quantidade=1,
            valor_unitario=Decimal("300.00"),
            origem="estoque",
            tipo_item="peca",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        tipos = set(Comissao.objects.filter(item_orcamento=item).values_list("tipo", flat=True))
        self.assertIn("PECA", tipos)
        self.assertIn("BONUS_PRODUTO", tipos)

    def test_motor_novo_cancela_comissao_quando_item_e_recusado(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_cancelamento",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("10.00"),
        )
        self.ordem.relatorio_tecnico = "Relatorio para cancelamento"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico para cancelar",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        self.assertTrue(Comissao.objects.filter(item_orcamento=item).exists())

        item.status = "recusado"
        item.save(update_fields=["status"])

        status_comissoes = set(Comissao.objects.filter(item_orcamento=item).values_list("status", flat=True))
        self.assertEqual(status_comissoes, {"CANCELADA"})

    def test_motor_novo_mantem_servico_de_orcamento_quando_peca_manual_existe(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_fontes_mistas",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("10.00"),
            percentual_comissao_peca=Decimal("5.00"),
        )
        self.ordem.relatorio_tecnico = "Relatório preenchido"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item_servico = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Mão de obra",
            descricao="Serviço técnico",
            quantidade=1,
            valor_unitario=Decimal("80.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        produto = Produto.objects.create(
            nome="Motor teste",
            ean="7894561235678",
            preco_final=Decimal("100.00"),
            quantidade=5,
            permite_comissao_peca=True,
            percentual_comissao_peca=Decimal("10.00"),
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="peca",
            nome=produto.nome,
            quantidade=1,
            valor_unitario=Decimal("200.00"),
            tecnico_responsavel=tecnico,
        )

        processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO")

        self.assertTrue(
            Comissao.objects.filter(
                ordem_servico=self.ordem,
                item_orcamento=item_servico,
                tipo="SERVICO",
                status="GERADA",
            ).exists()
        )
        self.assertTrue(
            Comissao.objects.filter(
                ordem_servico=self.ordem,
                tipo="PECA",
                status="GERADA",
            ).exists()
        )

    def test_cancelamento_automatico_nao_altera_comissao_paga(self):
        comissao = Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Comissão já paga",
            valor_base=Decimal("100.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="PAGA",
            chave_unica=f"SERVICO_FINALIZADO:SERVICO:os:{self.ordem.id}:paga",
        )

        total_canceladas = cancelar_comissoes_por_ordem(self.ordem, motivo="Teste de cancelamento")

        self.assertEqual(total_canceladas, 0)
        comissao.refresh_from_db()
        self.assertEqual(comissao.status, "PAGA")

    def test_status_comissao_bloqueia_transicoes_invalidas(self):
        comissao = Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Transição de status",
            valor_base=Decimal("120.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("12.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica=f"SERVICO_FINALIZADO:SERVICO:os:{self.ordem.id}:transicao",
        )

        aplicar_acao_comissao(comissao, acao="pagar", usuario=self.gerente, referencia_pagamento="PIX-1")
        comissao.refresh_from_db()
        self.assertEqual(comissao.status, "PAGA")
        self.assertTrue(bool(comissao.data_liberacao))
        self.assertTrue(bool(comissao.data_pagamento))

        with self.assertRaises(ComissaoStatusError):
            aplicar_acao_comissao(comissao, acao="pagar", usuario=self.gerente, referencia_pagamento="PIX-2")
        with self.assertRaises(ComissaoStatusError):
            aplicar_acao_comissao(comissao, acao="cancelar", usuario=self.gerente)

    def test_auditar_comissoes_reporta_sem_fonte_valida_e_paga_base_zerada(self):
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Inconsistente",
            valor_base=Decimal("0.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="PAGA",
            data_pagamento=timezone.now(),
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:999999",
        )
        out = StringIO()
        call_command("auditar_comissoes", stdout=out)
        saida = out.getvalue()
        self.assertIn("Inconsistências encontradas", saida)
        self.assertIn("sem_fonte_valida: 1", saida)
        self.assertIn("paga_base_zerada: 1", saida)

    def test_auditar_comissoes_pode_falhar_se_divergir(self):
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Inconsistente 2",
            valor_base=Decimal("0.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="PAGA",
            data_pagamento=timezone.now(),
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:999998",
        )
        with self.assertRaises(CommandError):
            call_command("auditar_comissoes", falhar_se_divergir=True)

    def test_auditar_comissoes_ok_quando_fontes_sao_validas(self):
        self.ordem.relatorio_tecnico = "Relatório de execução"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Serviço válido",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("150.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        out = StringIO()
        call_command("auditar_comissoes", stdout=out)
        self.assertIn("Nenhuma inconsistência encontrada", out.getvalue())

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

    def test_pagamento_gera_numero_talao_automatico(self):
        caixa = Caixa.objects.filter(aberto=True).first()
        pagamento = Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("50.00"),
            metodo="pix",
        )
        self.assertIsNotNone(pagamento.numero_talao)
        self.assertTrue(pagamento.numero_talao.startswith("000100"))

    def test_consulta_talao_e_impressao_2via(self):
        self.client.force_login(self.atendente)
        caixa = Caixa.objects.filter(aberto=True).first()
        pagamento = Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("75.00"),
            metodo="pix",
        )

        response_list = self.client.get(reverse("caixa:taloes"), {"q": pagamento.numero_talao})
        self.assertEqual(response_list.status_code, 200)
        self.assertContains(response_list, pagamento.numero_talao)

        response_print = self.client.get(reverse("caixa:imprimir_talao", args=[pagamento.id]))
        self.assertEqual(response_print.status_code, 200)
        self.assertContains(response_print, pagamento.numero_talao)

    def test_meu_desempenho_disponivel_para_tecnico(self):
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("caixa:meu_desempenho"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Painel de metas")

    def test_meu_desempenho_filtra_por_data_para_tecnico(self):
        comissao = ComissaoItemOrcamento.objects.create(
            item_orcamento=ItemOrcamento.objects.create(
                orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
                nome="Item comissao data",
                descricao="Teste",
                quantidade=1,
                valor_unitario=Decimal("50.00"),
                origem="manual",
                tipo_item="servico",
                tecnico_responsavel=self.tecnico,
                status="aprovado",
            ),
            ordem_servico=self.ordem,
            tecnico=self.tecnico,
            base_calculo=Decimal("50.00"),
            percentual_aplicado=Decimal("10.00"),
            valor_comissao=Decimal("5.00"),
        )
        comissao.criado_em = timezone.now() - timedelta(days=10)
        comissao.save(update_fields=["criado_em"])

        self.client.force_login(self.tecnico)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(reverse("caixa:meu_desempenho"), {"data_inicio": hoje, "data_fim": hoje})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Item comissao data")

    def test_meu_desempenho_gerente_filtra_por_tecnico(self):
        outro_tecnico = get_user_model().objects.create_user(
            username="tecnico_outro_relatorio",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        ComissaoItemOrcamento.objects.create(
            item_orcamento=ItemOrcamento.objects.create(
                orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
                nome="Comissao tecnico alvo",
                descricao="Teste",
                quantidade=1,
                valor_unitario=Decimal("80.00"),
                origem="manual",
                tipo_item="servico",
                tecnico_responsavel=self.tecnico,
                status="aprovado",
            ),
            ordem_servico=self.ordem,
            tecnico=self.tecnico,
            base_calculo=Decimal("80.00"),
            percentual_aplicado=Decimal("10.00"),
            valor_comissao=Decimal("8.00"),
        )
        ComissaoItemOrcamento.objects.create(
            item_orcamento=ItemOrcamento.objects.create(
                orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
                nome="Comissao outro tecnico",
                descricao="Teste",
                quantidade=1,
                valor_unitario=Decimal("60.00"),
                origem="manual",
                tipo_item="servico",
                tecnico_responsavel=outro_tecnico,
                status="aprovado",
            ),
            ordem_servico=self.ordem,
            tecnico=outro_tecnico,
            base_calculo=Decimal("60.00"),
            percentual_aplicado=Decimal("10.00"),
            valor_comissao=Decimal("6.00"),
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {"tecnico": str(self.tecnico.id), "data_inicio": hoje, "data_fim": hoje},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.tecnico.username)
        ordens_relatorio = response.context.get("ordens_relatorio", [])
        self.assertTrue(ordens_relatorio)
        self.assertTrue(all(row["tecnico"].id == self.tecnico.id for row in ordens_relatorio))

    def test_meu_desempenho_bloqueia_quando_datas_nao_informadas(self):
        ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Item sem datas",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:meu_desempenho"), {"tecnico": str(self.tecnico.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context.get("ordens_relatorio", []), [])
        mensagens = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("data de início e data de fim" in msg for msg in mensagens))

    def test_meu_desempenho_bloqueia_intervalo_maior_que_12_meses(self):
        ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Item periodo longo",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("110.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate()
        data_inicio = (hoje - timedelta(days=367)).isoformat()
        data_fim = hoje.isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {"tecnico": str(self.tecnico.id), "data_inicio": data_inicio, "data_fim": data_fim},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context.get("ordens_relatorio", []), [])
        mensagens = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("12 meses" in msg for msg in mensagens))

    def test_meu_desempenho_resultado_calculo_usa_tecnico_do_item(self):
        tecnico_os = get_user_model().objects.create_user(
            username="tecnico_da_os",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.ordem.tecnico_responsavel = tecnico_os
        self.ordem.save(update_fields=["tecnico_responsavel"])

        ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Item tecnico comissao",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "tecnico": str(self.tecnico.id),
                "data_inicio": hoje,
                "data_fim": hoje,
                "percentual_servicos": "25",
                "aplicar_servicos": "1",
                "aplicar_pecas": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        ordens_relatorio = response.context.get("ordens_relatorio", [])
        self.assertTrue(ordens_relatorio)
        self.assertEqual(ordens_relatorio[0]["tecnico"].id, self.tecnico.id)
        self.assertEqual(ordens_relatorio[0]["valor_comissao"], Decimal("30.00"))

    def test_meu_desempenho_usa_percentuais_padrao_da_configuracao(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.percentual_padrao_desempenho_servico = Decimal("18.00")
        config.percentual_padrao_desempenho_peca = Decimal("4.00")
        config.save(update_fields=["percentual_padrao_desempenho_servico", "percentual_padrao_desempenho_peca"])

        ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Item percentual config",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "tecnico": str(self.tecnico.id),
                "data_inicio": hoje,
                "data_fim": hoje,
                "aplicar_servicos": "1",
                "aplicar_pecas": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["percentual_servicos"], "18.00")
        ordens_relatorio = response.context.get("ordens_relatorio", [])
        self.assertTrue(ordens_relatorio)
        self.assertEqual(ordens_relatorio[0]["valor_comissao"], Decimal("18.00"))

    def test_meu_desempenho_recalcula_comissoes_geradas_com_percentual_do_filtro(self):
        item = ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Servico base",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("80.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        servico = ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=item,
            tipo="servico",
            nome="Servico base",
            quantidade=1,
            valor_unitario=Decimal("80.00"),
            tecnico_responsavel=self.tecnico,
        )
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            item_orcamento=item,
            tipo="SERVICO",
            descricao="Comissao antiga",
            valor_base=Decimal("80.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("8.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica=f"SERVICO_FINALIZADO:SERVICO:item:{item.id}",
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "tecnico": str(self.tecnico.id),
                "data_inicio": hoje,
                "data_fim": hoje,
                "percentual_servicos": "25",
                "aplicar_servicos": "1",
                "aplicar_pecas": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        linhas = response.context.get("comissoes_calculadas", [])
        self.assertTrue(linhas)
        self.assertEqual(linhas[0]["percentual_aplicado"], Decimal("25"))
        self.assertEqual(linhas[0]["valor_calculado"], Decimal("20.00"))

    def test_excluir_item_remove_servico_vinculado_e_cancela_comissao_sp(self):
        item = ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Item migrado",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("80.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        servico = ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=item,
            tipo="servico",
            nome="Servico item",
            quantidade=1,
            valor_unitario=Decimal("80.00"),
            tecnico_responsavel=self.tecnico,
        )
        comissao = Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            item_orcamento=item,
            tipo="SERVICO",
            descricao="Comissao SP",
            valor_base=Decimal("80.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("8.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica=f"SERVICO_FINALIZADO:SERVICO:sp:{servico.id}",
        )

        item.delete()

        self.assertFalse(ServicoPeca.objects.filter(id=servico.id).exists())
        comissao.refresh_from_db()
        self.assertEqual(comissao.status, "CANCELADA")

    def test_motor_ignora_servico_vinculado_item_nao_aprovado(self):
        self.ordem.relatorio_tecnico = "Relatorio preenchido"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        item = ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Item recusado",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("90.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="recusado",
        )
        servico = ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=item,
            tipo="servico",
            nome="Servico recusado",
            quantidade=1,
            valor_unitario=Decimal("90.00"),
            tecnico_responsavel=self.tecnico,
        )

        criadas = processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO")
        self.assertEqual(criadas, 0)
        self.assertFalse(Comissao.objects.filter(chave_unica=f"SERVICO_FINALIZADO:SERVICO:item:{item.id}").exists())

    def test_motor_nao_duplica_quando_fonte_muda_de_item_para_servico_peca(self):
        self.ordem.relatorio_tecnico = "Relatorio preenchido"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        RegraComissaoTecnico.objects.create(
            usuario=self.tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )
        item = ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Item unico",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )

        self.assertEqual(
            Comissao.objects.filter(chave_unica=f"SERVICO_FINALIZADO:SERVICO:item:{item.id}").count(),
            1,
        )
        total_primeira = processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO")
        self.assertEqual(total_primeira, 0)

        ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=item,
            tipo="servico",
            nome="Item unico",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            tecnico_responsavel=self.tecnico,
        )
        total_segunda = processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO")
        self.assertEqual(total_segunda, 0)
        self.assertEqual(
            Comissao.objects.filter(chave_unica=f"SERVICO_FINALIZADO:SERVICO:item:{item.id}").count(),
            1,
        )

    def test_meu_desempenho_exclui_canceladas_por_padrao(self):
        item = ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Servico desempenho",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        servico = ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=item,
            tipo="servico",
            nome="Servico desempenho",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            tecnico_responsavel=self.tecnico,
        )
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            item_orcamento=item,
            tipo="SERVICO",
            descricao="Cancelada",
            valor_base=Decimal("100.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="CANCELADA",
            chave_unica="SERVICO_FINALIZADO:SERVICO:sp:999999",
        )
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            item_orcamento=item,
            tipo="SERVICO",
            descricao="Gerada",
            valor_base=Decimal("100.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica=f"SERVICO_FINALIZADO:SERVICO:item:{item.id}",
        )
        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {"tecnico": str(self.tecnico.id), "data_inicio": hoje, "data_fim": hoje},
        )
        self.assertEqual(response.status_code, 200)
        calculadas = response.context.get("comissoes_calculadas", [])
        self.assertTrue(calculadas)
        descricoes = [row["comissao"].descricao for row in calculadas]
        self.assertIn("Gerada", descricoes)
        self.assertNotIn("Cancelada", descricoes)

    def test_meu_desempenho_checkbox_somente_fechadas(self):
        item_aberto = ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Item aberto",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("90.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=item_aberto,
            tipo="servico",
            nome="Item aberto",
            quantidade=1,
            valor_unitario=Decimal("90.00"),
            tecnico_responsavel=self.tecnico,
        )

        ordem_fechada = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo fechado",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="concluida",
            relatorio_tecnico="OK",
        )
        item_fechado = ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=ordem_fechada),
            nome="Item fechado",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        ServicoPeca.objects.create(
            ordem=ordem_fechada,
            item_orcamento=item_fechado,
            tipo="servico",
            nome="Item fechado",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            tecnico_responsavel=self.tecnico,
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "tecnico": str(self.tecnico.id),
                "data_inicio": hoje,
                "data_fim": hoje,
                "somente_fechadas": "1",
                "aplicar_servicos": "1",
                "aplicar_pecas": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        ordens_relatorio = response.context.get("ordens_relatorio", [])
        self.assertTrue(ordens_relatorio)
        numeros = {row["numero_os"] for row in ordens_relatorio}
        self.assertIn(ordem_fechada.numero_os, numeros)
        self.assertNotIn(self.ordem.numero_os, numeros)

    def test_meu_desempenho_modo_finalizados_inclui_autorizado_com_relatorio(self):
        self.ordem.status = "autorizado"
        self.ordem.relatorio_tecnico = "Servico executado"
        self.ordem.save(update_fields=["status", "relatorio_tecnico"])
        RegraComissaoTecnico.objects.create(
            usuario=self.tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )
        item_servico = ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Mao de obra",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("200.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=item_servico,
            tipo="servico",
            nome="Mao de obra",
            quantidade=1,
            valor_unitario=Decimal("200.00"),
            tecnico_responsavel=self.tecnico,
        )
        ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Motor",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("200.00"),
            origem="manual",
            tipo_item="peca",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {"tecnico": str(self.tecnico.id), "data_inicio": hoje, "data_fim": hoje},
        )
        self.assertEqual(response.status_code, 200)
        ordens_relatorio = response.context.get("ordens_relatorio", [])
        self.assertTrue(ordens_relatorio)
        self.assertEqual(ordens_relatorio[0]["numero_os"], self.ordem.numero_os)
        self.assertGreater(ordens_relatorio[0]["valor_servicos"], Decimal("0.00"))

    def test_meu_desempenho_oculta_comissao_sem_fonte_valida(self):
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Orfa",
            valor_base=Decimal("80.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("8.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica="SERVICO_FINALIZADO:SERVICO:sp:999999",
        )
        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {"tecnico": str(self.tecnico.id), "data_inicio": hoje, "data_fim": hoje},
        )
        self.assertEqual(response.status_code, 200)
        calculadas = response.context.get("comissoes_calculadas", [])
        self.assertEqual(calculadas, [])

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
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("180.00"),
            valor_mao_obra_tecnico=Decimal("0.00"),
            modalidade_pagamento="pix",
            prazo_pagamento_dias=30,
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
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("120.00"),
            valor_mao_obra_tecnico=Decimal("0.00"),
            modalidade_pagamento="pix",
            prazo_pagamento_dias=30,
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

    def test_bonus_retirada_so_apos_quitacao_total_da_conta(self):
        self.client.force_login(self.atendente)
        config = ConfiguracaoSistema.get_configuracao()
        config.dias_bonus_retirada_1 = 1
        config.valor_bonus_1 = Decimal("10.00")
        config.dias_bonus_retirada_2 = 3
        config.valor_bonus_2 = Decimal("5.00")
        config.dias_bonus_retirada_3 = 7
        config.valor_bonus_3 = Decimal("2.00")
        config.save(
            update_fields=[
                "dias_bonus_retirada_1",
                "valor_bonus_1",
                "dias_bonus_retirada_2",
                "valor_bonus_2",
                "dias_bonus_retirada_3",
                "valor_bonus_3",
            ]
        )

        self.ordem.status = "concluida"
        self.ordem.fechada = True
        self.ordem.relatorio_tecnico = "Reparo executado"
        self.ordem.data_conclusao = timezone.now() - timedelta(days=1)
        self.ordem.tecnico_responsavel = self.tecnico
        self.ordem.save(
            update_fields=["status", "fechada", "relatorio_tecnico", "data_conclusao", "tecnico_responsavel"]
        )

        resp_1 = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}",
            {"valor": "60.00", "metodo": "pix", "referencia": "RET-PARCIAL"},
        )
        self.assertEqual(resp_1.status_code, 302)
        conta = ContaReceber.objects.filter(ordem_servico=self.ordem, tipo_origem="cliente_os").first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.status, "parcial")
        self.assertEqual(
            Comissao.objects.filter(ordem_servico=self.ordem, tipo="BONUS_RETIRADA").count(),
            0,
        )

        resp_2 = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}",
            {"valor": "40.00", "metodo": "pix", "referencia": "RET-QUITADO"},
        )
        self.assertEqual(resp_2.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "paga")
        bonus = Comissao.objects.filter(ordem_servico=self.ordem, tipo="BONUS_RETIRADA")
        self.assertEqual(bonus.count(), 1)
        self.assertEqual(str(bonus.first().valor_comissao), "10.00")

    def test_historico_comissao_e_preservado_ao_excluir_os_e_tecnico(self):
        comissao = Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Historico de teste",
            valor_base=Decimal("100.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica=f"HIST:SERVICO:os:{self.ordem.id}:tec:{self.tecnico.id}",
        )

        self.ordem.delete()
        comissao.refresh_from_db()
        self.assertIsNone(comissao.ordem_servico)
        self.assertIsNotNone(comissao.tecnico)

        self.tecnico.delete()
        comissao.refresh_from_db()
        self.assertIsNone(comissao.tecnico)

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
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("130.00"),
            valor_mao_obra_tecnico=Decimal("30.00"),
            modalidade_pagamento="pix",
            prazo_pagamento_dias=30,
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

    def test_conta_pagar_exige_caixa_aberto_para_pagamento(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        caixa.aberto = False
        caixa.save(update_fields=["aberto"])
        conta = ContaPagar.objects.create(
            fornecedor="Fornecedor XPTO",
            descricao="Despesa sem caixa aberto",
            valor_total=Decimal("100.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate(),
            status="aberta",
        )
        response = self.client.post(
            reverse("caixa:detalhe_conta_pagar", args=[conta.id]),
            {"valor": "10.00"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("caixa:abrir_caixa"))
        conta.refresh_from_db()
        self.assertEqual(str(conta.valor_pago), "0.00")

    def test_dashboard_considera_pagamentos_sem_lancamento_no_total_entradas(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("50.00"),
            metodo="pix",
        )
        response = self.client.get(reverse("caixa:dashboard_caixa"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_entradas"], Decimal("50.00"))

    def test_relatorios_filtra_por_intervalo_datas(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        Pagamento.objects.create(caixa=caixa, ordem_servico=self.ordem, valor=Decimal("10.00"), metodo="pix")
        Pagamento.objects.create(caixa=caixa, ordem_servico=self.ordem, valor=Decimal("20.00"), metodo="pix")
        hoje = timezone.localdate().isoformat()
        response = self.client.get(reverse("caixa:relatorios"), {"data_inicio": hoje, "data_fim": hoje})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_entradas_pagamentos"], Decimal("30.00"))

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

    def test_comissao_item_garantia_pode_ser_calculada(self):
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
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
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
        self.assertTrue(ComissaoItemOrcamento.objects.exists())

    def test_garantias_fabricante_sincroniza_os_fechadas(self):
        self.client.force_login(self.gerente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Sync")
        marca = MarcaGarantia.objects.create(
            nome="Marca Sync",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("150.00"),
            parceira_garantia=True,
            ativo=True,
        )
        ordem_sync = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Sync",
            marca_garantia=marca,
            modelo_equipamento="Modelo Sync",
            defeito="Teste",
            tipo_reparo="Garantia",
            status="concluida",
            fechada=True,
        )
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("150.00"),
            valor_mao_obra_tecnico=Decimal("0.00"),
            modalidade_pagamento="faturado",
            prazo_pagamento_dias=30,
        )
        AuditoriaGarantia.objects.filter(ordem_servico=ordem_sync).delete()
        response = self.client.post(reverse("caixa:garantias_fabricante"), {"action": "sincronizar"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AuditoriaGarantia.objects.filter(ordem_servico=ordem_sync).exists())
