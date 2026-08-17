from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from caixa.models import (
    AuditoriaFinanceira,
    ContaBancaria,
    FechamentoBancario,
    LinhaExtratoBancario,
    MovimentoBancario,
)
from configuracoes.models import Empresa


class EdicaoContaBancariaTests(TestCase):
    def setUp(self):
        self.data_base = date(2026, 7, 17)
        self.empresa = Empresa.objects.create(
            nome="Empresa Tesouraria", cnpj="12.345.678/0001-90"
        )
        self.usuario = get_user_model().objects.create_user(
            username="gestor_conta_bancaria",
            password="senha-forte-123",
            tipo_usuario="gerente",
            empresa=self.empresa,
            perm_caixa_corrigir_lancamentos=True,
        )
        self.conta = ContaBancaria.objects.create(
            empresa=self.empresa,
            nome="Nubank",
            banco_nome="Nu Pagamentos",
            numero="123-4",
            tipo="pagamento",
            saldo_inicial=Decimal("1800.00"),
            data_saldo_inicial=self.data_base,
        )
        self.movimento = MovimentoBancario.objects.create(
            empresa=self.empresa,
            conta=self.conta,
            tipo="entrada",
            origem_tipo="aporte_capital",
            origem_id=1,
            descricao="Aporte inicial",
            valor=Decimal("1800.00"),
            data_movimento=self.data_base,
            chave_idempotencia="teste-aporte-inicial",
            registrado_por=self.usuario,
        )
        self.linha = LinhaExtratoBancario.objects.create(
            empresa=self.empresa,
            conta=self.conta,
            identificador_externo="linha-aporte-inicial",
            data_movimento=self.data_base,
            descricao="Transferência recebida do sócio",
            valor=Decimal("1800.00"),
            status="conciliado",
            movimento=self.movimento,
        )
        self.client.force_login(self.usuario)

    def _dados_edicao(self, **alteracoes):
        dados = {
            "nome": self.conta.nome,
            "banco_codigo": self.conta.banco_codigo,
            "banco_nome": self.conta.banco_nome,
            "agencia": self.conta.agencia,
            "numero": self.conta.numero,
            "tipo": self.conta.tipo,
            "saldo_inicial": "0.00",
            "data_saldo_inicial": self.data_base.isoformat(),
            "ativa": "on",
            "justificativa": "Saldo inicial duplicado pelo aporte importado.",
        }
        dados.update(alteracoes)
        return dados

    def test_tesouraria_exibe_alerta_e_botao_para_editar(self):
        resposta = self.client.get(reverse("caixa:tesouraria"))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Editar conta")
        self.assertContains(resposta, "pode estar sendo contada duas vezes")

    def test_edita_saldo_inicial_e_registra_auditoria(self):
        self.assertEqual(self.conta.saldo_atual, Decimal("3600.00"))

        resposta = self.client.post(
            reverse("caixa:editar_conta_bancaria", args=[self.conta.pk]),
            self._dados_edicao(),
        )

        self.assertRedirects(resposta, reverse("caixa:tesouraria"))
        self.conta.refresh_from_db()
        self.assertEqual(self.conta.saldo_inicial, Decimal("0.00"))
        self.assertEqual(self.conta.saldo_atual, Decimal("1800.00"))
        auditoria = AuditoriaFinanceira.objects.get(evento="conta_bancaria_editada")
        self.assertIn("1800.00 -> 0.00", auditoria.descricao)
        self.assertIn("Saldo inicial duplicado", auditoria.descricao)
        self.assertEqual(auditoria.usuario, self.usuario)

    def test_bloqueia_alteracao_da_base_com_periodo_fechado(self):
        FechamentoBancario.objects.create(
            empresa=self.empresa,
            conta=self.conta,
            periodo_inicio=self.data_base,
            periodo_fim=self.data_base + timedelta(days=30),
            saldo_sistema=Decimal("1800.00"),
            saldo_extrato=Decimal("1800.00"),
            diferenca=Decimal("0.00"),
            fechado_por=self.usuario,
        )

        resposta = self.client.post(
            reverse("caixa:editar_conta_bancaria", args=[self.conta.pk]),
            self._dados_edicao(),
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Reabra os períodos bancários fechados")
        self.conta.refresh_from_db()
        self.assertEqual(self.conta.saldo_inicial, Decimal("1800.00"))
        self.assertFalse(
            AuditoriaFinanceira.objects.filter(evento="conta_bancaria_editada").exists()
        )

    def test_saldo_desconsidera_movimentos_anteriores_a_data_base(self):
        MovimentoBancario.objects.create(
            empresa=self.empresa,
            conta=self.conta,
            tipo="entrada",
            origem_tipo="manual",
            descricao="Movimento anterior à data-base",
            valor=Decimal("250.00"),
            data_movimento=self.data_base - timedelta(days=1),
            chave_idempotencia="movimento-anterior-data-base",
            registrado_por=self.usuario,
        )

        self.assertEqual(self.conta.saldo_atual, Decimal("3600.00"))
        self.assertEqual(self.conta.saldo_projetado, Decimal("3600.00"))
