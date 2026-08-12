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
from caixa.services.saneamento_lancamentos import (
    cancelar_lancamento_manual,
    corrigir_lancamento_manual,
    listar_duplicidades_importacao_extrato,
    neutralizar_duplicidade_importacao_extrato,
)
from caixa.services.tesouraria import conciliar_linha, registrar_movimento_bancario
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

    def test_edita_descricao_e_valor_com_estorno_do_valor_anterior(self):
        lancamento = self._lancamento_incorreto(valor="30.00")
        corrigir_lancamento_manual(
            lancamento=lancamento, forma_pagamento=self.pix, conta_bancaria=self.conta,
            caixa_destino=None, categoria=self.categoria, centro_custo=self.centro,
            data_competencia=self.ontem, data_movimento=self.ontem,
            descricao="Despesa corrigida", valor=Decimal("22.50"),
            motivo="Corre\u00e7\u00e3o do documento e do valor efetivamente pago.", usuario=self.usuario,
        )
        lancamento.refresh_from_db()
        self.assertEqual(lancamento.descricao, "Despesa corrigida")
        self.assertEqual(lancamento.valor, Decimal("22.50"))
        self.assertEqual(self.conta.saldo_atual, Decimal("477.50"))

    def test_cancelamento_preserva_historico_e_remove_efeito_financeiro(self):
        lancamento = LancamentoCaixa.objects.create(
            empresa=self.empresa, conta_bancaria=self.conta, forma_pagamento=self.pix,
            categoria=self.categoria, centro_custo=self.centro, descricao="Despesa duplicada",
            valor=Decimal("18.00"), tipo="saida", data_competencia=self.ontem,
            data_movimento=self.ontem, usuario=self.usuario,
        )
        self.assertEqual(self.conta.saldo_atual, Decimal("482.00"))
        correcao = cancelar_lancamento_manual(
            lancamento=lancamento, motivo="Lan\u00e7amento inserido duas vezes por engano.", usuario=self.usuario,
        )
        self.assertEqual(correcao.tipo, "cancelamento")
        self.assertFalse(LancamentoCaixa.objects.filter(pk=lancamento.pk).exists())
        cancelado = LancamentoCaixa.todos.get(pk=lancamento.pk)
        self.assertEqual(cancelado.status, "cancelado")
        self.assertEqual(self.conta.saldo_atual, Decimal("500.00"))
        self.assertEqual(
            MovimentoBancario.objects.filter(chave_idempotencia=f"lancamento_caixa:{lancamento.pk}").get().status,
            "neutralizado",
        )

    def test_identifica_e_neutraliza_somente_duplicidade_do_fluxo_antigo(self):
        from caixa.models import LinhaExtratoBancario

        linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa, conta=self.conta, identificador_externo="DUP-1",
            data_movimento=self.ontem, descricao="Tarifa antiga", valor=Decimal("-12.00"),
        )
        original = registrar_movimento_bancario(
            conta=self.conta, tipo="saida", origem_tipo="manual", origem_id=linha.pk,
            descricao="Tarifa antiga", valor=Decimal("12.00"), data_movimento=self.ontem,
            chave=f"linha-extrato:{linha.pk}:movimento", usuario=self.usuario,
        )
        lancamento = LancamentoCaixa.objects.create(
            empresa=self.empresa, conta_bancaria=self.conta, forma_pagamento=self.pix,
            categoria=self.categoria, centro_custo=self.centro, descricao="Tarifa antiga",
            valor=Decimal("12.00"), tipo="saida", data_competencia=self.ontem,
            data_movimento=self.ontem, usuario=self.usuario,
        )
        duplicado = MovimentoBancario.objects.get(chave_idempotencia=f"lancamento_caixa:{lancamento.pk}")
        conciliar_linha(linha=linha, movimento=original, usuario=self.usuario)
        pares = listar_duplicidades_importacao_extrato(self.empresa)
        self.assertEqual([item["duplicado"].pk for item in pares], [duplicado.pk])
        neutralizar_duplicidade_importacao_extrato(
            movimento=duplicado, usuario=self.usuario,
            motivo="Duplicidade comprovada gerada pelo fluxo antigo.",
        )
        duplicado.refresh_from_db()
        self.assertEqual(duplicado.status, "neutralizado")
        self.assertEqual(listar_duplicidades_importacao_extrato(self.empresa), [])

    def test_cancela_movimento_que_ja_havia_sido_corrigido(self):
        lancamento = self._lancamento_incorreto(valor="14.00")
        primeira = corrigir_lancamento_manual(
            lancamento=lancamento, forma_pagamento=self.pix, conta_bancaria=self.conta,
            caixa_destino=None, categoria=self.categoria, centro_custo=self.centro,
            data_competencia=self.ontem, data_movimento=self.ontem,
            motivo="A despesa ocorreu no banco e não no caixa de hoje.", usuario=self.usuario,
        )
        cancelar_lancamento_manual(
            lancamento=lancamento, motivo="O lançamento corrigido também estava duplicado.", usuario=self.usuario,
        )
        primeira.movimento_bancario_corrigido.refresh_from_db()
        primeira.movimento_financeiro_corrigido.refresh_from_db()
        self.assertEqual(primeira.movimento_bancario_corrigido.status, "neutralizado")
        self.assertEqual(primeira.movimento_financeiro_corrigido.status, "estornado")
        self.assertEqual(self.conta.saldo_atual, Decimal("500.00"))
