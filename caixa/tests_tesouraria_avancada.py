from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from caixa.models import (
    AporteCapital, CartaoCorporativo, CategoriaFinanceira, CentroCusto, ContaBancaria,
    LancamentoCaixa, MovimentoBancario, MovimentoSocio,
)
from caixa.services.cartoes_corporativos import pagar_fatura_cartao, registrar_compra_cartao
from caixa.services.contabilidade import ativar_plano_contas, criar_plano_contas_gerencial
from caixa.services.tesouraria import (
    conciliar_linha, criar_movimento_de_linha_extrato, fechar_periodo_bancario, importar_extrato_arquivo, registrar_aporte_capital,
    movimentos_bancarios_disponiveis, registrar_movimento_bancario, registrar_movimento_socio,
)
from configuracoes.models import Empresa


class TesourariaAvancadaTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Tesouraria Avançada", cnpj="98.765.432/0001-10")
        self.usuario = get_user_model().objects.create_user(
            username="gestor_tesouraria", password="senha-123", tipo_usuario="gerente", empresa=self.empresa,
        )
        self.banco = ContaBancaria.objects.create(
            empresa=self.empresa, nome="Conta Principal", banco_nome="Banco Teste", numero="123",
            saldo_inicial=Decimal("1000.00"), data_saldo_inicial=date(2026, 1, 1),
        )
        self.categoria = CategoriaFinanceira.objects.create(empresa=self.empresa, nome="Materiais", tipo="saida")
        self.centro = CentroCusto.objects.create(empresa=self.empresa, nome="Administrativo")

    def test_telas_novas_renderizam_para_gestor(self):
        self.client.force_login(self.usuario)
        for rota in ("caixa:cartoes_corporativos", "caixa:tesouraria", "caixa:contabilidade_gerencial"):
            resposta = self.client.get(reverse(rota))
            self.assertEqual(resposta.status_code, 200, rota)

    def test_cartao_parcelado_reconhece_compra_e_banco_so_na_fatura(self):
        cartao = CartaoCorporativo.objects.create(
            empresa=self.empresa, nome="Corporativo", emissor="Banco Teste", final="1234",
            dia_fechamento=20, dia_vencimento=28, conta_pagamento_padrao=self.banco,
        )
        compra = registrar_compra_cartao(
            cartao=cartao, data_compra=date(2026, 3, 10), data_competencia=date(2026, 3, 10),
            fornecedor="Fornecedor", descricao="Insumos", valor_total="100.00", quantidade_parcelas=3,
            categoria=self.categoria, centro_custo=self.centro, usuario=self.usuario, chave="compra-cartao-1",
        )
        self.assertEqual(list(compra.parcelas.values_list("valor", flat=True)), [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")])
        self.assertEqual(MovimentoBancario.objects.count(), 0)
        fatura = compra.parcelas.order_by("numero").first().fatura
        pagamento = pagar_fatura_cartao(
            fatura=fatura, conta_bancaria=self.banco, data_movimento=date(2026, 3, 28),
            valor=fatura.saldo_aberto, referencia="FAT-03", usuario=self.usuario, chave="paga-fatura-1",
        )
        self.assertEqual(MovimentoBancario.objects.filter(tipo="saida").count(), 1)
        self.assertEqual(pagamento.valor, Decimal("33.33"))

    def test_lote_extrato_idempotente_e_fechamento_bloqueia_periodo(self):
        conteudo = b"data;descricao;valor;identificador\n2026-03-01;Saldo inicial;0,00;L1\n"
        criadas = importar_extrato_arquivo(
            conta=self.banco, conteudo=conteudo, nome_arquivo="marco.csv", usuario=self.usuario,
        )
        criadas[0].status = "ignorado"
        criadas[0].justificativa = "Linha informativa de saldo"
        criadas[0].save(update_fields=["status", "justificativa"])
        self.assertEqual(importar_extrato_arquivo(
            conta=self.banco, conteudo=conteudo, nome_arquivo="marco.csv", usuario=self.usuario,
        ), [])
        fechamento = fechar_periodo_bancario(
            conta=self.banco, periodo_inicio=date(2026, 3, 1), periodo_fim=date(2026, 3, 31),
            saldo_extrato=Decimal("1000.00"), usuario=self.usuario,
        )
        self.assertEqual(fechamento.diferenca, Decimal("0.00"))
        with self.assertRaises(ValidationError):
            registrar_movimento_bancario(
                conta=self.banco, tipo="saida", origem_tipo="manual", origem_id=None,
                descricao="Movimento tardio", valor=Decimal("10.00"), data_movimento=date(2026, 3, 15),
                chave="movimento-em-periodo-fechado", usuario=self.usuario,
            )

    def test_linha_desconhecida_vira_despesa_somente_com_classificacao_humana(self):
        linha = importar_extrato_arquivo(
            conta=self.banco,
            conteudo=b"data;descricao;valor;identificador\n2026-06-10;Tarifa mensal;-15,00;TAR1\n",
            nome_arquivo="junho.csv", usuario=self.usuario,
        )[0]
        movimento = criar_movimento_de_linha_extrato(
            linha=linha, classificacao="tarifa", descricao="Tarifa bancária mensal",
            usuario=self.usuario, categoria=self.categoria, centro_custo=self.centro,
        )
        conciliar_linha(linha=linha, movimento=movimento, usuario=self.usuario)
        linha.refresh_from_db()
        self.assertEqual(linha.status, "conciliado")
        self.assertEqual(movimento.tipo, "saida")
        self.assertEqual(
            MovimentoBancario.objects.filter(origem_tipo="lancamento_caixa", origem_id=movimento.origem_id).count(),
            1,
        )
        self.assertFalse(movimentos_bancarios_disponiveis().filter(pk=movimento.pk).exists())

    def test_movimento_ja_conciliado_nao_reaparece_e_post_antigo_nao_gera_500(self):
        self.client.force_login(self.usuario)
        linha = importar_extrato_arquivo(
            conta=self.banco,
            conteudo=b"data;descricao;valor;identificador\n2026-06-11;PIX venda;65,00;PIX65\n",
            nome_arquivo="pix.csv", usuario=self.usuario,
        )[0]
        lancamento = LancamentoCaixa.objects.create(
            empresa=self.empresa, conta_bancaria=self.banco, descricao="Venda de estoque via PIX",
            valor=Decimal("65.00"), tipo="entrada", data_competencia=linha.data_movimento,
            data_movimento=linha.data_movimento, usuario=self.usuario,
        )
        movimento = MovimentoBancario.objects.get(chave_idempotencia=f"lancamento_caixa:{lancamento.pk}")
        conciliar_linha(linha=linha, movimento=movimento, usuario=self.usuario)

        self.assertFalse(movimentos_bancarios_disponiveis().filter(pk=movimento.pk).exists())
        resposta = self.client.post(
            reverse("caixa:tratar_linha_extrato", args=[linha.pk]),
            {"movimento": movimento.pk, "justificativa": ""},
        )
        self.assertEqual(resposta.status_code, 200)
        linha.refresh_from_db()
        self.assertEqual(linha.status, "conciliado")

    def test_devolucao_de_afac_reduz_principal_sem_receita_operacional(self):
        aporte = registrar_aporte_capital(
            empresa=self.empresa, tipo="adiantamento_socio", descricao="AFAC inicial",
            aportante="Sócio A", documento_referencia="DOC-1", valor=Decimal("500.00"),
            data_competencia=date(2026, 2, 1), data_movimento=date(2026, 2, 1),
            conta_bancaria=self.banco, caixa=None, chave="aporte-afac-1", usuario=self.usuario,
        )
        saida = registrar_movimento_socio(
            aporte=aporte, tipo="devolucao_afac", descricao="Devolução parcial",
            valor=Decimal("200.00"), data_competencia=date(2026, 4, 1), data_movimento=date(2026, 4, 1),
            conta_bancaria=self.banco, caixa=None, documento_referencia="DOC-2", comprovante=None,
            chave="devolve-afac-1", usuario=self.usuario,
        )
        self.assertEqual(saida.natureza_resultado, "capital")
        self.assertEqual(MovimentoSocio.objects.get(pk=saida.pk).valor, Decimal("200.00"))
        self.assertEqual(AporteCapital.objects.get(pk=aporte.pk).movimentos_saida.count(), 1)
        with self.assertRaises(ValidationError):
            registrar_movimento_socio(
                aporte=aporte, tipo="devolucao_afac", descricao="Excesso", valor=Decimal("301.00"),
                data_competencia=date(2026, 4, 2), data_movimento=date(2026, 4, 2),
                conta_bancaria=self.banco, caixa=None, documento_referencia="", comprovante=None,
                chave="devolve-afac-excesso", usuario=self.usuario,
            )

    def test_plano_contabil_so_gera_lote_depois_de_validado_e_balanceado(self):
        from caixa.models import LoteContabil

        plano = criar_plano_contas_gerencial(empresa=self.empresa, usuario=self.usuario)
        cartao = CartaoCorporativo.objects.create(
            empresa=self.empresa, nome="Cartão Contábil", emissor="Banco", final="9876",
            dia_fechamento=20, dia_vencimento=28,
        )
        registrar_compra_cartao(
            cartao=cartao, data_compra=date(2026, 5, 1), data_competencia=date(2026, 5, 1),
            fornecedor="Fornecedor A", descricao="Compra antes da ativação", valor_total="50.00",
            quantidade_parcelas=1, categoria=self.categoria, centro_custo=self.centro,
            usuario=self.usuario, chave="compra-sem-contabil",
        )
        self.assertEqual(LoteContabil.objects.count(), 0)
        ativar_plano_contas(plano=plano, observacao_validacao="Validado em ambiente de teste pelo responsável contábil")
        registrar_compra_cartao(
            cartao=cartao, data_compra=date(2026, 5, 2), data_competencia=date(2026, 5, 2),
            fornecedor="Fornecedor B", descricao="Compra contabilizada", valor_total="75.00",
            quantidade_parcelas=1, categoria=self.categoria, centro_custo=self.centro,
            usuario=self.usuario, chave="compra-com-contabil",
        )
        lote = LoteContabil.objects.get(evento="compra_cartao")
        self.assertEqual(lote.total_debitos, Decimal("75.00"))
        self.assertEqual(lote.total_creditos, Decimal("75.00"))
