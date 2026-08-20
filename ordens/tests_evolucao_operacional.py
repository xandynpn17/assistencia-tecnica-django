from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from caixa.models import AuditoriaGarantia, ContaReceber
from clientes.models import Cliente
from configuracoes.models import Empresa, FornecedorGarantia, MarcaGarantia
from estoque.models import PontoOperacional, Produto, UbicacaoEstoque
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.models import OrdemServico, PedidoCompra
from ordens.services.compras_os import receber_pedido_os
from ordens.services.fechamento_os import FechamentoOSService


class EvolucaoOperacionalOSTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome="Empresa Evolução OS",
            cnpj="45.723.174/0001-10",
        )
        self.usuario = get_user_model().objects.create_user(
            username="gestor_evolucao_os",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
        )
        self.cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Cliente Evolução",
            documento="52998224725",
            telefone="11999990000",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            tipo_equipamento="aspirador",
            marca_equipamento="Marca Evolução",
            modelo_equipamento="EV-1",
            defeito="Não liga",
            tipo_reparo="Fora de Garantia",
            referencia_parceiro="RP-GAR-7788",
            local_armazenamento="Prateleira A",
        )
        self.client.force_login(self.usuario)

    def test_linha_de_trabalho_preserva_local_em_branco_e_permite_alterar(self):
        url = reverse("ordens:adicionar_linha", args=[self.ordem.id])
        response = self.client.post(
            url,
            {"status": "diagnosticar", "descricao": "Análise inicial", "local_armazenamento": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.local_armazenamento, "Prateleira A")

        response = self.client.post(
            url,
            {"status": "em_andamento", "descricao": "Movido para bancada", "local_armazenamento": "Bancada 3"},
        )
        self.assertEqual(response.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.local_armazenamento, "Bancada 3")

    def test_busca_por_referencia_parceiro_com_prefixo_rp(self):
        response = self.client.get(reverse("ordens:buscar_ordens"), {"q": "rp:GAR-7788"})
        self.assertEqual(response.status_code, 200)
        resultados = response.json()["resultados"]
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["id"], self.ordem.id)
        self.assertEqual(resultados[0]["referencia_parceiro"], "RP-GAR-7788")

    def test_orcamento_exibe_total_aprovado_e_total_selecionado(self):
        orcamento = Orcamento.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            ordem_servico=self.ordem,
        )
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Serviço aprovado",
            tipo_item="servico",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            status="aprovado",
        )
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Peça pendente",
            tipo_item="peca",
            quantidade=1,
            valor_unitario=Decimal("40.00"),
            status="pendente",
        )
        response = self.client.get(
            reverse("ordens:detalhes_ordem", args=[self.ordem.id]),
            {"tab": "orcamentos"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["orcamento_stats"]["total_aprovado"], Decimal("100.00"))
        self.assertContains(response, "Total selecionado")

    def test_dashboard_mostra_pedido_de_compra_pendente(self):
        PedidoCompra.objects.create(
            empresa=self.empresa,
            ordem=self.ordem,
            titulo="Comprar motor",
            status="pendente_marca",
        )
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["pedidos_compra_pendentes_total"], 1)
        self.assertContains(response, "Pedidos de compra pendentes")

    def test_reposicao_de_estoque_nao_pode_ser_recebida_como_custo_direto(self):
        ponto = PontoOperacional.objects.create(
            empresa=self.empresa,
            codigo="LOJA",
            nome="Loja",
        )
        local = UbicacaoEstoque.objects.create(ponto_operacional=ponto, codigo="A-01")
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Motor",
            tipo_item="peca",
            quantidade=0,
            custo_unitario=Decimal("0.00"),
            custo_medio=Decimal("0.00"),
            preco=Decimal("90.00"),
            preco_final=Decimal("90.00"),
            ponto_operacional=ponto,
            ubicacao_padrao=local,
        )
        pedido = PedidoCompra.objects.create(
            empresa=self.empresa,
            ordem=self.ordem,
            produto_estoque=produto,
            titulo="Repor motor usado na garantia",
            finalidade="reposicao_estoque_os",
            quantidade_solicitada=1,
        )
        with self.assertRaisesMessage(ValidationError, "devem ser recebidos como entrada no estoque"):
            receber_pedido_os(
                pedido=pedido,
                quantidade=1,
                custo_unitario="35.00",
                destino="uso_os",
                usuario=self.usuario,
                chave_idempotencia="reposicao-uso-direto-invalido",
            )

        recebimento = receber_pedido_os(
            pedido=pedido,
            quantidade=1,
            custo_unitario="35.00",
            destino="estoque",
            usuario=self.usuario,
            chave_idempotencia="reposicao-estoque-valido",
            produto_estoque=produto,
            ponto_operacional=ponto,
            ubicacao=local,
        )
        produto.refresh_from_db()
        self.assertEqual(produto.quantidade, 1)
        self.assertIsNotNone(recebimento.movimentacao_estoque_id)
        self.assertIsNone(recebimento.custo_os_id)

    def test_finalizacao_garantia_cria_conta_fabricante_sem_cobrar_cliente(self):
        fornecedor = FornecedorGarantia.objects.create(
            empresa=self.empresa,
            nome="Fabricante Evolução",
        )
        marca = MarcaGarantia.objects.create(
            empresa=self.empresa,
            nome="Marca Evolução",
            fornecedor=fornecedor,
            parceira_garantia=True,
            valor_mao_obra_garantia=Decimal("0.00"),
        )
        self.ordem.tipo_reparo = "Garantia"
        self.ordem.marca_garantia = marca
        self.ordem.relatorio_tecnico = "Equipamento reparado e testado."
        self.ordem.tipo_reparacao = "reparacao_sem_pecas"
        self.ordem.save(
            update_fields=["tipo_reparo", "marca_garantia", "relatorio_tecnico", "tipo_reparacao"]
        )
        orcamento = Orcamento.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            ordem_servico=self.ordem,
        )
        ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Mão de obra em garantia",
            tipo_item="servico",
            quantidade=1,
            valor_unitario=Decimal("100.00"),
            status="aprovado",
        )

        resultado = FechamentoOSService.finalizar_para_caixa(self.ordem, usuario=self.usuario)

        self.assertTrue(resultado.atualizou_auditoria_garantia)
        auditoria = AuditoriaGarantia.objects.get(ordem_servico=self.ordem)
        self.assertEqual(auditoria.valor_previsto_fabricante, Decimal("100.00"))
        conta = ContaReceber.objects.get(
            ordem_servico=self.ordem,
            tipo_origem="garantia_fabricante",
        )
        self.assertEqual(conta.valor_original, Decimal("100.00"))
        self.assertFalse(
            ContaReceber.objects.filter(
                ordem_servico=self.ordem,
                tipo_origem="cliente_os",
                status__in=["aberta", "parcial", "vencida"],
            ).exists()
        )

        FechamentoOSService.alternar_fechamento(self.ordem, usuario=self.usuario)
        conta.refresh_from_db()
        self.assertEqual(conta.status, "cancelada")
        self.assertEqual(conta.valor_aberto, Decimal("0.00"))
