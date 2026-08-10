from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import ContaBancaria, LinhaExtratoBancario, MovimentoBancario, MovimentoFinanceiro
from caixa.services.tesouraria import conciliar_grupo, registrar_aporte_capital, sugerir_correspondencias
from configuracoes.models import Empresa, UsuarioEmpresa
from estoque.models import PontoOperacional, Produto, SaldoEstoquePonto, TransferenciaEstoqueInterempresa, UbicacaoEstoque
from estoque.services import executar_transferencia_interempresa
from fiscal.models import FaixaTributaria, PerfilTributario, RegraTributaria
from fiscal.services_versionamento import criar_nova_versao_regra


class ComplementaresFinanceiroTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Complementar", cnpj="10.010.010/0001-10")
        self.usuario = get_user_model().objects.create_user(
            username="gerente_complementar", password="senha-forte", tipo_usuario="gerente", empresa=self.empresa,
        )
        self.conta = ContaBancaria.objects.create(
            empresa=self.empresa, nome="Conta principal", banco_nome="Banco", numero="1",
        )

    def test_aporte_retroativo_aumenta_saldo_sem_virar_receita_operacional(self):
        ontem = timezone.localdate() - timedelta(days=1)
        aporte = registrar_aporte_capital(
            empresa=self.empresa, tipo="capital_social", descricao="Integralização inicial",
            aportante="Sócio A", documento_referencia="ALTERACAO-001", valor=Decimal("5000.00"),
            data_competencia=ontem, data_movimento=ontem, conta_bancaria=self.conta, caixa=None,
            chave="aporte-teste-1", usuario=self.usuario,
        )
        self.assertEqual(aporte.movimento_bancario.origem_tipo, "aporte_capital")
        self.assertEqual(self.conta.saldo_atual, Decimal("5000.00"))
        movimento = MovimentoFinanceiro.objects.get(origem_tipo="aporte_capital", origem_id=aporte.pk)
        self.assertEqual(movimento.natureza, "capital")
        self.assertFalse(MovimentoFinanceiro.objects.filter(pk=movimento.pk, natureza="operacional").exists())

    def test_tesouraria_exibe_formulario_e_historico_de_aportes(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("caixa:tesouraria"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Capital inicial ou injeção de recursos")

    def test_conciliacao_registra_tarifa_e_sugere_documento_semelhante(self):
        hoje = timezone.localdate()
        linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa, conta=self.conta, identificador_externo="tarifa-1",
            data_movimento=hoje, descricao="TARIFA PACOTE SERVICOS", valor=Decimal("-12.00"),
        )
        conciliacao = conciliar_grupo(
            linhas=[linha], movimentos=[], usuario=self.usuario, registrar_diferenca=True,
            tipo_diferenca="tarifa", descricao_diferenca="Tarifa pacote de serviços",
        )
        self.assertEqual(conciliacao.status, "conciliado")
        self.assertEqual(conciliacao.movimento_diferenca.tipo, "saida")
        self.assertEqual(conciliacao.movimento_diferenca.valor, Decimal("12.00"))
        outra = LinhaExtratoBancario.objects.create(
            empresa=self.empresa, conta=self.conta, identificador_externo="pix-1",
            data_movimento=hoje, descricao="PIX CLIENTE MARIA", valor=Decimal("100.00"),
        )
        candidato = MovimentoBancario.objects.create(
            empresa=self.empresa, conta=self.conta, tipo="entrada", origem_tipo="manual",
            descricao="PIX recebido Maria", valor=Decimal("100.00"), data_movimento=hoje,
            chave_idempotencia="pix-maria",
        )
        self.assertEqual(sugerir_correspondencias(linha=outra, limite=1)[0]["movimento"], candidato)


class ComplementaresEstoqueFiscalTests(TestCase):
    def setUp(self):
        self.origem_empresa = Empresa.objects.create(nome="Empresa Origem", cnpj="20.020.020/0001-20")
        self.destino_empresa = Empresa.objects.create(nome="Empresa Destino", cnpj="30.030.030/0001-30")
        self.usuario = get_user_model().objects.create_user(
            username="gerente_interempresa", password="senha-forte", tipo_usuario="gerente", empresa=self.origem_empresa,
        )
        UsuarioEmpresa.objects.update_or_create(usuario=self.usuario, empresa=self.destino_empresa, defaults={"ativo": True})
        self.po_origem = PontoOperacional.objects.create(empresa=self.origem_empresa, codigo="O1", nome="Origem")
        self.po_destino = PontoOperacional.objects.create(empresa=self.destino_empresa, codigo="D1", nome="Destino")
        self.ub_origem = UbicacaoEstoque.objects.create(ponto_operacional=self.po_origem, codigo="A1")
        self.ub_destino = UbicacaoEstoque.objects.create(ponto_operacional=self.po_destino, codigo="B1")
        self.produto_origem = Produto.objects.create(
            empresa=self.origem_empresa, nome="Capa origem", quantidade=5, ponto_operacional=self.po_origem,
            ubicacao_padrao=self.ub_origem, custo_unitario=Decimal("20.00"), custo_medio=Decimal("20.00"),
        )
        self.produto_destino = Produto.objects.create(
            empresa=self.destino_empresa, nome="Capa destino", quantidade=0, ponto_operacional=self.po_destino,
            ubicacao_padrao=self.ub_destino, custo_unitario=Decimal("0.00"), custo_medio=Decimal("0.00"),
        )

    def test_transferencia_interempresa_exige_documento_e_separa_movimentos(self):
        with self.assertRaisesMessage(ValueError, "Documento fiscal"):
            executar_transferencia_interempresa(
                empresa_origem=self.origem_empresa, empresa_destino=self.destino_empresa,
                produto_origem=self.produto_origem, produto_destino=self.produto_destino,
                origem=self.po_origem, origem_ubicacao=self.ub_origem, destino=self.po_destino,
                destino_ubicacao=self.ub_destino, quantidade=2, documento_fiscal="",
                natureza_operacao="Transferência documentada", data_operacao=timezone.localdate(),
                usuario=self.usuario, chave="inter-sem-doc",
            )
        operacao = executar_transferencia_interempresa(
            empresa_origem=self.origem_empresa, empresa_destino=self.destino_empresa,
            produto_origem=self.produto_origem, produto_destino=self.produto_destino,
            origem=self.po_origem, origem_ubicacao=self.ub_origem, destino=self.po_destino,
            destino_ubicacao=self.ub_destino, quantidade=2, documento_fiscal="NFE-123",
            natureza_operacao="Transferência documentada", data_operacao=timezone.localdate(),
            usuario=self.usuario, chave="inter-com-doc",
        )
        self.assertIsInstance(operacao, TransferenciaEstoqueInterempresa)
        self.assertEqual(operacao.movimento_saida.tipo, "transferencia_interempresa_saida")
        self.assertEqual(operacao.movimento_entrada.tipo, "transferencia_interempresa_entrada")
        self.assertEqual(SaldoEstoquePonto.objects.get(produto=self.produto_origem, ponto_operacional=self.po_origem).quantidade, 3)
        self.assertEqual(SaldoEstoquePonto.objects.get(produto=self.produto_destino, ponto_operacional=self.po_destino).quantidade, 2)

    def test_tela_transferencia_interempresa_carrega_isolada(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("estoque:transferencia_interempresa"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Transferência controlada entre empresas/CNPJs")

    def test_regra_homologada_e_imutavel_e_nova_versao_copia_faixas(self):
        perfil = PerfilTributario.objects.create(
            empresa=self.origem_empresa, nome="Simples", regime="simples", inicio_vigencia=date(2026, 1, 1), status="homologado",
        )
        regra = RegraTributaria.objects.create(
            perfil=perfil, codigo="REV-I", nome="Revenda", tipo_item="produto", finalidade="revenda",
            anexo_simples="I", aliquota_estimativa=Decimal("6.00"), inicio_vigencia=date(2026, 1, 1), status="homologado",
        )
        FaixaTributaria.objects.create(
            regra=regra, anexo="I", nome="Faixa 1", receita_inicial=0,
            aliquota_nominal=Decimal("4.00"), parcela_deduzir=0,
        )
        regra.aliquota_estimativa = Decimal("7.00")
        with self.assertRaisesMessage(ValidationError, "imutável"):
            regra.save()
        nova = criar_nova_versao_regra(
            regra=regra, inicio_vigencia=date(2027, 1, 1), aliquota_estimativa=Decimal("7.00"),
            fonte_normativa="Orientação contador 2027", observacao="Revisão anual", usuario=self.usuario,
        )
        regra.refresh_from_db()
        self.assertEqual(regra.fim_vigencia, date(2026, 12, 31))
        self.assertEqual(nova.status, "rascunho")
        self.assertEqual(nova.faixas.count(), 1)
