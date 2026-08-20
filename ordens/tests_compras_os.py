from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from caixa.models import ContaPagar
from clientes.models import Cliente
from configuracoes.models import Empresa
from estoque.models import PontoOperacional, Produto, UbicacaoEstoque
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.models import CustoOrdemServico, OrdemServico, PedidoCompra, ServicoPeca
from ordens.forms import CustoOrdemServicoForm
from orcamentos.services import FluxoOrcamentoService
from ordens.services.compras_os import receber_pedido_os, estornar_recebimento_pedido_os
from ordens.services.fechamento_os import FechamentoOSService


class RecebimentoPedidoCompraOSTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome="Empresa Compras OS", cnpj="12.345.678/0001-90")
        self.usuario = get_user_model().objects.create_user(
            username="gestor_compras_os", password="senha-forte-123", tipo_usuario="gerente",
            empresa=self.empresa,
        )
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, nome="Cliente Compras", documento="52998224725",
            telefone="11999990000", estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            empresa=self.empresa, cliente=self.cliente, tipo_equipamento="climatizador",
            marca_equipamento="Marca", modelo_equipamento="Modelo", defeito="Falha",
            tipo_reparo="Fora de Garantia",
        )
        self.orcamento = Orcamento.objects.create(
            empresa=self.empresa, cliente=self.cliente, ordem_servico=self.ordem,
        )
        self.item = ItemOrcamento.objects.create(
            orcamento=self.orcamento, nome="Teclas", tipo_item="peca", origem="manual",
            quantidade=2, valor_unitario=Decimal("80.00"), situacao_aquisicao="solicitado",
        )
        self.pedido = PedidoCompra.objects.create(
            empresa=self.empresa, ordem=self.ordem, item_orcamento=self.item,
            titulo="Comprar teclas", quantidade_solicitada=Decimal("2.000"), criado_por=self.usuario,
        )

    def test_recebimento_parcial_e_total_gera_custo_real_sem_estoque(self):
        primeiro = receber_pedido_os(
            pedido=self.pedido, quantidade="1", custo_unitario="25.00", destino="uso_os",
            usuario=self.usuario, chave_idempotencia="receb-direto-1",
        )
        self.pedido.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.pedido.status, "recepcionado_parcial")
        self.assertEqual(self.item.situacao_aquisicao, "solicitado")
        self.assertEqual(primeiro.custo_os.total, Decimal("25.00"))

        segundo = receber_pedido_os(
            pedido=self.pedido, quantidade="1", custo_unitario="30.00", destino="uso_os",
            usuario=self.usuario, chave_idempotencia="receb-direto-2",
        )
        self.pedido.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.pedido.status, "recepcionado")
        self.assertEqual(self.item.situacao_aquisicao, "recebido")
        self.assertEqual(self.ordem.custo_real_financeiro(), Decimal("55.00"))

        estornar_recebimento_pedido_os(
            recebimento=segundo, usuario=self.usuario, motivo="Peça devolvida ao fornecedor",
        )
        segundo.custo_os.refresh_from_db()
        self.pedido.refresh_from_db()
        self.assertTrue(segundo.custo_os.estornado)
        self.assertEqual(self.pedido.status, "recepcionado_parcial")
        self.assertEqual(CustoOrdemServico.objects.filter(ordem=self.ordem, estornado_em__isnull=True).count(), 1)

    def test_entrada_estoque_atualiza_saldo_e_exige_natureza_ativo(self):
        ponto = PontoOperacional.objects.create(empresa=self.empresa, codigo="LAB", nome="Laboratório")
        local = UbicacaoEstoque.objects.create(ponto_operacional=ponto, codigo="A-01")
        produto = Produto.objects.create(
            empresa=self.empresa, nome="Tecla", tipo_item="peca", quantidade=0,
            custo_unitario=Decimal("0.00"), custo_medio=Decimal("0.00"), preco=Decimal("50.00"),
            preco_final=Decimal("50.00"), ponto_operacional=ponto, ubicacao_padrao=local,
        )
        conta_errada = ContaPagar.objects.create(
            empresa=self.empresa, descricao="Compra operacional", valor_total=Decimal("40.00"),
            vencimento=timezone.localdate(), natureza_economica="despesa_operacional",
        )
        with self.assertRaises(ValidationError):
            receber_pedido_os(
                pedido=self.pedido, quantidade="2", custo_unitario="20", destino="estoque",
                usuario=self.usuario, chave_idempotencia="estoque-invalido", produto_estoque=produto,
                ponto_operacional=ponto, ubicacao=local, conta_pagar=conta_errada,
            )

        conta_estoque = ContaPagar.objects.create(
            empresa=self.empresa, descricao="Compra de estoque", valor_total=Decimal("40.00"),
            vencimento=timezone.localdate(), natureza_economica="estoque",
        )
        recebimento = receber_pedido_os(
            pedido=self.pedido, quantidade="2", custo_unitario="20", destino="estoque",
            usuario=self.usuario, chave_idempotencia="estoque-valido", produto_estoque=produto,
            ponto_operacional=ponto, ubicacao=local, conta_pagar=conta_estoque,
        )
        produto.refresh_from_db()
        self.assertEqual(produto.quantidade, 2)
        self.assertEqual(produto.custo_unitario, Decimal("20.00"))
        self.assertIsNotNone(recebimento.movimentacao_estoque_id)
        self.assertIsNone(recebimento.custo_os_id)

        estornar_recebimento_pedido_os(
            recebimento=recebimento, usuario=self.usuario, motivo="Nota cancelada",
        )
        produto.refresh_from_db()
        self.assertEqual(produto.quantidade, 0)

    def test_fechamento_bloqueia_peca_manual_sem_custo_confirmado(self):
        item_servico = ServicoPeca.objects.create(
            ordem=self.ordem, item_orcamento=self.item, tipo="peca", nome="Teclas",
            quantidade=1, valor_unitario=Decimal("80.00"),
        )
        with self.assertRaisesMessage(ValueError, "Confirme o custo real"):
            FechamentoOSService.finalizar_para_caixa(self.ordem, usuario=self.usuario)
        CustoOrdemServico.objects.create(
            empresa=self.empresa, ordem=self.ordem, item_orcamento=self.item,
            servico_peca=item_servico, tipo="peca", origem="compra_especifica",
            descricao="Custo confirmado", quantidade=1, custo_unitario=Decimal("0.00"),
            criado_por=self.usuario,
        )
        self.ordem.relatorio_tecnico = "Peça substituída e equipamento testado."
        self.ordem.tipo_reparacao = "substituicao"
        self.ordem.save(update_fields=["relatorio_tecnico", "tipo_reparacao"])
        resultado = FechamentoOSService.finalizar_para_caixa(self.ordem, usuario=self.usuario)
        self.assertTrue(resultado.fechando)

    def test_fechamento_aceita_custo_real_vinculado_so_a_peca_comercial_migrada(self):
        self.item.status = "aprovado"
        self.item.save(update_fields=["status"])
        FluxoOrcamentoService.migrar_itens_aprovados_da_ordem(
            self.ordem,
            usuario=self.usuario,
            criar_historico=False,
        )
        peca = ServicoPeca.objects.get(ordem=self.ordem, item_orcamento=self.item)
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=self.ordem,
            servico_peca=peca,
            tipo="peca",
            origem="compra_especifica",
            estado="realizado",
            descricao="Tela comprada após aprovação",
            quantidade=1,
            custo_unitario=Decimal("60.00"),
            criado_por=self.usuario,
        )

        FechamentoOSService._validar_custos_pecas_manuais(self.ordem)

    def test_formulario_aceita_custo_vinculado_a_peca_da_propria_os(self):
        peca = ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=self.item,
            tipo="peca",
            nome="Tela comprada após orçamento",
            quantidade=1,
            valor_unitario=Decimal("130.00"),
        )
        form = CustoOrdemServicoForm(
            {
                "tipo": "peca",
                "origem": "compra_especifica",
                "estado": "realizado",
                "descricao": "Compra da tela",
                "quantidade": "1",
                "unidade": "UN",
                "custo_unitario": "60.00",
                "data_competencia": timezone.localdate().isoformat(),
                "servico_peca": str(peca.id),
            },
            ordem=self.ordem,
        )

        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_fechamento_nao_confunde_custo_previsto_com_custo_real(self):
        peca = ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=self.item,
            tipo="peca",
            nome="Tela comprada depois",
            quantidade=1,
            valor_unitario=Decimal("130.00"),
        )
        CustoOrdemServico.objects.create(
            empresa=self.empresa,
            ordem=self.ordem,
            servico_peca=peca,
            tipo="peca",
            origem="compra_especifica",
            estado="previsto",
            descricao="Cotação inicial",
            quantidade=1,
            custo_unitario=Decimal("60.00"),
            criado_por=self.usuario,
        )

        with self.assertRaisesMessage(ValueError, "Confirme o custo real"):
            FechamentoOSService._validar_custos_pecas_manuais(self.ordem)

    def test_migracao_repara_vinculo_estoque_ausente_por_ean(self):
        ponto = PontoOperacional.objects.create(
            empresa=self.empresa,
            codigo="LOJA",
            nome="Loja",
        )
        produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Teclas em estoque",
            ean="7909569284421",
            tipo_item="peca",
            quantidade=1,
            custo_unitario=Decimal("55.00"),
            custo_medio=Decimal("95.00"),
            preco=Decimal("130.00"),
            preco_final=Decimal("130.00"),
            ponto_operacional=ponto,
        )
        self.item.ean = produto.ean
        self.item.origem = "estoque"
        self.item.status = "aprovado"
        self.item.save(update_fields=["ean", "origem", "status"])
        servico = ServicoPeca.objects.create(
            ordem=self.ordem,
            item_orcamento=self.item,
            tipo="peca",
            nome=produto.nome,
            quantidade=1,
            valor_unitario=Decimal("130.00"),
        )

        FluxoOrcamentoService.migrar_itens_aprovados_da_ordem(
            self.ordem,
            usuario=self.usuario,
            criar_historico=False,
        )

        servico.refresh_from_db()
        self.assertEqual(servico.produto_estoque_id, produto.id)
        self.assertEqual(servico.ponto_operacional_reserva_id, ponto.id)
        FechamentoOSService._validar_custos_pecas_manuais(self.ordem)

    def test_fechamento_valida_peca_manual_depois_de_migrar_orcamento(self):
        self.item.status = "aprovado"
        self.item.save(update_fields=["status"])

        with self.assertRaisesMessage(ValueError, "Confirme o custo real"):
            FechamentoOSService.alternar_fechamento(self.ordem, usuario=self.usuario)
