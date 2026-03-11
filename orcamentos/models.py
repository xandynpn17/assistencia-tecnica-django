# orcamentos/models.py
from django.db import models
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

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    ordem_servico = models.ForeignKey(
        OrdemServico,
        on_delete=models.CASCADE,
        related_name='orcamentos'
    )
    numero = models.PositiveSmallIntegerField(default=1)  # 🔹 Novo campo
    tipo = models.CharField(max_length=1, choices=TIPO_CHOICES, default='1')
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    descricao = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pendente')
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Orçamento #{self.id} - {self.cliente} (nº {self.numero})"

    def total(self):
        return sum(item.total() for item in self.itens.all())

    def atualizar_total(self):
        self.valor_total = self.total()
        self.save(update_fields=["valor_total"])


class ItemOrcamento(models.Model):
    TIPO_ITEM_CHOICES = [
        ("servico", "Servico"),
        ("peca", "Peca"),
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

    orcamento = models.ForeignKey(Orcamento, on_delete=models.CASCADE, related_name='itens')
    ean = models.CharField(max_length=50, blank=True, null=True)
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True)
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    quantidade = models.PositiveIntegerField(default=1)
    tipo_item = models.CharField(max_length=20, choices=TIPO_ITEM_CHOICES, default="servico")
    origem = models.CharField(max_length=10, choices=ORIGEM_CHOICES, default='manual')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pendente')  # ← campo novo
    tecnico_responsavel = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_orcamento_responsavel",
        limit_choices_to={"tipo_usuario": "tecnico", "is_active": True},
    )

    def total(self):
        return self.valor_unitario * self.quantidade

    def save(self, *args, **kwargs):
        if not self.tipo_item:
            self.tipo_item = "peca" if self.origem == "estoque" else "servico"
        super().save(*args, **kwargs)
        self.orcamento.atualizar_total()
