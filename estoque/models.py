from decimal import Decimal
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class PontoOperacional(models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nome = models.CharField(max_length=80)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.nome}"


class UbicacaoEstoque(models.Model):
    ponto_operacional = models.ForeignKey(
        PontoOperacional,
        on_delete=models.CASCADE,
        related_name="ubicacoes",
    )
    codigo = models.CharField(max_length=30)
    descricao = models.CharField(max_length=120, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["ponto_operacional__codigo", "codigo"]
        unique_together = [("ponto_operacional", "codigo")]

    def __str__(self):
        base = f"{self.ponto_operacional.codigo} - {self.codigo}"
        return f"{base} ({self.descricao})" if self.descricao else base


class Produto(models.Model):
    TIPO_ITEM_CHOICES = [
        ("produto", "Produto"),
        ("servico", "Servico"),
    ]

    nome = models.CharField(max_length=100)
    sku = models.CharField(max_length=50, blank=True, null=True)
    ean = models.CharField(max_length=50, blank=True, null=True, unique=True)
    descricao = models.TextField(blank=True)
    categoria = models.CharField(max_length=50, blank=True)
    fornecedor = models.CharField(max_length=50, blank=True)

    custo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    custo_operacional = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    margem_lucro = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    icms = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    ipi = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    pis_cofins = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    pis = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    cofins = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    taxa_cartao = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    tipo_item = models.CharField(max_length=20, choices=TIPO_ITEM_CHOICES, default="produto")
    usar_aliquota_manual = models.BooleanField(default=False)
    aliquota_manual = models.DecimalField(max_digits=6, decimal_places=3, default=0, blank=True)
    preco_sugerido = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=0)
    preco_final = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    preco = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    quantidade = models.PositiveIntegerField(default=0)
    estoque_minimo = models.PositiveIntegerField(default=0)
    ativo = models.BooleanField(default=True)
    data_entrada = models.DateField(default=timezone.now, blank=True)
    is_servico = models.BooleanField(default=False, verbose_name="E um servico")
    ponto_operacional = models.ForeignKey(
        "estoque.PontoOperacional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produtos",
    )

    def save(self, *args, **kwargs):
        if not self.ponto_operacional:
            po3, _ = PontoOperacional.objects.get_or_create(codigo="PO3", defaults={"nome": "Loja", "ativo": True})
            self.ponto_operacional = po3

        if not self.ean:
            ultimo_produto = Produto.objects.order_by("-id").first()
            if ultimo_produto and ultimo_produto.ean:
                try:
                    self.ean = str(int(ultimo_produto.ean) + 1)
                except ValueError:
                    self.ean = "2200000000000"
            else:
                self.ean = "2200000000000"

        self.ean = str(self.ean).zfill(13)[:13]

        # Sincroniza legado com o novo tipo de item.
        if self.tipo_item == "servico":
            self.is_servico = True
        elif self.tipo_item == "produto":
            self.is_servico = False
        elif self.is_servico:
            self.tipo_item = "servico"
        else:
            self.tipo_item = "produto"

        custo_total = (self.custo_unitario or 0) + (self.custo_operacional or 0)

        aliquota_percent = Decimal("0")
        if self.usar_aliquota_manual:
            aliquota_percent = Decimal(str(self.aliquota_manual or 0))
        else:
            try:
                from configuracoes.models import Empresa

                empresa = Empresa.objects.first()
            except Exception:
                empresa = None

            if empresa:
                regime = (empresa.regime_tributario or "simples")
                modo = (empresa.modo_tributario or "basico")
                if regime == "simples" and modo == "basico":
                    aliquota_percent = Decimal(str(empresa.aliquota_servico if self.tipo_item == "servico" else empresa.aliquota_comercio))
                else:
                    aliquota_percent = Decimal(str((empresa.icms or 0) + (empresa.ipi or 0) + (empresa.pis or 0) + (empresa.cofins or 0)))
            else:
                # fallback legado
                aliquota_percent = Decimal(str((self.icms or 0) + (self.ipi or 0) + (self.pis or 0) + (self.cofins or 0) or (self.pis_cofins or 0)))

        taxa_cartao_percent = Decimal(str(self.taxa_cartao or 0))
        margem_percent = Decimal(str(self.margem_lucro or 0))
        fator = Decimal("1") - (aliquota_percent / Decimal("100")) - (taxa_cartao_percent / Decimal("100")) - (margem_percent / Decimal("100"))
        if fator <= Decimal("0"):
            self.preco_sugerido = custo_total
        else:
            self.preco_sugerido = custo_total / fator

        if not self.preco_final or self.preco_final <= 0:
            self.preco_final = self.preco_sugerido

        self.preco = self.preco_final

        if not self.data_entrada:
            self.data_entrada = timezone.now().date()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} - R$ {self.preco_final:.2f}"

    @property
    def custo_total(self):
        return self.custo_unitario + self.custo_operacional

    @property
    def valor_impostos(self):
        impostos_totais = (self.icms + self.ipi + self.pis_cofins) / 100
        return self.custo_total * impostos_totais

    @property
    def preco_sugerido_sem_margem(self):
        return self.custo_total * (1 + (self.icms + self.ipi + self.pis_cofins) / 100)

    @property
    def lucro_reais(self):
        return self.preco_final - self.preco_sugerido_sem_margem

    @property
    def lucro_percentual(self):
        if self.preco_sugerido_sem_margem == 0:
            return 0
        return (self.lucro_reais / self.preco_sugerido_sem_margem) * 100


class MovimentacaoEstoque(models.Model):
    TIPO_CHOICES = [
        ("transferencia", "Transferencia"),
        ("avaria", "Avaria"),
        ("ajuste", "Ajuste"),
        ("venda", "Venda"),
        ("reserva", "Reserva"),
        ("consumo_os", "Consumo em OS"),
        ("devolucao_reserva", "Devolucao de reserva"),
        ("inventario", "Inventario"),
    ]

    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="movimentacoes")
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="transferencia")
    quantidade = models.IntegerField()
    origem = models.ForeignKey(
        "estoque.PontoOperacional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes_origem",
    )
    destino = models.ForeignKey(
        "estoque.PontoOperacional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes_destino",
    )
    destino_ubicacao = models.CharField(max_length=80, blank=True)
    observacao = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"{self.produto.nome} - {self.get_tipo_display()} ({self.quantidade})"


class SaldoEstoquePonto(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="saldos_por_ponto")
    ponto_operacional = models.ForeignKey(PontoOperacional, on_delete=models.CASCADE, related_name="saldos")
    quantidade = models.IntegerField(default=0)

    class Meta:
        unique_together = [("produto", "ponto_operacional")]
        ordering = ["ponto_operacional__codigo"]

    def __str__(self):
        return f"{self.produto.nome} @ {self.ponto_operacional.codigo}: {self.quantidade}"


class VendaRapidaEstoque(models.Model):
    STATUS_CHOICES = [
        ("pre_reserva", "Pre-reserva"),
        ("vendida", "Vendida"),
        ("cancelada", "Cancelada"),
    ]

    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="vendas_rapidas")
    ponto_operacional = models.ForeignKey(PontoOperacional, on_delete=models.PROTECT, related_name="vendas_rapidas")
    quantidade = models.PositiveIntegerField(default=1)
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)
    funcionario_numero = models.CharField(max_length=30)
    cesto_codigo = models.CharField(max_length=24, blank=True, db_index=True)
    guia_pagamento = models.CharField(max_length=24, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pre_reserva")
    pagamento = models.ForeignKey("caixa.Pagamento", on_delete=models.SET_NULL, null=True, blank=True)
    usuario = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"{self.produto.nome} - {self.quantidade} - {self.get_status_display()}"


class ReservaEstoque(models.Model):
    STATUS_CHOICES = [
        ("ativa", "Ativa"),
        ("expirada", "Expirada"),
        ("convertida", "Convertida"),
        ("cancelada", "Cancelada"),
    ]

    codigo_reserva = models.CharField(max_length=14, unique=True)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="reservas")
    ponto_operacional = models.ForeignKey(
        PontoOperacional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reservas",
    )
    quantidade = models.PositiveIntegerField(default=1)
    nome_contato = models.CharField(max_length=120)
    telefone_contato = models.CharField(max_length=30, blank=True)
    valido_ate = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ativa")
    motivo_status = models.CharField(max_length=180, blank=True)
    convertida_em = models.DateTimeField(null=True, blank=True)
    expirada_em = models.DateTimeField(null=True, blank=True)
    cancelada_em = models.DateTimeField(null=True, blank=True)
    ordem_servico = models.ForeignKey(
        "ordens.OrdemServico",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reservas_estoque",
    )
    item_orcamento = models.ForeignKey(
        "orcamentos.ItemOrcamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reservas_estoque",
    )
    usuario = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"{self.codigo_reserva} - {self.produto.nome} ({self.status})"


class InventarioEstoque(models.Model):
    STATUS_CHOICES = [
        ("aberto", "Aberto"),
        ("fechado", "Fechado"),
        ("cancelado", "Cancelado"),
    ]

    ponto_operacional = models.ForeignKey(PontoOperacional, on_delete=models.PROTECT, related_name="inventarios")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="aberto")
    observacao = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    fechado_em = models.DateTimeField(null=True, blank=True)
    usuario = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"Inventario #{self.id} - {self.ponto_operacional.codigo} ({self.status})"


class ItemInventarioEstoque(models.Model):
    inventario = models.ForeignKey(InventarioEstoque, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="itens_inventario")
    quantidade_sistema = models.IntegerField(default=0)
    quantidade_contada = models.IntegerField(default=0)
    ajuste = models.IntegerField(default=0)
    observacao = models.CharField(max_length=160, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("inventario", "produto")]
        ordering = ["produto__nome"]

    def __str__(self):
        return f"{self.produto.nome} ({self.ajuste:+d})"


