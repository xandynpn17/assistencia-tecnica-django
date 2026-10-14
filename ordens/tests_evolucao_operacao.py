from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from caixa.models import Caixa, ContaPagar, ContaReceber, Pagamento
from clientes.models import Cliente
from configuracoes.models import Empresa, User
from ordens.models import ConfiguracaoOperacaoEmpresa, OrdemServico, ServicoPeca
from ordens.services.evolucao_operacional import historico_equipamento, pendencias_operacionais
from ordens.services.rentabilidade import resumo_rentabilidade_os


class EvolucaoOperacaoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nome="Empresa operação")
        cls.outra = Empresa.objects.create(nome="Outra operação")
        cls.gestor = User.objects.create_user(username="gestor_operacao", password="senha-forte-123", tipo_usuario="adm", empresa=cls.empresa)
        cls.cliente = Cliente.objects.create(nome="Cliente Operação", empresa=cls.empresa, documento="52998224725", estado="SP")
        cls.outro_cliente = Cliente.objects.create(nome="Cliente Outro", empresa=cls.empresa, documento="11144477735", estado="SP")
        cls.ordem = OrdemServico.objects.create(empresa=cls.empresa, cliente=cls.cliente, tipo_equipamento="celular", marca_equipamento="Marca", modelo_equipamento="M1", numero_serie_equipamento="SER123", defeito="Não liga", tipo_reparo="Fora de Garantia")

    def setUp(self):
        self.client.force_login(self.gestor)

    def test_alerta_os_parada_some_ao_concluir(self):
        OrdemServico.objects.filter(pk=self.ordem.pk).update(data_abertura=timezone.now() - timedelta(days=8))
        dados = pendencias_operacionais(self.empresa)
        self.assertEqual(dados["grupos"][0]["total"], 1)
        OrdemServico.objects.filter(pk=self.ordem.pk).update(status="concluida")
        self.assertEqual(pendencias_operacionais(self.empresa)["grupos"][0]["total"], 0)

    def test_valor_fabricante_so_aparece_para_gestao_financeira(self):
        ContaReceber.objects.create(empresa=self.empresa, descricao="Cobrança confidencial", tipo_origem="garantia_fabricante", valor_original=Decimal("55"), valor_aberto=Decimal("55"), vencimento=timezone.localdate() - timedelta(days=2))
        tecnico = User.objects.create_user(username="tecnico_pendencias", password="senha-forte-123", tipo_usuario="tecnico", empresa=self.empresa)
        self.client.force_login(tecnico)
        self.assertNotContains(self.client.get(reverse("ordens:central_pendencias")), "Cobrança confidencial")
        self.client.force_login(self.gestor)
        self.assertContains(self.client.get(reverse("ordens:central_pendencias")), "Cobrança confidencial")

    def test_historico_nao_expoe_outro_cliente(self):
        anterior = OrdemServico.objects.create(empresa=self.empresa, cliente=self.outro_cliente, tipo_equipamento="celular", marca_equipamento="Marca", modelo_equipamento="M1", numero_serie_equipamento="SER123", defeito="Segredo", tipo_reparo="Fora de Garantia")
        OrdemServico.objects.filter(pk=anterior.pk).update(data_abertura=self.ordem.data_abertura - timedelta(days=30))
        resultado = historico_equipamento(self.ordem, self.empresa)
        self.assertEqual(resultado["terceiros"], 1)
        self.assertEqual(resultado["ordens"], [])
        resposta = self.client.get(reverse("ordens:historico_equipamento", args=[self.ordem.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, "Segredo")

    def test_vinculo_historico_exige_confirmacao_e_pode_desfazer(self):
        anterior = OrdemServico.objects.create(empresa=self.empresa, cliente=self.cliente, tipo_equipamento="celular", marca_equipamento="Marca", modelo_equipamento="M1", numero_serie_equipamento="SER123", defeito="Falha anterior", tipo_reparo="Fora de Garantia")
        OrdemServico.objects.filter(pk=anterior.pk).update(data_abertura=self.ordem.data_abertura - timedelta(days=30))
        url = reverse("ordens:historico_equipamento", args=[self.ordem.pk])
        self.assertContains(self.client.get(url), "Falha anterior")
        self.assertEqual(historico_equipamento(self.ordem, self.empresa)["ordens"], [])
        self.assertEqual(self.client.post(url, {"ordem_anterior": anterior.pk}).status_code, 302)
        self.ordem.refresh_from_db()
        anterior.refresh_from_db()
        self.assertEqual(self.ordem.equipamento_grupo, anterior.equipamento_grupo)
        self.assertEqual(len(historico_equipamento(self.ordem, self.empresa)["ordens"]), 1)
        self.client.post(url, {"acao": "desvincular"})
        self.ordem.refresh_from_db()
        self.assertIsNone(self.ordem.equipamento_grupo)

    def test_checklist_snapshot_e_conclusao(self):
        ConfiguracaoOperacaoEmpresa.objects.create(empresa=self.empresa, checklist_itens=["Acessório entregue"], checklist_obrigatorio=True)
        url = reverse("ordens:checklist_entrega", args=[self.ordem.pk])
        self.assertEqual(self.client.post(url, {"item": ["Acessório entregue"], "concluir": "1"}).status_code, 200)
        self.assertIsNone(self.ordem.checklist_entrega.concluido_em)
        self.assertEqual(self.client.post(url, {"item": ["Acessório entregue"], "acessorios": "on", "testes": "on", "concluir": "1"}).status_code, 302)
        self.ordem.checklist_entrega.refresh_from_db()
        self.assertIsNotNone(self.ordem.checklist_entrega.concluido_em)
        ConfiguracaoOperacaoEmpresa.objects.filter(empresa=self.empresa).update(checklist_itens=["Novo item"])
        self.assertContains(self.client.get(url), "Acessório entregue")
        self.assertNotContains(self.client.get(url), "Novo item")

    def test_checklist_opcional_permite_conclusao_parcial(self):
        ConfiguracaoOperacaoEmpresa.objects.create(empresa=self.empresa, checklist_itens=["Conferir cabo"], checklist_obrigatorio=False)
        resposta = self.client.post(reverse("ordens:checklist_entrega", args=[self.ordem.pk]), {"concluir": "1"})
        self.assertEqual(resposta.status_code, 302)
        self.assertIsNotNone(self.ordem.checklist_entrega.concluido_em)
        self.assertEqual(self.ordem.checklist_entrega.marcados, [])

    def test_configuracao_prazos_e_checklist_por_empresa(self):
        resposta = self.client.post(reverse("ordens:configurar_operacao"), {
            "dias_os_parada": 4,
            "dias_orcamento_sem_resposta": 2,
            "dias_pronto_aguardando": 3,
            "dias_compra_pendente": 5,
            "dias_cobranca_fabricante": 0,
            "itens": "Conferir cabo\nDemonstrar teste",
            "itens_tipo": "celular | Conferir carregamento",
            "checklist_obrigatorio": "on",
        })
        self.assertEqual(resposta.status_code, 302)
        config = ConfiguracaoOperacaoEmpresa.objects.get(empresa=self.empresa)
        self.assertEqual(config.dias_os_parada, 4)
        self.assertEqual(config.checklist_itens, ["Conferir cabo", "Demonstrar teste"])
        self.assertEqual(config.checklist_por_tipo, {"celular": ["Conferir carregamento"]})
        self.assertFalse(ConfiguracaoOperacaoEmpresa.objects.filter(empresa=self.outra).exists())
        self.assertContains(self.client.get(reverse("ordens:checklist_entrega", args=[self.ordem.pk])), "Conferir carregamento")

    def test_tenant_bloqueado(self):
        outra_os = OrdemServico.objects.create(empresa=self.outra, cliente=Cliente.objects.create(nome="Outro", empresa=self.outra, documento="12345678909", estado="SP"), tipo_equipamento="celular", marca_equipamento="Marca", modelo_equipamento="M1", defeito="Oculto", tipo_reparo="Fora de Garantia")
        for nome in ("checklist_entrega", "historico_equipamento"):
            self.assertEqual(self.client.get(reverse(f"ordens:{nome}", args=[outra_os.pk])).status_code, 404)

    def test_margem_provisoria_com_custo_desconhecido(self):
        ServicoPeca.objects.create(ordem=self.ordem, tipo="peca", nome="Peça", quantidade=1, valor_unitario=Decimal("100.00"))
        resumo = resumo_rentabilidade_os(self.ordem)
        self.assertEqual(resumo["receita_registrada"], Decimal("100.00"))
        self.assertFalse(resumo["margem_confirmada"])
        self.assertTrue(resumo["custo_desconhecido"])
        resposta = self.client.get(reverse("caixa:rentabilidade_os"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Provisória")

    def test_previsao_separa_fabricante_e_conta_a_pagar(self):
        hoje = timezone.localdate()
        ContaReceber.objects.create(empresa=self.empresa, descricao="Fabricante", tipo_origem="garantia_fabricante", valor_original=Decimal("40"), valor_aberto=Decimal("40"), vencimento=hoje)
        ContaPagar.objects.create(empresa=self.empresa, descricao="Fornecedor", valor_total=Decimal("10"), vencimento=hoje)
        ContaReceber.objects.create(empresa=self.empresa, descricao="Em atraso", valor_original=Decimal("7"), valor_aberto=Decimal("7"), vencimento=hoje - timedelta(days=1))
        resposta = self.client.get(reverse("caixa:fluxo_projetado"))
        self.assertEqual(resposta.status_code, 200)
        mes = resposta.context["meses"][0]
        self.assertEqual(mes["entradas_fabricante"], Decimal("40"))
        self.assertEqual(mes["despesas_previstas"], Decimal("10"))
        self.assertEqual(mes["saldo_previsto"], Decimal("30"))
        self.assertEqual(resposta.context["vencido_receber"], Decimal("7"))

    def test_repasse_cartao_aparece_so_como_referencia(self):
        Pagamento.objects.create(
            empresa=self.empresa,
            caixa=Caixa.objects.create(empresa=self.empresa, aberto=True),
            valor=Decimal("100.00"),
            metodo="credito",
            data_movimento=timezone.localdate(),
            encargos_gerenciais_snapshot={"taxas_detalhe": [{"dias_recebimento": 2, "valor": "100.00", "taxa_valor": "3.00"}]},
        )
        resposta = self.client.get(reverse("caixa:fluxo_projetado"))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(sum((item["repasses_cartao"]["liquido"] for item in resposta.context["meses"]), Decimal("0.00")), Decimal("97.00"))
        self.assertEqual(resposta.context["total_entradas_previstas"], Decimal("0.00"))
