# orcamentos/models.py
from django.db import models
from django.db.models import Q
from clientes.models import Cliente
from ordens.models import OrdemServico
from decimal import Decimal

class Orcamento(models.Model):
    TIPO_CHOICES = (
        ('1', 'Orçamento Principal'),
    )

    STATUS_CHOICES = (
        ('pendente', 'Pendente'),
        ('aprovado', 'Aprovado'),
        ('recusado', 'Recusado'),
    )

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orcamentos",
    )
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    ordem_servico = models.ForeignKey(
        OrdemServico,
        on_delete=models.CASCADE,
        related_name='orcamentos'
    )
    numero = models.PositiveSmallIntegerField(default=1)  # 🔹 Novo campo
    tipo = models.CharField(max_length=1, choices=TIPO_CHOICES, default='1')
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    desconto_valor = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    desconto_percentual = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    descricao = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pendente')
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Orçamento #{self.id} - {self.cliente} (nº {self.numero})"

    def subtotal_itens(self):
        return sum(item.total() for item in self.itens.all())

    def desconto_calculado(self):
        subtotal = Decimal(self.subtotal_itens() or 0)
        percentual = Decimal(self.desconto_percentual or 0)
        valor = Decimal(self.desconto_valor or 0)
        if subtotal <= Decimal("0.00"):
            return Decimal("0.00")
        if percentual > Decimal("0.00"):
            desconto = (subtotal * percentual) / Decimal("100")
        else:
            desconto = valor
        if desconto < Decimal("0.00"):
            return Decimal("0.00")
        return min(desconto, subtotal)

    def total(self):
        subtotal = Decimal(self.subtotal_itens() or 0)
        return max(Decimal("0.00"), subtotal - self.desconto_calculado())

    def atualizar_total(self):
        self.valor_total = self.total()
        self.save(update_fields=["valor_total"])


class ItemOrcamento(models.Model):
    TIPO_ITEM_CHOICES = [
        ("servico", "Serviço"),
        ("peca", "Peça"),
    ]
    ORIGEM_CHOICES = [
        ('estoque', 'Estoque'),
        ('manual', 'Manual'),
    ]

    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('aprovado', 'Aprovado'),
        ('recusado', 'Recusado'),
    ]
    SITUACAO_AQUISICAO_CHOICES = [
        ("nao_necessario", "Não necessário"),
        ("a_comprar", "A comprar"),
        ("solicitado", "Solicitado"),
        ("recebido", "Recebido"),
        ("cancelado", "Cancelado"),
    ]

    orcamento = models.ForeignKey(Orcamento, on_delete=models.CASCADE, related_name='itens')
    ean = models.CharField(max_length=50, blank=True, null=True)
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True)
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    quantidade = models.PositiveIntegerField(default=1)
    desconto_valor = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    desconto_percentual = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tipo_item = models.CharField(max_length=20, choices=TIPO_ITEM_CHOICES, default="servico")
    origem = models.CharField(max_length=10, choices=ORIGEM_CHOICES, default='manual')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pendente')  # ← campo novo
    tecnico_responsavel = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_orcamento_responsavel",
        limit_choices_to=Q(is_active=True) & (Q(tipo_usuario="tecnico") | Q(atua_como_tecnico=True)),
    )
    comissionavel = models.BooleanField(default=True)
    custo_estimado_unitario = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    fornecedor_estimado = models.CharField(max_length=160, blank=True)
    referencia_cotacao = models.CharField(max_length=100, blank=True)
    situacao_aquisicao = models.CharField(
        max_length=20,
        choices=SITUACAO_AQUISICAO_CHOICES,
        default="nao_necessario",
    )

    def subtotal(self):
        return self.valor_unitario * self.quantidade

    def custo_estimado_total(self):
        if self.custo_estimado_unitario is None:
            return None
        return self.custo_estimado_unitario * self.quantidade

    def margem_estimada(self):
        custo = self.custo_estimado_total()
        if custo is None:
            return None
        return self.total() - custo

    def desconto_calculado(self):
        subtotal = Decimal(self.subtotal() or 0)
        percentual = Decimal(self.desconto_percentual or 0)
        valor = Decimal(self.desconto_valor or 0)
        if subtotal <= Decimal("0.00"):
            return Decimal("0.00")
        if percentual > Decimal("0.00"):
            desconto = (subtotal * percentual) / Decimal("100")
        else:
            desconto = valor
        if desconto < Decimal("0.00"):
            return Decimal("0.00")
        return min(desconto, subtotal)

    def total(self):
        return max(Decimal("0.00"), self.subtotal() - self.desconto_calculado())

    def save(self, *args, **kwargs):
        if not self.tipo_item:
            self.tipo_item = "peca" if self.origem == "estoque" else "servico"
        super().save(*args, **kwargs)
        self.orcamento.atualizar_total()
