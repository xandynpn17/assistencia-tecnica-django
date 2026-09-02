from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from caixa.models import (
    AdquirentePagamento,
    CategoriaFinanceira,
    Caixa,
    ContaBancaria,
    ContaPagar,
    FormaPagamento,
    MaquininhaPagamento,
    MovimentoBancario,
    Pagamento,
    TaxaMaquininha,
)
from caixa.forms import PagamentoForm
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

    def test_rateio_distorcido_usa_projecao_do_mes_atual_com_amostra_suficiente(self):
        referencia = date(2026, 8, 18)
        competencia_fechada = date(2026, 7, 1)
        ContaPagar.objects.create(
            empresa=self.empresa,
            descricao="Estrutura acumulada",
            data_emissao=competencia_fechada,
            data_competencia=competencia_fechada,
            vencimento=competencia_fechada + timedelta(days=9),
            valor_total=Decimal("1500.00"),
            categoria=self.categoria_estrutura,
        )
        Pagamento.objects.create(
            empresa=self.empresa,
            valor=Decimal("50.00"),
            data_competencia=competencia_fechada,
            data_movimento=competencia_fechada,
            encargos_gerenciais_snapshot={"base_produto": "50.00"},
        )
        for dia in (5, 10, 15):
            Pagamento.objects.create(
                empresa=self.empresa,
                valor=Decimal("500.00"),
                data_competencia=date(2026, 8, dia),
                data_movimento=date(2026, 8, dia),
                encargos_gerenciais_snapshot={"base_produto": "500.00"},
            )

        resultado = calcular_rateio_estrutura(
            empresa=self.empresa,
            escopo="produtos",
            data_referencia=referencia,
        )

        self.assertEqual(resultado["fonte_calculo"], "projecao_mes_atual")
        self.assertEqual(resultado["confiabilidade"], "provisoria")
        self.assertEqual(resultado["despesas_projetadas_mensais"], Decimal("1500.00"))
        self.assertEqual(resultado["receita_projetada_mensal"], Decimal("2583.33"))
        self.assertEqual(resultado["taxa_aplicada"], Decimal("58.065"))

    def test_rateio_distorcido_sem_amostra_nao_aplica_teto_artificial(self):
        referencia = date(2026, 8, 18)
        competencia_fechada = date(2026, 7, 1)
        ContaPagar.objects.create(
            empresa=self.empresa,
            descricao="Estrutura sem histórico",
            data_emissao=competencia_fechada,
            data_competencia=competencia_fechada,
            vencimento=competencia_fechada + timedelta(days=9),
            valor_total=Decimal("1500.00"),
            categoria=self.categoria_estrutura,
        )
        Pagamento.objects.create(
            empresa=self.empresa,
            valor=Decimal("50.00"),
            data_competencia=competencia_fechada,
            data_movimento=competencia_fechada,
            encargos_gerenciais_snapshot={"base_produto": "50.00"},
        )

        resultado = calcular_rateio_estrutura(
            empresa=self.empresa,
            escopo="produtos",
            data_referencia=referencia,
        )

        self.assertEqual(resultado["fonte_calculo"], "sem_base_confiavel")
        self.assertEqual(resultado["confiabilidade"], "insuficiente")
        self.assertEqual(resultado["taxa_fechada"], Decimal("3000.000"))
        self.assertEqual(resultado["taxa_aplicada"], Decimal("0.000"))

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

    def test_bandeira_e_parcelas_geram_liquidacao_bancaria_liquida(self):
        conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Nubank",
            banco_nome="Nubank",
            numero="1",
            saldo_inicial=0,
            data_saldo_inicial=self.hoje,
        )
        adquirente = AdquirentePagamento.objects.create(empresa=self.empresa, nome="Adquirente")
        maquininha = MaquininhaPagamento.objects.create(
            empresa=self.empresa,
            adquirente=adquirente,
            nome="Maquina 1",
            conta_bancaria_liquidacao=conta,
        )
        TaxaMaquininha.objects.create(
            empresa=self.empresa,
            maquininha=maquininha,
            modalidade="credito",
            bandeira="Visa",
            parcelas_de=2,
            parcelas_ate=2,
            taxa_percentual=Decimal("3.913"),
            vigencia_inicio=self.mes_anterior,
        )
        forma = FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="Credito",
            codigo="credito-maquina",
            modalidade="credito",
            maquininha=maquininha,
            conta_bancaria_liquidacao=conta,
        )

        pagamento = Pagamento.objects.create(
            empresa=self.empresa,
            valor=Decimal("460.00"),
            forma_pagamento=forma,
            formas_pagamento_compostas=[{
                "forma_id": forma.id,
                "forma_codigo": forma.codigo,
                "forma_nome": forma.nome,
                "valor": "460.00",
                "parcelas": 2,
                "bandeira": "Visa",
            }],
            data_movimento=self.hoje,
        )

        pagamento.refresh_from_db()
        movimento = MovimentoBancario.objects.get(origem_tipo="pagamento", origem_id=pagamento.id)
        self.assertEqual(pagamento.taxas_recebimento_estimadas, Decimal("18.00"))
        self.assertEqual(movimento.valor, Decimal("442.00"))
        self.assertEqual(movimento.metadados["bandeira"], "Visa")

    def test_tela_pagamento_expoe_previsao_de_taxa_bandeira_e_liquidacao(self):
        conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Conta da maquininha",
            banco_nome="Banco",
            numero="123",
            saldo_inicial=0,
            data_saldo_inicial=self.hoje,
        )
        adquirente = AdquirentePagamento.objects.create(empresa=self.empresa, nome="Rede UI")
        maquininha = MaquininhaPagamento.objects.create(
            empresa=self.empresa,
            adquirente=adquirente,
            nome="Rede Balcao",
            conta_bancaria_liquidacao=conta,
        )
        taxa = TaxaMaquininha.objects.create(
            empresa=self.empresa,
            maquininha=maquininha,
            modalidade="credito",
            bandeira="Visa",
            parcelas_de=2,
            parcelas_ate=6,
            taxa_percentual=Decimal("3.913"),
            dias_recebimento=2,
            vigencia_inicio=self.mes_anterior,
        )
        forma = FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="Credito Rede",
            codigo="credito-rede-ui",
            modalidade="credito",
            maquininha=maquininha,
            parcelas_padrao=2,
        )
        Caixa.objects.create(empresa=self.empresa, aberto=True, saldo_inicial=0)
        usuario = get_user_model().objects.create_user(
            username="atendente_taxa_ui",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
        )
        self.client.force_login(usuario)

        response = self.client.get(reverse("caixa:registrar_pagamento"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "L&iacute;quido banc&aacute;rio")
        self.assertContains(response, "Cr&eacute;dito previsto")
        meta = next(item for item in response.context["formas_pagamento_meta"] if item["id"] == forma.id)
        self.assertTrue(meta["liquida_em_banco"])
        self.assertEqual(meta["maquininha_nome"], "Rede Balcao")
        self.assertEqual(meta["condicoes"][0]["id"], taxa.id)
        self.assertEqual(meta["condicoes"][0]["bandeira"], "Visa")

    def test_pagamento_em_dinheiro_grava_recebido_e_troco_sem_erro(self):
        Caixa.objects.create(empresa=self.empresa, aberto=True, saldo_inicial=0)
        FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="Dinheiro",
            codigo="dinheiro",
            modalidade="dinheiro",
        )
        usuario = get_user_model().objects.create_user(
            username="atendente_troco",
            password="senha-forte-123",
            tipo_usuario="atendente",
            empresa=self.empresa,
        )
        self.client.force_login(usuario)

        response = self.client.post(
            reverse("caixa:registrar_pagamento"),
            {
                "valor": "80.00",
                "metodo": "dinheiro",
                "valor_recebido": "100.00",
                "referencia": "DIN-TROCO-001",
                "chave_idempotencia": "din-troco-profissional-1",
            },
        )

        self.assertEqual(response.status_code, 302)
        pagamento = Pagamento.objects.get(referencia="DIN-TROCO-001")
        self.assertEqual(pagamento.valor_recebido_dinheiro, Decimal("100.00"))
        self.assertEqual(pagamento.troco_entregue, Decimal("20.00"))

    def test_form_pagamento_bloqueia_maquininha_sem_taxa_compativel(self):
        adquirente = AdquirentePagamento.objects.create(empresa=self.empresa, nome="Stone")
        conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Conta Stone",
            banco_nome="Banco",
            numero="001",
            saldo_inicial=0,
            data_saldo_inicial=self.hoje,
        )
        maquininha = MaquininhaPagamento.objects.create(
            empresa=self.empresa,
            adquirente=adquirente,
            nome="Stone Balcao",
            conta_bancaria_liquidacao=conta,
        )
        forma = FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="Credito Stone",
            codigo="credito-stone",
            modalidade="credito",
            maquininha=maquininha,
            parcelas_padrao=3,
        )

        form = PagamentoForm(
            data={
                "valor": "460.00",
                "forma_pagamento": str(forma.id),
                "parcelas_principal": "3",
                "data_movimento": self.hoje.isoformat(),
            },
            empresa=self.empresa,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Nao existe taxa vigente", form.errors["parcelas_principal"][0])

    def test_form_pagamento_aceita_apenas_combinacao_com_taxa_vigente(self):
        adquirente = AdquirentePagamento.objects.create(empresa=self.empresa, nome="Stone Taxada")
        conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Conta Stone Taxada",
            banco_nome="Banco",
            numero="002",
            saldo_inicial=0,
            data_saldo_inicial=self.hoje,
        )
        maquininha = MaquininhaPagamento.objects.create(
            empresa=self.empresa,
            adquirente=adquirente,
            nome="Stone Taxada Balcao",
            conta_bancaria_liquidacao=conta,
        )
        forma = FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="Credito Stone Taxada",
            codigo="credito-stone-taxada",
            modalidade="credito",
            maquininha=maquininha,
            parcelas_padrao=3,
        )
        TaxaMaquininha.objects.create(
            empresa=self.empresa,
            maquininha=maquininha,
            modalidade="credito",
            parcelas_de=2,
            parcelas_ate=6,
            taxa_percentual=Decimal("3.913"),
            vigencia_inicio=self.mes_anterior,
        )

        form = PagamentoForm(
            data={
                "valor": "460.00",
                "forma_pagamento": str(forma.id),
                "parcelas_principal": "3",
                "data_movimento": self.hoje.isoformat(),
            },
            empresa=self.empresa,
        )

        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_form_pagamento_exige_conta_de_liquidacao_da_maquininha(self):
        adquirente = AdquirentePagamento.objects.create(empresa=self.empresa, nome="Rede sem conta")
        maquininha = MaquininhaPagamento.objects.create(
            empresa=self.empresa,
            adquirente=adquirente,
            nome="Rede sem liquidacao",
        )
        forma = FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="Debito sem liquidacao",
            codigo="debito-sem-liquidacao",
            modalidade="debito",
            maquininha=maquininha,
        )
        TaxaMaquininha.objects.create(
            empresa=self.empresa,
            maquininha=maquininha,
            modalidade="debito",
            taxa_percentual=Decimal("1.490"),
            vigencia_inicio=self.mes_anterior,
        )

        form = PagamentoForm(
            data={
                "valor": "100.00",
                "forma_pagamento": str(forma.id),
                "parcelas_principal": "1",
                "data_movimento": self.hoje.isoformat(),
            },
            empresa=self.empresa,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("conta bancaria de liquidacao", form.errors["forma_pagamento"][0])

    def test_taxa_referencia_sem_historico_usa_maior_taxa_ativa(self):
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
        self.assertEqual(resultado["taxa_percentual"], Decimal("3.000"))
        self.assertEqual(resultado["fonte"], "maior_taxa_ativa")
        self.assertEqual(resultado["condicoes_ativas"], 2)

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
