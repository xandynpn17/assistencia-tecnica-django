from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from configuracoes.models import Empresa

from .models import (
    ClassificacaoPessoaFinanceira,
    ContaBancaria,
    ContaInvestimento,
    EstornoFinanceiroVinculado,
    MovimentoBancario,
    MovimentoFinanceiro,
    MovimentoPessoaFinanceira,
    PessoaFinanceira,
    TransacaoAdquirente,
)
from .services.livro_financeiro import registrar_movimento_financeiro
from .services.patrimonio import (
    aprovar_classificacao_pessoa,
    classificar_movimento_pessoa,
    registrar_estorno_vinculado,
    registrar_movimento_investimento,
    registrar_movimento_pessoa,
    vincular_estorno_pendente,
)
from .services.tesouraria import importar_extrato_arquivo


class PatrimonioFinanceiroTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Patrimônio", cnpj="12.111.222/0001-10")
        self.usuario = get_user_model().objects.create_user(
            username="gestor_patrimonio", password="senha-123", tipo_usuario="gerente", empresa=self.empresa,
        )
        self.banco = ContaBancaria.objects.create(
            empresa=self.empresa, nome="Nubank", banco_nome="Nubank", numero="123",
            saldo_inicial=Decimal("1000.00"), data_saldo_inicial=date(2026, 1, 1),
        )
        self.alexandre = PessoaFinanceira.objects.create(
            empresa=self.empresa, nome="Alexandre", tipo="socio", inicio_vinculo=date(2026, 1, 1),
        )
        self.diana = PessoaFinanceira.objects.create(
            empresa=self.empresa, nome="Diana", tipo="relacionada", inicio_vinculo=date(2026, 1, 1),
        )

    def test_tela_renderiza_sem_alterar_fluxo_rapido(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("caixa:patrimonio_financeiro"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Pessoas, investimentos e estornos")

    def test_saida_nunca_pode_ser_aporte(self):
        with self.assertRaisesRegex(ValidationError, "Aporte representa entrada"):
            registrar_movimento_pessoa(
                empresa=self.empresa, pessoa=self.alexandre, direcao="pessoa_deve",
                natureza="aporte_capital", valor="100.00", data_competencia=date(2026, 10, 1),
                data_movimento=date(2026, 10, 1), descricao="Tentativa inválida",
                conta_bancaria=self.banco, chave="aporte-saida-invalido", usuario=self.usuario,
            )
        self.assertFalse(MovimentoBancario.objects.exists())

    def test_retirada_idempotente_e_fora_da_dre_operacional(self):
        kwargs = dict(
            empresa=self.empresa, pessoa=self.alexandre, direcao="pessoa_deve",
            natureza="retirada_classificar", valor="200.00", data_competencia=date(2026, 10, 1),
            data_movimento=date(2026, 10, 1), descricao="Retirada semanal Alexandre",
            conta_bancaria=self.banco, chave="retirada-alexandre-1", usuario=self.usuario,
        )
        primeiro = registrar_movimento_pessoa(**kwargs)
        segundo = registrar_movimento_pessoa(**kwargs)
        self.assertEqual(primeiro.pk, segundo.pk)
        self.assertEqual(MovimentoBancario.objects.filter(origem_id=primeiro.pk).count(), 1)
        livro = MovimentoFinanceiro.objects.get(origem_id=primeiro.pk, chave_idempotencia=f"pessoa_financeira:{primeiro.pk}")
        self.assertEqual(livro.natureza, "capital")

    def test_movimento_bancario_antigo_e_classificado_sem_duplicar_saldo(self):
        banco_antigo = MovimentoBancario.objects.create(
            empresa=self.empresa, conta=self.banco, tipo="saida", origem_tipo="manual",
            descricao="Transferência antiga para Alexandre", valor=Decimal("150.00"),
            data_movimento=date(2026, 9, 10), chave_idempotencia="banco-antigo-alexandre",
            registrado_por=self.usuario,
        )
        movimento = registrar_movimento_pessoa(
            empresa=self.empresa, pessoa=self.alexandre, direcao="pessoa_deve",
            natureza="retirada_classificar", valor="150.00", data_competencia=date(2026, 9, 1),
            data_movimento=date(2026, 9, 10), descricao="Retirada histórica Alexandre",
            movimento_bancario_existente=banco_antigo, chave="classifica-banco-antigo", usuario=self.usuario,
        )
        self.assertEqual(movimento.movimento_bancario, banco_antigo)
        self.assertEqual(MovimentoBancario.objects.count(), 1)
        self.assertFalse(MovimentoFinanceiro.objects.filter(chave_idempotencia=f"pessoa_financeira:{movimento.pk}").exists())

    def test_pessoa_nao_socia_nao_recebe_distribuicao(self):
        movimento = registrar_movimento_pessoa(
            empresa=self.empresa, pessoa=self.diana, direcao="pessoa_deve",
            natureza="remuneracao_pendente", valor="200.00", data_competencia=date(2026, 10, 1),
            data_movimento=date(2026, 10, 1), descricao="Apoio administrativo",
            conta_bancaria=self.banco, chave="diana-adm-1", usuario=self.usuario,
        )
        with self.assertRaisesRegex(ValidationError, "exclusiva de sócio"):
            classificar_movimento_pessoa(
                movimento=movimento, natureza_definitiva="distribuicao_lucros", valor="200.00",
                competencia=date(2026, 10, 1), justificativa="Classificação contábil de teste",
                chave="class-diana-invalida", usuario=self.usuario, aprovar=True,
            )
        self.assertFalse(ClassificacaoPessoaFinanceira.objects.exists())

    def test_proposta_pode_ser_aprovada_depois_sem_alterar_movimento(self):
        movimento = registrar_movimento_pessoa(
            empresa=self.empresa, pessoa=self.alexandre, direcao="pessoa_deve",
            natureza="retirada_classificar", valor="300.00", data_competencia=date(2026, 10, 1),
            data_movimento=date(2026, 10, 1), descricao="Retirada pendente de fechamento",
            conta_bancaria=self.banco, chave="retirada-classificar-300", usuario=self.usuario,
        )
        classificacao = classificar_movimento_pessoa(
            movimento=movimento, natureza_definitiva="pro_labore", valor="300.00",
            competencia=date(2026, 10, 1), justificativa="Orientação contábil anexada ao fechamento",
            chave="classificacao-proposta-300", usuario=self.usuario, aprovar=False,
        )
        movimento.refresh_from_db()
        self.assertEqual(classificacao.status, "proposta")
        self.assertEqual(movimento.status, "classificado")
        aprovar_classificacao_pessoa(classificacao=classificacao, usuario=self.usuario)
        classificacao.refresh_from_db()
        movimento.refresh_from_db()
        self.assertEqual(classificacao.status, "aprovada")
        self.assertEqual(movimento.status, "aprovado")
        self.assertEqual(movimento.natureza_provisoria, "retirada_classificar")

    def test_aplicacao_resgate_e_rendimento_tem_tratamento_separado(self):
        conta = ContaInvestimento.objects.create(
            empresa=self.empresa, conta_bancaria=self.banco, nome="RDB Nubank", instituicao="Nubank", produto="RDB",
        )
        registrar_movimento_investimento(
            conta=conta, tipo="aplicacao", valor="1000.00", data_competencia=date(2026, 10, 2),
            data_movimento=date(2026, 10, 2), descricao="Aplicação RDB", chave="rdb-aplicacao", usuario=self.usuario,
        )
        registrar_movimento_investimento(
            conta=conta, tipo="rendimento", valor="10.00", data_competencia=date(2026, 10, 3),
            data_movimento=date(2026, 10, 3), descricao="Rendimento RDB", chave="rdb-rendimento", usuario=self.usuario,
        )
        registrar_movimento_investimento(
            conta=conta, tipo="resgate_principal", valor="200.00", data_competencia=date(2026, 10, 4),
            data_movimento=date(2026, 10, 4), descricao="Resgate RDB", chave="rdb-resgate", usuario=self.usuario,
        )
        self.assertEqual(conta.saldo_principal, Decimal("800.00"))
        self.assertEqual(conta.rendimento_liquido, Decimal("10.00"))
        self.assertEqual(MovimentoFinanceiro.objects.filter(natureza="financeiro").count(), 1)
        self.assertEqual(MovimentoFinanceiro.objects.filter(descricao__icontains="Aplicação").count(), 0)

    def test_aplicacao_rdb_antiga_reutiliza_movimento_bancario(self):
        conta = ContaInvestimento.objects.create(
            empresa=self.empresa, conta_bancaria=self.banco, nome="RDB Histórico", instituicao="Nubank", produto="RDB",
        )
        banco_antigo = MovimentoBancario.objects.create(
            empresa=self.empresa, conta=self.banco, tipo="saida", origem_tipo="manual",
            descricao="Aplicação RDB antiga", valor=Decimal("1050.00"),
            data_movimento=date(2026, 9, 10), chave_idempotencia="rdb-antigo-banco",
            registrado_por=self.usuario,
        )
        movimento = registrar_movimento_investimento(
            conta=conta, tipo="aplicacao", valor="1050.00", data_competencia=date(2026, 9, 1),
            data_movimento=date(2026, 9, 10), descricao="Reclassificação aplicação RDB",
            movimento_bancario_existente=banco_antigo, chave="rdb-antigo-classificado", usuario=self.usuario,
        )
        self.assertEqual(movimento.movimento_bancario, banco_antigo)
        self.assertEqual(MovimentoBancario.objects.count(), 1)

    def test_estorno_parcial_vinculado_nao_pode_ultrapassar_origem(self):
        original = registrar_movimento_financeiro(
            empresa=self.empresa, caixa=None, origem_tipo="ajuste", origem_id=99,
            origem_referencia="VENDA-99", tipo="entrada", natureza="operacional", valor="100.00",
            descricao="Venda de teste", data_competencia=date(2026, 10, 1),
            data_movimento=date(2026, 10, 1), chave_idempotencia="venda-estorno-99", usuario=self.usuario,
        )
        estorno = registrar_estorno_vinculado(
            empresa=self.empresa, movimento_original=original, valor="40.00",
            data_movimento=date(2026, 10, 2), motivo="Devolução parcial confirmada",
            chave="estorno-parcial-1", usuario=self.usuario,
        )
        repetido = registrar_estorno_vinculado(
            empresa=self.empresa, movimento_original=original, valor="40.00",
            data_movimento=date(2026, 10, 2), motivo="Devolução parcial confirmada",
            chave="estorno-parcial-1", usuario=self.usuario,
        )
        self.assertEqual(estorno.pk, repetido.pk)
        self.assertEqual(estorno.movimento_contrapartida.tipo, "saida")
        with self.assertRaisesRegex(ValidationError, "supera o saldo"):
            registrar_estorno_vinculado(
                empresa=self.empresa, movimento_original=original, valor="70.00",
                data_movimento=date(2026, 10, 3), motivo="Tentativa acima do saldo",
                chave="estorno-parcial-2", usuario=self.usuario,
            )
        self.assertEqual(EstornoFinanceiroVinculado.objects.count(), 1)

    def test_estorno_sem_origem_pode_ser_vinculado_depois(self):
        original = registrar_movimento_financeiro(
            empresa=self.empresa, caixa=None, origem_tipo="ajuste", origem_id=101,
            origem_referencia="VENDA-101", tipo="entrada", natureza="operacional", valor="80.00",
            descricao="Venda para vínculo posterior", data_competencia=date(2026, 10, 1),
            data_movimento=date(2026, 10, 1), chave_idempotencia="venda-estorno-101", usuario=self.usuario,
        )
        pendente = registrar_estorno_vinculado(
            empresa=self.empresa, movimento_original=None, valor="80.00",
            data_movimento=date(2026, 10, 2), motivo="Origem ainda não identificada",
            referencia_externa="CHARGEBACK-101", chave="estorno-pendente-101", usuario=self.usuario,
        )
        self.assertEqual(pendente.status, "pendente")
        vinculado = vincular_estorno_pendente(
            estorno=pendente, movimento_original=original, usuario=self.usuario,
        )
        self.assertEqual(vinculado.status, "vinculado")
        self.assertEqual(vinculado.movimento_original, original)
        self.assertEqual(vinculado.movimento_contrapartida.valor, Decimal("80.00"))

    def test_sumup_guarda_bruto_taxa_liquido_e_e_idempotente(self):
        conteudo = (
            "Conta,Registro de data e hora,Código da transação,Tipo de transação,Status,"
            "Bandeira do cartão,Últimos 4 dígitos do cartão,Modalidade do cartão,"
            "Valor da transação,Valor da taxa,Valor pago\n"
            "loja@example.com,2026-10-01 16:12:19,TAAA444RZ9M,Pagamento,Efetuado,"
            "VISA,2923,DEBIT,175.0,1.4,173.6\n"
        ).encode("utf-8")
        importar_extrato_arquivo(conta=self.banco, conteudo=conteudo, nome_arquivo="sumup.csv", usuario=self.usuario)
        importar_extrato_arquivo(conta=self.banco, conteudo=conteudo, nome_arquivo="sumup.csv", usuario=self.usuario)
        transacao = TransacaoAdquirente.objects.get()
        self.assertEqual(transacao.valor_bruto, Decimal("175.00"))
        self.assertEqual(transacao.taxa, Decimal("1.40"))
        self.assertEqual(transacao.valor_liquido, Decimal("173.60"))
        self.assertEqual(TransacaoAdquirente.objects.count(), 1)
