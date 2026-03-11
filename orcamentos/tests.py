from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from decimal import Decimal

from caixa.models import ComissaoItemOrcamento, RegraComissaoTecnico
from clientes.models import Cliente
from estoque.models import Produto
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.models import OrdemServico


class ItemOrcamentoTecnicoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente_orc",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.tecnico = user_model.objects.create_user(
            username="tecnico_orc",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.client.force_login(self.atendente)

        self.cliente = Cliente.objects.create(
            nome="Cliente Orcamento",
            documento="39053344705",
            telefone="11999998888",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca O",
            modelo_equipamento="Modelo O",
            defeito="Teste",
            tipo_reparo="Fora de Garantia",
            status="diagnosticar",
        )
        self.orcamento = Orcamento.objects.create(cliente=self.cliente, ordem_servico=self.ordem)

    def test_adicionar_item_com_tecnico_responsavel(self):
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "7890001112223",
                "nome": "Troca de Tela",
                "descricao": "Servico",
                "valor_unitario": "200.00",
                "quantidade": "1",
                "tipo_item": "servico",
                "origem": "manual",
                "tecnico_responsavel": str(self.tecnico.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        item = ItemOrcamento.objects.latest("id")
        self.assertEqual(item.tecnico_responsavel_id, self.tecnico.id)
        self.assertEqual(item.tipo_item, "servico")

    def test_editar_item_atualiza_tecnico_responsavel(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Bateria",
            descricao="Peca",
            valor_unitario="90.00",
            quantidade=1,
            origem="manual",
        )
        response = self.client.post(
            reverse("orcamentos:editar_item", args=[item.id]),
            {
                "nome": "Bateria",
                "descricao": "Peca",
                "quantidade": "1",
                "valor_unitario": "90.00",
                "tipo_item": "peca",
                "origem": "manual",
                "tecnico_responsavel": str(self.tecnico.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.tecnico_responsavel_id, self.tecnico.id)

    def test_adicionar_item_detecta_origem_estoque_por_ean(self):
        produto = Produto.objects.create(
            nome="Tela Original",
            ean="7891234567890",
            preco_final=Decimal("150.00"),
            quantidade=5,
        )
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": produto.ean,
                "nome": "Tela Original",
                "descricao": "Peca",
                "valor_unitario": "150.00",
                "quantidade": "1",
                "tipo_item": "peca",
                "origem": "manual",
            },
        )
        self.assertEqual(response.status_code, 302)
        item = ItemOrcamento.objects.latest("id")
        self.assertEqual(item.origem, "estoque")
        self.assertEqual(item.tipo_item, "peca")

    def test_editar_item_atualiza_ean_e_origem_automaticamente(self):
        produto = Produto.objects.create(
            nome="Conector Carga",
            ean="7891234567001",
            preco_final=Decimal("35.00"),
            quantidade=3,
        )
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Servico Solda",
            descricao="Manual",
            valor_unitario="35.00",
            quantidade=1,
            origem="manual",
        )
        response = self.client.post(
            reverse("orcamentos:editar_item", args=[item.id]),
            {
                "ean": produto.ean,
                "nome": produto.nome,
                "descricao": "Peca",
                "quantidade": "1",
                "valor_unitario": "35.00",
                "tipo_item": "peca",
                "origem": "manual",
            },
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.ean, produto.ean)
        self.assertEqual(item.origem, "estoque")

    def test_adicionar_item_sem_tipo_reabre_modal_orcamento(self):
        response = self.client.post(
            reverse("orcamentos:adicionar_item", args=[self.orcamento.id]),
            {
                "ean": "7890001112223",
                "nome": "Item sem tipo",
                "descricao": "Teste",
                "valor_unitario": "50.00",
                "quantidade": "1",
                "tipo_item": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("open_modal=adicionar_item", response.url)

    def test_migrar_para_servicos_preserva_tecnico_responsavel(self):
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Servico tecnico",
            descricao="Teste",
            valor_unitario="100.00",
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
        )
        response = self.client.post(
            reverse("orcamentos:migrar_para_servicos", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
        )
        self.assertEqual(response.status_code, 302)
        servico = self.ordem.servicos_pecas.order_by("-id").first()
        self.assertIsNotNone(servico)
        self.assertEqual(servico.tecnico_responsavel_id, self.tecnico.id)

    def test_aceitar_itens_gera_comissao_antecipada_quando_ordem_qualifica(self):
        self.ordem.status = "pronto_contactado"
        self.ordem.save(update_fields=["status"])
        RegraComissaoTecnico.objects.create(
            usuario=self.tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Mao de obra",
            descricao="Servico",
            valor_unitario=Decimal("100.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="pendente",
        )
        response = self.client.post(
            reverse("orcamentos:aceitar_orcamento", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ComissaoItemOrcamento.objects.filter(
                item_orcamento=item,
                tecnico=self.tecnico,
                modo_pagamento="antecipado",
            ).exists()
        )
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "pronto_contactado")

    def test_aceitar_itens_muda_status_para_autorizado_quando_nao_final(self):
        self.ordem.status = "bancada"
        self.ordem.save(update_fields=["status"])
        item = ItemOrcamento.objects.create(
            orcamento=self.orcamento,
            nome="Mao de obra",
            descricao="Servico",
            valor_unitario=Decimal("100.00"),
            quantidade=1,
            origem="manual",
            tipo_item="servico",
            tecnico_responsavel=self.tecnico,
            status="pendente",
        )
        response = self.client.post(
            reverse("orcamentos:aceitar_orcamento", args=[self.orcamento.id]),
            {"itens_selecionados": [str(item.id)]},
        )
        self.assertEqual(response.status_code, 302)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "autorizado")
