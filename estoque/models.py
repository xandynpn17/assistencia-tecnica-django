from decimal import Decimal
from django.core.exceptions import ValidationError
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


class CategoriaProduto(models.Model):
    nome = models.CharField(max_length=80, unique=True)
    margem_padrao = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(1000)],
    )
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class ServicoReferencia(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Produto(models.Model):
    MODO_PRECO_CHOICES = [
        ("simples", "Simples"),
        ("avancado", "Avançado"),
    ]

    TIPO_ITEM_CHOICES = [
        ("produto", "Produto"),
        ("peca", "Peça"),
        ("consumivel", "Consumível"),
        ("servico", "Servico"),
    ]

    nome = models.CharField(max_length=100)
    sku = models.CharField(max_length=50, blank=True, null=True)
    ean = models.CharField(max_length=50, blank=True, null=True, unique=True)
    descricao = models.TextField(blank=True)
    categoria = models.CharField(max_length=50, blank=True)
    categoria_config = models.ForeignKey(
        "estoque.CategoriaProduto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produtos",
    )
    fornecedor = models.CharField(max_length=50, blank=True)
    fornecedor_config = models.ForeignKey(
        "configuracoes.FornecedorGarantia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produtos_estoque",
    )
    fornecedor_manual = models.CharField(max_length=120, blank=True)
    marca = models.ForeignKey(
        "configuracoes.MarcaGarantia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produtos_estoque",
    )
    modelos_compativeis = models.TextField(blank=True)
    localizacao = models.CharField(max_length=120, blank=True)
    foto = models.ImageField(upload_to="estoque/produtos/", null=True, blank=True)
    garantia_peca_dias = models.PositiveIntegerField(null=True, blank=True)
    observacao_interna = models.TextField(blank=True)
    permite_os = models.BooleanField(default=True)
    permite_comissao_peca = models.BooleanField(default=False)
    percentual_comissao_peca = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    bonus_venda = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    modo_preco = models.CharField(max_length=10, choices=MODO_PRECO_CHOICES, default="avancado")

    custo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    custo_operacional = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    custo_frete = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    custo_impostos = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    custo_comissao = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    custo_marketplace = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    custo_medio = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    margem_lucro = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    margem_minima = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(99.99)],
    )
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
    preco_minimo = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=0)
    preco_final = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    preco = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    quantidade = models.PositiveIntegerField(default=0)
    estoque_minimo = models.PositiveIntegerField(default=0)
    ativo = models.BooleanField(default=True)
    data_entrada = models.DateField(default=timezone.now, blank=True)
    is_servico = models.BooleanField(default=False, verbose_name="É um serviço")
    ponto_operacional = models.ForeignKey(
        "estoque.PontoOperacional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produtos",
    )
    servicos_compativeis = models.ManyToManyField(
        "estoque.ServicoReferencia",
        blank=True,
        related_name="produtos",
    )

    def _gerar_codigo_ean(self):
        ultimo = Produto.objects.order_by("-id").first()
        if ultimo and ultimo.ean:
            try:
                base = int(ultimo.ean)
            except ValueError:
                base = 2200000000000
        else:
            base = 2200000000000

        candidato = base + 1
        while Produto.objects.filter(ean=str(candidato).zfill(13)[:13]).exclude(pk=self.pk).exists():
            candidato += 1
        return str(candidato).zfill(13)[:13]

    def _gerar_sku(self):
        if self.sku:
            return str(self.sku).strip().upper()

        ultimo = Produto.objects.order_by("-id").first()
        base = (ultimo.id + 1) if ultimo else 1
        while True:
            candidato = f"SKU-{base:06d}"
            if not Produto.objects.filter(sku=candidato).exclude(pk=self.pk).exists():
                return candidato
            base += 1

    def _aliquota_percentual(self):
        if self.usar_aliquota_manual:
            return Decimal(str(self.aliquota_manual or 0))

        try:
            from configuracoes.models import Empresa

            empresa = Empresa.objects.first()
        except Exception:
            empresa = None

        if empresa:
            regime = (empresa.regime_tributario or "simples")
            modo = (empresa.modo_tributario or "basico")
            if regime == "simples" and modo == "basico":
                if self.tipo_item == "servico":
                    return Decimal(str(empresa.aliquota_servico or 0))
                return Decimal(str(empresa.aliquota_comercio or 0))
            return Decimal(str((empresa.icms or 0) + (empresa.ipi or 0) + (empresa.pis or 0) + (empresa.cofins or 0)))

        return Decimal(str((self.icms or 0) + (self.ipi or 0) + (self.pis or 0) + (self.cofins or 0) or (self.pis_cofins or 0)))

    def save(self, *args, **kwargs):
        if not self.ponto_operacional:
            po3, _ = PontoOperacional.objects.get_or_create(codigo="PO3", defaults={"nome": "Loja", "ativo": True})
            self.ponto_operacional = po3

        self.sku = self._gerar_sku()

        ean_digits = "".join(ch for ch in str(self.ean or "") if ch.isdigit())
        if not ean_digits:
            self.ean = self._gerar_codigo_ean()
        else:
            self.ean = ean_digits.zfill(13)[:13]

        if self.marca and not self.fornecedor_config and self.marca.fornecedor_id:
            self.fornecedor_config = self.marca.fornecedor
        if self.fornecedor_config:
            self.fornecedor = self.fornecedor_config.nome
        elif self.fornecedor_manual:
            self.fornecedor = self.fornecedor_manual
        if self.categoria_config:
            self.categoria = self.categoria_config.nome

        custo_operacional_detalhado = (self.custo_frete or 0) + (self.custo_impostos or 0) + (self.custo_comissao or 0) + (self.custo_marketplace or 0)
        if custo_operacional_detalhado > 0:
            self.custo_operacional = custo_operacional_detalhado

        if (self.custo_medio or 0) <= 0 and (self.custo_unitario or 0) > 0:
            self.custo_medio = self.custo_unitario

        if self.categoria_config and (self.margem_lucro or 0) <= 0 and (self.categoria_config.margem_padrao or 0) > 0:
            self.margem_lucro = self.categoria_config.margem_padrao

        if self.tipo_item == "servico":
            self.is_servico = True
            self.quantidade = 0
            self.estoque_minimo = 0
            self.permite_comissao_peca = False
            self.percentual_comissao_peca = 0
        else:
            self.is_servico = False

        custo_total = Decimal(str((self.custo_unitario or 0) + (self.custo_operacional or 0)))
        margem_percent = Decimal(str(self.margem_lucro or 0))
        taxa_cartao_percent = Decimal(str(self.taxa_cartao or 0))

        if self.modo_preco == "simples":
            self.preco_sugerido = custo_total * (Decimal("1") + (margem_percent / Decimal("100")))
        else:
            aliquota_percent = self._aliquota_percentual()
            fator = Decimal("1") - (aliquota_percent / Decimal("100")) - (taxa_cartao_percent / Decimal("100")) - (margem_percent / Decimal("100"))
            if fator <= Decimal("0"):
                self.preco_sugerido = custo_total
            else:
                self.preco_sugerido = custo_total / fator

        margem_min = Decimal(str(self.margem_minima or 0))
        if margem_min <= Decimal("0"):
            self.preco_minimo = custo_total
        else:
            fator_min = Decimal("1") - (margem_min / Decimal("100"))
            self.preco_minimo = custo_total if fator_min <= 0 else (custo_total / fator_min)

        if not self.preco_final or self.preco_final <= 0:
            self.preco_final = self.preco_sugerido

        self.preco = self.preco_final

        if not self.data_entrada:
            self.data_entrada = timezone.now().date()

        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome

    @property
    def custo_total(self):
        return self.custo_unitario + self.custo_operacional

    @property
    def lucro_estimado(self):
        return (self.preco_final or 0) - (self.custo_total or 0)

    @property
    def margem_real_percentual(self):
        if not self.preco_final:
            return Decimal("0")
        return (self.lucro_estimado / self.preco_final) * Decimal("100")

    @property
    def valor_recebido_cartao(self):
        taxa = Decimal(str(self.taxa_cartao or 0))
        return (self.preco_final or 0) * (Decimal("1") - (taxa / Decimal("100")))

    @property
    def lucro_cartao(self):
        return self.valor_recebido_cartao - (self.custo_total or 0)

    @property
    def venda_abaixo_margem_minima(self):
        return bool(self.preco_final and self.preco_minimo and self.preco_final < self.preco_minimo)

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


class TabelaPreco(models.Model):
    nome = models.CharField(max_length=80, unique=True)
    ativo = models.BooleanField(default=True)
    margem_extra = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(200)],
    )

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class ProdutoPrecoTabela(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="precos_tabela")
    tabela = models.ForeignKey(TabelaPreco, on_delete=models.CASCADE, related_name="itens_preco")
    preco = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        unique_together = [("produto", "tabela")]
        ordering = ["tabela__nome"]

    def __str__(self):
        return f"{self.produto.nome} - {self.tabela.nome}"


class ProdutoEquivalente(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="equivalentes_principais")
    equivalente = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="equivalente_de")
    observacao = models.CharField(max_length=160, blank=True)

    class Meta:
        unique_together = [("produto", "equivalente")]
        ordering = ["produto__nome", "equivalente__nome"]

    def clean(self):
        if self.produto_id and self.equivalente_id and self.produto_id == self.equivalente_id:
            raise ValidationError("Produto equivalente não pode ser o mesmo produto.")

    def __str__(self):
        return f"{self.produto.nome} ~ {self.equivalente.nome}"


class ProdutoKitItem(models.Model):
    produto_kit = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="kit_componentes")
    componente = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="usado_em_kits")
    quantidade = models.DecimalField(max_digits=10, decimal_places=3, default=1, validators=[MinValueValidator(0.001)])

    class Meta:
        unique_together = [("produto_kit", "componente")]
        ordering = ["produto_kit__nome", "componente__nome"]

    def clean(self):
        if self.produto_kit_id and self.componente_id and self.produto_kit_id == self.componente_id:
            raise ValidationError("Componente do kit não pode ser o mesmo produto.")

    def __str__(self):
        return f"{self.produto_kit.nome} -> {self.componente.nome} ({self.quantidade})"


class MovimentacaoEstoque(models.Model):
    TIPO_CHOICES = [
        ("entrada", "Entrada de estoque"),
        ("transferencia", "Transferência"),
        ("avaria", "Avaria"),
        ("ajuste", "Ajuste"),
        ("venda", "Venda"),
        ("reserva", "Reserva"),
        ("consumo_os", "Consumo em OS"),
        ("devolucao_reserva", "Devolução de reserva"),
        ("inventario", "Inventário"),
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
    valor_unitario_custo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
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






