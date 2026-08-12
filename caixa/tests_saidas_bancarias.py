from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import (
    Caixa,
    AporteCapital,
    CategoriaFinanceira,
    CentroCusto,
    ContaBancaria,
    ContaPagar,
    FormaPagamento,
    LancamentoCaixa,
    MovimentoBancario,
    MovimentoFinanceiro,
    PagamentoContaPagar,
)
from configuracoes.models import Empresa
from caixa.services.tesouraria import importar_extrato_arquivo, registrar_aporte_capital
from clientes.models import Cliente
from ordens.models import CustoOrdemServico, OrdemServico


class SaidasPorContaFinanceiraTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Saídas", cnpj="66.666.666/0001-66")
        self.usuario = get_user_model().objects.create_user(
            username="gestor_saidas",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
            perm_caixa_lancamento_retroativo=True,
            perm_caixa_ver_dre=True,
        )
        self.categoria = CategoriaFinanceira.objects.create(
            empresa=self.empresa,
            nome="Insumos de reparo",
            tipo="saida",
        )
        self.centro = CentroCusto.objects.create(
            empresa=self.empresa,
            nome="Assistência técnica",
            tipo="variavel",
        )
        self.conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Conta operacional",
            banco_nome="Banco Teste",
            numero="12345-6",
            saldo_inicial=Decimal("1000.00"),
            data_saldo_inicial=timezone.localdate() - timedelta(days=30),
        )
        self.pix = FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="PIX Saída",
            codigo="pix-saida",
            tipo="avista",
        )
        self.client.force_login(self.usuario)

    def test_saida_bancaria_retroativa_nao_exige_caixa_aberto(self):
        ontem = timezone.localdate() - timedelta(days=1)
        response = self.client.post(
            reverse("caixa:registrar_saida"),
            {
                "descricao": "Compra de teclas",
                "categoria": self.categoria.id,
                "centro_custo": self.centro.id,
                "valor": "35.00",
                "forma_pagamento": self.pix.id,
                "conta_bancaria": self.conta.id,
                "caixa": "",
                "data_competencia": ontem.isoformat(),
                "data_movimento": ontem.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)
        saida = LancamentoCaixa.objects.get(descricao="Compra de teclas")
        self.assertIsNone(saida.caixa_id)
        self.assertEqual(saida.conta_bancaria, self.conta)
        self.assertEqual(saida.forma_pagamento, self.pix)
        movimento = MovimentoBancario.objects.get(chave_idempotencia=f"lancamento_caixa:{saida.id}")
        self.assertEqual(movimento.tipo, "saida")
        self.assertEqual(movimento.data_movimento, ontem)
        self.assertEqual(self.conta.saldo_atual, Decimal("965.00"))

    def test_dinheiro_exige_caixa_e_nao_cria_movimento_bancario(self):
        dinheiro = FormaPagamento.objects.create(
            empresa=self.empresa,
            nome="Dinheiro saída",
            codigo="dinheiro-saida",
            tipo="avista",
        )
        caixa = Caixa.objects.create(empresa=self.empresa, saldo_inicial=Decimal("100.00"))
        response = self.client.post(
            reverse("caixa:registrar_saida"),
            {
                "descricao": "Material de limpeza",
                "categoria": self.categoria.id,
                "centro_custo": self.centro.id,
                "valor": "10.00",
                "forma_pagamento": dinheiro.id,
                "caixa": caixa.id,
                "conta_bancaria": "",
                "data_competencia": timezone.localdate().isoformat(),
                "data_movimento": timezone.localdate().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)
        saida = LancamentoCaixa.objects.get(descricao="Material de limpeza")
        self.assertEqual(saida.caixa, caixa)
        self.assertIsNone(saida.conta_bancaria_id)
        self.assertFalse(MovimentoBancario.objects.filter(origem_id=saida.id, origem_tipo="lancamento_caixa").exists())

    def test_importacao_ofx_preserva_fitid_e_nao_duplica(self):
        conteudo = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260810120000[-3:BRT]<TRNAMT>-35.00<FITID>OFX-001<NAME>PIX FORNECEDOR<MEMO>Compra de teclas</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""

        primeira = importar_extrato_arquivo(
            conta=self.conta,
            conteudo=conteudo,
            nome_arquivo="extrato.ofx",
            usuario=self.usuario,
        )
        segunda = importar_extrato_arquivo(
            conta=self.conta,
            conteudo=conteudo,
            nome_arquivo="extrato.ofx",
            usuario=self.usuario,
        )

        self.assertEqual(len(primeira), 1)
        self.assertEqual(len(segunda), 0)
        self.assertEqual(primeira[0].identificador_externo, "OFX-001")
        self.assertEqual(primeira[0].valor, Decimal("-35.00"))
        self.assertIn("Compra de teclas", primeira[0].descricao)

    def test_aporte_bancario_aceita_data_retroativa_e_caixa_fisico_nao(self):
        ontem = timezone.localdate() - timedelta(days=1)
        aporte = registrar_aporte_capital(
            empresa=self.empresa,
            tipo="capital_social",
            descricao="Capital inicial",
            valor=Decimal("500.00"),
            data_competencia=ontem,
            data_movimento=ontem,
            chave="aporte-retroativo-banco",
            usuario=self.usuario,
            conta_bancaria=self.conta,
        )
        self.assertEqual(aporte.data_movimento, ontem)
        self.assertEqual(self.conta.saldo_atual, Decimal("1500.00"))

        caixa = Caixa.objects.create(empresa=self.empresa, saldo_inicial=Decimal("0.00"))
        with self.assertRaises(ValidationError):
            registrar_aporte_capital(
                empresa=self.empresa,
                tipo="capital_social",
                descricao="Capital retroativo em dinheiro",
                valor=Decimal("100.00"),
                data_competencia=ontem,
                data_movimento=ontem,
                chave="aporte-retroativo-caixa",
                usuario=self.usuario,
                caixa=caixa,
            )
        self.assertFalse(AporteCapital.objects.filter(chave_idempotencia="aporte-retroativo-caixa").exists())

    def test_dre_classifica_custo_os_e_nao_duplica_saida_vinculada(self):
        hoje = timezone.localdate()
        cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Cliente DRE OS",
            documento="52998224725",
            telefone="11999998888",
            estado="SP",
        )
        ordem = OrdemServico.objects.create(
            empresa=self.empresa,
            cliente=cliente,
            tipo_equipamento="climatizador",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Teclas",
            tipo_reparo="Fora de Garantia",
        )
        saida = LancamentoCaixa.objects.create(
            empresa=self.empresa,
            conta_bancaria=self.conta,
            forma_pagamento=self.pix,
            descricao="Compra específica da OS",
            categoria=self.categoria,
            centro_custo=self.centro,
            valor=Decimal("40.00"),
            tipo="saida",
            natureza="operacional",
            data_competencia=hoje,
            data_movimento=hoje,
            usuario=self.usuario,
        )
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=ordem,
            origem="despesa_paga",
            tipo="componente",
            descricao="Teclas compradas",
            quantidade=1,
            custo_unitario=Decimal("40.00"),
            data_competencia=hoje,
            lancamento_caixa=saida,
            criado_por=self.usuario,
        )
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=ordem,
            origem="manual",
            tipo="insumo",
            descricao="Solda utilizada",
            quantidade=1,
            custo_unitario=Decimal("5.00"),
            data_competencia=hoje,
            criado_por=self.usuario,
        )

        response = self.client.get(
            reverse("caixa:dre"),
            {"data_inicio": hoje.isoformat(), "data_fim": hoje.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["custos_diretos_os"], Decimal("45.00"))
        self.assertEqual(response.context["custos_os_vinculados"], Decimal("40.00"))
        self.assertEqual(response.context["despesas_operacionais"], Decimal("0.00"))
        self.assertEqual(response.context["cmv"], Decimal("45.00"))

    def test_pagamento_fornecedor_bancario_retroativo_e_estorno_preservam_auditoria(self):
        ontem = timezone.localdate() - timedelta(days=1)
        conta_pagar = ContaPagar.objects.create(
            empresa=self.empresa,
            fornecedor="Fornecedor de componentes",
            descricao="Compra para reparo",
            categoria=self.categoria,
            centro_custo=self.centro,
            data_emissao=ontem,
            data_competencia=ontem,
            valor_total=Decimal("80.00"),
            vencimento=ontem,
        )
        response = self.client.post(
            reverse("caixa:detalhe_conta_pagar", args=[conta_pagar.id]),
            {
                "action": "pagar",
                "valor": "80.00",
                "forma_pagamento": self.pix.id,
                "caixa": "",
                "conta_bancaria": self.conta.id,
                "data_competencia": ontem.isoformat(),
                "data_movimento": ontem.isoformat(),
                "referencia": "PIX-FORN-001",
                "observacao": "Pagamento retroativo",
            },
        )
        self.assertEqual(response.status_code, 302)
        pagamento = PagamentoContaPagar.objects.get(conta=conta_pagar)
        conta_pagar.refresh_from_db()
        self.assertEqual(conta_pagar.status, "paga")
        self.assertEqual(pagamento.data_movimento, ontem)
        self.assertEqual(pagamento.conta_bancaria, self.conta)
        self.assertIsNone(pagamento.caixa_id)
        self.assertEqual(
            MovimentoBancario.objects.get(origem_tipo="conta_pagar", origem_id=pagamento.id).data_movimento,
            ontem,
        )

        response = self.client.post(
            reverse("caixa:detalhe_conta_pagar", args=[conta_pagar.id]),
            {
                "action": "estornar_pagamento",
                "pagamento_id": pagamento.id,
                "motivo_estorno": "Pagamento registrado na conta errada",
            },
        )
        self.assertEqual(response.status_code, 302)
        pagamento.refresh_from_db()
        conta_pagar.refresh_from_db()
        self.assertEqual(pagamento.status, "estornado")
        self.assertEqual(conta_pagar.valor_pago, Decimal("0.00"))
        self.assertEqual(conta_pagar.status, "vencida")
        self.assertTrue(
            MovimentoFinanceiro.objects.filter(
                estorno_de__origem_tipo="conta_pagar",
                estorno_de__origem_id=pagamento.id,
            ).exists()
        )
        movimento_original = MovimentoBancario.objects.get(
            origem_tipo="conta_pagar", origem_id=pagamento.id
        )
        movimento_inverso = movimento_original.movimento_neutralizador
        self.assertEqual(movimento_original.status, "neutralizado")
        self.assertEqual(movimento_inverso.status, "neutralizado")
        self.assertEqual(movimento_inverso.tipo, "entrada")
        self.assertEqual(movimento_inverso.valor, Decimal("80.00"))
        self.assertEqual(movimento_inverso.data_movimento, ontem)
        self.assertEqual(movimento_inverso.neutralizacao_de_id, movimento_original.id)

    def test_custo_os_nao_pode_ultrapassar_obrigacao_vinculada(self):
        cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Cliente Rateio",
            documento="39053344705",
            telefone="11999990000",
            estado="SP",
        )
        ordem = OrdemServico.objects.create(
            empresa=self.empresa,
            cliente=cliente,
            tipo_equipamento="outros",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Defeito",
            tipo_reparo="Fora de Garantia",
        )
        obrigacao = ContaPagar.objects.create(
            empresa=self.empresa,
            fornecedor="Fornecedor Rateio",
            descricao="Componentes",
            categoria=self.categoria,
            centro_custo=self.centro,
            valor_total=Decimal("50.00"),
            vencimento=timezone.localdate(),
        )
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=ordem,
            conta_pagar=obrigacao,
            tipo="componente",
            origem="compra_especifica",
            descricao="Componente A",
            quantidade=1,
            custo_unitario=Decimal("40.00"),
            data_competencia=obrigacao.data_competencia,
        )
        excedente = CustoOrdemServico(
            empresa=self.empresa,
            ordem=ordem,
            conta_pagar=obrigacao,
            tipo="componente",
            origem="compra_especifica",
            descricao="Componente B",
            quantidade=1,
            custo_unitario=Decimal("20.00"),
            data_competencia=obrigacao.data_competencia,
        )
        with self.assertRaises(ValidationError):
            excedente.full_clean()

    def test_dre_reconhece_obrigacao_na_competencia_sem_duplicar_custo_da_os(self):
        hoje = timezone.localdate()
        cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Cliente Competência",
            documento="11144477735",
            telefone="11988887777",
            estado="SP",
        )
        ordem = OrdemServico.objects.create(
            empresa=self.empresa,
            cliente=cliente,
            tipo_equipamento="outros",
            marca_equipamento="Marca",
            modelo_equipamento="Modelo",
            defeito="Defeito",
            tipo_reparo="Fora de Garantia",
        )
        obrigacao_os = ContaPagar.objects.create(
            empresa=self.empresa,
            fornecedor="Fornecedor OS",
            descricao="Peça específica",
            categoria=self.categoria,
            centro_custo=self.centro,
            data_competencia=hoje,
            valor_total=Decimal("40.00"),
            vencimento=hoje + timedelta(days=10),
        )
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=ordem,
            conta_pagar=obrigacao_os,
            origem="compra_especifica",
            tipo="peca",
            descricao="Peça específica",
            quantidade=1,
            custo_unitario=Decimal("40.00"),
            data_competencia=hoje,
        )
        ContaPagar.objects.create(
            empresa=self.empresa,
            fornecedor="Contabilidade",
            descricao="Honorários mensais",
            categoria=self.categoria,
            centro_custo=self.centro,
            data_competencia=hoje,
            valor_total=Decimal("100.00"),
            vencimento=hoje + timedelta(days=10),
        )

        response = self.client.get(
            reverse("caixa:dre"),
            {"data_inicio": hoje.isoformat(), "data_fim": hoje.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["custos_diretos_os"], Decimal("40.00"))
        self.assertEqual(response.context["obrigacoes_operacionais"], Decimal("140.00"))
        self.assertEqual(response.context["despesas_obrigacoes"], Decimal("100.00"))
        self.assertEqual(response.context["despesas_operacionais"], Decimal("100.00"))
        self.assertEqual(response.context["cmv"], Decimal("40.00"))
