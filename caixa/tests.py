from decimal import Decimal
from datetime import date, timedelta
from calendar import monthrange
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import (
    AuditoriaFinanceira,
    AuditoriaGarantia,
    Caixa,
    ConciliacaoBancaria,
    CategoriaFinanceira,
    CentroCusto,
    Comissao,
    ComissaoLotePagamento,
    ComissaoItemOrcamento,
    ContaPagar,
    ContaBancaria,
    ContaReceber,
    CustoFixoMensal,
    DREFechamento,
    DespesaRecorrente,
    FaixaPremioMeta,
    FormaPagamento,
    LancamentoCaixa,
    LinhaExtratoBancario,
    MovimentoFinanceiro,
    MovimentoBancario,
    Pagamento,
    PagamentoContaPagar,
    PremioColaboradorCompetencia,
    RecebimentoConta,
    RegraComissaoTecnico,
    RegraPremioMeta,
    TransferenciaTesouraria,
)
from clientes.models import Cliente
from configuracoes.models import ConfiguracaoSistema, Empresa, FornecedorGarantia, MarcaGarantia, RegraGarantiaMarca
from estoque.models import MovimentacaoEstoque, PontoOperacional, Produto, SaldoEstoquePonto, VendaRapidaEstoque
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.models import LinhaTrabalho, OrdemServico, ServicoPeca
from caixa.services.comissao_status import ComissaoStatusError, aplicar_acao_comissao
from caixa.services.comissoes import (
    cancelar_comissoes_por_ordem,
    processar_evento_servico_finalizado,
)
from caixa.services.livro_financeiro import estornar_movimento_financeiro
from caixa.services.pagamentos import excluir_pagamento_com_justificativa
from caixa.services.tesouraria import (
    conciliar_grupo,
    conciliar_linha,
    desfazer_conciliacao,
    importar_extrato_csv,
    registrar_transferencia,
)


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
        self.financeiro_extra = user_model.objects.create_user(
            username="financeiro_extra",
            password="senha-forte-123",
            tipo_usuario="atendente",
            acesso_caixa_financeiro_extra=True,
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
            tipo_reparacao="substituicao",
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
        response = self.client.get(reverse("caixa:dashboard_financeiro"))
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

    def test_gerente_reabre_caixa_encerrado_do_mesmo_dia_com_auditoria(self):
        caixa = Caixa.objects.get(aberto=True)
        caixa.aberto = False
        caixa.saldo_final = Decimal("250.00")
        caixa.valor_contado_fisico = Decimal("0.00")
        caixa.save(update_fields=["aberto", "saldo_final", "valor_contado_fisico"])
        self.client.force_login(self.gerente)

        response = self.client.post(
            reverse("caixa:abrir_caixa"),
            {
                "acao": "reabrir",
                "motivo_reabertura": "Fechado antes do fim do expediente",
            },
        )

        self.assertEqual(response.status_code, 302)
        caixa.refresh_from_db()
        self.assertTrue(caixa.aberto)
        auditoria = AuditoriaFinanceira.objects.filter(evento="caixa_reaberto").latest("id")
        self.assertIn("Fechado antes do fim do expediente", auditoria.descricao)

    def test_reabrir_caixa_exige_justificativa(self):
        caixa = Caixa.objects.get(aberto=True)
        caixa.aberto = False
        caixa.save(update_fields=["aberto"])
        self.client.force_login(self.gerente)

        response = self.client.post(
            reverse("caixa:abrir_caixa"),
            {"acao": "reabrir", "motivo_reabertura": ""},
        )

        self.assertEqual(response.status_code, 200)
        caixa.refresh_from_db()
        self.assertFalse(caixa.aberto)
        self.assertContains(response, "Informe o motivo da reabertura")

    def test_gerente_com_acesso_ao_dashboard_financeiro(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:dashboard_financeiro"))
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

    def test_usuario_financeiro_extra_sem_perm_nao_cria_conta_receber(self):
        self.client.force_login(self.financeiro_extra)
        response = self.client.get(reverse("caixa:criar_conta_receber"))
        self.assertEqual(response.status_code, 403)

    def test_usuario_financeiro_extra_sem_perm_nao_cria_conta_pagar(self):
        self.client.force_login(self.financeiro_extra)
        response = self.client.get(reverse("caixa:criar_conta_pagar"))
        self.assertEqual(response.status_code, 403)

    def test_atendente_sem_acesso_a_dre_e_comissoes(self):
        self.client.force_login(self.atendente)
        resp_dre = self.client.get(reverse("caixa:dre"))
        resp_comissao = self.client.get(reverse("caixa:comissoes_tecnicos"))
        resp_pagamento_comissao = self.client.get(reverse("caixa:comissoes_pagamento"))
        resp_pendencias_comissao = self.client.get(reverse("caixa:comissoes_pendencias"))
        self.assertEqual(resp_dre.status_code, 403)
        self.assertEqual(resp_comissao.status_code, 403)
        self.assertEqual(resp_pagamento_comissao.status_code, 403)
        self.assertEqual(resp_pendencias_comissao.status_code, 403)

    def test_gerente_com_acesso_a_dre_e_fluxo(self):
        self.client.force_login(self.gerente)
        resp_dre = self.client.get(reverse("caixa:dre"))
        resp_fluxo = self.client.get(reverse("caixa:fluxo_projetado"))
        self.assertEqual(resp_dre.status_code, 200)
        self.assertEqual(resp_fluxo.status_code, 200)

    def test_atendente_sem_acesso_a_custos_fixos(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:custos_fixos"))
        self.assertEqual(response.status_code, 403)

    def test_gerente_cadastra_custo_fixo_mensal(self):
        self.client.force_login(self.gerente)
        competencia = timezone.localdate().replace(day=1).isoformat()
        response = self.client.post(
            reverse("caixa:custos_fixos"),
            {
                "action": "salvar",
                "competencia": competencia,
                "descricao": "Aluguel loja",
                "categoria": "Infraestrutura",
                "valor_previsto": "2500.00",
                "valor_pago": "1000.00",
                "vencimento": competencia,
                "observacao": "Pagamento parcial",
                "ativo": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        custo = CustoFixoMensal.objects.filter(descricao="Aluguel loja").first()
        self.assertIsNotNone(custo)
        self.assertEqual(custo.status, "parcial")

    def test_dashboard_exibe_resumo_custos_fixos_mes(self):
        self.client.force_login(self.gerente)
        competencia = timezone.localdate().replace(day=1)
        CustoFixoMensal.objects.create(
            competencia=competencia,
            descricao="Internet",
            categoria="Infraestrutura",
            valor_previsto=Decimal("300.00"),
            valor_pago=Decimal("100.00"),
            ativo=True,
        )
        response = self.client.get(reverse("caixa:dashboard_financeiro"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["custos_fixos_previsto_mes"], Decimal("300.00"))
        self.assertEqual(response.context["custos_fixos_pago_mes"], Decimal("100.00"))
        self.assertEqual(response.context["custos_fixos_diferenca_mes"], Decimal("200.00"))

    def test_dashboard_exibe_saida_por_categoria_e_cac_periodo(self):
        self.client.force_login(self.gerente)
        categoria = CategoriaFinanceira.objects.create(
            nome="Marketing e AquisiÃ§Ã£o",
            tipo="saida",
            ativa=True,
        )
        conta = ContaPagar.objects.create(
            fornecedor="Google Ads",
            descricao="Campanha",
            categoria=categoria,
            valor_total=Decimal("150.00"),
            valor_pago=Decimal("150.00"),
            vencimento=timezone.localdate(),
            status="paga",
        )
        PagamentoContaPagar.objects.create(
            conta=conta,
            caixa=Caixa.objects.filter(aberto=True).first(),
            valor=Decimal("150.00"),
        )
        Cliente.objects.create(
            nome="Cliente Marketing",
            documento="39053344705",
            telefone="11999998887",
            estado="SP",
            origem_cliente="google",
        )

        response = self.client.get(reverse("caixa:dashboard_financeiro"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saídas por categoria")
        self.assertEqual(response.context["despesas_marketing_periodo"], Decimal("150.00"))
        self.assertEqual(response.context["novos_clientes_periodo"], 2)
        self.assertEqual(response.context["cac_medio_periodo"], Decimal("75.00"))

    def test_dashboard_exibe_acoes_do_dia(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:dashboard_caixa"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registrar pagamento")
        self.assertContains(response, "Fechar caixa")
        self.assertContains(response, reverse("caixa:registrar_pagamento"))

    def test_dashboard_operacional_exibe_eventos_criticos_recentes(self):
        self.client.force_login(self.gerente)
        AuditoriaFinanceira.objects.create(
            evento="pagamento_excluido",
            descricao="Pagamento removido com justificativa.",
            valor=Decimal("40.00"),
            usuario=self.gerente,
        )
        response = self.client.get(reverse("caixa:dashboard_caixa"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ver auditoria")
        self.assertContains(response, "Pagamento removido com justificativa.")
        self.assertContains(response, "Ver motivo")
        self.assertContains(response, reverse("caixa:taloes"))

    def test_dashboard_operacional_linka_evento_de_fecho_ao_detalhe_do_caixa(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        caixa.aberto = False
        caixa.saldo_final = Decimal("100.00")
        caixa.valor_contado_fisico = Decimal("98.00")
        caixa.diferenca_fechamento = Decimal("-2.00")
        caixa.save(update_fields=["aberto", "saldo_final", "valor_contado_fisico", "diferenca_fechamento"])
        AuditoriaFinanceira.objects.create(
            evento="caixa_fechado",
            descricao=f"Caixa #{caixa.id} | contado=98.00 | diferenca=-2.00",
            valor=Decimal("100.00"),
            usuario=self.gerente,
        )

        response = self.client.get(reverse("caixa:dashboard_caixa"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fecho de caixa")
        self.assertContains(response, reverse("caixa:detalhe_caixa", args=[caixa.id]))

    def test_dashboard_financeiro_exibe_visao_gerencial(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:dashboard_financeiro"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Financeiro do caixa")

    def test_dashboard_financeiro_exibe_indicadores_executivos(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        categoria = CategoriaFinanceira.objects.create(nome="Fretes", tipo="saida", ativa=True)
        centro = CentroCusto.objects.create(nome="Logistica", tipo="variavel", ativo=True)
        Pagamento.objects.create(caixa=caixa, ordem_servico=self.ordem, valor=Decimal("200.00"), metodo="pix")
        LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Frete urgente",
            tipo="saida",
            valor=Decimal("40.00"),
            categoria=categoria,
            centro_custo=centro,
            usuario=self.gerente,
        )
        conta = ContaPagar.objects.create(
            fornecedor="Transportadora",
            descricao="Conta logistica",
            valor_total=Decimal("80.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate(),
            categoria=categoria,
            centro_custo=centro,
            status="aberta",
        )
        PagamentoContaPagar.objects.create(
            conta=conta,
            caixa=caixa,
            valor=Decimal("30.00"),
            usuario=self.gerente,
        )

        response = self.client.get(reverse("caixa:dashboard_financeiro"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ticket")
        self.assertContains(response, "Cobertura do caixa")
        self.assertContains(response, "Leitura executiva")
        self.assertEqual(response.context["ticket_medio_pagamento"], Decimal("200.00"))
        self.assertIsNotNone(response.context["margem_operacional_percentual"])
        self.assertEqual(response.context["contas_pagar_total_aberto"], Decimal("80.00"))

    def test_dashboard_financeiro_exibe_comparativos_por_categoria_e_centro(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        categoria = CategoriaFinanceira.objects.create(nome="Fretes expressos", tipo="saida", ativa=True)
        centro = CentroCusto.objects.create(nome="Logistica comparativo", tipo="variavel", ativo=True)
        atual = LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Frete atual",
            tipo="saida",
            valor=Decimal("40.00"),
            categoria=categoria,
            centro_custo=centro,
            usuario=self.gerente,
        )
        anterior = LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Frete anterior",
            tipo="saida",
            valor=Decimal("25.00"),
            categoria=categoria,
            centro_custo=centro,
            usuario=self.gerente,
        )
        hoje = timezone.localdate()
        LancamentoCaixa.objects.filter(pk=atual.pk).update(data=timezone.make_aware(timezone.datetime.combine(hoje, timezone.datetime.min.time())))
        LancamentoCaixa.objects.filter(pk=anterior.pk).update(data=timezone.make_aware(timezone.datetime.combine(hoje - timedelta(days=1), timezone.datetime.min.time())))

        response = self.client.get(reverse("caixa:dashboard_financeiro"), {"data_inicio": hoje.isoformat(), "data_fim": hoje.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Comparativo por categoria")
        self.assertContains(response, "Comparativo por centro de custo")
        self.assertContains(response, "Fretes expressos")
        self.assertContains(response, "Logistica comparativo")
        self.assertContains(response, "Formas de pagamento")
        self.assertContains(response, "mensal")

    def test_gerente_com_acesso_a_pagamento_comissoes(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:comissoes_pagamento"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Comissões")
        self.assertContains(response, "Selecione os filtros e clique em")

    def test_comissoes_pagamento_restauram_ultimos_filtros(self):
        self.client.force_login(self.gerente)
        self.client.get(reverse("caixa:comissoes_pagamento"), {"status": "PAGA", "criterio": "retirado_pago"})
        response = self.client.get(reverse("caixa:comissoes_pagamento"), {"restaurar": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("status=PAGA", response.url)
        self.assertIn("criterio=retirado_pago", response.url)

    def test_comissoes_pagamento_exibe_resumo_de_lotes_por_competencia(self):
        self.client.force_login(self.gerente)
        competencia = timezone.localdate().replace(day=1)
        ComissaoLotePagamento.objects.create(
            codigo="LOT-TESTE-01",
            competencia=competencia,
            data_inicio=competencia,
            data_fim=competencia,
            criterio="servicos_finalizados",
            total_itens=3,
            total_valor=Decimal("120.00"),
            status="PAGO",
            criado_por=self.gerente,
        )

        response = self.client.get(
            reverse("caixa:comissoes_pagamento"),
            {"competencia_mes": f"{competencia.month:02d}", "competencia_ano": str(competencia.year), "status": "PAGA"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lotes da compet")
        self.assertContains(response, "Valor em lotes pagos")
        self.assertContains(response, "LOT-TESTE-01")

    def test_comissoes_pagamento_exibe_competencias_recentes(self):
        self.client.force_login(self.gerente)
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Competencia recente",
            valor_base=Decimal("110.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("11.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="PAGA",
            competencia=timezone.localdate().replace(day=1),
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:competencia-recente",
        )

        response = self.client.get(reverse("caixa:comissoes_pagamento"), {"status": "PAGA"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Compet")

    def test_comissoes_pendencias_exibe_resumo_executivo_da_competencia(self):
        self.client.force_login(self.gerente)
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Resumo pendencia",
            valor_base=Decimal("100.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            competencia=timezone.localdate().replace(day=1),
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:resumo-pendencia",
        )

        response = self.client.get(reverse("caixa:comissoes_pendencias"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total da compet")
        self.assertContains(response, "Geradas")

    def test_comissoes_tecnicos_exibe_visao_mensal_por_colaborador(self):
        self.client.force_login(self.gerente)
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Visao mensal",
            valor_base=Decimal("90.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("9.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            competencia=timezone.localdate().replace(day=1),
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:visao-mensal",
        )

        response = self.client.get(reverse("caixa:comissoes_tecnicos"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mensal")
        self.assertContains(response, self.tecnico.username)

    def test_gerente_com_acesso_a_pendencias_comissoes(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:comissoes_pendencias"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pend")

    def test_comissoes_pendencias_restauram_ultimos_filtros(self):
        self.client.force_login(self.gerente)
        self.client.get(reverse("caixa:comissoes_pendencias"), {"competencia_mes": "03", "competencia_ano": "2026", "criterio": "retirado_pago"})
        response = self.client.get(reverse("caixa:comissoes_pendencias"), {"restaurar": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("competencia_mes=03", response.url)
        self.assertIn("competencia_ano=2026", response.url)
        self.assertIn("criterio=retirado_pago", response.url)

    def test_pendencias_comissoes_exibe_atendente_e_tecnico_da_os_sem_relatorio(self):
        self.client.force_login(self.gerente)
        self.ordem.status = "pronto_contactado"
        self.ordem.tecnico_responsavel = self.tecnico
        self.ordem.relatorio_tecnico = ""
        self.ordem.save(update_fields=["status", "tecnico_responsavel", "relatorio_tecnico"])
        LinhaTrabalho.objects.create(
            ordem=self.ordem,
            usuario=self.atendente,
            status="criada",
            descricao="Ordem criada",
            tipo_evento="manual",
        )

        response = self.client.get(reverse("caixa:comissoes_pendencias"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Atendente")
        self.assertContains(response, self.tecnico.username)
        self.assertContains(response, self.atendente.username)

    def test_pagamento_comissoes_nao_carrega_lista_sem_filtro(self):
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Comissao sem filtro inicial",
            valor_base=Decimal("80.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("8.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:sem-filtro-inicial",
        )
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:comissoes_pagamento"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Comissao sem filtro inicial")

    def test_pagamento_comissoes_paga_lote(self):
        comissao = Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Comissao lote simples",
            valor_base=Decimal("120.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("12.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:teste-lote-simples",
        )
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("caixa:comissoes_pagamento"),
            {
                "action": "pagar_lote",
                "comissao_ids": [str(comissao.id)],
                "referencia_pagamento_lote": "LOTE-SIMPLES-01",
            },
        )
        self.assertEqual(response.status_code, 302)
        comissao.refresh_from_db()
        self.assertEqual(comissao.status, "PAGA")
        self.assertEqual(comissao.referencia_pagamento, "LOTE-SIMPLES-01")
        self.assertIsNotNone(comissao.lote_pagamento)
        self.assertEqual(comissao.lote_pagamento.status, "PAGO")
        self.assertEqual(comissao.lote_pagamento.total_itens, 1)

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

    def test_baixa_conta_receber_aplica_juros_no_caixa_e_desconto_na_quitacao(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="OS com juros",
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
                "valor": "90.00",
                "desconto": "10.00",
                "juros": "5.00",
                "referencia": "REC-2",
                "observacao": "",
                "metodo": "pix",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        pagamento = Pagamento.objects.latest("id")
        self.assertEqual(str(pagamento.valor), "95.00")
        self.assertEqual(str(conta.valor_aberto), "0.00")
        self.assertEqual(conta.status, "paga")

    def test_baixa_conta_receber_bloqueia_abatimento_maior_que_saldo(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="OS com desconto excedente",
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
                "valor": "95.00",
                "desconto": "10.00",
                "juros": "0.00",
                "referencia": "REC-3",
                "observacao": "",
                "metodo": "pix",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(str(conta.valor_aberto), "100.00")
        self.assertFalse(Pagamento.objects.filter(referencia="REC-3").exists())

    def test_usuario_financeiro_extra_sem_perm_nao_baixa_conta_receber(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="Conta bloqueada para baixa",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="100.00",
            vencimento="2030-01-01",
            status="aberta",
        )
        self.client.force_login(self.financeiro_extra)
        response = self.client.post(
            reverse("caixa:detalhe_conta_receber", args=[conta.id]),
            {
                "valor": "40.00",
                "desconto": "0.00",
                "juros": "0.00",
                "referencia": "REC-BLOCK",
                "observacao": "",
                "metodo": "pix",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(str(conta.valor_aberto), "100.00")
        self.assertFalse(Pagamento.objects.filter(referencia="REC-BLOCK").exists())

    def test_usuario_financeiro_extra_sem_perm_nao_cancela_conta_receber(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="Conta sem cancelamento",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="100.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        self.client.force_login(self.financeiro_extra)
        response = self.client.post(
            reverse("caixa:detalhe_conta_receber", args=[conta.id]),
            {
                "action": "cancelar",
                "motivo_cancelamento": "Cobranca criada em duplicidade.",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "aberta")

    def test_usuario_financeiro_extra_sem_perm_nao_edita_conta_receber(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="Conta sem edicao",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="100.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        self.client.force_login(self.financeiro_extra)
        response = self.client.get(reverse("caixa:editar_conta_receber", args=[conta.id]))
        self.assertEqual(response.status_code, 403)

    def test_usuario_financeiro_extra_com_perm_edita_conta_receber_sem_movimentacao(self):
        self.financeiro_extra.perm_caixa_editar_conta_receber = True
        self.financeiro_extra.save(update_fields=["perm_caixa_editar_conta_receber"])
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="Conta original",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="100.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        self.client.force_login(self.financeiro_extra)
        response = self.client.post(
            reverse("caixa:editar_conta_receber", args=[conta.id]),
            {
                "ordem_servico": self.ordem.id,
                "descricao": "Conta editada",
                "cliente_nome": "Cliente ajustado",
                "ponto_operacional": "",
                "categoria": "",
                "valor_original": "180.00",
                "vencimento": "2030-01-15",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.descricao, "Conta editada")
        self.assertEqual(conta.cliente_nome, "Cliente ajustado")
        self.assertEqual(str(conta.valor_original), "180.00")
        self.assertEqual(str(conta.valor_aberto), "180.00")

    def test_edicao_conta_receber_movimentada_preserva_valor_original(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="Conta movimentada",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="80.00",
            vencimento=timezone.localdate(),
            status="parcial",
        )
        pagamento = Pagamento.objects.create(
            caixa=Caixa.objects.filter(aberto=True).first(),
            ordem_servico=self.ordem,
            valor=Decimal("20.00"),
            metodo="pix",
            referencia="REC-EDIT-LOCK",
        )
        conta.recebimentos.create(
            pagamento=pagamento,
            valor=Decimal("20.00"),
            desconto=Decimal("0.00"),
            juros=Decimal("0.00"),
            referencia="REC-EDIT-LOCK",
            usuario=self.gerente,
        )
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("caixa:editar_conta_receber", args=[conta.id]),
            {
                "ordem_servico": "",
                "descricao": "Conta movimentada ajustada",
                "cliente_nome": "Cliente revisado",
                "ponto_operacional": "",
                "categoria": "",
                "valor_original": "500.00",
                "vencimento": "2030-01-20",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.descricao, "Conta movimentada ajustada")
        self.assertEqual(conta.cliente_nome, "Cliente revisado")
        self.assertEqual(str(conta.valor_original), "100.00")
        self.assertEqual(str(conta.valor_aberto), "80.00")

    def test_gerente_cancela_conta_receber_sem_recebimentos(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="Conta cancelavel",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="100.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("caixa:detalhe_conta_receber", args=[conta.id]),
            {
                "action": "cancelar",
                "motivo_cancelamento": "Cobranca criada em duplicidade.",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "cancelada")
        auditoria = AuditoriaFinanceira.objects.get(evento="conta_receber_cancelada", conta=conta)
        self.assertIn("duplicidade", auditoria.descricao)

    def test_gerente_nao_cancela_conta_receber_sem_justificativa(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="Conta sem justificativa",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="100.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        self.client.force_login(self.gerente)

        response = self.client.post(
            reverse("caixa:detalhe_conta_receber", args=[conta.id]),
            {"action": "cancelar", "motivo_cancelamento": ""},
        )

        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "aberta")

    def test_conta_receber_com_recebimentos_nao_pode_ser_cancelada(self):
        conta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="Conta com recebimento",
            cliente_nome=self.cliente.nome,
            valor_original="100.00",
            valor_aberto="100.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        pagamento = Pagamento.objects.create(
            caixa=Caixa.objects.filter(aberto=True).first(),
            ordem_servico=self.ordem,
            valor=Decimal("20.00"),
            metodo="pix",
            referencia="REC-CANCEL-BLOCK",
        )
        conta.recebimentos.create(
            pagamento=pagamento,
            valor=Decimal("20.00"),
            desconto=Decimal("0.00"),
            juros=Decimal("0.00"),
            referencia="REC-CANCEL-BLOCK",
            usuario=self.gerente,
        )
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("caixa:detalhe_conta_receber", args=[conta.id]),
            {"action": "cancelar"},
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "aberta")

    def test_nao_permite_abrir_novo_caixa_no_mesmo_dia_apos_fechamento(self):
        caixa = Caixa.objects.filter(aberto=True).first()
        caixa.aberto = False
        caixa.saldo_final = Decimal("0.00")
        caixa.save(update_fields=["aberto", "saldo_final"])

        self.client.force_login(self.atendente)
        response = self.client.post(reverse("caixa:abrir_caixa"), {"saldo_inicial": "10.00"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ja existe um caixa registrado para hoje")
        self.assertEqual(Caixa.objects.count(), 1)

    def test_abrir_caixa_exibe_saldo_sugerido_com_base_no_ultimo_fechamento(self):
        caixa = Caixa.objects.filter(aberto=True).first()
        caixa.aberto = False
        caixa.data = timezone.localdate() - timedelta(days=1)
        caixa.saldo_final = Decimal("120.00")
        caixa.valor_contado_fisico = Decimal("135.00")
        caixa.save(update_fields=["aberto", "data", "saldo_final", "valor_contado_fisico"])

        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:abrir_caixa"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["saldo_sugerido_abertura"], Decimal("135.00"))
        self.assertContains(response, "Checklist da abertura")

    def test_fechar_caixa_exibe_resumo_de_conferencia(self):
        caixa = Caixa.objects.filter(aberto=True).first()
        forma = FormaPagamento.objects.create(nome="Dinheiro Teste", codigo="dinheiro_teste", tipo="avista")
        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("90.00"),
            forma_pagamento=forma,
            metodo="dinheiro_teste",
        )
        LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Compra de material",
            tipo="saida",
            valor=Decimal("10.00"),
            usuario=self.atendente,
        )

        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:fechar_caixa"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fechamento")
        self.assertContains(response, "Formas de pagamento no caixa")
        self.assertEqual(response.context["quantidade_pagamentos"], 1)
        self.assertEqual(response.context["quantidade_saidas"], 1)

    def test_fechar_caixa_salva_conferencia_por_forma_pagamento(self):
        caixa = Caixa.objects.filter(aberto=True).first()
        forma = FormaPagamento.objects.create(nome="PIX Teste", codigo="pix_teste", tipo="avista")
        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("80.00"),
            forma_pagamento=forma,
            metodo="pix_teste",
        )

        self.client.force_login(self.atendente)
        response = self.client.post(
            reverse("caixa:fechar_caixa"),
            {
                "valor_contado_fisico": "0.00",
                "justificativa_diferenca": "",
                "conferencia_pix_teste": "80.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        caixa.refresh_from_db()
        self.assertFalse(caixa.aberto)
        self.assertEqual(len(caixa.conferencia_formas_pagamento), 1)
        self.assertEqual(caixa.conferencia_formas_pagamento[0]["codigo"], "pix_teste")

    def test_fechar_caixa_separa_pagamento_misto_e_confere_somente_dinheiro_fisico(self):
        caixa = Caixa.objects.filter(aberto=True).first()
        caixa.saldo_inicial = Decimal("50.00")
        caixa.save(update_fields=["saldo_inicial"])
        forma_pix = FormaPagamento.objects.create(nome="PIX misto fecho", codigo="pix_misto_fecho", tipo="avista")
        forma_dinheiro, _ = FormaPagamento.objects.get_or_create(
            codigo="dinheiro",
            defaults={"nome": "Dinheiro", "tipo": "avista", "ativa": True},
        )
        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("120.00"),
            forma_pagamento=forma_pix,
            metodo="pix_misto_fecho",
            formas_pagamento_compostas=[
                {
                    "forma_id": forma_pix.id,
                    "forma_codigo": forma_pix.codigo,
                    "forma_nome": forma_pix.nome,
                    "valor": "100.00",
                    "referencia": "PIX-100",
                },
                {
                    "forma_id": forma_dinheiro.id,
                    "forma_codigo": forma_dinheiro.codigo,
                    "forma_nome": forma_dinheiro.nome,
                    "valor": "20.00",
                    "referencia": "DIN-20",
                },
            ],
        )
        LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Saida em especie",
            tipo="saida",
            valor=Decimal("10.00"),
            usuario=self.atendente,
        )

        self.client.force_login(self.atendente)
        response_get = self.client.get(reverse("caixa:fechar_caixa"))

        self.assertEqual(response_get.context["saldo"], Decimal("60.00"))
        self.assertEqual(response_get.context["saldo_contabil"], Decimal("160.00"))
        apurado = {item["codigo"]: item["apurado"] for item in response_get.context["conferencia_formas"]}
        self.assertEqual(apurado["pix_misto_fecho"], Decimal("100.00"))
        self.assertEqual(apurado["dinheiro"], Decimal("20.00"))

        response_post = self.client.post(
            reverse("caixa:fechar_caixa"),
            {
                "valor_contado_fisico": "60.00",
                "justificativa_diferenca": "",
                "conferencia_pix_misto_fecho": "100.00",
                "conferencia_dinheiro": "20.00",
            },
        )

        self.assertEqual(response_post.status_code, 302)
        caixa.refresh_from_db()
        self.assertFalse(caixa.aberto)
        self.assertEqual(caixa.saldo_final, Decimal("160.00"))
        self.assertEqual(caixa.valor_contado_fisico, Decimal("60.00"))
        self.assertEqual(caixa.diferenca_fechamento, Decimal("0.00"))

    def test_detalhe_caixa_exibe_conferencia_salva(self):
        caixa = Caixa.objects.filter(aberto=True).first()
        forma = FormaPagamento.objects.create(nome="Cartao Teste", codigo="cartao_teste", tipo="avista")
        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("120.00"),
            forma_pagamento=forma,
            metodo="cartao_teste",
        )
        caixa.aberto = False
        caixa.saldo_final = Decimal("120.00")
        caixa.valor_contado_fisico = Decimal("118.00")
        caixa.diferenca_fechamento = Decimal("-2.00")
        caixa.justificativa_diferenca = "Ajuste no fechamento."
        caixa.conferencia_formas_pagamento = [
            {
                "codigo": "cartao_teste",
                "nome": "Cartao Teste",
                "apurado": "120.00",
                "contado": "118.00",
                "diferenca": "-2.00",
            }
        ]
        caixa.save(
            update_fields=[
                "aberto",
                "saldo_final",
                "valor_contado_fisico",
                "diferenca_fechamento",
                "justificativa_diferenca",
                "conferencia_formas_pagamento",
            ]
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:detalhe_caixa", args=[caixa.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cartao Teste")
        self.assertContains(response, "Cartao Teste")
        self.assertContains(response, "Ajuste no fechamento.")

    def test_detalhe_caixa_exibe_eventos_financeiros_relacionados(self):
        caixa = Caixa.objects.filter(aberto=True).first()
        caixa.aberto = False
        caixa.saldo_final = Decimal("90.00")
        caixa.valor_contado_fisico = Decimal("88.00")
        caixa.diferenca_fechamento = Decimal("-2.00")
        caixa.save(update_fields=["aberto", "saldo_final", "valor_contado_fisico", "diferenca_fechamento"])
        AuditoriaFinanceira.objects.create(
            evento="caixa_fechado",
            descricao=f"Caixa #{caixa.id} | contado=88.00 | diferenca=-2.00",
            valor=Decimal("90.00"),
            usuario=self.gerente,
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:detalhe_caixa", args=[caixa.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Eventos financeiros do caixa")
        self.assertContains(response, "caixa_fechado")

    def test_dashboard_filtra_movimento_por_periodo(self):
        self.client.force_login(self.gerente)
        caixa_hoje = Caixa.objects.filter(aberto=True).first()
        Pagamento.objects.create(caixa=caixa_hoje, ordem_servico=self.ordem, valor=Decimal("50.00"), metodo="pix")

        caixa_hoje.aberto = False
        caixa_hoje.data = timezone.localdate() - timedelta(days=1)
        caixa_hoje.saldo_final = Decimal("50.00")
        caixa_hoje.save(update_fields=["aberto", "data", "saldo_final"])

        caixa_novo = Caixa.objects.create(aberto=True, saldo_inicial=Decimal("0.00"))
        Pagamento.objects.create(caixa=caixa_novo, ordem_servico=self.ordem, valor=Decimal("20.00"), metodo="pix")

        response = self.client.get(
            reverse("caixa:dashboard_caixa"),
            {"data_inicio": timezone.localdate().isoformat(), "data_fim": timezone.localdate().isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_entradas"], Decimal("20.00"))

    def test_registrar_saida_garante_centros_padrao_e_exibe_saldo(self):
        self.client.force_login(self.atendente)
        CentroCusto.objects.all().delete()

        response = self.client.get(reverse("caixa:registrar_saida"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saldo atual")
        self.assertTrue(CentroCusto.objects.filter(nome="Operacional", ativo=True).exists())
        self.assertGreater(response.context["form"].fields["centro_custo"].queryset.count(), 0)

    def test_criar_conta_pagar_garante_centros_padrao(self):
        self.client.force_login(self.gerente)
        CentroCusto.objects.all().delete()

        response = self.client.get(reverse("caixa:criar_conta_pagar"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(CentroCusto.objects.filter(nome="Administrativo", ativo=True).exists())
        self.assertGreater(response.context["form"].fields["categoria"].queryset.count(), 0)
        self.assertGreater(response.context["form"].fields["centro_custo"].queryset.count(), 0)

    def test_contas_pagar_filtra_prioridade_hoje(self):
        categoria = CategoriaFinanceira.objects.create(nome="Fornecedor DiÃ¡rio", tipo="saida", ativa=True)
        conta_hoje = ContaPagar.objects.create(
            fornecedor="Fornecedor Hoje",
            descricao="Conta vence hoje",
            categoria=categoria,
            valor_total=Decimal("120.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate(),
            status="aberta",
        )
        ContaPagar.objects.create(
            fornecedor="Fornecedor Futuro",
            descricao="Conta futura",
            categoria=categoria,
            valor_total=Decimal("90.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate() + timedelta(days=5),
            status="aberta",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:contas_pagar"), {"prioridade": "hoje"})

        self.assertEqual(response.status_code, 200)
        contas = list(response.context["contas"])
        self.assertEqual(len(contas), 1)
        self.assertEqual(contas[0].id, conta_hoje.id)

    def test_contas_pagar_filtra_prioridade_criticas(self):
        categoria = CategoriaFinanceira.objects.create(nome="Fornecedor Critico", tipo="saida", ativa=True)
        conta_vencida = ContaPagar.objects.create(
            fornecedor="Fornecedor Vencido",
            descricao="Conta vencida",
            categoria=categoria,
            valor_total=Decimal("140.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate() - timedelta(days=2),
            status="aberta",
        )
        conta_sem_categoria = ContaPagar.objects.create(
            fornecedor="Fornecedor Sem Categoria",
            descricao="Conta sem categoria",
            valor_total=Decimal("90.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate() + timedelta(days=4),
            status="aberta",
        )
        ContaPagar.objects.create(
            fornecedor="Fornecedor Normal",
            descricao="Conta normal",
            categoria=categoria,
            valor_total=Decimal("75.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate() + timedelta(days=10),
            status="aberta",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:contas_pagar"), {"prioridade": "criticas"})

        self.assertEqual(response.status_code, 200)
        contas_ids = {conta.id for conta in response.context["contas"]}
        self.assertEqual(contas_ids, {conta_vencida.id, conta_sem_categoria.id})

    def test_contas_pagar_exibe_resumos_operacionais(self):
        ContaPagar.objects.create(
            fornecedor="Fornecedor Hoje",
            descricao="Conta do dia",
            valor_total=Decimal("120.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate(),
            status="aberta",
        )
        ContaPagar.objects.create(
            fornecedor="Fornecedor Atrasado",
            descricao="Conta vencida",
            valor_total=Decimal("80.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate() - timedelta(days=3),
            status="aberta",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:contas_pagar"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["pagar_hoje_total"], Decimal("120.00"))
        self.assertEqual(response.context["pagar_vencidas_total"], Decimal("80.00"))
        self.assertContains(response, "Pagar hoje")
        self.assertContains(response, "Sem categoria")

    def test_contas_pagar_exibe_aging_visual_por_faixas(self):
        ContaPagar.objects.create(
            fornecedor="Fornecedor Aging",
            descricao="Conta muito vencida",
            valor_total=Decimal("90.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate() - timedelta(days=45),
            status="vencida",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:contas_pagar"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 a 30 dias")
        self.assertContains(response, "31 a 60 dias")

    def test_contas_pagar_restauram_ultimos_filtros(self):
        self.client.force_login(self.gerente)
        self.client.get(reverse("caixa:contas_pagar"), {"prioridade": "vencidas", "status": "aberta"})
        response = self.client.get(reverse("caixa:contas_pagar"), {"restaurar": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("prioridade=vencidas", response.url)
        self.assertIn("status=aberta", response.url)

    def test_relatorios_restauram_ultimos_filtros(self):
        self.client.force_login(self.gerente)
        self.client.get(reverse("caixa:relatorios"), {"preset": "30d", "todos_caixas": "1", "tipo_lancamento": "saida"})
        response = self.client.get(reverse("caixa:relatorios"), {"restaurar": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("preset=30d", response.url)
        self.assertIn("todos_caixas=1", response.url)
        self.assertIn("tipo_lancamento=saida", response.url)

    def test_auditoria_operacional_restaurar_ultimos_filtros(self):
        self.client.force_login(self.gerente)
        self.client.get(reverse("caixa:auditoria_operacional"), {"dias": "90"})
        response = self.client.get(reverse("caixa:auditoria_operacional"), {"restaurar": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("dias=90", response.url)

    def test_contas_receber_filtra_por_busca_e_origem(self):
        conta_cliente = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="Reparo notebook",
            cliente_nome="Cliente Caixa",
            tipo_origem="cliente_os",
            valor_original="150.00",
            valor_aberto="150.00",
            vencimento="2030-01-01",
            status="aberta",
        )
        ContaReceber.objects.create(
            descricao="Garantia fabricante",
            cliente_nome="Outro cliente",
            tipo_origem="garantia_fabricante",
            valor_original="90.00",
            valor_aberto="90.00",
            vencimento="2030-01-01",
            status="aberta",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(
            reverse("caixa:contas_receber"),
            {"q": "notebook", "tipo_origem": "cliente_os"},
        )
        self.assertEqual(response.status_code, 200)
        contas = list(response.context["contas"])
        self.assertEqual(len(contas), 1)
        self.assertEqual(contas[0].id, conta_cliente.id)

    def test_contas_receber_filtra_prioridade_vencidas(self):
        conta_vencida = ContaReceber.objects.create(
            descricao="Receber atrasado",
            cliente_nome="Cliente A",
            tipo_origem="avulso",
            valor_original="50.00",
            valor_aberto="50.00",
            vencimento=timezone.localdate() - timedelta(days=2),
            status="aberta",
        )
        ContaReceber.objects.create(
            descricao="Receber futuro",
            cliente_nome="Cliente B",
            tipo_origem="avulso",
            valor_original="70.00",
            valor_aberto="70.00",
            vencimento=timezone.localdate() + timedelta(days=3),
            status="aberta",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:contas_receber"), {"prioridade": "vencidas"})

        self.assertEqual(response.status_code, 200)
        contas = list(response.context["contas"])
        self.assertEqual(len(contas), 1)
        self.assertEqual(contas[0].id, conta_vencida.id)
        self.assertEqual(contas[0].dias_atraso, 2)

    def test_contas_receber_filtra_prioridade_criticas(self):
        conta_vencida = ContaReceber.objects.create(
            descricao="Receber vencido",
            cliente_nome="Cliente Vencido",
            tipo_origem="avulso",
            valor_original="80.00",
            valor_aberto="80.00",
            vencimento=timezone.localdate() - timedelta(days=3),
            status="aberta",
        )
        self.ordem.status = "pronto_contactado"
        self.ordem.save(update_fields=["status"])
        conta_pronta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="OS pronta sem recebimento",
            cliente_nome=self.cliente.nome,
            tipo_origem="cliente_os",
            valor_original="120.00",
            valor_aberto="120.00",
            vencimento=timezone.localdate() + timedelta(days=5),
            status="aberta",
        )
        ContaReceber.objects.create(
            descricao="Receber normal",
            cliente_nome="Cliente Normal",
            tipo_origem="avulso",
            valor_original="60.00",
            valor_aberto="60.00",
            vencimento=timezone.localdate() + timedelta(days=12),
            status="aberta",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:contas_receber"), {"prioridade": "criticas"})

        self.assertEqual(response.status_code, 200)
        contas_ids = {conta.id for conta in response.context["contas"]}
        self.assertEqual(contas_ids, {conta_vencida.id, conta_pronta.id})

    def test_contas_receber_exibe_resumos_operacionais(self):
        ContaReceber.objects.create(
            descricao="Garantia fabricante",
            cliente_nome="Cliente Garantia",
            tipo_origem="garantia_fabricante",
            valor_original="90.00",
            valor_aberto="90.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        ContaReceber.objects.create(
            descricao="Receber atrasado",
            cliente_nome="Cliente Atraso",
            tipo_origem="avulso",
            valor_original="50.00",
            valor_aberto="50.00",
            vencimento=timezone.localdate() - timedelta(days=1),
            status="aberta",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:contas_receber"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["receber_garantia_qtd"], 1)
        self.assertEqual(response.context["receber_garantia_total"], Decimal("90.00"))
        self.assertEqual(response.context["receber_vencidas_total"], Decimal("50.00"))
        self.assertContains(response, "Garantia fabricante")
        self.assertContains(response, "Receber hoje")

    def test_contas_receber_restauram_ultimos_filtros(self):
        self.client.force_login(self.gerente)
        self.client.get(reverse("caixa:contas_receber"), {"prioridade": "vencidas", "tipo_origem": "cliente_os"})
        response = self.client.get(reverse("caixa:contas_receber"), {"restaurar": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("prioridade=vencidas", response.url)
        self.assertIn("tipo_origem=cliente_os", response.url)

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

    def test_venda_mostrador_gera_comissao_total_e_bonus_produto(self):
        self.client.force_login(self.atendente)
        self.atendente.numero_vendedor = "12"
        self.atendente.percentual_comissao_vendas = Decimal("6.00")
        self.atendente.save(update_fields=["numero_vendedor", "percentual_comissao_vendas"])

        ponto = PontoOperacional.objects.create(codigo="PO3A", nome="Loja A")
        produto = Produto.objects.create(
            nome="Copo Liquidificador",
            ean="7899991110012",
            preco_final=Decimal("100.00"),
            preco=Decimal("100.00"),
            quantidade=5,
            ponto_operacional=ponto,
            ativo=True,
            bonus_venda=Decimal("4.00"),
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=5)
        venda = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            valor_total=Decimal("100.00"),
            funcionario_numero="12",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?venda={venda.id}",
            {"valor": "100.00", "metodo": "pix", "referencia": "PDV-COM-1"},
        )
        self.assertEqual(response.status_code, 302)

        venda.refresh_from_db()
        self.assertEqual(venda.status, "vendida")
        tipos = {
            row["tipo"]: row["valor_comissao"]
            for row in Comissao.objects.filter(tecnico=self.atendente).values("tipo", "valor_comissao")
        }
        self.assertEqual(tipos["COMISSAO_VENDAS"], Decimal("6.00"))
        self.assertEqual(tipos["BONUS_PRODUTO"], Decimal("4.00"))

        hoje = timezone.localdate().isoformat()
        response_desempenho = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "data_inicio": hoje,
                "data_fim": hoje,
                "percentual_servicos": "0",
                "percentual_pecas": "0",
                "percentual_vendas": "6",
                "aplicar_servicos": "0",
                "aplicar_pecas": "0",
                "aplicar_vendas": "1",
            },
        )
        self.assertEqual(response_desempenho.status_code, 200)
        self.assertEqual(response_desempenho.context["total_base_vendas_relatorio"], Decimal("100.00"))
        self.assertEqual(response_desempenho.context["total_comissao_vendas_relatorio"], Decimal("6.00"))
        self.assertEqual(response_desempenho.context["total_comissao_relatorio"], Decimal("10.00"))
        self.assertEqual(response_desempenho.context["resumo"]["bonus_produto"], Decimal("4.00"))

    def test_venda_mostrador_bonus_produto_respeita_quantidade(self):
        self.client.force_login(self.atendente)
        self.atendente.numero_vendedor = "13"
        self.atendente.percentual_comissao_vendas = Decimal("0.00")
        self.atendente.save(update_fields=["numero_vendedor", "percentual_comissao_vendas"])

        ponto = PontoOperacional.objects.create(codigo="PO3B", nome="Loja B")
        produto = Produto.objects.create(
            nome="Pelicula Premium",
            ean="7899991110013",
            preco_final=Decimal("30.00"),
            preco=Decimal("30.00"),
            quantidade=10,
            ponto_operacional=ponto,
            ativo=True,
            bonus_venda=Decimal("1.00"),
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=10)
        venda = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=3,
            valor_unitario=Decimal("30.00"),
            valor_total=Decimal("90.00"),
            funcionario_numero="13",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?venda={venda.id}",
            {"valor": "90.00", "metodo": "pix", "referencia": "PDV-BONUS-QTD"},
        )
        self.assertEqual(response.status_code, 302)

        bonus = Comissao.objects.filter(tecnico=self.atendente, tipo="BONUS_PRODUTO").order_by("-id").first()
        self.assertIsNotNone(bonus)
        self.assertEqual(bonus.valor_comissao, Decimal("3.00"))
        self.assertEqual((bonus.dados_extras or {}).get("quantidade"), 3)
        self.assertEqual(Decimal(str((bonus.dados_extras or {}).get("bonus_por_unidade"))), Decimal("1.00"))

    def test_venda_mostrador_pode_desligar_bonus_produto_por_configuracao(self):
        self.client.force_login(self.atendente)
        self.atendente.numero_vendedor = "14"
        self.atendente.percentual_comissao_vendas = Decimal("5.00")
        self.atendente.save(update_fields=["numero_vendedor", "percentual_comissao_vendas"])
        config = ConfiguracaoSistema.get_configuracao()
        config.comissao_bonus_produto_ativo = False
        config.save(update_fields=["comissao_bonus_produto_ativo"])

        ponto = PontoOperacional.objects.create(codigo="PO3C", nome="Loja C")
        produto = Produto.objects.create(
            nome="Carregador Turbo",
            ean="7899991110014",
            preco_final=Decimal("100.00"),
            preco=Decimal("100.00"),
            quantidade=5,
            ponto_operacional=ponto,
            ativo=True,
            bonus_venda=Decimal("4.00"),
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=5)
        venda = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            valor_total=Decimal("100.00"),
            funcionario_numero="14",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?venda={venda.id}",
            {"valor": "100.00", "metodo": "pix", "referencia": "PDV-BONUS-OFF"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Comissao.objects.filter(tecnico=self.atendente, tipo="COMISSAO_VENDAS").exists())
        self.assertFalse(Comissao.objects.filter(tecnico=self.atendente, tipo="BONUS_PRODUTO").exists())

    def test_auditar_comissoes_ok_para_venda_mostrador(self):
        self.atendente.numero_vendedor = "18"
        self.atendente.percentual_comissao_vendas = Decimal("5.00")
        self.atendente.save(update_fields=["numero_vendedor", "percentual_comissao_vendas"])

        ponto = PontoOperacional.objects.create(codigo="POAUD", nome="Loja Auditoria")
        produto = Produto.objects.create(
            nome="Produto Auditoria",
            ean="7899991110099",
            preco_final=Decimal("80.00"),
            preco=Decimal("80.00"),
            quantidade=3,
            ponto_operacional=ponto,
            ativo=True,
            bonus_venda=Decimal("2.00"),
        )
        venda = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("80.00"),
            valor_total=Decimal("80.00"),
            funcionario_numero="18",
            status="vendida",
            usuario=self.atendente,
            concluido_em=timezone.now(),
        )
        Comissao.objects.create(
            tecnico=self.atendente,
            produto=produto,
            tipo="COMISSAO_VENDAS",
            descricao="Comissao venda mostrador - Produto Auditoria",
            valor_base=Decimal("80.00"),
            percentual=Decimal("5.00"),
            valor_comissao=Decimal("4.00"),
            evento_gerador="VENDA_MOSTRADOR",
            status="GERADA",
            chave_unica=f"VENDA_MOSTRADOR:COMISSAO_VENDAS:venda:{venda.id}",
        )
        Comissao.objects.create(
            tecnico=self.atendente,
            produto=produto,
            tipo="BONUS_PRODUTO",
            descricao="Bonus por venda mostrador - Produto Auditoria",
            valor_base=Decimal("80.00"),
            percentual=Decimal("0.00"),
            valor_comissao=Decimal("2.00"),
            evento_gerador="VENDA_MOSTRADOR",
            status="GERADA",
            chave_unica=f"VENDA_MOSTRADOR:BONUS_PRODUTO:venda:{venda.id}",
        )

        out = StringIO()
        call_command("auditar_comissoes", stdout=out)
        self.assertIn("Nenhuma inconsist", out.getvalue())

    def test_comissoes_tecnicos_lista_atendente_com_comissao_vendas(self):
        Comissao.objects.create(
            tecnico=self.atendente,
            tipo="COMISSAO_VENDAS",
            descricao="Comissao venda balcao",
            valor_base=Decimal("100.00"),
            percentual=Decimal("7.00"),
            valor_comissao=Decimal("7.00"),
            evento_gerador="VENDA_MOSTRADOR",
            status="GERADA",
            chave_unica="VENDA_MOSTRADOR:COMISSAO_VENDAS:venda:2701",
        )

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:comissoes_tecnicos"), {"tecnico": str(self.atendente.id)})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.atendente, list(response.context["tecnicos"]))
        self.assertEqual(list(response.context["comissoes"])[0].tecnico_id, self.atendente.id)

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

    def test_finalizar_guia_no_caixa_preserva_contexto_no_redirect_sucesso(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO2", nome="Armazem")
        produto = Produto.objects.create(
            nome="Flex X",
            ean="7899991110004",
            preco_final=Decimal("30.00"),
            preco=Decimal("30.00"),
            quantidade=10,
            ponto_operacional=ponto,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=10)
        VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=2,
            valor_unitario=Decimal("30.00"),
            valor_total=Decimal("60.00"),
            funcionario_numero="12",
            cesto_codigo="CES-ABC",
            guia_pagamento="GUIA-POS-01",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + "?guia=GUIA-POS-01",
            {"valor": "60.00", "metodo": "pix", "referencia": "PDV-GUIA-CTX"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("guia=GUIA-POS-01", response.url)
        self.assertIn("sucesso=", response.url)

    def test_registrar_pagamento_exibe_resumo_e_acoes_da_guia(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja")
        produto = Produto.objects.create(
            nome="Bateria A",
            ean="7899991110005",
            preco_final=Decimal("45.00"),
            preco=Decimal("45.00"),
            quantidade=8,
            ponto_operacional=ponto,
            ativo=True,
        )
        VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("45.00"),
            valor_total=Decimal("45.00"),
            funcionario_numero="12",
            cesto_codigo="CES-XYZ",
            guia_pagamento="GUIA-VISUAL-01",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.get(reverse("caixa:registrar_pagamento") + "?guia=GUIA-VISUAL-01")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumo da Guia")
        self.assertContains(response, "Venda a mostrador")
        self.assertContains(response, "Abrir guia")
        self.assertContains(response, "Voltar ao POS")

    def test_registrar_pagamento_modo_guia_exibe_resumo_operacional_sem_bloco_de_os(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja")
        produto = Produto.objects.create(
            nome="Frontal J7",
            ean="7899991110006",
            preco_final=Decimal("65.00"),
            preco=Decimal("65.00"),
            quantidade=8,
            ponto_operacional=ponto,
            ativo=True,
        )
        VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=2,
            valor_unitario=Decimal("65.00"),
            valor_total=Decimal("130.00"),
            funcionario_numero="12",
            cesto_codigo="CES-UI-01",
            guia_pagamento="GUIA-UI-01",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.get(reverse("caixa:registrar_pagamento") + "?guia=GUIA-UI-01")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumo da Guia")
        self.assertContains(response, "Pendente de recebimento")
        self.assertContains(response, "Total da guia")
        self.assertContains(response, "Operador")
        self.assertContains(response, "Vendedor")
        self.assertNotContains(response, "OS v&aacute;lida")

    def test_registrar_pagamento_modo_guia_exibe_identificacao_opcional_do_comprador(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja")
        produto = Produto.objects.create(
            nome="Carregador Turbo",
            ean="7899991110007",
            preco_final=Decimal("75.00"),
            preco=Decimal("75.00"),
            quantidade=4,
            ponto_operacional=ponto,
            ativo=True,
        )
        VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("75.00"),
            valor_total=Decimal("75.00"),
            funcionario_numero="12",
            cesto_codigo="CES-CLI-01",
            guia_pagamento="GUIA-CLI-01",
            status="pre_reserva",
            usuario=self.atendente,
        )

        response = self.client.get(reverse("caixa:registrar_pagamento") + "?guia=GUIA-CLI-01")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Identificacao opcional do comprador")
        self.assertContains(response, "CPF/CNPJ")
        self.assertContains(response, "Telefone/WhatsApp")
        self.assertContains(response, "Pagamento misto opcional")

    def test_finalizar_guia_persiste_identificacao_do_comprador(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO3", nome="Loja")
        produto = Produto.objects.create(
            nome="Display A13",
            ean="7899991110008",
            preco_final=Decimal("120.00"),
            preco=Decimal("120.00"),
            quantidade=5,
            ponto_operacional=ponto,
            ativo=True,
        )
        VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            valor_total=Decimal("120.00"),
            funcionario_numero="12",
            cesto_codigo="CES-CLI-02",
            guia_pagamento="GUIA-CLI-02",
            status="pre_reserva",
            usuario=self.atendente,
        )
        forma = FormaPagamento.objects.create(nome="Pix balcÃ£o", codigo="pix_balcao", tipo="avista", ativa=True)

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + "?guia=GUIA-CLI-02",
            {
                "valor": "120.00",
                "forma_pagamento": str(forma.id),
                "referencia": "GUIA-CLI-02-PG",
                "cliente_nome": "Marina Souza",
                "cliente_documento": "12345678900",
                "cliente_telefone": "62999998888",
                "chave_idempotencia": "guia-cliente-opcional-01",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        pagamento = Pagamento.objects.get(chave_idempotencia="guia-cliente-opcional-01")
        self.assertEqual(pagamento.cliente_nome, "Marina Souza")
        self.assertEqual(pagamento.cliente_documento, "12345678900")
        self.assertEqual(pagamento.cliente_telefone, "62999998888")

    def test_finalizar_guia_persiste_composicao_pagamento_misto(self):
        self.client.force_login(self.atendente)
        ponto = PontoOperacional.objects.create(codigo="PO3M", nome="Loja Mista")
        produto = Produto.objects.create(
            nome="Bateria Premium",
            ean="7899991110108",
            preco_final=Decimal("120.00"),
            preco=Decimal("120.00"),
            quantidade=5,
            ponto_operacional=ponto,
            ativo=True,
        )
        SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=5)
        VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            valor_total=Decimal("120.00"),
            funcionario_numero="12",
            cesto_codigo="CES-MISTO-01",
            guia_pagamento="GUIA-MISTO-01",
            status="pre_reserva",
            usuario=self.atendente,
        )
        forma_pix = FormaPagamento.objects.create(nome="PIX misto", codigo="pix_misto", tipo="avista", ativa=True)
        forma_dinheiro, _ = FormaPagamento.objects.get_or_create(
            codigo="dinheiro",
            defaults={"nome": "Dinheiro", "tipo": "avista", "ativa": True},
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + "?guia=GUIA-MISTO-01",
            {
                "valor": "120.00",
                "forma_pagamento": str(forma_pix.id),
                "referencia": "PIX-120",
                "forma_pagamento_secundaria": str(forma_dinheiro.id),
                "valor_secundario": "20.00",
                "referencia_secundaria": "TROCO-20",
                "valor_recebido": "20.00",
                "cliente_nome": "Lucas Misto",
                "chave_idempotencia": "guia-pagamento-misto-01",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        pagamento = Pagamento.objects.get(chave_idempotencia="guia-pagamento-misto-01")
        self.assertEqual(len(pagamento.formas_pagamento_compostas), 2)
        self.assertEqual(pagamento.formas_pagamento_compostas[0]["forma_codigo"], "pix_misto")
        self.assertEqual(pagamento.formas_pagamento_compostas[1]["forma_codigo"], "dinheiro")
        self.assertContains(
            self.client.get(reverse("caixa:imprimir_talao", args=[pagamento.id])),
            "Composicao",
        )

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
        self.ordem.relatorio_tecnico = "Diagnostico e execucao concluidos."
        self.ordem.save(update_fields=["relatorio_tecnico"])
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
        self.ordem.relatorio_tecnico = "Servico concluido e pronto para conferencia."
        self.ordem.save(update_fields=["fechada", "relatorio_tecnico"])
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
        self.ordem.relatorio_tecnico = "Pagamento confirmado com servico tecnicamente concluido."
        self.ordem.save(update_fields=["relatorio_tecnico"])
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
        self.ordem.relatorio_tecnico = "Entrega concluida com laudo tecnico."
        self.ordem.save(update_fields=["status", "relatorio_tecnico"])
        response2 = self.client.post(reverse("caixa:comissoes_tecnicos"), {"action": "recalcular_itens_antecipado"})
        self.assertEqual(response2.status_code, 302)
        self.assertTrue(ComissaoItemOrcamento.objects.filter(item_orcamento=item).exists())

    def test_comissao_item_pronto_contactar_nao_qualifica_motor_novo(self):
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
        self.assertFalse(ComissaoItemOrcamento.objects.filter(item_orcamento=item).exists())

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

    def test_motor_novo_nao_gera_sem_item_orcamento_aprovado(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_sem_item_aprovado",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("12.00"),
        )
        self.ordem.relatorio_tecnico = "Relatorio valido"
        self.ordem.tipo_reparacao = "substituicao"
        self.ordem.save(update_fields=["relatorio_tecnico", "tipo_reparacao"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico pendente",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="pendente",
        )

        criadas = processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO")
        self.assertEqual(criadas, 0)
        self.assertFalse(Comissao.objects.filter(item_orcamento=item).exists())

    def test_motor_novo_nao_gera_quando_tipo_reparacao_e_nada_efetuado(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_nada_efetuado",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("12.00"),
        )
        self.ordem.relatorio_tecnico = "Equipamento sem reparo"
        self.ordem.tipo_reparacao = "nada"
        self.ordem.save(update_fields=["relatorio_tecnico", "tipo_reparacao"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico nada efetuado",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )

        criadas = processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO")
        self.assertEqual(criadas, 0)
        self.assertFalse(Comissao.objects.filter(item_orcamento=item).exists())

    def test_motor_novo_nao_gera_quando_tipo_reparacao_e_recusado_preco(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_recusado_preco",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("12.00"),
        )
        self.ordem.relatorio_tecnico = "Cliente recusou o valor"
        self.ordem.tipo_reparacao = "recusado_preco"
        self.ordem.status = "recusado"
        self.ordem.save(update_fields=["relatorio_tecnico", "tipo_reparacao", "status"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico recusado por preco",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )

        criadas = processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO")
        self.assertEqual(criadas, 0)
        self.assertFalse(Comissao.objects.filter(item_orcamento=item).exists())

    def test_motor_novo_gera_comissao_servico_e_eh_idempotente(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_servico",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("15.00"),
        )
        self.ordem.relatorio_tecnico = "Relatorio aprovado"
        self.ordem.tipo_reparacao = "substituicao"
        self.ordem.save(update_fields=["relatorio_tecnico", "tipo_reparacao"])
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

    def test_motor_novo_bloqueia_duplicidade_por_assinatura_com_evento_diferente(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_motor_novo_assinatura",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("15.00"),
        )
        self.ordem.relatorio_tecnico = "Relatorio para assinatura"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico assinatura",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("180.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        primeira = Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").first()
        self.assertIsNotNone(primeira)
        self.assertEqual(primeira.fonte_referencia, f"item:{item.id}")

        criadas = processar_evento_servico_finalizado(self.ordem, evento="SERVICO_FINALIZADO_REPROCESSADO")
        self.assertEqual(criadas, 0)
        total = Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").count()
        self.assertEqual(total, 1)

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
            item_orcamento=ItemOrcamento.objects.create(
                orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
                nome="Servico tipo filtro",
                descricao="Base aprovada",
                quantidade=1,
                valor_unitario=Decimal("100.00"),
                origem="manual",
                tipo_item="servico",
                tecnico_responsavel=tecnico,
                status="aprovado",
            ),
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

    def test_motor_novo_gera_comissao_peca_sem_bonus_produto_na_os(self):
        config = ConfiguracaoSistema.get_configuracao()
        config.comissao_aplicar_pecas = True
        config.save(update_fields=["comissao_aplicar_pecas"])
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
        self.assertNotIn("BONUS_PRODUTO", tipos)

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
        config = ConfiguracaoSistema.get_configuracao()
        config.comissao_aplicar_pecas = True
        config.save(update_fields=["comissao_aplicar_pecas"])
        tecnico = get_user_model().objects.create_user(
            username="tecnico_fontes_mistas",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("10.00"),
            percentual_comissao_peca=Decimal("5.00"),
        )
        self.ordem.relatorio_tecnico = "Relatorio preenchido"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item_servico = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="MÃ£o de obra",
            descricao="Servico tÃ©cnico",
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
            descricao="Comissao jÃ¡ paga",
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
            descricao="TransiÃ§Ã£o de status",
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

    def test_comissoes_tecnicos_liberar_lote_aplica_em_varios_itens(self):
        self.client.force_login(self.gerente)
        c1 = Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Lote liberar 1",
            valor_base=Decimal("100.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica=f"SERVICO_FINALIZADO:SERVICO:os:{self.ordem.id}:lote-liberar-1",
        )
        c2 = Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="PECA",
            descricao="Lote liberar 2",
            valor_base=Decimal("80.00"),
            percentual=Decimal("5.00"),
            valor_comissao=Decimal("4.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica=f"SERVICO_FINALIZADO:PECA:os:{self.ordem.id}:lote-liberar-2",
        )
        response = self.client.post(
            reverse("caixa:comissoes_tecnicos"),
            {
                "action": "liberar_lote",
                "comissao_ids": [str(c1.id), str(c2.id)],
                "return_query": "status=GERADA",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("status=GERADA", response.url)
        c1.refresh_from_db()
        c2.refresh_from_db()
        self.assertEqual(c1.status, "LIBERADA")
        self.assertEqual(c2.status, "LIBERADA")
        self.assertIsNotNone(c1.data_liberacao)
        self.assertIsNotNone(c2.data_liberacao)

    def test_comissoes_tecnicos_pagar_lote_respeita_status_e_referencia(self):
        self.client.force_login(self.gerente)
        c1 = Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Lote pagar 1",
            valor_base=Decimal("120.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("12.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica=f"SERVICO_FINALIZADO:SERVICO:os:{self.ordem.id}:lote-pagar-1",
        )
        c2 = Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Lote pagar 2 bloqueada",
            valor_base=Decimal("50.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("5.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="CANCELADA",
            chave_unica=f"SERVICO_FINALIZADO:SERVICO:os:{self.ordem.id}:lote-pagar-2",
        )
        response = self.client.post(
            reverse("caixa:comissoes_tecnicos"),
            {
                "action": "pagar_lote",
                "comissao_ids": [str(c1.id), str(c2.id)],
                "referencia_pagamento_lote": "LOTE-PIX-001",
            },
        )
        self.assertEqual(response.status_code, 302)
        c1.refresh_from_db()
        c2.refresh_from_db()
        self.assertEqual(c1.status, "PAGA")
        self.assertEqual(c1.referencia_pagamento, "LOTE-PIX-001")
        self.assertIsNotNone(c1.data_pagamento)
        self.assertEqual(c2.status, "CANCELADA")

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
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("auditar_comissoes", falhar_se_divergir=True, stdout=out)

    def test_auditar_comissoes_ok_quando_fontes_sao_validas(self):
        self.ordem.relatorio_tecnico = "Relatorio de execuÃ§Ã£o"
        self.ordem.save(update_fields=["relatorio_tecnico"])
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico vÃ¡lido",
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
            cliente_nome="Renata Lima",
            cliente_documento="98765432100",
            cliente_telefone="62988887777",
            observacao="Apresente este comprovante no retorno.",
        )

        response_list = self.client.get(reverse("caixa:taloes"), {"q": pagamento.numero_talao})
        self.assertEqual(response_list.status_code, 200)
        self.assertContains(response_list, pagamento.numero_talao)

        response_print = self.client.get(reverse("caixa:imprimir_talao", args=[pagamento.id]))
        self.assertEqual(response_print.status_code, 200)
        self.assertContains(response_print, pagamento.numero_talao)
        self.assertContains(response_print, "Renata Lima")
        self.assertContains(response_print, "98765432100")
        self.assertContains(response_print, "62988887777")
        self.assertContains(response_print, "Mensagem adicional")
        self.assertContains(response_print, "Apresente este comprovante no retorno.")

    def test_meu_desempenho_disponivel_para_tecnico(self):
        self.client.force_login(self.tecnico)
        response = self.client.get(reverse("caixa:meu_desempenho"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Meu desempenho")

    def test_meu_desempenho_restaurar_ultimos_filtros(self):
        self.client.force_login(self.gerente)
        self.client.get(
            reverse("caixa:meu_desempenho"),
            {"tecnico": str(self.tecnico.id), "criterio": "retirado_pago", "data_inicio": timezone.localdate().isoformat(), "data_fim": timezone.localdate().isoformat()},
        )
        response = self.client.get(reverse("caixa:meu_desempenho"), {"restaurar": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"tecnico={self.tecnico.id}", response.url)
        self.assertIn("criterio=retirado_pago", response.url)

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
        OrdemServico.objects.filter(id=self.ordem.id).update(
            data_abertura=timezone.now() - timedelta(days=10),
            data_conclusao=timezone.now() - timedelta(days=10),
        )

        self.client.force_login(self.tecnico)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(reverse("caixa:meu_desempenho"), {"data_inicio": hoje, "data_fim": hoje})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Item comissao data")

    def test_meu_desempenho_filtra_por_criterio_pronto_reparado(self):
        ordem_retirada = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="notebook",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo pago",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="concluida",
            fechada=True,
        )
        pagamento = Pagamento.objects.create(
            caixa=Caixa.objects.filter(aberto=True).first(),
            ordem_servico=ordem_retirada,
            valor=Decimal("150.00"),
            metodo="pix",
        )
        self.assertIsNotNone(pagamento.id)

        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Servico pronto",
            valor_base=Decimal("100.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:pronto-1",
        )
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=ordem_retirada,
            tipo="SERVICO",
            descricao="Servico retirado",
            valor_base=Decimal("150.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("15.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:retirada-1",
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "tecnico": str(self.tecnico.id),
                "data_inicio": hoje,
                "data_fim": hoje,
                "criterio": "pronto_reparado",
            },
        )
        self.assertEqual(response.status_code, 200)
        referencias = [row["referencia"] for row in response.context["linhas_realizadas"]]
        self.assertIn(self.ordem.numero_os, referencias)
        self.assertNotIn(ordem_retirada.numero_os, referencias)

    def test_meu_desempenho_separa_comissoes_por_tipo(self):
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="SERVICO",
            descricao="Troca de display",
            valor_base=Decimal("120.00"),
            percentual=Decimal("10.00"),
            valor_comissao=Decimal("12.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica="SERVICO_FINALIZADO:SERVICO:item:sep-1",
        )
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="PECA",
            descricao="Peca aplicada",
            valor_base=Decimal("80.00"),
            percentual=Decimal("5.00"),
            valor_comissao=Decimal("4.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica="SERVICO_FINALIZADO:PECA:item:sep-2",
        )
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="BONUS_SERVICO",
            descricao="Bonus tecnico",
            valor_base=Decimal("0.00"),
            percentual=Decimal("0.00"),
            valor_comissao=Decimal("7.00"),
            evento_gerador="SERVICO_FINALIZADO",
            status="GERADA",
            chave_unica="SERVICO_FINALIZADO:BONUS_SERVICO:item:sep-3",
        )
        Comissao.objects.create(
            tecnico=self.tecnico,
            tipo="COMISSAO_VENDAS",
            descricao="Venda de mostrador",
            valor_base=Decimal("200.00"),
            percentual=Decimal("6.00"),
            valor_comissao=Decimal("12.00"),
            evento_gerador="VENDA_MOSTRADOR",
            status="GERADA",
            chave_unica="VENDA_MOSTRADOR:COMISSAO_VENDAS:venda:sep-4",
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {"tecnico": str(self.tecnico.id), "data_inicio": hoje, "data_fim": hoje},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vendas")
        self.assertContains(response, "Vendas")
        self.assertEqual(response.context["resumo_por_tipo_real"]["servicos"], Decimal("12.00"))
        self.assertEqual(response.context["resumo_por_tipo_real"]["pecas"], Decimal("4.00"))
        self.assertEqual(response.context["resumo_por_tipo_real"]["bonus"], Decimal("7.00"))
        self.assertEqual(response.context["resumo_por_tipo_real"]["vendas"], Decimal("12.00"))
        self.assertEqual(len(response.context["linhas_realizadas_por_tipo"]["servicos"]), 1)
        self.assertEqual(len(response.context["linhas_realizadas_por_tipo"]["pecas"]), 1)
        self.assertEqual(len(response.context["linhas_realizadas_por_tipo"]["bonus"]), 1)
        self.assertEqual(len(response.context["linhas_realizadas_por_tipo"]["vendas"]), 1)

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
        self.ordem.relatorio_tecnico = "Execucao concluida para filtro por tecnico."
        self.ordem.save(update_fields=["relatorio_tecnico"])

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
        self.ordem.relatorio_tecnico = "Execucao concluida para uso do periodo padrao."
        self.ordem.save(update_fields=["relatorio_tecnico"])

        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:meu_desempenho"), {"tecnico": str(self.tecnico.id)})
        self.assertEqual(response.status_code, 200)
        hoje = timezone.localdate()
        inicio_mes = hoje.replace(day=1).isoformat()
        fim_mes = date(hoje.year, hoje.month, monthrange(hoje.year, hoje.month)[1]).isoformat()
        self.assertEqual(response.context["data_inicio"], inicio_mes)
        self.assertEqual(response.context["data_fim"], fim_mes)
        self.assertTrue(response.context.get("ordens_relatorio", []))

    def test_meu_desempenho_exibe_checkbox_para_calcular_pecas(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:meu_desempenho"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="aplicar_pecas"')
        self.assertContains(response, 'type="checkbox"')

    def test_meu_desempenho_separa_folha_por_tipo_de_comissao(self):
        ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Servico folha",
            descricao="Teste servico",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Peca folha",
            descricao="Teste peca",
            quantidade=1,
            valor_unitario=Decimal("50.00"),
            origem="manual",
            tipo_item="peca",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        self.ordem.relatorio_tecnico = "Execucao concluida para separar folha por tipo."
        self.ordem.save(update_fields=["relatorio_tecnico"])
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="COMISSAO_VENDAS",
            descricao="Venda folha",
            valor_base=Decimal("200.00"),
            percentual=Decimal("5.00"),
            valor_comissao=Decimal("10.00"),
            evento_gerador="VENDA_MOSTRADOR",
            status="GERADA",
            chave_unica="VENDA_MOSTRADOR:COMISSAO_VENDAS:folha-sep-1",
        )
        Comissao.objects.create(
            tecnico=self.tecnico,
            ordem_servico=self.ordem,
            tipo="BONUS_PRODUTO",
            descricao="Bonus folha",
            valor_base=Decimal("0.00"),
            percentual=Decimal("0.00"),
            valor_comissao=Decimal("4.00"),
            evento_gerador="VENDA_MOSTRADOR",
            status="GERADA",
            chave_unica="VENDA_MOSTRADOR:BONUS_PRODUTO:folha-sep-2",
        )

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "tecnico": str(self.tecnico.id),
                "data_inicio": hoje,
                "data_fim": hoje,
                "percentual_servicos": "10",
                "percentual_pecas": "5",
                "aplicar_servicos": "1",
                "aplicar_pecas": "1",
                "aplicar_vendas": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        folhas = response.context.get("folhas_colaboradores", [])
        self.assertTrue(folhas)
        folha = next((row for row in folhas if row["tecnico"].id == self.tecnico.id), None)
        self.assertIsNotNone(folha)
        self.assertTrue(folha["servicos"]["linhas"])
        self.assertTrue(folha["pecas"]["linhas"])
        self.assertTrue(folha["vendas"]["linhas"])
        self.assertTrue(folha["bonus"]["linhas"])
        self.assertEqual(len(folha["secoes"]), 4)

    def test_meu_desempenho_checkbox_pecas_desmarcado_nao_calcula_pecas(self):
        ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Servico base checkbox",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Peca base checkbox",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("70.00"),
            origem="manual",
            tipo_item="peca",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        self.ordem.relatorio_tecnico = "Execucao pronta para validar servico sem pecas."
        self.ordem.save(update_fields=["relatorio_tecnico"])

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "tecnico": str(self.tecnico.id),
                "data_inicio": hoje,
                "data_fim": hoje,
                "percentual_servicos": "10",
                "percentual_pecas": "5",
                "aplicar_servicos": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["aplicar_pecas"])
        self.assertEqual(response.context["total_comissao_pecas_relatorio"], Decimal("0.00"))
        folhas = response.context.get("folhas_colaboradores", [])
        folha = next((row for row in folhas if row["tecnico"].id == self.tecnico.id), None)
        self.assertIsNotNone(folha)
        self.assertEqual(folha["pecas"]["linhas"], [])

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
        self.ordem.relatorio_tecnico = "Execucao concluida pelo tecnico do item."
        self.ordem.save(update_fields=["tecnico_responsavel", "relatorio_tecnico"])

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
        self.ordem.relatorio_tecnico = "Execucao concluida para percentuais padrao."
        self.ordem.save(update_fields=["relatorio_tecnico"])

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
        self.ordem.relatorio_tecnico = "Execucao concluida para recalculo de comissao."
        self.ordem.save(update_fields=["relatorio_tecnico"])

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

    def test_meu_desempenho_nao_reapresenta_fonte_ja_paga(self):
        self.tecnico.percentual_comissao_servico = Decimal("10.00")
        self.tecnico.save(update_fields=["percentual_comissao_servico"])
        self.ordem.relatorio_tecnico = "Relatorio para evitar duplicidade"
        self.ordem.status = "pronto_contactado"
        self.ordem.save(update_fields=["relatorio_tecnico", "status"])
        item = ItemOrcamento.objects.create(
            orcamento=Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem),
            nome="Servico ja pago",
            descricao="Teste",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        chave = f"SERVICO_FINALIZADO:SERVICO:item:{item.id}"
        comissao = Comissao.objects.filter(chave_unica=chave).first()
        self.assertIsNotNone(comissao)
        aplicar_acao_comissao(comissao, acao="pagar", usuario=self.gerente, referencia_pagamento="PAGO-1")

        self.client.force_login(self.gerente)
        hoje = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "tecnico": str(self.tecnico.id),
                "data_inicio": hoje,
                "data_fim": hoje,
                "percentual_servicos": "10",
                "aplicar_servicos": "1",
                "aplicar_pecas": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        folhas = response.context.get("folhas_colaboradores", [])
        linhas = []
        for folha in folhas:
            if folha["tecnico"].id == self.tecnico.id:
                linhas.extend(folha["linhas"])
        self.assertFalse(any(linha["descricao"] == "Servico ja pago" for linha in linhas))

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
        self.ordem.relatorio_tecnico = "Execucao concluida para excluir canceladas."
        self.ordem.save(update_fields=["relatorio_tecnico"])
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
            tipo_reparacao="substituicao",
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

    def test_meu_desempenho_modo_finalizados_nao_inclui_autorizado(self):
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
        numeros = {row["numero_os"] for row in ordens_relatorio}
        self.assertNotIn(self.ordem.numero_os, numeros)

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
        config.comissao_bonus_retirada_ativo = True
        config.dias_bonus_retirada_1 = 1
        config.valor_bonus_1 = Decimal("10.00")
        config.dias_bonus_retirada_2 = 3
        config.valor_bonus_2 = Decimal("5.00")
        config.dias_bonus_retirada_3 = 7
        config.valor_bonus_3 = Decimal("2.00")
        config.save(
            update_fields=[
                "comissao_bonus_retirada_ativo",
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

    def test_registrar_pagamento_exibe_resumo_financeiro_da_os(self):
        self.client.force_login(self.atendente)
        self.ordem.tecnico_responsavel = self.tecnico
        self.ordem.save(update_fields=["tecnico_responsavel"])
        LinhaTrabalho.objects.create(
            ordem=self.ordem,
            usuario=self.atendente,
            status="criada",
            descricao="Ordem criada",
            tipo_evento="manual",
        )
        Pagamento.objects.create(
            caixa=Caixa.objects.filter(aberto=True).first(),
            ordem_servico=self.ordem,
            valor=Decimal("40.00"),
            metodo="pix",
        )
        response = self.client.get(reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ordem_total_os"], Decimal("100.00"))
        self.assertEqual(response.context["ordem_total_pago"], Decimal("40.00"))
        self.assertEqual(response.context["ordem_valor_aberto"], Decimal("60.00"))
        self.assertContains(response, "Saldo aberto")
        self.assertContains(response, "Pronto contactado")
        self.assertContains(response, "Atendente:")
        self.assertContains(response, self.atendente.username)
        self.assertContains(response, "T&eacute;cnico respons&aacute;vel:")
        self.assertContains(response, self.tecnico.username)
        self.assertContains(response, "Receber saldo total")
        self.assertContains(response, "Pagamento parcial")
        self.assertContains(response, "Como o cliente pagou?")
        self.assertContains(response, "Receber e concluir")
        self.assertContains(response, "Mais op&ccedil;&otilde;es")
        self.assertContains(response, 'data-atalho="opcoes"')
        self.assertContains(response, 'id="pdv-operacao-principal"')
        self.assertContains(response, 'id="pdv-forma-atual"')
        self.assertContains(response, 'id="pdv-opcoes-drawer"')
        self.assertContains(response, 'id="opcao-outras-formas"')
        self.assertContains(response, 'id="opcao-pagamento-misto"')
        self.assertContains(response, 'id="opcao-desconto"')
        self.assertContains(response, ">Dinheiro</button>")
        self.assertContains(response, ">PIX</button>")
        self.assertNotContains(response, ">Custo da Loja</button>")
        self.assertNotContains(response, ">Garantia Fabricante</button>")
        self.assertNotContains(response, "Valores r&aacute;pidos")

    def test_registrar_pagamento_sem_origem_inicia_como_avulso(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("caixa:registrar_pagamento"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="pdv-aguardando-origem"')
        self.assertContains(response, 'id="pdv-operacao-principal"')
        self.assertNotContains(response, 'id="pdv-operacao-principal" class="d-none"')
        self.assertContains(response, "Avulso ativo")
        self.assertContains(response, 'id="id_guia_codigo_busca"')
        self.assertContains(response, "Origem do recebimento (opcional)")
        self.assertContains(response, 'aria-keyshortcuts="Alt+1"')
        self.assertContains(response, 'aria-keyshortcuts="Alt+Enter"')
        self.assertContains(response, "event.altKey")

    def test_registrar_pagamento_avulso_sem_validar_os(self):
        self.client.force_login(self.atendente)

        response = self.client.post(
            reverse("caixa:registrar_pagamento"),
            {
                "valor": "35.00",
                "metodo": "pix",
                "referencia": "AVULSO-SEM-OS",
                "chave_idempotencia": "avulso-sem-os-1",
            },
        )

        self.assertEqual(response.status_code, 302)
        pagamento = Pagamento.objects.get(chave_idempotencia="avulso-sem-os-1")
        self.assertIsNone(pagamento.ordem_servico_id)
        self.assertIsNone(pagamento.stock_item_id)
        self.assertEqual(pagamento.valor, Decimal("35.00"))

    def test_registrar_pagamento_em_dinheiro_valida_valor_recebido(self):
        self.client.force_login(self.atendente)
        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}",
            {
                "valor": "100.00",
                "metodo": "dinheiro",
                "referencia": "DIN-001",
                "valor_recebido": "90.00",
                "chave_idempotencia": "token-dinheiro-1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "valor recebido")
        self.assertFalse(Pagamento.objects.filter(referencia="DIN-001").exists())

    def test_registrar_pagamento_nao_duplica_com_mesma_chave_idempotencia(self):
        self.client.force_login(self.atendente)
        payload = {
            "valor": "100.00",
            "metodo": "pix",
            "referencia": "IDEMP-001",
            "chave_idempotencia": "token-idempotencia-1",
        }
        response_1 = self.client.post(reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}", payload)
        response_2 = self.client.post(reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}", payload)

        self.assertEqual(response_1.status_code, 302)
        self.assertEqual(response_2.status_code, 302)
        self.assertEqual(Pagamento.objects.filter(referencia="IDEMP-001").count(), 1)

    def test_registrar_pagamento_exibe_acoes_pos_pagamento(self):
        self.client.force_login(self.gerente)
        pagamento = Pagamento.objects.create(
            caixa=Caixa.objects.filter(aberto=True).first(),
            ordem_servico=self.ordem,
            valor=Decimal("40.00"),
            metodo="pix",
        )
        response = self.client.get(reverse("caixa:registrar_pagamento") + f"?sucesso={pagamento.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Imprimir cupom")
        self.assertContains(response, reverse("caixa:imprimir_talao", args=[pagamento.id]))
        self.assertContains(response, "Emitir documento fiscal")
        self.assertContains(response, pagamento.numero_talao)

    def test_registrar_pagamento_exibe_fluxo_entrega_para_os_quitada(self):
        self.client.force_login(self.gerente)
        self.ordem.fechada = True
        self.ordem.status = "concluida"
        self.ordem.save(update_fields=["fechada", "status"])
        total_os = self.ordem.receita_total_financeira()
        pagamento = Pagamento.objects.create(
            caixa=Caixa.objects.filter(aberto=True).first(),
            ordem_servico=self.ordem,
            valor=total_os,
            metodo="pix",
        )

        response = self.client.get(reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}&sucesso={pagamento.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OS quitada e liberada para entrega ao cliente")
        self.assertContains(response, "Voltar para a OS")

    def test_registrar_pagamento_bloqueia_garantia_fabricante_fora_de_ordem_em_garantia(self):
        self.client.force_login(self.atendente)
        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}",
            {
                "valor": "100.00",
                "metodo": "garantia_fabricante",
                "referencia": "GAR-FORA-001",
                "chave_idempotencia": "token-garantia-fora-1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "permitido apenas para ordens em garantia")
        self.assertFalse(Pagamento.objects.filter(referencia="GAR-FORA-001").exists())

    def test_registrar_pagamento_permite_parcela_do_cliente_em_ordem_de_garantia(self):
        fornecedor = FornecedorGarantia.objects.create(nome="Fabricante Obrigatorio")
        MarcaGarantia.objects.create(
            nome="Marca Obrigatoria",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("180.00"),
            parceira_garantia=True,
            ativo=True,
        )
        ordem_garantia = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Obrigatoria",
            modelo_equipamento="Modelo G",
            defeito="Teste garantia",
            tipo_reparo="Garantia",
            status="diagnosticar",
        )

        self.client.force_login(self.atendente)
        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={ordem_garantia.id}",
            {
                "valor": "100.00",
                "metodo": "pix",
                "referencia": "GAR-OBR-001",
                "chave_idempotencia": "token-garantia-obr-1",
            },
        )
        self.assertEqual(response.status_code, 302)
        pagamento = Pagamento.objects.get(referencia="GAR-OBR-001")
        self.assertEqual(pagamento.ordem_servico, ordem_garantia)
        self.assertEqual(pagamento.valor, Decimal("100.00"))
        self.assertNotEqual(pagamento.metodo, "garantia_fabricante")

    def test_excluir_pagamento_exige_justificativa_e_reverte_conta(self):
        self.client.force_login(self.gerente)
        response_pagamento = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}",
            {
                "valor": "100.00",
                "metodo": "pix",
                "referencia": "EXC-001",
                "chave_idempotencia": "token-excluir-1",
            },
        )
        self.assertEqual(response_pagamento.status_code, 302)
        pagamento = Pagamento.objects.get(referencia="EXC-001")
        conta = ContaReceber.objects.get(ordem_servico=self.ordem, tipo_origem="cliente_os")
        self.assertEqual(conta.status, "paga")
        detalhe_conta = self.client.get(reverse("caixa:detalhe_conta_receber", args=[conta.id]))
        self.assertContains(detalhe_conta, "Estornar")

        response_sem_justificativa = self.client.post(
            reverse("caixa:excluir_pagamento", args=[pagamento.id]),
            {"justificativa": ""},
        )
        self.assertEqual(response_sem_justificativa.status_code, 200)
        self.assertTrue(Pagamento.objects.filter(id=pagamento.id).exists())

        response_excluir = self.client.post(
            reverse("caixa:excluir_pagamento", args=[pagamento.id]),
            {
                "justificativa": "Pagamento lanÃ§ado em duplicidade no balcÃ£o.",
                "next": reverse("caixa:detalhe_conta_receber", args=[conta.id]),
            },
        )
        self.assertEqual(response_excluir.status_code, 302)
        self.assertEqual(response_excluir.url, reverse("caixa:detalhe_conta_receber", args=[conta.id]))
        self.assertFalse(Pagamento.objects.filter(id=pagamento.id).exists())
        conta.refresh_from_db()
        self.assertEqual(conta.status, "aberta")
        self.assertEqual(conta.valor_aberto, Decimal("100.00"))

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

    def test_pagamento_garantia_fabricante_bloqueado_quando_regra_tem_valor_zero(self):
        self.client.force_login(self.atendente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fabricante Zero")
        marca = MarcaGarantia.objects.create(
            nome="Marca Zero",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("0.00"),
            parceira_garantia=True,
            ativo=True,
        )
        ordem_garantia = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca Zero",
            marca_garantia=marca,
            modelo_equipamento="Modelo Zero",
            defeito="Sem imagem",
            tipo_reparo="Garantia",
            status="diagnosticar",
        )
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("0.00"),
            valor_mao_obra_tecnico=Decimal("0.00"),
            modalidade_pagamento="pix",
            prazo_pagamento_dias=30,
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={ordem_garantia.id}",
            {"valor": "90.00", "metodo": "garantia_fabricante", "referencia": "GAR-ZERO"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "valor de mao de obra maior que zero")
        self.assertFalse(Pagamento.objects.filter(referencia="GAR-ZERO").exists())

    def test_conta_garantia_fabricante_fica_identificada_com_marca_fornecedor_e_empresa(self):
        empresa = Empresa.objects.create(nome="Empresa Garantia")
        self.atendente.empresa = empresa
        self.atendente.save(update_fields=["empresa"])
        Caixa.objects.create(empresa=empresa, aberto=True, saldo_inicial=0)
        self.client.force_login(self.atendente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fabricante Conta Nome")
        marca = MarcaGarantia.objects.create(
            nome="Marca Conta Nome",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("150.00"),
            parceira_garantia=True,
            ativo=True,
        )
        ordem_garantia = OrdemServico.objects.create(
            cliente=self.cliente,
            empresa=empresa,
            tipo_equipamento="celular",
            marca_equipamento="Marca Conta Nome",
            marca_garantia=marca,
            modelo_equipamento="Modelo Conta",
            defeito="Nao liga",
            tipo_reparo="Garantia",
            status="concluida",
            fechada=True,
        )
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("150.00"),
            valor_mao_obra_tecnico=Decimal("0.00"),
            modalidade_pagamento="pix",
            prazo_pagamento_dias=30,
        )

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={ordem_garantia.id}",
            {"valor": "150.00", "metodo": "garantia_fabricante", "referencia": "GAR-CONTA-ID"},
        )
        self.assertEqual(response.status_code, 302)
        conta = ContaReceber.objects.filter(ordem_servico=ordem_garantia, tipo_origem="garantia_fabricante").first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.empresa, empresa)
        self.assertEqual(conta.cliente_nome, "Fabricante Conta Nome")
        self.assertIn("Fabricante Conta Nome", conta.descricao)
        self.assertEqual(conta.fornecedor_garantia, fornecedor)
        self.assertEqual(conta.marca_garantia, marca)
        self.assertIsNotNone(conta.regra_garantia)
        self.assertEqual(conta.valor_aprovado_garantia, Decimal("150.00"))
        self.assertEqual(conta.prazo_pagamento_dias, 30)
        self.assertIsNotNone(conta.data_base_cobranca)

    def test_relatorio_garantias_fabricante_disponivel_para_gerente(self):
        self.client.force_login(self.gerente)
        fornecedor = FornecedorGarantia.objects.create(
            nome="Fornecedor Rel",
            email_cobranca="financeiro@rel.com",
            portal_garantia_url="https://portal.rel.com",
            documentos_exigidos="NF e laudo",
            procedimento_cobranca="Abrir portal e anexar a OS.",
        )
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
        self.assertContains(response, "financeiro@rel.com")
        self.assertContains(response, "NF e laudo")
        self.assertContains(response, "Abrir portal e anexar a OS.")

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
        response = self.client.post(
            reverse("caixa:garantias_fabricante"),
            {
                "auditoria_id": auditoria.id,
                "status_faturamento": "pago",
                "valor_aprovado_fabricante": "125.00",
                "valor_recebido_fabricante": "125.00",
                "referencia_faturamento": "FAT-BAIXA-001",
                "observacoes": "Pago no fechamento mensal",
            },
        )
        self.assertEqual(response.status_code, 302)
        auditoria.refresh_from_db()
        conta = ContaReceber.objects.filter(ordem_servico=ordem, descricao__icontains="Garantia fabricante").first()
        self.assertIsNotNone(conta)
        self.assertEqual(conta.status, "paga")
        self.assertEqual(str(conta.valor_aberto), "0.00")
        self.assertEqual(conta.valor_aprovado_garantia, Decimal("125.00"))
        self.assertEqual(conta.fornecedor_garantia, fornecedor)
        self.assertEqual(conta.marca_garantia, marca)
        self.assertEqual(conta.referencia_cobranca, "FAT-BAIXA-001")
        self.assertEqual(auditoria.conta_receber, conta)
        self.assertEqual(auditoria.valor_aprovado_fabricante, Decimal("125.00"))
        self.assertEqual(auditoria.valor_recebido_fabricante, Decimal("125.00"))
        self.assertEqual(RecebimentoConta.objects.filter(conta=conta).aggregate(total=Sum("valor"))["total"], Decimal("125.00"))

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
        self.assertIn("Valor Aprovado", conteudo)
        self.assertIn("Valor Recebido", conteudo)

    def test_contas_receber_filtra_garantia_por_marca_e_fornecedor(self):
        self.client.force_login(self.gerente)
        fornecedor_a = FornecedorGarantia.objects.create(nome="Fornecedor A")
        fornecedor_b = FornecedorGarantia.objects.create(nome="Fornecedor B")
        marca_a = MarcaGarantia.objects.create(nome="Marca A", fornecedor=fornecedor_a, parceira_garantia=True, ativo=True)
        marca_b = MarcaGarantia.objects.create(nome="Marca B", fornecedor=fornecedor_b, parceira_garantia=True, ativo=True)
        ContaReceber.objects.create(
            descricao="Garantia A",
            tipo_origem="garantia_fabricante",
            cliente_nome="Fornecedor A",
            fornecedor_garantia=fornecedor_a,
            marca_garantia=marca_a,
            valor_original=Decimal("100.00"),
            valor_aberto=Decimal("100.00"),
            valor_aprovado_garantia=Decimal("90.00"),
            vencimento=timezone.localdate() + timedelta(days=10),
            status="aberta",
        )
        ContaReceber.objects.create(
            descricao="Garantia B",
            tipo_origem="garantia_fabricante",
            cliente_nome="Fornecedor B",
            fornecedor_garantia=fornecedor_b,
            marca_garantia=marca_b,
            valor_original=Decimal("140.00"),
            valor_aberto=Decimal("140.00"),
            valor_aprovado_garantia=Decimal("140.00"),
            vencimento=timezone.localdate() + timedelta(days=15),
            status="aberta",
        )

        response = self.client.get(
            reverse("caixa:contas_receber"),
            {"tipo_origem": "garantia_fabricante", "fornecedor": str(fornecedor_a.id), "marca": str(marca_a.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Garantia A")
        self.assertNotContains(response, "Garantia B")

    def test_detalhe_conta_receber_exibe_bloco_de_garantia(self):
        self.client.force_login(self.gerente)
        fornecedor = FornecedorGarantia.objects.create(
            nome="Fornecedor Detalhe",
            email_cobranca="financeiro@detalhe.com",
            portal_garantia_url="https://portal.detalhe.com",
            documentos_exigidos="NF e laudo tecnico",
            procedimento_cobranca="Abrir portal e anexar documentos.",
        )
        marca = MarcaGarantia.objects.create(nome="Marca Detalhe", fornecedor=fornecedor, parceira_garantia=True, ativo=True)
        regra = RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("150.00"),
            valor_mao_obra_tecnico=Decimal("45.00"),
            modalidade_pagamento="pix",
            prazo_pagamento_dias=30,
        )
        conta = ContaReceber.objects.create(
            descricao="Garantia detalhe",
            tipo_origem="garantia_fabricante",
            cliente_nome="Fornecedor Detalhe",
            fornecedor_garantia=fornecedor,
            marca_garantia=marca,
            regra_garantia=regra,
            valor_original=Decimal("150.00"),
            valor_aberto=Decimal("150.00"),
            valor_aprovado_garantia=Decimal("120.00"),
            data_base_cobranca=timezone.localdate(),
            prazo_pagamento_dias=30,
            referencia_cobranca="GAR-DET-001",
            vencimento=timezone.localdate() + timedelta(days=30),
            status="aberta",
        )
        AuditoriaGarantia.objects.create(
            ordem_servico=self.ordem,
            conta_receber=conta,
            fornecedor=fornecedor,
            marca=marca,
            regra_garantia=regra,
            valor_previsto_fabricante=Decimal("150.00"),
            valor_aprovado_fabricante=Decimal("120.00"),
            valor_recebido_fabricante=Decimal("0.00"),
            comissao_prevista_tecnica=Decimal("45.00"),
            data_base_cobranca=timezone.localdate(),
            prazo_pagamento_dias=30,
            vencimento_previsto=timezone.localdate() + timedelta(days=30),
            status_faturamento="enviado",
            referencia_faturamento="GAR-DET-001",
        )

        response = self.client.get(reverse("caixa:detalhe_conta_receber", args=[conta.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Carteira de garantia")
        self.assertContains(response, "Fornecedor Detalhe")
        self.assertContains(response, "Marca Detalhe")
        self.assertContains(response, "GAR-DET-001")
        self.assertContains(response, "financeiro@detalhe.com")
        self.assertContains(response, "NF e laudo tecnico")
        self.assertContains(response, "Abrir portal e anexar documentos.")

    def test_editar_conta_garantia_redireciona_para_painel_de_garantias(self):
        self.client.force_login(self.gerente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Edicao")
        marca = MarcaGarantia.objects.create(nome="Marca Edicao", fornecedor=fornecedor, parceira_garantia=True, ativo=True)
        conta = ContaReceber.objects.create(
            descricao="Garantia protegida",
            tipo_origem="garantia_fabricante",
            cliente_nome="Fornecedor Edicao",
            fornecedor_garantia=fornecedor,
            marca_garantia=marca,
            valor_original=Decimal("110.00"),
            valor_aberto=Decimal("110.00"),
            valor_aprovado_garantia=Decimal("110.00"),
            vencimento=timezone.localdate() + timedelta(days=20),
            status="aberta",
        )

        response = self.client.get(reverse("caixa:editar_conta_receber", args=[conta.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("caixa:garantias_fabricante"))

    def test_dashboard_financeiro_destaca_marcas_de_garantia_em_atraso(self):
        self.client.force_login(self.gerente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Dashboard")
        marca = MarcaGarantia.objects.create(nome="Marca Dashboard", fornecedor=fornecedor, parceira_garantia=True, ativo=True)
        ContaReceber.objects.create(
            descricao="Garantia atrasada dashboard",
            tipo_origem="garantia_fabricante",
            cliente_nome="Fornecedor Dashboard",
            fornecedor_garantia=fornecedor,
            marca_garantia=marca,
            valor_original=Decimal("180.00"),
            valor_aberto=Decimal("180.00"),
            valor_aprovado_garantia=Decimal("150.00"),
            vencimento=timezone.localdate() - timedelta(days=12),
            status="vencida",
        )

        response = self.client.get(reverse("caixa:dashboard_financeiro"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Marcas de garantia em atraso")
        self.assertContains(response, "Marca Dashboard")
        self.assertContains(response, "Garantias vencidas")

    def test_aging_receber_destaca_marcas_de_garantia_vencidas(self):
        self.client.force_login(self.gerente)
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor Aging")
        marca = MarcaGarantia.objects.create(nome="Marca Aging", fornecedor=fornecedor, parceira_garantia=True, ativo=True)
        ContaReceber.objects.create(
            descricao="Garantia aging",
            tipo_origem="garantia_fabricante",
            cliente_nome="Fornecedor Aging",
            fornecedor_garantia=fornecedor,
            marca_garantia=marca,
            valor_original=Decimal("95.00"),
            valor_aberto=Decimal("95.00"),
            valor_aprovado_garantia=Decimal("90.00"),
            vencimento=timezone.localdate() - timedelta(days=8),
            status="vencida",
        )

        response = self.client.get(reverse("caixa:aging_receber"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Marcas de garantia mais atrasadas")
        self.assertContains(response, "Marca Aging")

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

    def test_usuario_financeiro_extra_sem_perm_nao_paga_conta_pagar(self):
        self.client.force_login(self.financeiro_extra)
        conta = ContaPagar.objects.create(
            fornecedor="Fornecedor bloqueado",
            descricao="Despesa bloqueada",
            valor_total=Decimal("100.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate(),
            status="aberta",
        )
        response = self.client.post(
            reverse("caixa:detalhe_conta_pagar", args=[conta.id]),
            {"valor": "10.00", "action": "pagar"},
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(str(conta.valor_pago), "0.00")
        self.assertFalse(PagamentoContaPagar.objects.filter(conta=conta).exists())

    def test_usuario_financeiro_extra_sem_perm_nao_cancela_conta_pagar(self):
        self.client.force_login(self.financeiro_extra)
        conta = ContaPagar.objects.create(
            fornecedor="Fornecedor sem cancelamento",
            descricao="Despesa ativa",
            valor_total=Decimal("100.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate(),
            status="aberta",
        )
        response = self.client.post(
            reverse("caixa:detalhe_conta_pagar", args=[conta.id]),
            {"action": "cancelar"},
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "aberta")

    def test_usuario_financeiro_extra_sem_perm_nao_edita_conta_pagar(self):
        self.client.force_login(self.financeiro_extra)
        conta = ContaPagar.objects.create(
            fornecedor="Fornecedor sem edicao",
            descricao="Despesa ativa",
            valor_total=Decimal("100.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate(),
            status="aberta",
        )
        response = self.client.get(reverse("caixa:editar_conta_pagar", args=[conta.id]))
        self.assertEqual(response.status_code, 403)

    def test_usuario_financeiro_extra_com_perm_edita_conta_pagar_sem_movimentacao(self):
        self.financeiro_extra.perm_caixa_editar_conta_pagar = True
        self.financeiro_extra.save(update_fields=["perm_caixa_editar_conta_pagar"])
        categoria = CategoriaFinanceira.objects.create(nome="Categoria edicao pagar", tipo="saida", ativa=True)
        conta = ContaPagar.objects.create(
            fornecedor="Fornecedor antigo",
            descricao="Despesa original",
            categoria=categoria,
            valor_total=Decimal("100.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate(),
            status="aberta",
        )
        self.client.force_login(self.financeiro_extra)
        response = self.client.post(
            reverse("caixa:editar_conta_pagar", args=[conta.id]),
            {
                "fornecedor": "Fornecedor novo",
                "descricao": "Despesa editada",
                "categoria": str(categoria.id),
                "valor_total": "190.00",
                "vencimento": "2030-02-01",
                "centro_custo": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.fornecedor, "Fornecedor novo")
        self.assertEqual(conta.descricao, "Despesa editada")
        self.assertEqual(str(conta.valor_total), "190.00")

    def test_edicao_conta_pagar_movimentada_preserva_valor_total(self):
        categoria = CategoriaFinanceira.objects.create(nome="Categoria bloqueada pagar", tipo="saida", ativa=True)
        conta = ContaPagar.objects.create(
            fornecedor="Fornecedor travado",
            descricao="Despesa com pagamento",
            categoria=categoria,
            valor_total=Decimal("100.00"),
            valor_pago=Decimal("30.00"),
            vencimento=timezone.localdate(),
            status="parcial",
        )
        PagamentoContaPagar.objects.create(
            conta=conta,
            caixa=Caixa.objects.filter(aberto=True).first(),
            valor=Decimal("30.00"),
            usuario=self.gerente,
        )
        self.client.force_login(self.gerente)
        response = self.client.post(
            reverse("caixa:editar_conta_pagar", args=[conta.id]),
            {
                "fornecedor": "Fornecedor revisado",
                "descricao": "Despesa revisada",
                "categoria": str(categoria.id),
                "valor_total": "500.00",
                "vencimento": "2030-02-05",
                "centro_custo": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        conta.refresh_from_db()
        self.assertEqual(conta.fornecedor, "Fornecedor revisado")
        self.assertEqual(conta.descricao, "Despesa revisada")
        self.assertEqual(str(conta.valor_total), "100.00")

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
        self.assertEqual(response.context["total_entradas"], Decimal("30.00"))

    def test_relatorios_exibe_diferencas_por_forma(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        caixa.aberto = False
        caixa.saldo_final = Decimal("120.00")
        caixa.valor_contado_fisico = Decimal("118.00")
        caixa.conferencia_formas_pagamento = [
            {"codigo": "pix", "nome": "PIX", "apurado": "120.00", "contado": "118.00", "diferenca": "-2.00"}
        ]
        caixa.save(update_fields=["aberto", "saldo_final", "valor_contado_fisico", "conferencia_formas_pagamento"])

        response = self.client.get(
            reverse("caixa:relatorios"),
            {"data_inicio": timezone.localdate().isoformat(), "data_fim": timezone.localdate().isoformat(), "todos_caixas": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PIX")
        self.assertContains(response, "PIX")
        self.assertContains(response, "-2,00")

    def test_relatorios_exibe_tendencia_por_categoria_e_centro(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        categoria = CategoriaFinanceira.objects.create(nome="Tendencia categoria", tipo="saida", ativa=True)
        centro = CentroCusto.objects.create(nome="Tendencia centro", tipo="variavel", ativo=True)
        atual = LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Saida atual",
            valor=Decimal("60.00"),
            tipo="saida",
            categoria=categoria,
            centro_custo=centro,
            usuario=self.gerente,
        )
        anterior = LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Saida anterior",
            valor=Decimal("25.00"),
            tipo="saida",
            categoria=categoria,
            centro_custo=centro,
            usuario=self.gerente,
        )
        hoje = timezone.localdate()
        LancamentoCaixa.objects.filter(pk=atual.pk).update(data=timezone.make_aware(timezone.datetime.combine(hoje, timezone.datetime.min.time())))
        LancamentoCaixa.objects.filter(pk=anterior.pk).update(data=timezone.make_aware(timezone.datetime.combine(hoje - timedelta(days=1), timezone.datetime.min.time())))

        response = self.client.get(reverse("caixa:relatorios"), {"data_inicio": hoje.isoformat(), "data_fim": hoje.isoformat(), "todos_caixas": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tendencia categoria")
        self.assertContains(response, "Tendencia centro")

    def test_relatorios_exibe_tendencia_por_forma(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        forma = FormaPagamento.objects.create(nome="PIX tendencia", codigo="pix-tend", tipo="avista", ativa=True)
        pagamento_atual = Pagamento.objects.create(caixa=caixa, ordem_servico=self.ordem, valor=Decimal("70.00"), forma_pagamento=forma, metodo="pix")
        pagamento_anterior = Pagamento.objects.create(caixa=caixa, ordem_servico=self.ordem, valor=Decimal("20.00"), forma_pagamento=forma, metodo="pix")
        hoje = timezone.localdate()
        Pagamento.objects.filter(pk=pagamento_atual.pk).update(data=timezone.make_aware(timezone.datetime.combine(hoje, timezone.datetime.min.time())))
        Pagamento.objects.filter(pk=pagamento_anterior.pk).update(data=timezone.make_aware(timezone.datetime.combine(hoje - timedelta(days=1), timezone.datetime.min.time())))

        response = self.client.get(reverse("caixa:relatorios"), {"data_inicio": hoje.isoformat(), "data_fim": hoje.isoformat(), "todos_caixas": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PIX tendencia")

    def test_relatorios_export_executivo_csv(self):
        self.client.force_login(self.gerente)
        response = self.client.get(reverse("caixa:relatorios"), {"export": "csv", "dataset": "executivo"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])

    def test_relatorios_exibe_atendente_e_tecnico_responsavel_da_os(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        self.ordem.tecnico_responsavel = self.tecnico
        self.ordem.save(update_fields=["tecnico_responsavel"])
        LinhaTrabalho.objects.create(
            ordem=self.ordem,
            usuario=self.atendente,
            status="criada",
            descricao="Ordem criada",
            tipo_evento="manual",
        )
        Pagamento.objects.create(caixa=caixa, ordem_servico=self.ordem, valor=Decimal("10.00"), metodo="pix")

        response = self.client.get(reverse("caixa:relatorios"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Atendente")
        self.assertContains(response, self.atendente.username)
        self.assertContains(response, self.tecnico.username)

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

    def test_comissao_item_garantia_bloqueada_nao_gera_item_antecipado(self):
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
        self.assertFalse(ComissaoItemOrcamento.objects.exists())

    def test_comissao_item_garantia_pode_ser_calculada_quando_regra_permita(self):
        self.client.force_login(self.gerente)
        tecnico = get_user_model().objects.create_user(
            username="tecnico_garantia_com_comissao",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.ordem.tipo_reparo = "Garantia"
        self.ordem.status = "pronto_contactado"
        self.ordem.relatorio_tecnico = "Garantia aprovada para comissao."
        self.ordem.save(update_fields=["tipo_reparo", "status", "relatorio_tecnico"])
        RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("5.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            comissionar_garantia=True,
            ativo=True,
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico garantia permitido",
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

    def test_relatorios_filtra_por_forma_pagamento_e_centro_custo(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        forma_pix = FormaPagamento.objects.create(nome="PIX teste", codigo="pix-teste", tipo="avista", ativa=True)
        forma_cartao = FormaPagamento.objects.create(nome="Cartao teste", codigo="cartao-teste", tipo="avista", ativa=True)
        centro_operacional = CentroCusto.objects.create(nome="Operacional teste", tipo="variavel", ativo=True)
        centro_marketing = CentroCusto.objects.create(nome="Marketing teste", tipo="variavel", ativo=True)

        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("40.00"),
            forma_pagamento=forma_pix,
            metodo="pix",
        )
        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("60.00"),
            forma_pagamento=forma_cartao,
            metodo="cartao",
        )
        LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Compra operacional",
            forma_pagamento=forma_pix,
            centro_custo=centro_operacional,
            valor=Decimal("15.00"),
            tipo="saida",
            usuario=self.gerente,
        )
        LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Campanha",
            forma_pagamento=forma_cartao,
            centro_custo=centro_marketing,
            valor=Decimal("25.00"),
            tipo="saida",
            usuario=self.gerente,
        )

        response = self.client.get(
            reverse("caixa:relatorios"),
            {
                "forma_pagamento": str(forma_pix.id),
                "centro_custo": str(centro_operacional.id),
                "tipo_lancamento": "saida",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["pagamentos"].count(), 1)
        self.assertEqual(response.context["lancamentos"].count(), 1)
        self.assertEqual(response.context["pagamentos"].first().forma_pagamento_id, forma_pix.id)
        self.assertEqual(response.context["lancamentos"].first().centro_custo_id, centro_operacional.id)
        self.assertEqual(response.context["total_entradas"], Decimal("40.00"))
        self.assertEqual(response.context["total_saidas"], Decimal("15.00"))

    def test_dre_intervalo_customizado_separa_cliente_garantia_e_despesa(self):
        self.client.force_login(self.gerente)
        forma_dinheiro = FormaPagamento.objects.create(nome="Dinheiro teste", codigo="dinheiro-teste", tipo="avista", ativa=True)
        forma_garantia, _ = FormaPagamento.objects.get_or_create(
            codigo="garantia_fabricante",
            defaults={
                "nome": "Garantia fabricante teste",
                "tipo": "aprazo",
                "ativa": True,
            },
        )
        centro = CentroCusto.objects.create(nome="Assistencia tecnica", tipo="variavel", ativo=True)
        caixa = Caixa.objects.filter(aberto=True).first()

        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("80.00"),
            forma_pagamento=forma_dinheiro,
            metodo="dinheiro",
        )
        Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("20.00"),
            forma_pagamento=forma_garantia,
            metodo="garantia_fabricante",
        )
        LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Despesa tecnica",
            centro_custo=centro,
            valor=Decimal("30.00"),
            tipo="saida",
            usuario=self.gerente,
        )
        produto_cmv = Produto.objects.create(
            nome="Peca contabilizada no DRE",
            tipo_item="produto",
            custo_unitario=Decimal("20.00"),
            preco_final=Decimal("50.00"),
            preco=Decimal("50.00"),
        )
        MovimentacaoEstoque.objects.create(
            produto=produto_cmv,
            tipo="venda",
            quantidade=-1,
            valor_unitario_custo=Decimal("20.00"),
            valor_total_custo=Decimal("20.00"),
        )
        MovimentacaoEstoque.objects.create(
            produto=produto_cmv,
            tipo="oferta",
            quantidade=-1,
            valor_unitario_custo=Decimal("5.00"),
            valor_total_custo=Decimal("5.00"),
        )

        hoje = timezone.localdate().isoformat()
        response = self.client.get(reverse("caixa:dre"), {"data_inicio": hoje, "data_fim": hoje})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["receita_bruta"], Decimal("100.00"))
        self.assertEqual(response.context["receita_cliente"], Decimal("80.00"))
        self.assertEqual(response.context["receita_garantia"], Decimal("20.00"))
        self.assertEqual(response.context["cmv"], Decimal("20.00"))
        self.assertEqual(response.context["perdas_estoque"], Decimal("5.00"))
        self.assertEqual(response.context["lucro_bruto"], Decimal("80.00"))
        self.assertEqual(response.context["resultado_operacional"], Decimal("45.00"))


class CaixaMultiempresaTests(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(nome="Empresa Caixa A")
        self.empresa_b = Empresa.objects.create(nome="Empresa Caixa B")
        self.gerente_a = get_user_model().objects.create_user(
            username="gerente_caixa_empresa_a",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa_a,
        )
        self.gerente_b = get_user_model().objects.create_user(
            username="gerente_caixa_empresa_b",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa_b,
        )

    def test_empresas_podem_ter_caixa_aberto_no_mesmo_dia(self):
        caixa_a = Caixa.objects.create(empresa=self.empresa_a, aberto=True, saldo_inicial=Decimal("10.00"))
        caixa_b = Caixa.objects.create(empresa=self.empresa_b, aberto=True, saldo_inicial=Decimal("20.00"))

        self.assertNotEqual(caixa_a.id, caixa_b.id)
        self.assertEqual(Caixa.objects.filter(aberto=True).count(), 2)

    def test_dashboard_financeiro_isola_valores_por_empresa(self):
        caixa_a = Caixa.objects.create(empresa=self.empresa_a, aberto=True, saldo_inicial=Decimal("0.00"))
        caixa_b = Caixa.objects.create(empresa=self.empresa_b, aberto=True, saldo_inicial=Decimal("0.00"))
        Pagamento.objects.create(empresa=self.empresa_a, caixa=caixa_a, valor=Decimal("100.00"), metodo="pix")
        Pagamento.objects.create(empresa=self.empresa_b, caixa=caixa_b, valor=Decimal("900.00"), metodo="pix")
        self.client.force_login(self.gerente_a)

        response = self.client.get(reverse("caixa:dashboard_financeiro"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_entradas"], Decimal("100.00"))
        self.assertNotContains(response, "900,00")

    def test_detalhe_caixa_de_outra_empresa_retorna_404(self):
        caixa_a = Caixa.objects.create(empresa=self.empresa_a, aberto=False, saldo_inicial=Decimal("0.00"))
        caixa_b = Caixa.objects.create(empresa=self.empresa_b, aberto=False, saldo_inicial=Decimal("0.00"))
        self.client.force_login(self.gerente_a)

        self.assertEqual(self.client.get(reverse("caixa:detalhe_caixa", args=[caixa_a.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("caixa:detalhe_caixa", args=[caixa_b.id])).status_code, 404)

    def test_fluxo_projetado_isola_recebimentos_e_despesas_por_empresa(self):
        vencimento = timezone.localdate() + timedelta(days=5)
        ContaReceber.objects.create(
            empresa=self.empresa_a,
            descricao="Receber A",
            valor_original=Decimal("100.00"),
            valor_aberto=Decimal("100.00"),
            vencimento=vencimento,
            status="aberta",
        )
        ContaReceber.objects.create(
            empresa=self.empresa_b,
            descricao="Receber B",
            valor_original=Decimal("900.00"),
            valor_aberto=Decimal("900.00"),
            vencimento=vencimento,
            status="aberta",
        )
        DespesaRecorrente.objects.create(empresa=self.empresa_a, nome="Aluguel A", valor_mensal=Decimal("30.00"))
        DespesaRecorrente.objects.create(empresa=self.empresa_b, nome="Aluguel B", valor_mensal=Decimal("300.00"))
        self.client.force_login(self.gerente_a)

        response = self.client.get(reverse("caixa:fluxo_projetado"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_entradas_previstas"], Decimal("100.00"))
        self.assertEqual(response.context["total_despesas_previstas"], Decimal("180.00"))
        self.assertContains(response, "Aluguel A")
        self.assertNotContains(response, "Aluguel B")

    def test_dre_desconta_e_congela_impostos_e_taxas_do_pagamento(self):
        self.empresa_a.regime_tributario = "simples"
        self.empresa_a.modo_tributario = "basico"
        self.empresa_a.aliquota_comercio = Decimal("6.00")
        self.empresa_a.save(update_fields=["regime_tributario", "modo_tributario", "aliquota_comercio"])
        caixa = Caixa.objects.create(empresa=self.empresa_a, aberto=True, saldo_inicial=Decimal("0.00"))
        forma = FormaPagamento.objects.create(
            nome="Cartao DRE snapshot",
            codigo="cartao-dre-snapshot",
            taxa_percentual=Decimal("2.00"),
        )
        pagamento = Pagamento.objects.create(
            empresa=self.empresa_a,
            caixa=caixa,
            forma_pagamento=forma,
            valor=Decimal("100.00"),
            metodo=forma.codigo,
        )
        pagamento.refresh_from_db()
        self.assertEqual(pagamento.impostos_estimados, Decimal("6.00"))
        self.assertEqual(pagamento.taxas_recebimento_estimadas, Decimal("2.00"))

        self.client.force_login(self.gerente_a)
        hoje = timezone.localdate()
        inicio = hoje.replace(day=1)
        fim = hoje.replace(day=monthrange(hoje.year, hoje.month)[1])
        response = self.client.get(
            reverse("caixa:dre"),
            {"data_inicio": inicio.isoformat(), "data_fim": fim.isoformat()},
        )
        self.assertEqual(response.context["impostos_estimados"], Decimal("6.00"))
        self.assertEqual(response.context["taxas_recebimento"], Decimal("2.00"))
        self.assertEqual(response.context["receita_liquida"], Decimal("92.00"))
        self.assertEqual(response.context["resultado_operacional"], Decimal("92.00"))

        self.client.post(
            reverse("caixa:dre"),
            {"data_inicio": inicio.isoformat(), "data_fim": fim.isoformat()},
        )
        fechamento = DREFechamento.objects.get(empresa=self.empresa_a, competencia=inicio)
        self.assertEqual(fechamento.impostos_estimados, Decimal("6.00"))
        self.assertEqual(fechamento.taxas_recebimento, Decimal("2.00"))
        self.assertEqual(fechamento.resultado_operacional, Decimal("92.00"))

        forma.taxa_percentual = Decimal("9.00")
        forma.save(update_fields=["taxa_percentual"])
        self.empresa_a.aliquota_comercio = Decimal("12.00")
        self.empresa_a.save(update_fields=["aliquota_comercio"])
        pagamento.refresh_from_db()
        fechamento.refresh_from_db()
        self.assertEqual(pagamento.impostos_estimados, Decimal("6.00"))
        self.assertEqual(pagamento.taxas_recebimento_estimadas, Decimal("2.00"))
        self.assertEqual(fechamento.resultado_operacional, Decimal("92.00"))


class PagamentoComDescontoTests(TestCase):
    def setUp(self):
        super().setUp()
        user_model = get_user_model()
        self.gerente = user_model.objects.create_user(
            username="gerente_desconto_pagamento",
            password="senha-forte-123",
            tipo_usuario="gerente",
        )
        self.atendente = user_model.objects.create_user(
            username="atendente_desconto_pagamento",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.client.force_login(self.gerente)
        self.caixa = Caixa.objects.create(aberto=True, saldo_inicial=Decimal("0.00"))
        self.forma_pix = FormaPagamento.objects.create(nome="PIX Teste", codigo="pix_teste", tipo="avista", ativa=True)
        self.cliente = Cliente.objects.create(
            nome="Cliente desconto caixa",
            documento="39053344705",
            telefone="11999998888",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca D",
            modelo_equipamento="Modelo D",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="pronto_contactado",
            relatorio_tecnico="RelatÃ³rio",
        )
        ServicoPeca.objects.create(
            ordem=self.ordem,
            tipo="servico",
            nome="MÃ£o de obra",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
        )

    def test_registrar_pagamento_aplica_desconto_no_recebivel(self):
        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}",
            {
                "ordem_servico": str(self.ordem.id),
                "valor": "100.00",
                "forma_pagamento": str(self.forma_pix.id),
                "referencia": "PIX-100",
                "desconto_valor": "10.00",
                "desconto_percentual": "",
                "chave_idempotencia": "pagamento-desconto-os-1",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        pagamento = Pagamento.objects.get(chave_idempotencia="pagamento-desconto-os-1")
        self.assertEqual(pagamento.valor, Decimal("90.00"))
        self.assertEqual(pagamento.desconto, Decimal("10.00"))
        conta = ContaReceber.objects.get(ordem_servico=self.ordem, tipo_origem="cliente_os")
        self.assertEqual(conta.status, "paga")
        self.assertEqual(conta.valor_aberto, Decimal("0.00"))
        recebimento = conta.recebimentos.latest("id")
        self.assertEqual(recebimento.valor, Decimal("90.00"))
        self.assertEqual(recebimento.desconto, Decimal("10.00"))

    def test_registrar_pagamento_com_desconto_exige_permissao(self):
        self.client.force_login(self.atendente)
        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}",
            {
                "ordem_servico": str(self.ordem.id),
                "valor": "100.00",
                "forma_pagamento": str(self.forma_pix.id),
                "referencia": "PIX-BLOQ",
                "desconto_valor": "10.00",
                "desconto_percentual": "",
                "chave_idempotencia": "pagamento-desconto-bloqueado-1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Pagamento.objects.filter(chave_idempotencia="pagamento-desconto-bloqueado-1").exists())
        self.assertIn("desconto_valor", response.context["form"].errors)

    def test_desconto_no_caixa_nao_reduz_comissao(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_desconto_caixa",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("10.00"),
        )
        servico = self.ordem.servicos_pecas.first()
        servico.tecnico_responsavel = tecnico
        servico.comissionavel = True
        servico.save(update_fields=["tecnico_responsavel", "comissionavel"])

        response = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={self.ordem.id}",
            {
                "ordem_servico": str(self.ordem.id),
                "valor": "100.00",
                "forma_pagamento": str(self.forma_pix.id),
                "referencia": "PIX-COMISSAO",
                "desconto_valor": "20.00",
                "desconto_percentual": "",
                "chave_idempotencia": "pagamento-desconto-comissao-caixa-1",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        pagamento = Pagamento.objects.get(chave_idempotencia="pagamento-desconto-comissao-caixa-1")
        self.assertEqual(pagamento.valor, Decimal("80.00"))
        self.assertEqual(pagamento.desconto, Decimal("20.00"))

        comissao = Comissao.objects.filter(ordem_servico=self.ordem, tipo="SERVICO").order_by("-id").first()
        self.assertIsNotNone(comissao)
        self.assertEqual(comissao.valor_base, Decimal("100.00"))
        self.assertEqual(comissao.percentual, Decimal("10.00"))
        self.assertEqual(comissao.valor_comissao, Decimal("10.00"))

    def test_desconto_no_orcamento_nao_reduz_comissao(self):
        tecnico = get_user_model().objects.create_user(
            username="tecnico_desconto_orcamento",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("10.00"),
        )
        ordem_orc = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca O2",
            modelo_equipamento="Modelo O2",
            defeito="Teste desconto orcamento",
            tipo_reparo="Fora de Garantia",
            status="pronto_contactado",
            relatorio_tecnico="Relatorio tecnico",
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=ordem_orc)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico com desconto no orcamento",
            descricao="Teste",
            valor_unitario=Decimal("100.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        orcamento.desconto_percentual = Decimal("25.00")
        orcamento.save(update_fields=["desconto_percentual"])
        orcamento.atualizar_total()

        processar_evento_servico_finalizado(ordem_orc, evento="SERVICO_FINALIZADO_TESTE_ORC")
        comissao = Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").order_by("-id").first()
        self.assertIsNotNone(comissao)
        self.assertEqual(comissao.valor_base, Decimal("100.00"))
        self.assertEqual(comissao.percentual, Decimal("10.00"))
        self.assertEqual(comissao.valor_comissao, Decimal("10.00"))


class ComissaoGarantiaServicoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente_caixa_garantia",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.gerente = user_model.objects.create_user(
            username="gerente_caixa_garantia",
            password="senha-forte-123",
            tipo_usuario="gerente",
        )
        self.superuser = user_model.objects.create_superuser(
            username="root_caixa_garantia",
            password="senha-forte-123",
            email="root.garantia@caixa.com",
        )
        Caixa.objects.create(aberto=True, saldo_inicial=0)
        self.cliente = Cliente.objects.create(
            nome="Cliente Caixa Garantia",
            documento="86288366757",
            telefone="11999998888",
            estado="SP",
        )
        self.tecnico = user_model.objects.create_user(
            username="tecnico_caixa_garantia",
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
        self.tecnico_retorno = user_model.objects.create_user(
            username="tecnico_retorno_garantia",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("10.00"),
        )
        self.cliente_retorno = Cliente.objects.create(
            nome="Cliente retorno garantia",
            documento="39053344705",
            telefone="11999990000",
            estado="SP",
        )
        self.ordem_retorno = OrdemServico.objects.create(
            cliente=self.cliente_retorno,
            tipo_equipamento="celular",
            marca_equipamento="Marca R",
            modelo_equipamento="Modelo R",
            defeito="Retorno",
            tipo_reparo="Garantia de serviÃ§o",
            status="pronto_contactado",
            relatorio_tecnico="RelatÃ³rio tÃ©cnico preenchido",
        )
        self.orcamento_retorno = Orcamento.objects.create(cliente=self.cliente_retorno, ordem_servico=self.ordem_retorno)

    def test_garantia_de_servico_nao_comissiona_retorno_padrao(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento_retorno,
            nome="Retorno garantia",
            descricao="Retorno",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico_retorno,
            status="aprovado",
            comissionavel=False,
        )
        criadas = processar_evento_servico_finalizado(self.ordem_retorno, evento="SERVICO_FINALIZADO")
        self.assertEqual(criadas, 0)
        self.assertFalse(Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").exists())

    def test_garantia_de_servico_comissiona_servico_extra(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento_retorno,
            nome="ServiÃ§o extra",
            descricao="CobranÃ§a adicional",
            quantidade=1,
            valor_unitario=Decimal("120.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico_retorno,
            status="aprovado",
            comissionavel=True,
        )
        self.assertTrue(Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").exists())
        criadas = processar_evento_servico_finalizado(self.ordem_retorno, evento="SERVICO_FINALIZADO")
        self.assertEqual(criadas, 0)
        self.assertTrue(Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").exists())

    def test_garantia_fabricante_usa_base_tecnica_fixa_da_regra(self):
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor comissao garantia")
        marca = MarcaGarantia.objects.create(
            nome="Marca comissao garantia",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("200.00"),
            parceira_garantia=True,
            ativo=True,
        )
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("200.00"),
            valor_mao_obra_tecnico=Decimal("30.00"),
            modalidade_pagamento="faturado",
            prazo_pagamento_dias=30,
            ativo=True,
        )
        RegraComissaoTecnico.objects.create(
            usuario=self.tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            comissionar_garantia=True,
            ativo=True,
        )
        self.ordem.tipo_reparo = "Garantia"
        self.ordem.status = "pronto_contactado"
        self.ordem.relatorio_tecnico = "Garantia finalizada"
        self.ordem.marca_garantia = marca
        self.ordem.marca_equipamento = marca.nome
        self.ordem.save(
            update_fields=["tipo_reparo", "status", "relatorio_tecnico", "marca_garantia", "marca_equipamento"]
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico garantia fabricante",
            descricao="Reparo garantia fabricante",
            quantidade=1,
            valor_unitario=Decimal("200.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        comissao = Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").first()
        self.assertIsNotNone(comissao)
        self.assertEqual(comissao.valor_base, Decimal("30.00"))
        self.assertEqual(comissao.percentual, Decimal("100.00"))
        self.assertEqual(comissao.valor_comissao, Decimal("30.00"))
        self.assertEqual(comissao.dados_extras.get("modo_calculo"), "garantia_regra_tecnica_fixa")
        self.assertEqual(Decimal(comissao.dados_extras.get("base_original_item")), Decimal("200.00"))

    def test_garantia_fabricante_respeita_bloqueio_de_comissao_na_regra_do_tecnico(self):
        fornecedor = FornecedorGarantia.objects.create(nome="Fornecedor bloqueio garantia")
        marca = MarcaGarantia.objects.create(
            nome="Marca bloqueio garantia",
            fornecedor=fornecedor,
            valor_mao_obra_garantia=Decimal("180.00"),
            parceira_garantia=True,
            ativo=True,
        )
        RegraGarantiaMarca.objects.create(
            marca=marca,
            tipo_produto="celular",
            valor_mao_obra=Decimal("180.00"),
            valor_mao_obra_tecnico=Decimal("40.00"),
            modalidade_pagamento="faturado",
            prazo_pagamento_dias=30,
            ativo=True,
        )
        RegraComissaoTecnico.objects.create(
            usuario=self.tecnico,
            percentual_servico=Decimal("12.00"),
            percentual_peca=Decimal("0.00"),
            comissionar_garantia=False,
            ativo=True,
        )
        self.tecnico.percentual_comissao_servico = Decimal("15.00")
        self.tecnico.save(update_fields=["percentual_comissao_servico"])
        self.ordem.tipo_reparo = "Garantia"
        self.ordem.status = "pronto_contactado"
        self.ordem.relatorio_tecnico = "Garantia bloqueada"
        self.ordem.marca_garantia = marca
        self.ordem.marca_equipamento = marca.nome
        self.ordem.save(
            update_fields=["tipo_reparo", "status", "relatorio_tecnico", "marca_garantia", "marca_equipamento"]
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)
        item = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Servico garantia bloqueado",
            descricao="Sem comissao",
            quantidade=1,
            valor_unitario=Decimal("180.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="aprovado",
        )
        self.assertFalse(Comissao.objects.filter(item_orcamento=item, tipo="SERVICO").exists())

    def test_dre_exibe_leitura_executiva_e_comparativos(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        categoria = CategoriaFinanceira.objects.create(nome="Despesa DRE", tipo="saida", ativa=True)
        centro = CentroCusto.objects.create(nome="Centro DRE", tipo="variavel", ativo=True)
        Pagamento.objects.create(caixa=caixa, ordem_servico=self.ordem, valor=Decimal("100.00"), metodo="pix")
        LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Despesa DRE atual",
            centro_custo=centro,
            categoria=categoria,
            valor=Decimal("30.00"),
            tipo="saida",
            usuario=self.gerente,
        )

        hoje = timezone.localdate().isoformat()
        response = self.client.get(reverse("caixa:dre"), {"data_inicio": hoje, "data_fim": hoje})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Leitura executiva")
        self.assertContains(response, "Comparativo por categoria")
        self.assertContains(response, "Comparativo por centro de custo")
        self.assertContains(response, "DRE")

    def test_fechamento_dre_mensal_e_unico_e_imutavel(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        Pagamento.objects.create(caixa=caixa, valor=Decimal("100.00"), metodo="pix")
        hoje = timezone.localdate()
        inicio = hoje.replace(day=1)
        fim = hoje.replace(day=monthrange(hoje.year, hoje.month)[1])

        response = self.client.post(
            reverse("caixa:dre"),
            {"data_inicio": inicio.isoformat(), "data_fim": fim.isoformat()},
        )

        self.assertEqual(response.status_code, 302)
        fechamento = DREFechamento.objects.get(competencia=inicio)
        self.assertEqual(fechamento.receita_bruta, Decimal("100.00"))
        Pagamento.objects.create(caixa=caixa, valor=Decimal("50.00"), metodo="dinheiro")
        self.client.post(
            reverse("caixa:dre"),
            {"data_inicio": inicio.isoformat(), "data_fim": fim.isoformat()},
        )
        self.assertEqual(DREFechamento.objects.filter(competencia=inicio).count(), 1)
        fechamento.refresh_from_db()
        self.assertEqual(fechamento.receita_bruta, Decimal("100.00"))
        fechamento.resultado_operacional = Decimal("999.00")
        with self.assertRaises(ValidationError):
            fechamento.save()
        with self.assertRaises(ValidationError):
            fechamento.delete()

    def test_aging_receber_exibe_faixas_detalhadas(self):
        self.client.force_login(self.gerente)
        ContaReceber.objects.create(
            descricao="Conta aging 1",
            cliente_nome="Cliente aging",
            tipo_origem="avulso",
            valor_original="120.00",
            valor_aberto="120.00",
            vencimento=timezone.localdate() - timedelta(days=10),
            status="vencida",
        )
        ContaReceber.objects.create(
            descricao="Conta aging 2",
            cliente_nome="Cliente futuro",
            tipo_origem="avulso",
            valor_original="80.00",
            valor_aberto="80.00",
            vencimento=timezone.localdate() + timedelta(days=5),
            status="aberta",
        )

        response = self.client.get(reverse("caixa:aging_receber"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total em aberto")
        self.assertContains(response, "A vencer")
        self.assertContains(response, "1 a 30 dias")
        self.assertContains(response, "Receber")

    def test_aging_pagar_exibe_faixas_e_acao_direta(self):
        self.client.force_login(self.gerente)
        ContaPagar.objects.create(
            fornecedor="Fornecedor pagar aging",
            descricao="Conta pagar aging",
            valor_total=Decimal("60.00"),
            valor_pago=Decimal("0.00"),
            vencimento=timezone.localdate() - timedelta(days=12),
            status="vencida",
        )

        response = self.client.get(reverse("caixa:aging_pagar"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aging de contas a pagar")
        self.assertContains(response, "Abrir fila")
        self.assertContains(response, "Pagar")

    def test_contas_receber_filtra_por_bucket_aging(self):
        self.client.force_login(self.gerente)
        ContaReceber.objects.create(
            descricao="Conta 90+",
            cliente_nome="Cliente 90+",
            tipo_origem="avulso",
            valor_original="50.00",
            valor_aberto="50.00",
            vencimento=timezone.localdate() - timedelta(days=120),
            status="vencida",
        )
        ContaReceber.objects.create(
            descricao="Conta recente",
            cliente_nome="Cliente recente",
            tipo_origem="avulso",
            valor_original="30.00",
            valor_aberto="30.00",
            vencimento=timezone.localdate() - timedelta(days=10),
            status="vencida",
        )

        response = self.client.get(reverse("caixa:contas_receber"), {"aging": "vencidas_90_plus"})

        self.assertEqual(response.status_code, 200)
        contas = list(response.context["contas"])
        self.assertEqual(len(contas), 1)
        self.assertEqual(contas[0].descricao, "Conta 90+")

    def test_auditoria_operacional_lista_pendencias(self):
        self.client.force_login(self.gerente)
        caixa = Caixa.objects.filter(aberto=True).first()
        caixa.aberto = False
        caixa.saldo_final = Decimal("100.00")
        caixa.valor_contado_fisico = Decimal("95.00")
        caixa.diferenca_fechamento = Decimal("-5.00")
        caixa.save(update_fields=["aberto", "saldo_final", "valor_contado_fisico", "diferenca_fechamento"])

        conta_pronta = ContaReceber.objects.create(
            ordem_servico=self.ordem,
            descricao="OS pronta sem recebimento",
            cliente_nome=self.cliente.nome,
            tipo_origem="cliente_os",
            valor_original="120.00",
            valor_aberto="120.00",
            vencimento=timezone.localdate(),
            status="aberta",
        )
        conta_vencida = ContaReceber.objects.create(
            descricao="Conta vencida",
            cliente_nome="Cliente vencido",
            tipo_origem="avulso",
            valor_original="80.00",
            valor_aberto="80.00",
            vencimento=timezone.localdate() - timedelta(days=2),
            status="vencida",
        )
        pagamento_sem_talao = Pagamento.objects.create(
            caixa=caixa,
            ordem_servico=self.ordem,
            valor=Decimal("55.00"),
            metodo="pix",
        )
        Pagamento.objects.filter(pk=pagamento_sem_talao.pk).update(numero_talao="")
        LancamentoCaixa.objects.create(
            caixa=caixa,
            descricao="Saida sem centro",
            valor=Decimal("12.00"),
            tipo="saida",
            usuario=self.gerente,
        )
        AuditoriaGarantia.objects.create(
            ordem_servico=OrdemServico.objects.create(
                cliente=self.cliente,
                tipo_equipamento="celular",
                marca_equipamento="Marca G",
                modelo_equipamento="Modelo G",
                defeito="Teste garantia pendente",
                tipo_reparo="Garantia",
                status="concluida",
                fechada=True,
            ),
            status_faturamento="pendente",
            valor_previsto_fabricante=Decimal("150.00"),
        )

        response = self.client.get(reverse("caixa:auditoria_operacional"), {"dias": "30"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(conta_pronta, response.context["ordens_prontas_sem_recebimento"])
        self.assertIn(conta_vencida, response.context["contas_vencidas"])
        self.assertEqual(response.context["total_caixas_com_diferenca"], 1)
        self.assertEqual(response.context["total_pagamentos_sem_talao"], 1)
        self.assertEqual(response.context["total_saidas_sem_centro"], 1)
        self.assertEqual(response.context["total_garantias_pendentes"], 1)

    def test_auditoria_operacional_exibe_eventos_criticos(self):
        self.client.force_login(self.gerente)
        AuditoriaFinanceira.objects.create(
            evento="pagamento_excluido",
            descricao="Pagamento 10 excluÃ­do com justificativa.",
            valor=Decimal("45.00"),
            usuario=self.gerente,
        )

        response = self.client.get(reverse("caixa:auditoria_operacional"), {"dias": "30"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_eventos_criticos"], 1)
        self.assertContains(response, "Pagamento 10")

    def test_fluxo_integrado_fechamento_pagamento_e_comissoes_tecnico(self):
        self.client.force_login(self.gerente)
        config = ConfiguracaoSistema.get_configuracao()
        config.comissao_aplicar_pecas = True
        config.save(update_fields=["comissao_aplicar_pecas"])
        tecnico = get_user_model().objects.create_user(
            username="tecnico_fluxo_integrado",
            password="senha-forte-123",
            tipo_usuario="tecnico",
            percentual_comissao_servico=Decimal("10.00"),
            percentual_comissao_peca=Decimal("4.00"),
        )
        produto = Produto.objects.create(
            nome="Motor Integrado",
            ean="7891231231231",
            preco_final=Decimal("80.00"),
            quantidade=3,
            permite_comissao_peca=True,
            percentual_comissao_peca=Decimal("12.00"),
            bonus_venda=Decimal("5.00"),
        )
        ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="maquina_lavar",
            marca_equipamento="Marca Integrada",
            modelo_equipamento="Modelo Integrado",
            defeito="Nao centrifuga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
            relatorio_tecnico="Motor e mao de obra executados.",
            tipo_reparacao="substituicao",
        )
        orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=ordem)
        item_servico = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Mao de obra integrada",
            descricao="Servico principal",
            quantidade=1,
            valor_unitario=Decimal("200.00"),
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )
        item_peca = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome=produto.nome,
            ean=produto.ean,
            descricao="Peca aplicada",
            quantidade=1,
            valor_unitario=Decimal("80.00"),
            origem="estoque",
            tipo_item="peca",
            tecnico_responsavel=tecnico,
            status="aprovado",
        )

        response_fechamento = self.client.get(reverse("ordens:toggle_fechamento_os", args=[ordem.id]) + "?ir_caixa=1")
        self.assertEqual(response_fechamento.status_code, 302)
        self.assertIn(reverse("caixa:registrar_pagamento"), response_fechamento.url)
        ordem.refresh_from_db()
        self.assertTrue(ordem.fechada)
        self.assertEqual(ordem.status, "concluida")
        self.assertEqual(ServicoPeca.objects.filter(ordem=ordem).count(), 2)

        comissoes_fechamento = Comissao.objects.filter(ordem_servico=ordem, tecnico=tecnico).order_by("tipo")
        self.assertEqual(comissoes_fechamento.count(), 2)
        self.assertEqual(
            {row["tipo"]: row["valor_comissao"] for row in comissoes_fechamento.values("tipo", "valor_comissao")},
            {
                "PECA": Decimal("9.60"),
                "SERVICO": Decimal("20.00"),
            },
        )

        response_pagamento = self.client.post(
            reverse("caixa:registrar_pagamento") + f"?os={ordem.id}",
            {"valor": "280.00", "metodo": "pix", "referencia": "FLUXO-INT-001"},
        )
        self.assertEqual(response_pagamento.status_code, 302)

        pagamento = Pagamento.objects.filter(ordem_servico=ordem, referencia="FLUXO-INT-001").first()
        self.assertIsNotNone(pagamento)
        self.assertTrue(bool(pagamento.numero_talao))

        comissoes = Comissao.objects.filter(ordem_servico=ordem, tecnico=tecnico).order_by("tipo")
        self.assertEqual(comissoes.count(), 2)
        self.assertEqual(
            {row["tipo"]: row["valor_comissao"] for row in comissoes.values("tipo", "valor_comissao")},
            {
                "PECA": Decimal("9.60"),
                "SERVICO": Decimal("20.00"),
            },
        )
        self.assertEqual(ordem.total_comissoes_financeiro(), Decimal("29.60"))

        hoje = timezone.localdate().isoformat()
        response_desempenho = self.client.get(
            reverse("caixa:meu_desempenho"),
            {
                "tecnico": str(tecnico.id),
                "data_inicio": hoje,
                "data_fim": hoje,
                "percentual_servicos": "10",
                "percentual_pecas": "12",
                "aplicar_servicos": "1",
                "aplicar_pecas": "1",
                "somente_fechadas": "1",
            },
        )
        self.assertEqual(response_desempenho.status_code, 200)
        self.assertEqual(response_desempenho.context["total_comissao_servicos_relatorio"], Decimal("20.00"))
        self.assertEqual(response_desempenho.context["total_comissao_pecas_relatorio"], Decimal("9.60"))
        self.assertEqual(response_desempenho.context["total_comissao_relatorio"], Decimal("29.60"))


class LivroFinanceiroFaseUmTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Livro", cnpj="11.222.333/0001-81")
        self.gerente = get_user_model().objects.create_user(
            username="gerente_livro",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
        )
        self.atendente = get_user_model().objects.create_user(
            username="atendente_livro",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
        )
        self.caixa = Caixa.objects.create(empresa=self.empresa, saldo_inicial=Decimal("0.00"))
        self.categoria = CategoriaFinanceira.objects.create(
            empresa=self.empresa,
            nome="Despesas gerais livro",
            tipo="saida",
        )
        self.centro = CentroCusto.objects.create(
            empresa=self.empresa,
            nome="Operação livro",
            tipo="variavel",
        )

    def test_pagamento_e_lancamento_manual_geram_livro_idempotente(self):
        pagamento = Pagamento.objects.create(
            empresa=self.empresa,
            caixa=self.caixa,
            valor=Decimal("125.00"),
            metodo="pix",
        )
        pagamento.observacao = "Atualização sem novo movimento"
        pagamento.save(update_fields=["observacao"])
        LancamentoCaixa.objects.create(
            empresa=self.empresa,
            caixa=self.caixa,
            descricao="Material de consumo",
            categoria=self.categoria,
            centro_custo=self.centro,
            valor=Decimal("25.00"),
            tipo="saida",
            usuario=self.gerente,
        )

        self.assertEqual(MovimentoFinanceiro.objects.filter(empresa=self.empresa).count(), 2)
        self.assertEqual(
            MovimentoFinanceiro.objects.get(chave_idempotencia=f"pagamento:{pagamento.id}").valor,
            Decimal("125.00"),
        )

    def test_estorno_preserva_original_e_cria_contramovimento(self):
        pagamento = Pagamento.objects.create(
            empresa=self.empresa,
            caixa=self.caixa,
            valor=Decimal("80.00"),
            metodo="dinheiro",
        )
        original = MovimentoFinanceiro.objects.get(chave_idempotencia=f"pagamento:{pagamento.id}")
        estorno = estornar_movimento_financeiro(
            movimento=original,
            motivo="Pagamento lançado em duplicidade",
            usuario=self.gerente,
        )
        original.refresh_from_db()

        self.assertEqual(original.status, "estornado")
        self.assertEqual(estorno.tipo, "saida")
        self.assertEqual(estorno.valor, original.valor)
        self.assertEqual(estorno.estorno_de, original)
        with self.assertRaises(ValidationError):
            original.delete()
        with self.assertRaises(ValidationError):
            original.valor = Decimal("81.00")
            original.save()

    def test_exclusao_pagamento_estorna_livro_sem_apagar_historico(self):
        pagamento = Pagamento.objects.create(
            empresa=self.empresa,
            caixa=self.caixa,
            valor=Decimal("40.00"),
            metodo="pix",
        )
        pagamento_id = pagamento.id
        excluir_pagamento_com_justificativa(
            pagamento=pagamento,
            usuario=self.gerente,
            justificativa="Pagamento registrado no cliente incorreto",
        )

        self.assertFalse(Pagamento.objects.filter(pk=pagamento_id).exists())
        movimentos = MovimentoFinanceiro.objects.filter(empresa=self.empresa).order_by("id")
        self.assertEqual(movimentos.count(), 2)
        self.assertEqual(sum((m.valor if m.tipo == "entrada" else -m.valor for m in movimentos), Decimal("0.00")), Decimal("0.00"))

    def test_data_retroativa_exige_permissao_especifica(self):
        ontem = timezone.localdate() - timedelta(days=1)
        conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Conta retroativa livro",
            banco_nome="Banco Teste",
            numero="RETRO-1",
            data_saldo_inicial=ontem,
        )
        pix = FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="PIX retroativo livro",
            codigo="pix-retroativo-livro",
        )
        payload = {
            "descricao": "Despesa retroativa",
            "categoria": self.categoria.id,
            "centro_custo": self.centro.id,
            "valor": "30.00",
            "forma_pagamento": pix.id,
            "conta_bancaria": conta.id,
            "caixa": "",
            "data_competencia": ontem.isoformat(),
            "data_movimento": ontem.isoformat(),
        }
        self.client.force_login(self.atendente)
        resposta_negada = self.client.post(reverse("caixa:registrar_saida"), payload)
        self.assertEqual(resposta_negada.status_code, 200)
        self.assertFalse(LancamentoCaixa.objects.filter(descricao="Despesa retroativa").exists())

        self.atendente.perm_caixa_lancamento_retroativo = True
        self.atendente.save(update_fields=["perm_caixa_lancamento_retroativo"])
        resposta_permitida = self.client.post(reverse("caixa:registrar_saida"), payload)
        self.assertEqual(resposta_permitida.status_code, 302)
        saida = LancamentoCaixa.objects.get(descricao="Despesa retroativa")
        self.assertEqual(saida.data_competencia, ontem)
        self.assertEqual(saida.data_movimento, ontem)
        self.assertEqual(MovimentoFinanceiro.objects.get(origem_tipo="lancamento_caixa", origem_id=saida.id).registrado_por, self.atendente)

    def test_relatorio_alterna_caixa_e_competencia(self):
        hoje = timezone.localdate()
        competencia = hoje - timedelta(days=40)
        Pagamento.objects.create(
            empresa=self.empresa,
            caixa=self.caixa,
            valor=Decimal("90.00"),
            metodo="pix",
            data_competencia=competencia,
            data_movimento=hoje,
        )
        self.client.force_login(self.gerente)
        parametros = {
            "data_inicio": hoje.isoformat(),
            "data_fim": hoje.isoformat(),
            "todos_caixas": "1",
        }
        resposta_caixa = self.client.get(reverse("caixa:relatorios"), {**parametros, "regime_data": "movimento"})
        resposta_competencia = self.client.get(reverse("caixa:relatorios"), {**parametros, "regime_data": "competencia"})

        self.assertEqual(resposta_caixa.status_code, 200)
        self.assertEqual(resposta_caixa.context["pagamentos"].count(), 1)
        self.assertEqual(resposta_caixa.context["saldo_livro"], Decimal("90.00"))
        self.assertEqual(resposta_competencia.context["pagamentos"].count(), 0)
        self.assertEqual(resposta_competencia.context["saldo_livro"], Decimal("0.00"))


class TesourariaFaseDoisTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Banco", cnpj="22.333.444/0001-06")
        self.usuario = get_user_model().objects.create_user(username="gerente_banco", password="senha-forte-123", tipo_usuario="gerente", empresa=self.empresa)
        self.caixa = Caixa.objects.create(empresa=self.empresa, saldo_inicial=Decimal("100.00"))
        self.conta_a = ContaBancaria.objects.create(empresa=self.empresa, nome="Principal", banco_nome="Banco A", numero="100-1", saldo_inicial=Decimal("50.00"))
        self.conta_b = ContaBancaria.objects.create(empresa=self.empresa, nome="Reserva", banco_nome="Banco B", numero="200-2")

    def test_pagamento_vinculado_a_forma_gera_movimento_bancario(self):
        forma = FormaPagamento.objects.create(empresa=self.empresa, nome="PIX Banco", codigo="pix-banco", conta_bancaria_liquidacao=self.conta_a)
        pagamento = Pagamento.objects.create(empresa=self.empresa, caixa=self.caixa, valor=Decimal("75.00"), forma_pagamento=forma, metodo="pix")
        movimento = MovimentoBancario.objects.get(origem_tipo="pagamento", origem_id=pagamento.id)
        self.assertEqual(movimento.conta, self.conta_a)
        self.assertEqual(self.conta_a.saldo_atual, Decimal("125.00"))
        pagamento.save(update_fields=["observacao"])
        self.assertEqual(MovimentoBancario.objects.filter(origem_tipo="pagamento", origem_id=pagamento.id).count(), 1)

    def test_pagamento_conta_pagar_bancario_gera_saida_conciliavel_sem_reduzir_dinheiro(self):
        forma = FormaPagamento.objects.create(
            empresa=self.empresa, nome="PIX fornecedores", codigo="pix-fornecedores",
            conta_bancaria_liquidacao=self.conta_a,
        )
        conta = ContaPagar.objects.create(
            empresa=self.empresa, fornecedor="Fornecedor XML", descricao="Compra de mercadorias",
            valor_total=Decimal("80.00"), vencimento=timezone.localdate(),
        )
        self.caixa.aberto = False
        self.caixa.save(update_fields=["aberto"])
        self.client.force_login(self.usuario)
        resposta = self.client.post(
            reverse("caixa:detalhe_conta_pagar", args=[conta.id]),
            {"valor": "80.00", "forma_pagamento": forma.id, "referencia": "PIX-123", "observacao": "Quitação"},
        )
        self.assertEqual(resposta.status_code, 302)
        pagamento = PagamentoContaPagar.objects.get(conta=conta)
        self.assertIsNone(pagamento.caixa_id)
        movimento = MovimentoBancario.objects.get(origem_tipo="conta_pagar", origem_id=pagamento.id)
        self.assertEqual(movimento.tipo, "saida")
        self.assertEqual(movimento.valor, Decimal("80.00"))
        self.assertEqual(movimento.conta, self.conta_a)
        self.assertTrue(MovimentoFinanceiro.objects.filter(origem_tipo="conta_pagar", origem_id=pagamento.id).exists())
        self.assertFalse(LancamentoCaixa.objects.filter(descricao=f"Pagamento conta a pagar #{conta.id}").exists())
        relatorio = self.client.get(
            reverse("caixa:relatorios"),
            {
                "data_inicio": timezone.localdate().isoformat(),
                "data_fim": timezone.localdate().isoformat(),
                "todos_caixas": "1",
            },
        )
        self.assertEqual(relatorio.status_code, 200)
        self.assertEqual(relatorio.context["total_saidas"], Decimal("80.00"))
        self.assertEqual(relatorio.context["pagamentos_contas_bancarios"].count(), 1)

    def test_detalhe_conta_pagar_nao_vaza_entre_empresas(self):
        outra_empresa = Empresa.objects.create(nome="Empresa externa", cnpj="33.444.555/0001-70")
        conta = ContaPagar.objects.create(
            empresa=outra_empresa, fornecedor="Outro", descricao="Conta externa",
            valor_total=Decimal("10.00"), vencimento=timezone.localdate(),
        )
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("caixa:detalhe_conta_pagar", args=[conta.id])).status_code, 404)

    def test_cartao_agenda_liquidacao_liquida_sem_antecipar_saldo_realizado(self):
        forma = FormaPagamento.objects.create(empresa=self.empresa, nome="Cartão Banco", codigo="cartao-banco", conta_bancaria_liquidacao=self.conta_a, taxa_percentual=Decimal("2.00"), dias_recebimento=30)
        pagamento = Pagamento.objects.create(empresa=self.empresa, caixa=self.caixa, valor=Decimal("100.00"), forma_pagamento=forma, metodo="cartao")
        movimento = MovimentoBancario.objects.get(origem_tipo="pagamento", origem_id=pagamento.id)
        self.assertEqual(movimento.valor, Decimal("98.00"))
        self.assertEqual(movimento.data_movimento, timezone.localdate() + timedelta(days=30))
        self.assertEqual(self.conta_a.saldo_atual, Decimal("50.00"))
        self.assertEqual(self.conta_a.saldo_projetado, Decimal("148.00"))

    def test_transferencia_banco_banco_e_caixa_banco_nao_gera_receita_despesa(self):
        registrar_transferencia(empresa=self.empresa, valor=Decimal("20.00"), data_movimento=timezone.localdate(), chave="transf-bancos-1", usuario=self.usuario, conta_origem=self.conta_a, conta_destino=self.conta_b)
        registrar_transferencia(empresa=self.empresa, valor=Decimal("30.00"), data_movimento=timezone.localdate(), chave="transf-caixa-1", usuario=self.usuario, caixa_origem=self.caixa, conta_destino=self.conta_a)
        self.assertEqual(TransferenciaTesouraria.objects.count(), 2)
        self.assertEqual(MovimentoFinanceiro.objects.count(), 0)
        lancamento = LancamentoCaixa.objects.get(natureza="transferencia")
        self.assertEqual(lancamento.tipo, "saida")
        self.assertEqual(self.conta_a.saldo_atual, Decimal("60.00"))
        self.assertEqual(self.conta_b.saldo_atual, Decimal("20.00"))

    def test_importacao_e_conciliacao_sao_idempotentes(self):
        movimento = MovimentoBancario.objects.create(empresa=self.empresa, conta=self.conta_a, tipo="entrada", origem_tipo="manual", descricao="Crédito teste", valor=Decimal("100.00"), data_movimento=timezone.localdate(), chave_idempotencia="credito-100")
        csv_data = f"data;descricao;valor;identificador\n{timezone.localdate():%d/%m/%Y};Crédito teste;100,00;linha-001\n".encode()
        self.assertEqual(len(importar_extrato_csv(conta=self.conta_a, conteudo=csv_data, usuario=self.usuario)), 1)
        self.assertEqual(len(importar_extrato_csv(conta=self.conta_a, conteudo=csv_data, usuario=self.usuario)), 0)
        linha = LinhaExtratoBancario.objects.get(identificador_externo="linha-001")
        conciliar_linha(linha=linha, movimento=movimento, usuario=self.usuario)
        linha.refresh_from_db()
        self.assertEqual(linha.status, "conciliado")
        with self.assertRaises(ValidationError):
            conciliar_linha(linha=linha, movimento=movimento, usuario=self.usuario)

    def test_conciliacao_agrupada_um_para_muitos(self):
        linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa,
            conta=self.conta_a,
            identificador_externo="grupo-1",
            data_movimento=timezone.localdate(),
            descricao="Recebimentos agrupados",
            valor=Decimal("100.00"),
        )
        movimentos = [
            MovimentoBancario.objects.create(
                empresa=self.empresa, conta=self.conta_a, tipo="entrada", origem_tipo="manual",
                descricao="Parcela A", valor=Decimal("40.00"), data_movimento=timezone.localdate(),
                chave_idempotencia="grupo-mov-a",
            ),
            MovimentoBancario.objects.create(
                empresa=self.empresa, conta=self.conta_a, tipo="entrada", origem_tipo="manual",
                descricao="Parcela B", valor=Decimal("60.00"), data_movimento=timezone.localdate(),
                chave_idempotencia="grupo-mov-b",
            ),
        ]
        conciliacao = conciliar_grupo(linhas=[linha], movimentos=movimentos, usuario=self.usuario)
        linha.refresh_from_db()
        self.assertEqual(conciliacao.status, "conciliado")
        self.assertEqual(conciliacao.total_extrato, Decimal("100.00"))
        self.assertEqual(conciliacao.itens_movimento.count(), 2)
        self.assertIsNone(linha.movimento)

    def test_conciliacao_agrupada_muitos_para_um(self):
        linhas = [
            LinhaExtratoBancario.objects.create(
                empresa=self.empresa, conta=self.conta_a, identificador_externo=f"grupo-linha-{indice}",
                data_movimento=timezone.localdate(), descricao=f"Linha {indice}", valor=valor,
            )
            for indice, valor in enumerate((Decimal("35.00"), Decimal("65.00")), start=1)
        ]
        movimento = MovimentoBancario.objects.create(
            empresa=self.empresa, conta=self.conta_a, tipo="entrada", origem_tipo="manual",
            descricao="Lote único", valor=Decimal("100.00"), data_movimento=timezone.localdate(),
            chave_idempotencia="grupo-mov-unico",
        )
        conciliacao = conciliar_grupo(linhas=linhas, movimentos=[movimento], usuario=self.usuario)
        self.assertEqual(conciliacao.itens_extrato.count(), 2)
        self.assertFalse(LinhaExtratoBancario.objects.filter(pk__in=[item.pk for item in linhas], status="pendente").exists())
        self.assertTrue(all(item.movimento_id == movimento.id for item in LinhaExtratoBancario.objects.filter(pk__in=[item.pk for item in linhas])))

    def test_divergencia_exige_justificativa_e_desfazimento_preserva_auditoria(self):
        linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa, conta=self.conta_a, identificador_externo="grupo-divergente",
            data_movimento=timezone.localdate(), descricao="Crédito com diferença", valor=Decimal("101.00"),
        )
        movimento = MovimentoBancario.objects.create(
            empresa=self.empresa, conta=self.conta_a, tipo="entrada", origem_tipo="manual",
            descricao="Crédito sistema", valor=Decimal("100.00"), data_movimento=timezone.localdate(),
            chave_idempotencia="grupo-divergente-mov",
        )
        with self.assertRaises(ValidationError):
            conciliar_grupo(linhas=[linha], movimentos=[movimento], usuario=self.usuario)
        conciliacao = conciliar_grupo(
            linhas=[linha], movimentos=[movimento], usuario=self.usuario, justificativa="Tarifa bancária não lançada"
        )
        self.assertEqual(conciliacao.status, "divergente")
        self.assertEqual(conciliacao.diferenca, Decimal("1.00"))
        desfazer_conciliacao(conciliacao=conciliacao, usuario=self.usuario, motivo="Correspondência incorreta")
        conciliacao.refresh_from_db()
        linha.refresh_from_db()
        self.assertEqual(conciliacao.status, "desfeito")
        self.assertEqual(conciliacao.itens_extrato.count(), 1)
        self.assertEqual(conciliacao.itens_movimento.count(), 1)
        self.assertEqual(linha.status, "pendente")
        nova = conciliar_grupo(
            linhas=[linha], movimentos=[movimento], usuario=self.usuario, justificativa="Diferença confirmada"
        )
        self.assertNotEqual(nova.pk, conciliacao.pk)

    def test_conciliacao_agrupada_bloqueia_empresa_conta_e_reuso_ativos(self):
        outra_empresa = Empresa.objects.create(nome="Outra Empresa", cnpj="11.222.333/0001-81")
        outra_conta = ContaBancaria.objects.create(empresa=outra_empresa, nome="Outra", banco_nome="Banco", numero="3")
        linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa, conta=self.conta_a, identificador_externo="grupo-isolado",
            data_movimento=timezone.localdate(), descricao="Linha", valor=Decimal("10.00"),
        )
        movimento_outra = MovimentoBancario.objects.create(
            empresa=outra_empresa, conta=outra_conta, tipo="entrada", origem_tipo="manual", descricao="Outro",
            valor=Decimal("10.00"), data_movimento=timezone.localdate(), chave_idempotencia="outro-mov",
        )
        with self.assertRaises(ValidationError):
            conciliar_grupo(linhas=[linha], movimentos=[movimento_outra], usuario=self.usuario)

        movimento = MovimentoBancario.objects.create(
            empresa=self.empresa, conta=self.conta_a, tipo="entrada", origem_tipo="manual", descricao="Correto",
            valor=Decimal("10.00"), data_movimento=timezone.localdate(), chave_idempotencia="correto-mov",
        )
        conciliar_grupo(linhas=[linha], movimentos=[movimento], usuario=self.usuario)
        nova_linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa, conta=self.conta_a, identificador_externo="grupo-reuso",
            data_movimento=timezone.localdate(), descricao="Nova linha", valor=Decimal("10.00"),
        )
        with self.assertRaises(ValidationError):
            conciliar_grupo(linhas=[nova_linha], movimentos=[movimento], usuario=self.usuario)

