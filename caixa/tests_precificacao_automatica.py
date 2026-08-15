from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone

from caixa.models import (
    AdquirentePagamento,
    CategoriaFinanceira,
    ContaBancaria,
    ContaPagar,
    FormaPagamento,
    MaquininhaPagamento,
    Pagamento,
    TaxaMaquininha,
)
from caixa.services.precificacao_automatica import (
    calcular_rateio_estrutura,
    calcular_taxa_canal_referencia,
    listar_precos_por_canal,
)
from configuracoes.models import Empresa


class PrecificacaoAutomaticaTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Precificação", cnpj="11.222.333/0001-44")
        self.hoje = timezone.localdate()
        self.mes_anterior = (self.hoje.replace(day=1) - timedelta(days=1)).replace(day=1)
        self.categoria_estrutura = CategoriaFinanceira.objects.create(
            empresa=self.empresa,
            nome="Aluguel",
            tipo="saida",
            classificacao_despesa="fixa",
            tratamento_rateio="estrutura_geral",
        )

    def test_rateio_usa_despesas_classificadas_e_receita_de_produtos(self):
        ContaPagar.objects.create(
            empresa=self.empresa,
            descricao="Aluguel da loja",
            data_emissao=self.mes_anterior,
            data_competencia=self.mes_anterior,
            vencimento=self.mes_anterior + timedelta(days=9),
            valor_total=Decimal("100.00"),
            categoria=self.categoria_estrutura,
        )
        Pagamento.objects.create(
            empresa=self.empresa,
            valor=Decimal("1000.00"),
            data_competencia=self.mes_anterior,
            data_movimento=self.mes_anterior,
            encargos_gerenciais_snapshot={"base_produto": "1000.00", "base_servico": "0.00"},
        )

        resultado = calcular_rateio_estrutura(empresa=self.empresa, escopo="produtos")

        self.assertEqual(resultado["despesas_alocadas"], Decimal("100.00"))
        self.assertEqual(resultado["receita_escopo"], Decimal("1000.00"))
        self.assertEqual(resultado["taxa_aplicada"], Decimal("10.000"))

    def test_despesa_de_estoque_nao_duplica_rateio_estrutural(self):
        categoria_estoque = CategoriaFinanceira.objects.create(
            empresa=self.empresa,
            nome="Compra de mercadoria",
            tipo="saida",
            classificacao_despesa="variavel",
            tratamento_rateio="estoque_cmv",
        )
        ContaPagar.objects.create(
            empresa=self.empresa,
            descricao="Mercadoria",
            data_emissao=self.mes_anterior,
            data_competencia=self.mes_anterior,
            vencimento=self.mes_anterior + timedelta(days=9),
            valor_total=Decimal("500.00"),
            categoria=categoria_estoque,
        )
        resultado = calcular_rateio_estrutura(empresa=self.empresa, escopo="produtos")
        self.assertEqual(resultado["despesas_alocadas"], Decimal("0.00"))

    def test_forma_pagamento_resolve_taxa_da_maquininha_por_vigencia_e_parcelas(self):
        conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Conta adquirente",
            banco_nome="Banco",
            numero="123",
            saldo_inicial=0,
            data_saldo_inicial=self.mes_anterior,
        )
        adquirente = AdquirentePagamento.objects.create(empresa=self.empresa, nome="Stone")
        maquininha = MaquininhaPagamento.objects.create(
            empresa=self.empresa,
            adquirente=adquirente,
            nome="Stone Balcão",
            conta_bancaria_liquidacao=conta,
        )
        taxa = TaxaMaquininha.objects.create(
            empresa=self.empresa,
            maquininha=maquininha,
            modalidade="credito",
            parcelas_de=2,
            parcelas_ate=6,
            taxa_percentual=Decimal("4.250"),
            taxa_fixa=Decimal("0.30"),
            dias_recebimento=30,
            vigencia_inicio=self.mes_anterior,
        )
        forma = FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="Crédito Stone 3x",
            codigo="credito-stone-3x",
            modalidade="credito",
            parcelas_padrao=3,
            maquininha=maquininha,
            taxa_percentual=Decimal("9.99"),
        )

        condicao = forma.obter_condicao_vigente(data_referencia=self.hoje, parcelas=3)

        self.assertEqual(condicao["condicao_id"], taxa.pk)
        self.assertEqual(condicao["taxa_percentual"], Decimal("4.250"))
        self.assertEqual(condicao["taxa_fixa"], Decimal("0.30"))

    def test_taxa_referencia_sem_historico_usa_media_das_tabelas(self):
        adquirente = AdquirentePagamento.objects.create(empresa=self.empresa, nome="Rede")
        maquininha = MaquininhaPagamento.objects.create(
            empresa=self.empresa, adquirente=adquirente, nome="Rede Loja"
        )
        TaxaMaquininha.objects.create(
            empresa=self.empresa, maquininha=maquininha, modalidade="debito",
            taxa_percentual=Decimal("1.000"), vigencia_inicio=self.mes_anterior,
        )
        TaxaMaquininha.objects.create(
            empresa=self.empresa, maquininha=maquininha, modalidade="credito",
            taxa_percentual=Decimal("3.000"), vigencia_inicio=self.mes_anterior,
        )
        resultado = calcular_taxa_canal_referencia(empresa=self.empresa)
        self.assertEqual(resultado["taxa_percentual"], Decimal("2.000"))
        self.assertEqual(resultado["fonte"], "media_tabelas_ativas")

    def test_preco_por_canal_incorpora_tarifa_fixa_antes_das_aliquotas(self):
        adquirente = AdquirentePagamento.objects.create(empresa=self.empresa, nome="Getnet")
        maquininha = MaquininhaPagamento.objects.create(
            empresa=self.empresa, adquirente=adquirente, nome="Getnet balcão"
        )
        TaxaMaquininha.objects.create(
            empresa=self.empresa,
            maquininha=maquininha,
            modalidade="credito",
            taxa_percentual=Decimal("4.000"),
            taxa_fixa=Decimal("0.30"),
            vigencia_inicio=self.mes_anterior,
        )

        precos = listar_precos_por_canal(
            empresa=self.empresa,
            custo_base=Decimal("100.00"),
            aliquota=0,
            margem_minima=0,
            margem_alvo=20,
            taxa_estrutura=0,
        )

        self.assertEqual(precos[0]["preco_minimo"], Decimal("104.48"))
        self.assertEqual(precos[0]["preco_recomendado"], Decimal("131.97"))

    def test_bloqueia_taxas_ativas_com_vigencia_e_parcelas_sobrepostas(self):
        adquirente = AdquirentePagamento.objects.create(empresa=self.empresa, nome="Cielo")
        maquininha = MaquininhaPagamento.objects.create(
            empresa=self.empresa, adquirente=adquirente, nome="Cielo balcão"
        )
        TaxaMaquininha.objects.create(
            empresa=self.empresa,
            maquininha=maquininha,
            modalidade="credito",
            parcelas_de=1,
            parcelas_ate=6,
            taxa_percentual=Decimal("3.000"),
            vigencia_inicio=self.mes_anterior,
        )
        nova = TaxaMaquininha(
            empresa=self.empresa,
            maquininha=maquininha,
            modalidade="credito",
            parcelas_de=4,
            parcelas_ate=10,
            taxa_percentual=Decimal("4.000"),
            vigencia_inicio=self.hoje,
        )
        with self.assertRaises(ValidationError):
            nova.full_clean()
