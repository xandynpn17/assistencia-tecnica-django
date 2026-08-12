from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from caixa.models import (
    Caixa,
    CategoriaFinanceira,
    CentroCusto,
    ContaBancaria,
    ContaPagar,
    FormaPagamento,
    LancamentoCaixa,
    LinhaExtratoBancario,
    MovimentoBancario,
    MovimentoFinanceiro,
    Pagamento,
    PagamentoContaPagar,
)
from caixa.services.reset_saidas import resetar_saidas_para_reconciliacao
from caixa.services.tesouraria import (
    conciliar_linha,
    criar_movimento_de_linha_extrato,
    registrar_movimento_bancario,
)
from configuracoes.models import Empresa


class ResetSaidasReconciliacaoTests(TestCase):
    def setUp(self):
        self.data = timezone.localdate()
        self.empresa = Empresa.objects.create(nome="Empresa Reset", cnpj="44.444.444/0001-44")
        self.usuario = get_user_model().objects.create_user(
            username="gestor_reset", password="senha-forte-123", tipo_usuario="gerente",
            empresa=self.empresa, perm_caixa_corrigir_lancamentos=True,
        )
        self.caixa = Caixa.objects.create(empresa=self.empresa, saldo_inicial=Decimal("100.00"))
        self.banco = ContaBancaria.objects.create(
            empresa=self.empresa, nome="Banco", banco_nome="Banco Teste", numero="1",
            saldo_inicial=Decimal("500.00"), data_saldo_inicial=self.data,
        )
        self.forma = FormaPagamento.objects.create(
            empresa=self.empresa, nome="PIX", codigo="pix-reset", tipo="avista"
        )
        self.categoria = CategoriaFinanceira.objects.create(
            empresa=self.empresa, nome="Despesa", tipo="saida"
        )
        self.centro = CentroCusto.objects.create(empresa=self.empresa, nome="Operacional")

    def test_reset_cancela_saidas_reabre_conta_e_devolve_extrato(self):
        LancamentoCaixa.objects.create(
            empresa=self.empresa, caixa=self.caixa, forma_pagamento=self.forma,
            categoria=self.categoria, centro_custo=self.centro, descricao="Saída manual",
            valor=Decimal("20.00"), tipo="saida", data_competencia=self.data,
            data_movimento=self.data, usuario=self.usuario,
        )
        conta = ContaPagar.objects.create(
            empresa=self.empresa, descricao="Conta fornecedor", valor_total=Decimal("30.00"),
            valor_pago=Decimal("30.00"), vencimento=self.data, data_competencia=self.data,
            status="paga", categoria=self.categoria, centro_custo=self.centro,
        )
        pagamento_conta = PagamentoContaPagar.objects.create(
            empresa=self.empresa, conta=conta, caixa=self.caixa, forma_pagamento=self.forma,
            valor=Decimal("30.00"), data_competencia=self.data, data_movimento=self.data,
            usuario=self.usuario, chave_idempotencia="reset-conta-1",
        )
        LancamentoCaixa.objects.create(
            empresa=self.empresa, caixa=self.caixa, pagamento_conta_pagar=pagamento_conta,
            forma_pagamento=self.forma, categoria=self.categoria, centro_custo=self.centro,
            descricao="Pagamento conta fornecedor", valor=Decimal("30.00"), tipo="saida",
            data_competencia=self.data, data_movimento=self.data, usuario=self.usuario,
        )
        linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa, conta=self.banco, identificador_externo="RESET-LINHA",
            data_movimento=self.data, descricao="Débito desconhecido", valor=Decimal("-10.00"),
        )
        movimento_extrato = registrar_movimento_bancario(
            conta=self.banco, tipo="saida", origem_tipo="manual", origem_id=linha.pk,
            descricao=linha.descricao, valor=Decimal("10.00"), data_movimento=self.data,
            chave=f"linha-extrato:{linha.pk}:movimento", usuario=self.usuario,
            metadados={"linha_extrato_id": linha.pk, "classificacao": "despesa_operacional"},
        )
        LancamentoCaixa.objects.create(
            empresa=self.empresa, conta_bancaria=self.banco, forma_pagamento=self.forma,
            categoria=self.categoria, centro_custo=self.centro, descricao=linha.descricao,
            valor=Decimal("10.00"), tipo="saida", data_competencia=self.data,
            data_movimento=self.data, usuario=self.usuario,
        )
        conciliar_linha(linha=linha, movimento=movimento_extrato, usuario=self.usuario)

        resultado = resetar_saidas_para_reconciliacao(
            empresa=self.empresa, usuario=self.usuario,
            motivo="Reinício auditado das saídas usando o extrato bancário.",
            quantidade_esperada=3, total_esperado=Decimal("60.00"),
        )

        self.assertEqual(resultado["total_cancelado"], Decimal("60.00"))
        self.assertEqual(LancamentoCaixa.objects.filter(empresa=self.empresa, tipo="saida").count(), 0)
        self.assertEqual(LancamentoCaixa.todos.filter(empresa=self.empresa, status="cancelado").count(), 3)
        linha.refresh_from_db()
        conta.refresh_from_db()
        pagamento_conta.refresh_from_db()
        self.assertEqual(linha.status, "pendente")
        self.assertEqual(conta.valor_pago, Decimal("0.00"))
        self.assertNotEqual(conta.status, "paga")
        self.assertEqual(pagamento_conta.status, "estornado")
        self.assertFalse(MovimentoBancario.objects.filter(empresa=self.empresa, status="ativo").exists())

    def test_liquidacao_cartao_nao_reconhece_receita_novamente(self):
        linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa, conta=self.banco, identificador_externo="CARTAO-1",
            data_movimento=self.data, descricao="Liquidação adquirente", valor=Decimal("65.00"),
        )
        movimento = criar_movimento_de_linha_extrato(
            linha=linha, classificacao="liquidacao_cartao", descricao=linha.descricao,
            usuario=self.usuario,
        )
        self.assertEqual(movimento.valor, Decimal("65.00"))
        self.assertEqual(LancamentoCaixa.objects.filter(empresa=self.empresa).count(), 0)
        self.assertEqual(MovimentoFinanceiro.objects.filter(empresa=self.empresa).count(), 0)

    def test_credito_extrato_pode_ser_vinculado_a_recebimento_existente_sem_duplicar_receita(self):
        pagamento = Pagamento.objects.create(
            empresa=self.empresa, caixa=self.caixa, valor=Decimal("65.00"),
            forma_pagamento=self.forma, metodo="pix", data_movimento=self.data,
        )
        lancamentos_antes = LancamentoCaixa.todos.filter(empresa=self.empresa).count()
        livro_antes = MovimentoFinanceiro.objects.filter(empresa=self.empresa).count()
        linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa, conta=self.banco, identificador_externo="PIX-65",
            data_movimento=self.data, descricao="PIX recebido", valor=Decimal("65.00"),
        )

        movimento = criar_movimento_de_linha_extrato(
            linha=linha, classificacao="recebimento_registrado", descricao=linha.descricao,
            pagamento=pagamento, usuario=self.usuario,
        )

        self.assertEqual(movimento.origem_tipo, "pagamento")
        self.assertEqual(movimento.origem_id, pagamento.pk)
        self.assertEqual(LancamentoCaixa.todos.filter(empresa=self.empresa).count(), lancamentos_antes)
        self.assertEqual(MovimentoFinanceiro.objects.filter(empresa=self.empresa).count(), livro_antes)
