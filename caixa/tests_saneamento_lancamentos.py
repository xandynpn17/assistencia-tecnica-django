from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import (
    Caixa,
    CategoriaFinanceira,
    CentroCusto,
    ContaBancaria,
    CorrecaoLancamentoCaixa,
    FormaPagamento,
    LancamentoCaixa,
    MovimentoBancario,
    MovimentoFinanceiro,
)
from caixa.services.saneamento_lancamentos import corrigir_lancamento_manual
from configuracoes.models import Empresa


class SaneamentoLancamentosRetroativosTests(TestCase):
    def setUp(self):
        self.hoje = timezone.localdate()
        self.ontem = self.hoje - timedelta(days=1)
        self.empresa = Empresa.objects.create(nome="Empresa Saneamento", cnpj="77.777.777/0001-77")
        self.usuario = get_user_model().objects.create_user(
            username="gestor_saneamento",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
            perm_caixa_lancamento_retroativo=True,
            perm_caixa_corrigir_lancamentos=True,
        )
        self.categoria = CategoriaFinanceira.objects.create(
            empresa=self.empresa, nome="Despesas diversas", tipo="saida"
        )
        self.centro = CentroCusto.objects.create(
            empresa=self.empresa, nome="Administrativo", tipo="variavel"
        )
        self.dinheiro = FormaPagamento.objects.create(
            empresa=self.empresa, nome="Dinheiro", codigo="dinheiro", tipo="avista"
        )
        self.pix = FormaPagamento.objects.create(
            empresa=self.empresa, nome="PIX", codigo="pix", tipo="avista"
        )
        self.conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Banco operacional",
            banco_nome="Banco Teste",
            numero="123",
            saldo_inicial=Decimal("500.00"),
            data_saldo_inicial=self.ontem,
        )
        self.caixa_atual = Caixa.objects.create(empresa=self.empresa, saldo_inicial=Decimal("100.00"))
        self.client.force_login(self.usuario)

    def _lancamento_incorreto(self, valor="30.00"):
        return LancamentoCaixa.objects.create(
            empresa=self.empresa,
            caixa=self.caixa_atual,
            forma_pagamento=self.dinheiro,
            categoria=self.categoria,
            centro_custo=self.centro,
            descricao="Despesa retroativa vinculada ao caixa atual",
            valor=Decimal(valor),
            tipo="saida",
            data_competencia=self.ontem,
            data_movimento=self.ontem,
            usuario=self.usuario,
        )

    def test_nova_saida_retroativa_em_dinheiro_nao_usa_caixa_atual(self):
        response = self.client.post(
            reverse("caixa:registrar_saida"),
            {
                "descricao": "Despesa antiga em dinheiro",
                "categoria": self.categoria.pk,
                "centro_custo": self.centro.pk,
                "valor": "20.00",
                "forma_pagamento": self.dinheiro.pk,
                "caixa": self.caixa_atual.pk,
                "conta_bancaria": "",
                "data_competencia": self.ontem.isoformat(),
                "data_movimento": self.ontem.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "deve pertencer ao caixa da mesma data")
        self.assertFalse(LancamentoCaixa.objects.filter(descricao="Despesa antiga em dinheiro").exists())

    def test_corrige_saida_do_caixa_atual_para_banco_com_auditoria(self):
        lancamento = self._lancamento_incorreto()
        movimento_original = MovimentoFinanceiro.objects.get(
            chave_idempotencia=f"lancamento_caixa:{lancamento.pk}"
        )

        correcao = corrigir_lancamento_manual(
            lancamento=lancamento,
            forma_pagamento=self.pix,
            conta_bancaria=self.conta,
            caixa_destino=None,
            categoria=self.categoria,
            centro_custo=self.centro,
            data_competencia=self.ontem,
            data_movimento=self.ontem,
            motivo="A despesa foi paga por PIX no dia anterior.",
            usuario=self.usuario,
        )

        lancamento.refresh_from_db()
        movimento_original.refresh_from_db()
        self.assertIsNone(lancamento.caixa_id)
        self.assertEqual(lancamento.conta_bancaria, self.conta)
        self.assertEqual(movimento_original.status, "estornado")
        self.assertEqual(correcao.movimento_financeiro_corrigido.caixa_id, None)
        self.assertIsNotNone(correcao.movimento_bancario_corrigido_id)
        self.assertEqual(self.conta.saldo_atual, Decimal("470.00"))
        self.assertFalse(self.caixa_atual.lancamentos.filter(pk=lancamento.pk).exists())
        self.assertEqual(CorrecaoLancamentoCaixa.objects.filter(lancamento=lancamento).count(), 1)

    def test_corrige_entrada_manual_retroativa_sem_afetar_caixa_atual(self):
        categoria_entrada = CategoriaFinanceira.objects.create(
            empresa=self.empresa, nome="Receita avulsa", tipo="entrada"
        )
        lancamento = LancamentoCaixa.objects.create(
            empresa=self.empresa,
            caixa=self.caixa_atual,
            forma_pagamento=self.dinheiro,
            categoria=categoria_entrada,
            centro_custo=self.centro,
            descricao="Entrada retroativa vinculada ao caixa atual",
            valor=Decimal("25.00"),
            tipo="entrada",
            data_competencia=self.ontem,
            data_movimento=self.ontem,
            usuario=self.usuario,
        )
        corrigir_lancamento_manual(
            lancamento=lancamento,
            forma_pagamento=self.pix,
            conta_bancaria=self.conta,
            caixa_destino=None,
            categoria=categoria_entrada,
            centro_custo=self.centro,
            data_competencia=self.ontem,
            data_movimento=self.ontem,
            motivo="A entrada ocorreu via PIX no dia anterior.",
            usuario=self.usuario,
        )
        lancamento.refresh_from_db()
        self.assertIsNone(lancamento.caixa_id)
        self.assertEqual(lancamento.conta_bancaria, self.conta)
        self.assertEqual(self.conta.saldo_atual, Decimal("525.00"))
        self.assertFalse(self.caixa_atual.lancamentos.filter(pk=lancamento.pk).exists())

    def test_move_para_caixa_historico_e_recalcula_fechamento(self):
        Caixa.objects.filter(pk=self.caixa_atual.pk).update(
            aberto=False, data=self.ontem - timedelta(days=1)
        )
        caixa_historico = Caixa.objects.create(
            empresa=self.empresa,
            aberto=False,
            saldo_inicial=Decimal("100.00"),
            saldo_final=Decimal("100.00"),
            valor_contado_fisico=Decimal("90.00"),
            diferenca_fechamento=Decimal("0.00"),
        )
        Caixa.objects.filter(pk=caixa_historico.pk).update(data=self.ontem)
        caixa_historico.refresh_from_db()
        Caixa.objects.filter(pk=self.caixa_atual.pk).update(aberto=True)
        self.caixa_atual.refresh_from_db()
        lancamento = self._lancamento_incorreto(valor="10.00")

        corrigir_lancamento_manual(
            lancamento=lancamento,
            forma_pagamento=self.dinheiro,
            conta_bancaria=None,
            caixa_destino=caixa_historico,
            categoria=self.categoria,
            centro_custo=self.centro,
            data_competencia=self.ontem,
            data_movimento=self.ontem,
            motivo="Pagamento realmente realizado em dinheiro no caixa histórico.",
            usuario=self.usuario,
        )

        lancamento.refresh_from_db()
        caixa_historico.refresh_from_db()
        self.assertEqual(lancamento.caixa, caixa_historico)
        self.assertEqual(caixa_historico.saldo_final, Decimal("90.00"))
        self.assertEqual(caixa_historico.diferenca_fechamento, Decimal("10.00"))

    def test_tela_lista_inconsistencia_e_exige_permissao(self):
        lancamento = self._lancamento_incorreto()
        response = self.client.get(reverse("caixa:saneamento_lancamentos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{lancamento.pk}")

        atendente = get_user_model().objects.create_user(
            username="atendente_sem_saneamento",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
            acesso_caixa_financeiro_extra=True,
        )
        self.client.force_login(atendente)
        response = self.client.get(reverse("caixa:saneamento_lancamentos"))
        self.assertEqual(response.status_code, 403)

    def test_correcao_bancaria_cria_contrapartida_ao_reclassificar_novamente(self):
        lancamento = self._lancamento_incorreto(valor="15.00")
        primeira = corrigir_lancamento_manual(
            lancamento=lancamento,
            forma_pagamento=self.pix,
            conta_bancaria=self.conta,
            caixa_destino=None,
            categoria=self.categoria,
            centro_custo=self.centro,
            data_competencia=self.ontem,
            data_movimento=self.ontem,
            motivo="Primeira correção para a conta bancária operacional.",
            usuario=self.usuario,
        )
        outra_conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Banco correto",
            banco_nome="Outro Banco",
            numero="456",
            saldo_inicial=Decimal("200.00"),
            data_saldo_inicial=self.ontem,
        )
        segunda = corrigir_lancamento_manual(
            lancamento=lancamento,
            forma_pagamento=self.pix,
            conta_bancaria=outra_conta,
            caixa_destino=None,
            categoria=self.categoria,
            centro_custo=self.centro,
            data_competencia=self.ontem,
            data_movimento=self.ontem,
            motivo="A primeira conta informada estava incorreta; usar o outro banco.",
            usuario=self.usuario,
        )
        self.assertIsNotNone(segunda.movimento_bancario_estorno_id)
        self.assertEqual(self.conta.saldo_atual, Decimal("500.00"))
        self.assertEqual(outra_conta.saldo_atual, Decimal("185.00"))
        self.assertEqual(MovimentoBancario.objects.filter(origem_id=segunda.pk, origem_tipo="manual").count(), 2)
        self.assertNotEqual(primeira.pk, segunda.pk)
