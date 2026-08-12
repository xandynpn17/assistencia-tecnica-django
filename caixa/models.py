from calendar import monthrange
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils import timezone

from .services.pagamentos import gerar_numero_talao_pagamento


class Caixa(models.Model):
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="caixas",
    )
    data = models.DateField(auto_now_add=True)
    aberto = models.BooleanField(default=True)
    saldo_inicial = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    saldo_final = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_contado_fisico = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    diferenca_fechamento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    justificativa_diferenca = models.TextField(blank=True)
    conferencia_formas_pagamento = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-data", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "data"],
                condition=Q(empresa__isnull=False),
                name="caixa_empresa_unico_por_data",
            ),
            models.UniqueConstraint(
                fields=["data"],
                condition=Q(empresa__isnull=True),
                name="caixa_legado_unico_por_data",
            ),
            models.UniqueConstraint(
                fields=["empresa"],
                condition=Q(aberto=True, empresa__isnull=False),
                name="caixa_empresa_apenas_um_aberto",
            ),
            models.UniqueConstraint(
                fields=["aberto"],
                condition=Q(aberto=True, empresa__isnull=True),
                name="caixa_legado_apenas_um_aberto",
            ),
        ]

    def clean(self):
        super().clean()
        escopo = Caixa.objects.exclude(pk=self.pk)
        escopo = escopo.filter(empresa_id=self.empresa_id) if self.empresa_id else escopo.filter(empresa__isnull=True)
        if self.data and escopo.filter(data=self.data).exists():
            raise ValidationError({"data": "Ja existe um caixa registrado para esta data."})
        if self.aberto and escopo.filter(aberto=True).exists():
            raise ValidationError("Ja existe um caixa aberto.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Caixa {self.data} - {'Aberto' if self.aberto else 'Fechado'}"


class Pagamento(models.Model):
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pagamentos",
    )
    caixa = models.ForeignKey("Caixa", on_delete=models.CASCADE, related_name="pagamentos", null=True, blank=True)
    ordem_servico = models.ForeignKey("ordens.OrdemServico", on_delete=models.SET_NULL, null=True, blank=True)
    stock_item = models.ForeignKey("estoque.Produto", on_delete=models.SET_NULL, null=True, blank=True)
    cliente_nome = models.CharField(max_length=120, blank=True)
    cliente_documento = models.CharField(max_length=30, blank=True)
    cliente_telefone = models.CharField(max_length=30, blank=True)
    formas_pagamento_compostas = models.JSONField(default=list, blank=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    desconto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    desconto_percentual = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    impostos_estimados = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    taxas_recebimento_estimadas = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    aliquota_tributaria_estimada = models.DecimalField(max_digits=7, decimal_places=3, default=0, editable=False)
    encargos_gerenciais_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    forma_pagamento = models.ForeignKey(
        "FormaPagamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagamentos",
    )
    metodo = models.CharField(max_length=50, blank=True, default="")
    referencia = models.CharField(max_length=50, blank=True, null=True, help_text="Número do talão ou comprovante")
    numero_talao = models.CharField(max_length=32, unique=True, null=True, blank=True, db_index=True)
    chave_idempotencia = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    data_emissao_talao = models.DateTimeField(null=True, blank=True)
    data_competencia = models.DateField(default=timezone.localdate, db_index=True)
    data_movimento = models.DateField(default=timezone.localdate, db_index=True)
    data = models.DateTimeField(auto_now_add=True)
    observacao = models.TextField(blank=True, null=True)

    @property
    def metodo_display(self):
        if self.forma_pagamento:
            return self.forma_pagamento.nome
        return self.metodo or "-"

    @property
    def valor_liquidado(self):
        return (self.valor or Decimal("0.00")) + (self.desconto or Decimal("0.00"))

    @property
    def pagamento_misto(self):
        return len(self.formas_pagamento_compostas or []) > 1

    @property
    def composicao_pagamento_legivel(self):
        composicao = self.formas_pagamento_compostas or []
        linhas = []
        for item in composicao:
            nome = (item or {}).get("forma_nome") or "-"
            valor = Decimal(str((item or {}).get("valor") or "0"))
            referencia = (item or {}).get("referencia") or ""
            trecho = f"{nome}: R$ {valor:.2f}"
            if referencia:
                trecho = f"{trecho} ({referencia})"
            linhas.append(trecho)
        if linhas:
            return linhas
        if self.forma_pagamento:
            return [f"{self.forma_pagamento.nome}: R$ {Decimal(self.valor or Decimal('0.00')):.2f}"]
        return []

    def __str__(self):
        origem = (
            f"OS {self.ordem_servico.numero_os}" if self.ordem_servico else
            f"Venda #{self.stock_item.id}" if self.stock_item else
            "Avulso"
        )
        return f"{origem} - {self.metodo} - {self.valor}"

    def _gerar_numero_talao(self):
        from configuracoes.models import ConfiguracaoSistema

        return gerar_numero_talao_pagamento(
            pagamento=self,
            configuracao_sistema_model=ConfiguracaoSistema,
        )

    def save(self, *args, **kwargs):
        criando = self.pk is None
        if not self.empresa_id:
            self.empresa_id = (
                getattr(self.stock_item, "empresa_id", None)
                or getattr(self.ordem_servico, "empresa_id", None)
                or getattr(self.caixa, "empresa_id", None)
            )
        super().save(*args, **kwargs)
        if not self.numero_talao and self.pk:
            self.numero_talao = self._gerar_numero_talao()
            if not self.data_emissao_talao:
                self.data_emissao_talao = self.data or timezone.now()
            super().save(update_fields=["numero_talao", "data_emissao_talao"])
        if criando and not self.encargos_gerenciais_snapshot:
            from .services.pagamentos import registrar_snapshot_encargos_pagamento

            registrar_snapshot_encargos_pagamento(self)


class FormaPagamento(models.Model):
    TIPO_CHOICES = [
        ("avista", "à vista"),
        ("aprazo", "A prazo"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="formas_pagamento",
    )
    conta_bancaria_liquidacao = models.ForeignKey(
        "ContaBancaria",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="formas_pagamento",
    )
    nome = models.CharField(max_length=60)
    codigo = models.SlugField(max_length=40)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default="avista")
    taxa_percentual = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    dias_recebimento = models.PositiveIntegerField(default=0)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(empresa__isnull=False),
                name="caixa_forma_empresa_nome_unico",
            ),
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                condition=models.Q(empresa__isnull=False),
                name="caixa_forma_empresa_codigo_unico",
            ),
            models.UniqueConstraint(
                fields=["nome"],
                condition=models.Q(empresa__isnull=True),
                name="caixa_forma_legado_nome_unico",
            ),
            models.UniqueConstraint(
                fields=["codigo"],
                condition=models.Q(empresa__isnull=True),
                name="caixa_forma_legado_codigo_unico",
            ),
        ]

    def __str__(self):
        return self.nome


class CategoriaFinanceira(models.Model):
    TIPOS = [
        ("entrada", "Entrada"),
        ("saida", "Saída"),
        ("receber", "Contas a Receber"),
    ]
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="categorias_financeiras",
    )
    nome = models.CharField(max_length=80)
    tipo = models.CharField(max_length=10, choices=TIPOS, default="receber")
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome", "tipo"],
                condition=models.Q(empresa__isnull=False),
                name="caixa_categoria_empresa_nome_tipo_unico",
            ),
            models.UniqueConstraint(
                fields=["nome", "tipo"],
                condition=models.Q(empresa__isnull=True),
                name="caixa_categoria_legado_nome_tipo_unico",
            ),
        ]

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"


class ContaReceber(models.Model):
    TIPO_ORIGEM = [
        ("cliente_os", "Cliente OS"),
        ("garantia_fabricante", "Garantia Fabricante"),
        ("avulso", "Avulso"),
    ]
    STATUS = [
        ("aberta", "Aberta"),
        ("parcial", "Parcial"),
        ("paga", "Paga"),
        ("vencida", "Vencida"),
        ("cancelada", "Cancelada"),
    ]
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contas_receber",
    )
    ordem_servico = models.ForeignKey("ordens.OrdemServico", on_delete=models.SET_NULL, null=True, blank=True)
    ponto_operacional = models.ForeignKey("estoque.PontoOperacional", on_delete=models.SET_NULL, null=True, blank=True)
    categoria = models.ForeignKey(CategoriaFinanceira, on_delete=models.SET_NULL, null=True, blank=True)
    fornecedor_garantia = models.ForeignKey(
        "configuracoes.FornecedorGarantia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contas_receber_garantia",
    )
    marca_garantia = models.ForeignKey(
        "configuracoes.MarcaGarantia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contas_receber_garantia",
    )
    regra_garantia = models.ForeignKey(
        "configuracoes.RegraGarantiaMarca",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contas_receber_garantia",
    )
    descricao = models.CharField(max_length=200)
    tipo_origem = models.CharField(max_length=24, choices=TIPO_ORIGEM, default="avulso", db_index=True)
    cliente_nome = models.CharField(max_length=120, blank=True)
    valor_original = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_aberto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_aprovado_garantia = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    data_base_cobranca = models.DateField(null=True, blank=True)
    prazo_pagamento_dias = models.PositiveIntegerField(default=0)
    referencia_cobranca = models.CharField(max_length=80, blank=True)
    vencimento = models.DateField()
    status = models.CharField(max_length=12, choices=STATUS, default="aberta")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-vencimento", "-id"]

    def __str__(self):
        return f"{self.descricao} - {self.get_status_display()} - {self.valor_aberto}"

    @property
    def eh_garantia_fabricante(self):
        return self.tipo_origem == "garantia_fabricante"

    @property
    def dias_para_vencimento(self):
        if not self.vencimento:
            return None
        return (self.vencimento - timezone.localdate()).days

    @property
    def valor_recebido_total(self):
        return max(Decimal("0.00"), (self.valor_original or Decimal("0.00")) - (self.valor_aberto or Decimal("0.00")))

    @property
    def possui_divergencia_garantia(self):
        if not self.eh_garantia_fabricante:
            return False
        valor_aprovado = Decimal(self.valor_aprovado_garantia or Decimal("0.00"))
        valor_original = Decimal(self.valor_original or Decimal("0.00"))
        return valor_aprovado > Decimal("0.00") and valor_aprovado != valor_original

    def atualizar_status_automatico(self):
        if self.status == "cancelada":
            return
        if self.valor_aberto <= Decimal("0.00"):
            self.valor_aberto = Decimal("0.00")
            self.status = "paga"
        elif self.valor_aberto < self.valor_original:
            self.status = "parcial"
        elif self.vencimento < timezone.localdate():
            self.status = "vencida"
        else:
            self.status = "aberta"


class RecebimentoConta(models.Model):
    conta = models.ForeignKey(ContaReceber, on_delete=models.CASCADE, related_name="recebimentos")
    pagamento = models.ForeignKey(Pagamento, on_delete=models.SET_NULL, null=True, blank=True)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    desconto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    juros = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    referencia = models.CharField(max_length=60, blank=True)
    observacao = models.TextField(blank=True)
    data = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"Recebimento {self.valor} - Conta #{self.conta_id}"


class LancamentoCaixa(models.Model):
    NATUREZAS = [
        ("operacional", "Operacional"),
        ("transferencia", "Transferência de tesouraria"),
        ("capital", "Capital e aportes"),
    ]
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos_caixa",
    )
    TIPOS = [
        ("entrada", "Entrada"),
        ("saida", "Saída"),
    ]

    caixa = models.ForeignKey(
        Caixa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos",
    )
    conta_bancaria = models.ForeignKey(
        "ContaBancaria",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos_financeiros",
    )
    forma_pagamento = models.ForeignKey(
        "FormaPagamento",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lancamentos_saida",
    )
    pagamento = models.OneToOneField(
        "Pagamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamento_caixa",
    )
    descricao = models.CharField(max_length=200)
    categoria = models.ForeignKey(
        "CategoriaFinanceira",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos",
    )
    centro_custo = models.ForeignKey(
        "CentroCusto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos",
    )
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    tipo = models.CharField(max_length=10, choices=TIPOS)
    natureza = models.CharField(max_length=20, choices=NATUREZAS, default="operacional", db_index=True)
    data_competencia = models.DateField(default=timezone.localdate, db_index=True)
    data_movimento = models.DateField(default=timezone.localdate, db_index=True)
    data = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.tipo} - R${self.valor}"

    def save(self, *args, **kwargs):
        if not self.empresa_id:
            self.empresa_id = (
                getattr(self.usuario, "empresa_id", None)
                or getattr(self.caixa, "empresa_id", None)
                or getattr(self.conta_bancaria, "empresa_id", None)
            )
        return super().save(*args, **kwargs)

    @property
    def categoria_display(self):
        return getattr(self.categoria, "nome", "") or "Sem categoria"


class MovimentoFinanceiro(models.Model):
    TIPOS = [
        ("entrada", "Entrada"),
        ("saida", "Saída"),
    ]
    NATUREZAS = [
        ("operacional", "Operacional"),
        ("transferencia", "Transferência de tesouraria"),
        ("capital", "Capital e aportes"),
    ]
    STATUS = [
        ("confirmado", "Confirmado"),
        ("estornado", "Estornado"),
    ]
    ORIGENS = [
        ("pagamento", "Pagamento"),
        ("conta_pagar", "Pagamento de conta a pagar"),
        ("conciliacao_diferenca", "Diferença de conciliação"),
        ("aporte_capital", "Capital ou aporte"),
        ("lancamento_caixa", "Lançamento de caixa"),
        ("estorno", "Estorno"),
        ("ajuste", "Ajuste controlado"),
    ]
    CAMPOS_IMUTAVEIS = (
        "empresa_id",
        "caixa_id",
        "origem_tipo",
        "origem_id",
        "origem_referencia",
        "tipo",
        "natureza",
        "valor",
        "descricao",
        "data_competencia",
        "data_movimento",
        "registrado_por_id",
        "estorno_de_id",
        "chave_idempotencia",
        "metadados",
    )

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movimentos_financeiros",
    )
    caixa = models.ForeignKey(
        Caixa,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movimentos_financeiros",
    )
    origem_tipo = models.CharField(max_length=30, choices=ORIGENS)
    origem_id = models.PositiveBigIntegerField(null=True, blank=True)
    origem_referencia = models.CharField(max_length=120, blank=True)
    tipo = models.CharField(max_length=10, choices=TIPOS)
    natureza = models.CharField(max_length=20, choices=NATUREZAS, default="operacional", db_index=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    descricao = models.CharField(max_length=255)
    data_competencia = models.DateField(db_index=True)
    data_movimento = models.DateField(db_index=True)
    registrado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentos_financeiros_registrados",
    )
    status = models.CharField(max_length=12, choices=STATUS, default="confirmado", db_index=True)
    estornado_em = models.DateTimeField(null=True, blank=True)
    estornado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentos_financeiros_estornados",
    )
    motivo_estorno = models.TextField(blank=True)
    estorno_de = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movimento_estorno",
    )
    chave_idempotencia = models.CharField(max_length=160, unique=True, db_index=True)
    metadados = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-data_movimento", "-registrado_em", "-id"]
        indexes = [
            models.Index(fields=["empresa", "data_movimento"], name="cx_mov_emp_mov_idx"),
            models.Index(fields=["empresa", "data_competencia"], name="cx_mov_emp_comp_idx"),
            models.Index(fields=["origem_tipo", "origem_id"], name="cx_mov_origem_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(valor__gt=0), name="movimento_financeiro_valor_positivo"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} R$ {self.valor} - {self.descricao}"

    def save(self, *args, **kwargs):
        if self.pk:
            anterior = type(self).objects.filter(pk=self.pk).values(*self.CAMPOS_IMUTAVEIS).first()
            if anterior and any(anterior[campo] != getattr(self, campo) for campo in self.CAMPOS_IMUTAVEIS):
                raise ValidationError("Movimentos financeiros são imutáveis; registre um estorno.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Movimentos financeiros não podem ser excluídos; registre um estorno.")


class ContaBancaria(models.Model):
    TIPOS = [("corrente", "Conta corrente"), ("poupanca", "Poupança"), ("pagamento", "Conta de pagamento")]
    empresa = models.ForeignKey("configuracoes.Empresa", on_delete=models.PROTECT, related_name="contas_bancarias")
    nome = models.CharField(max_length=100)
    banco_codigo = models.CharField(max_length=10, blank=True)
    banco_nome = models.CharField(max_length=100)
    agencia = models.CharField(max_length=30, blank=True)
    numero = models.CharField(max_length=40)
    tipo = models.CharField(max_length=15, choices=TIPOS, default="corrente")
    saldo_inicial = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    data_saldo_inicial = models.DateField(default=timezone.localdate)
    ativa = models.BooleanField(default=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome", "id"]
        constraints = [models.UniqueConstraint(fields=["empresa", "nome"], name="conta_bancaria_empresa_nome_unico")]

    def __str__(self):
        return f"{self.nome} - {self.banco_nome}"

    @property
    def saldo_atual(self):
        realizados = self.movimentos.filter(data_movimento__lte=timezone.localdate())
        entradas = realizados.filter(tipo="entrada").aggregate(total=models.Sum("valor"))["total"] or Decimal("0.00")
        saidas = realizados.filter(tipo="saida").aggregate(total=models.Sum("valor"))["total"] or Decimal("0.00")
        return Decimal(self.saldo_inicial or 0) + entradas - saidas

    @property
    def saldo_projetado(self):
        entradas = self.movimentos.filter(tipo="entrada").aggregate(total=models.Sum("valor"))["total"] or Decimal("0.00")
        saidas = self.movimentos.filter(tipo="saida").aggregate(total=models.Sum("valor"))["total"] or Decimal("0.00")
        return Decimal(self.saldo_inicial or 0) + entradas - saidas


class MovimentoBancario(models.Model):
    TIPOS = [("entrada", "Entrada"), ("saida", "Saída")]
    ORIGENS = [("pagamento", "Pagamento"), ("conta_pagar", "Pagamento de conta a pagar"), ("conciliacao_diferenca", "Diferença de conciliação"), ("aporte_capital", "Aporte de capital"), ("transferencia", "Transferência"), ("lancamento_caixa", "Lançamento financeiro"), ("manual", "Manual")]
    empresa = models.ForeignKey("configuracoes.Empresa", on_delete=models.PROTECT, related_name="movimentos_bancarios")
    conta = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT, related_name="movimentos")
    tipo = models.CharField(max_length=10, choices=TIPOS)
    origem_tipo = models.CharField(max_length=30, choices=ORIGENS)
    origem_id = models.PositiveBigIntegerField(null=True, blank=True)
    descricao = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    data_movimento = models.DateField(db_index=True)
    registrado_em = models.DateTimeField(auto_now_add=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    chave_idempotencia = models.CharField(max_length=180, unique=True)
    metadados = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-data_movimento", "-id"]
        constraints = [models.CheckConstraint(condition=Q(valor__gt=0), name="movimento_bancario_valor_positivo")]
        indexes = [models.Index(fields=["empresa", "conta", "data_movimento"], name="cx_mov_banco_data_idx")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Movimentos bancários são imutáveis; registre o movimento inverso.")
        if self.conta_id and self.empresa_id != self.conta.empresa_id:
            raise ValidationError("A conta bancária não pertence à empresa do movimento.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Movimentos bancários não podem ser excluídos.")

    def __str__(self):
        sinal = "+" if self.tipo == "entrada" else "-"
        return f"{self.data_movimento:%d/%m/%Y} · {self.descricao} · {sinal} R$ {self.valor:.2f}"


class TransferenciaTesouraria(models.Model):
    empresa = models.ForeignKey("configuracoes.Empresa", on_delete=models.PROTECT, related_name="transferencias_tesouraria")
    conta_origem = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT, null=True, blank=True, related_name="transferencias_saida")
    caixa_origem = models.ForeignKey(Caixa, on_delete=models.PROTECT, null=True, blank=True, related_name="transferencias_saida")
    conta_destino = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT, null=True, blank=True, related_name="transferencias_entrada")
    caixa_destino = models.ForeignKey(Caixa, on_delete=models.PROTECT, null=True, blank=True, related_name="transferencias_entrada")
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    data_movimento = models.DateField(default=timezone.localdate)
    descricao = models.CharField(max_length=255, blank=True)
    chave_idempotencia = models.CharField(max_length=160, unique=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    registrada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_movimento", "-id"]
        constraints = [models.CheckConstraint(condition=Q(valor__gt=0), name="transferencia_tesouraria_valor_positivo")]

    def clean(self):
        super().clean()
        if bool(self.conta_origem_id) == bool(self.caixa_origem_id):
            raise ValidationError("Informe exatamente uma origem: conta bancária ou caixa.")
        if bool(self.conta_destino_id) == bool(self.caixa_destino_id):
            raise ValidationError("Informe exatamente um destino: conta bancária ou caixa.")
        if self.conta_origem_id and self.conta_origem_id == self.conta_destino_id:
            raise ValidationError("Origem e destino não podem ser a mesma conta.")
        if self.caixa_origem_id and self.caixa_origem_id == self.caixa_destino_id:
            raise ValidationError("Origem e destino não podem ser o mesmo caixa.")
        for endpoint in (self.conta_origem, self.conta_destino, self.caixa_origem, self.caixa_destino):
            if endpoint and endpoint.empresa_id != self.empresa_id:
                raise ValidationError("Todos os pontos da transferência devem pertencer à mesma empresa.")


class AporteCapital(models.Model):
    TIPOS = [
        ("capital_social", "Capital social inicial/aumento de capital"),
        ("adiantamento_socio", "Adiantamento para futuro aumento de capital"),
        ("emprestimo_socio", "Empréstimo de sócio"),
        ("outro", "Outra injeção de recursos"),
    ]
    empresa = models.ForeignKey("configuracoes.Empresa", on_delete=models.PROTECT, related_name="aportes_capital")
    tipo = models.CharField(max_length=24, choices=TIPOS)
    descricao = models.CharField(max_length=255)
    aportante = models.CharField(max_length=160, blank=True)
    documento_referencia = models.CharField(max_length=100, blank=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    data_competencia = models.DateField(db_index=True)
    data_movimento = models.DateField(db_index=True)
    conta_bancaria = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT, null=True, blank=True, related_name="aportes_capital")
    caixa = models.ForeignKey(Caixa, on_delete=models.PROTECT, null=True, blank=True, related_name="aportes_capital")
    movimento_bancario = models.OneToOneField(MovimentoBancario, on_delete=models.PROTECT, null=True, blank=True, related_name="aporte_capital")
    lancamento_caixa = models.OneToOneField(LancamentoCaixa, on_delete=models.PROTECT, null=True, blank=True, related_name="aporte_capital")
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    registrado_em = models.DateTimeField(auto_now_add=True)
    chave_idempotencia = models.CharField(max_length=160, unique=True)

    class Meta:
        ordering = ["-data_movimento", "-id"]
        constraints = [models.CheckConstraint(condition=Q(valor__gt=0), name="aporte_capital_valor_positivo")]

    def clean(self):
        super().clean()
        if bool(self.conta_bancaria_id) == bool(self.caixa_id):
            raise ValidationError("Informe exatamente um destino: conta bancária ou caixa.")
        destino = self.conta_bancaria or self.caixa
        if destino and destino.empresa_id != self.empresa_id:
            raise ValidationError("O destino do aporte não pertence à empresa.")
        if self.caixa_id and self.data_movimento and self.caixa.data != self.data_movimento:
            raise ValidationError(
                "Aporte em dinheiro deve usar o caixa da mesma data do movimento. "
                "Para aporte retroativo, prefira a conta bancária correspondente."
            )
        if self.caixa_id and not self.caixa.aberto:
            raise ValidationError("Não é permitido alterar um caixa físico já fechado.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Aportes confirmados são imutáveis; corrija mediante lançamento inverso documentado.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Aportes confirmados não podem ser excluídos.")

    def __str__(self):
        return f"{self.get_tipo_display()} - R$ {self.valor:.2f}"


class LinhaExtratoBancario(models.Model):
    STATUS = [("pendente", "Pendente"), ("conciliado", "Conciliado"), ("divergente", "Divergente"), ("ignorado", "Ignorado justificadamente")]
    empresa = models.ForeignKey("configuracoes.Empresa", on_delete=models.PROTECT, related_name="linhas_extrato_bancario")
    conta = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT, related_name="linhas_extrato")
    identificador_externo = models.CharField(max_length=180)
    data_movimento = models.DateField(db_index=True)
    descricao = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=14, decimal_places=2, help_text="Positivo para crédito e negativo para débito.")
    status = models.CharField(max_length=12, choices=STATUS, default="pendente", db_index=True)
    movimento = models.ForeignKey(MovimentoBancario, on_delete=models.PROTECT, null=True, blank=True, related_name="linhas_extrato")
    justificativa = models.TextField(blank=True)
    importado_em = models.DateTimeField(auto_now_add=True)
    conciliado_em = models.DateTimeField(null=True, blank=True)
    conciliado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-data_movimento", "-id"]
        constraints = [models.UniqueConstraint(fields=["conta", "identificador_externo"], name="extrato_conta_identificador_unico")]

    def __str__(self):
        return f"{self.data_movimento:%d/%m/%Y} · {self.descricao} · R$ {self.valor:.2f}"


class ConciliacaoBancaria(models.Model):
    STATUS = [
        ("conciliado", "Conciliado"),
        ("divergente", "Divergente justificado"),
        ("desfeito", "Desfeito"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        related_name="conciliacoes_bancarias",
    )
    conta = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT, related_name="conciliacoes")
    status = models.CharField(max_length=12, choices=STATUS, db_index=True)
    total_extrato = models.DecimalField(max_digits=14, decimal_places=2)
    total_movimentos = models.DecimalField(max_digits=14, decimal_places=2)
    diferenca = models.DecimalField(max_digits=14, decimal_places=2)
    justificativa = models.TextField(blank=True)
    conciliado_em = models.DateTimeField(auto_now_add=True)
    conciliado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conciliacoes_bancarias_realizadas",
    )
    desfeito_em = models.DateTimeField(null=True, blank=True)
    desfeito_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conciliacoes_bancarias_desfeitas",
    )
    motivo_desfazimento = models.TextField(blank=True)
    tipo_diferenca = models.CharField(
        max_length=20,
        blank=True,
        choices=[("tarifa", "Tarifa bancária"), ("juros", "Juros"), ("rendimento", "Rendimento"), ("ajuste", "Outro ajuste")],
    )
    descricao_diferenca = models.CharField(max_length=255, blank=True)
    movimento_diferenca = models.ForeignKey(
        MovimentoBancario,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="conciliacoes_com_diferenca_lancada",
    )

    class Meta:
        ordering = ["-conciliado_em", "-id"]
        indexes = [models.Index(fields=["empresa", "conta", "status"], name="cx_conc_emp_cta_st_idx")]

    def clean(self):
        super().clean()
        if self.conta_id and self.empresa_id != self.conta.empresa_id:
            raise ValidationError("A conta bancária não pertence à empresa da conciliação.")


class ConciliacaoBancariaLinha(models.Model):
    conciliacao = models.ForeignKey(ConciliacaoBancaria, on_delete=models.PROTECT, related_name="itens_extrato")
    linha = models.ForeignKey(LinhaExtratoBancario, on_delete=models.PROTECT, related_name="historico_conciliacoes")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conciliacao", "linha"], name="conciliacao_linha_unica")
        ]

    def clean(self):
        super().clean()
        if self.conciliacao_id and self.linha_id and (
            self.conciliacao.empresa_id != self.linha.empresa_id
            or self.conciliacao.conta_id != self.linha.conta_id
        ):
            raise ValidationError("A linha do extrato não pertence à empresa e conta da conciliação.")


class ConciliacaoBancariaMovimento(models.Model):
    conciliacao = models.ForeignKey(ConciliacaoBancaria, on_delete=models.PROTECT, related_name="itens_movimento")
    movimento = models.ForeignKey(MovimentoBancario, on_delete=models.PROTECT, related_name="historico_conciliacoes")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conciliacao", "movimento"], name="conciliacao_movimento_unico")
        ]

    def clean(self):
        super().clean()
        if self.conciliacao_id and self.movimento_id and (
            self.conciliacao.empresa_id != self.movimento.empresa_id
            or self.conciliacao.conta_id != self.movimento.conta_id
        ):
            raise ValidationError("O movimento não pertence à empresa e conta da conciliação.")


class AuditoriaFinanceira(models.Model):
    evento = models.CharField(max_length=80)
    descricao = models.CharField(max_length=255, blank=True)
    conta = models.ForeignKey(ContaReceber, on_delete=models.SET_NULL, null=True, blank=True)
    pagamento = models.ForeignKey(Pagamento, on_delete=models.SET_NULL, null=True, blank=True)
    valor = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]


class CentroCusto(models.Model):
    TIPO_CHOICES = [
        ("fixo", "Fixo"),
        ("variavel", "Variável"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="centros_custo",
    )
    nome = models.CharField(max_length=120)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="variavel")
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(empresa__isnull=False),
                name="caixa_centro_empresa_nome_unico",
            ),
            models.UniqueConstraint(
                fields=["nome"],
                condition=models.Q(empresa__isnull=True),
                name="caixa_centro_legado_nome_unico",
            ),
        ]

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"


class RegraComissaoTecnico(models.Model):
    MOMENTO_LIBERACAO_CHOICES = [
        ("entregue_pago", "Somente após entrega ao cliente + pagamento"),
        ("pronto_contactado", "A partir de pronto contactado (adiantamento)"),
    ]

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="regra_comissao")
    percentual_servico = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    percentual_peca = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    momento_liberacao = models.CharField(max_length=24, choices=MOMENTO_LIBERACAO_CHOICES, default="entregue_pago")
    exigir_pagamento_para_liberar = models.BooleanField(default=True)
    comissionar_garantia = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["usuario__username"]

    def __str__(self):
        return f"Comissão {self.usuario} ({self.percentual_servico}%/{self.percentual_peca}%)"


class ComissaoTecnico(models.Model):
    STATUS_CHOICES = [
        ("pendente", "Pendente"),
        ("paga", "Paga"),
        ("cancelada", "Cancelada"),
    ]

    ordem_servico = models.ForeignKey("ordens.OrdemServico", on_delete=models.CASCADE, related_name="comissoes")
    tecnico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comissoes_tecnico")
    regra = models.ForeignKey(RegraComissaoTecnico, on_delete=models.SET_NULL, null=True, blank=True)
    base_servico = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    base_peca = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_comissao = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    considerar_pecas = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pendente")
    referencia_pagamento = models.CharField(max_length=80, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        unique_together = [("ordem_servico", "tecnico", "considerar_pecas")]

    def __str__(self):
        return f"Comissão {self.tecnico} - OS {self.ordem_servico.numero_os} - {self.valor_comissao}"


class ComissaoItemOrcamento(models.Model):
    STATUS_CHOICES = [
        ("pendente", "Pendente"),
        ("paga", "Paga"),
        ("cancelada", "Cancelada"),
    ]
    MODO_CHOICES = [
        ("antecipado", "Antecipado"),
        ("fechamento", "No fechamento"),
    ]

    item_orcamento = models.ForeignKey("orcamentos.ItemOrcamento", on_delete=models.CASCADE, related_name="comissoes")
    ordem_servico = models.ForeignKey("ordens.OrdemServico", on_delete=models.CASCADE, related_name="comissoes_itens")
    tecnico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comissoes_itens_tecnico")
    regra = models.ForeignKey(RegraComissaoTecnico, on_delete=models.SET_NULL, null=True, blank=True)
    modo_pagamento = models.CharField(max_length=20, choices=MODO_CHOICES, default="fechamento")
    base_calculo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    percentual_aplicado = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    valor_comissao = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pendente")
    referencia_pagamento = models.CharField(max_length=80, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        unique_together = [("item_orcamento", "modo_pagamento")]

    def __str__(self):
        return f"Comissão item #{self.item_orcamento_id} - {self.tecnico} - {self.valor_comissao}"


class ComissaoLotePagamento(models.Model):
    STATUS_CHOICES = [
        ("ABERTO", "Aberto"),
        ("PAGO", "Pago"),
        ("CANCELADO", "Cancelado"),
    ]
    CRITERIO_CHOICES = [
        ("servicos_finalizados", "Serviços finalizados"),
        ("retirado_pago", "Retirado e pago"),
    ]

    codigo = models.CharField(max_length=48, unique=True, db_index=True)
    competencia = models.DateField(db_index=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    criterio = models.CharField(max_length=24, choices=CRITERIO_CHOICES, default="servicos_finalizados")
    percentual_servicos = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    percentual_pecas = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    percentual_vendas = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    incluir_servicos = models.BooleanField(default=True)
    incluir_pecas = models.BooleanField(default=True)
    incluir_vendas = models.BooleanField(default=False)
    total_itens = models.PositiveIntegerField(default=0)
    total_valor = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="ABERTO")
    observacao = models.CharField(max_length=180, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lotes_comissao_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["competencia", "status"]),
        ]

    def __str__(self):
        return f"{self.codigo} ({self.competencia:%m/%Y})"


class Comissao(models.Model):
    TIPO_CHOICES = [
        ("SERVICO", "Serviço"),
        ("PECA", "Peça"),
        ("COMISSAO_VENDAS", "Comissão sobre vendas"),
        ("BONUS_PRODUTO", "Bônus por produto"),
        ("BONUS_RETIRADA", "Bônus por retirada"),
        ("BONUS_SERVICO", "Bônus de serviço"),
    ]
    STATUS_CHOICES = [
        ("GERADA", "Gerada"),
        ("LIBERADA", "Liberada"),
        ("PAGA", "Paga"),
        ("CANCELADA", "Cancelada"),
    ]

    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comissoes_gerais",
    )
    ordem_servico = models.ForeignKey(
        "ordens.OrdemServico",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comissoes_gerais",
    )
    item_orcamento = models.ForeignKey(
        "orcamentos.ItemOrcamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comissoes_gerais",
    )
    produto = models.ForeignKey(
        "estoque.Produto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comissoes_gerais",
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    descricao = models.CharField(max_length=180, blank=True)
    valor_base = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    percentual = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    valor_comissao = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    evento_gerador = models.CharField(max_length=40, default="SERVICO_FINALIZADO")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="GERADA")
    chave_unica = models.CharField(max_length=160, unique=True)
    fonte_referencia = models.CharField(max_length=120, blank=True, default="")
    competencia = models.DateField(null=True, blank=True, db_index=True)
    lote_pagamento = models.ForeignKey(
        "ComissaoLotePagamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comissoes",
    )
    referencia_pagamento = models.CharField(max_length=80, blank=True)
    data_liberacao = models.DateTimeField(null=True, blank=True)
    data_pagamento = models.DateTimeField(null=True, blank=True)
    dados_extras = models.JSONField(default=dict, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_criacao", "-id"]
        indexes = [
            models.Index(fields=["tecnico", "status"]),
            models.Index(fields=["ordem_servico", "status"]),
            models.Index(fields=["tipo"]),
            models.Index(fields=["evento_gerador"]),
            models.Index(fields=["fonte_referencia"]),
        ]

    def __str__(self):
        tecnico = getattr(self.tecnico, "username", None) or "SEM_TECNICO"
        numero_os = getattr(self.ordem_servico, "numero_os", None) or "SEM_OS"
        return f"{self.tipo} | {tecnico} | OS {numero_os} | {self.valor_comissao}"


class RegraPremioMeta(models.Model):
    METRICA_CHOICES = [
        ("margem_loja", "Margem da loja"),
        ("faturamento_loja", "Faturamento da loja"),
    ]
    PUBLICO_CHOICES = [
        ("tecnico", "Técnicos"),
        ("atendente", "Atendentes"),
        ("todos_operacionais", "Todos operacionais"),
    ]

    nome = models.CharField(max_length=120)
    metrica = models.CharField(max_length=30, choices=METRICA_CHOICES, default="margem_loja")
    meta_alvo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    publico = models.CharField(max_length=30, choices=PUBLICO_CHOICES, default="tecnico")
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.get_metrica_display()})"


class FaixaPremioMeta(models.Model):
    regra = models.ForeignKey(RegraPremioMeta, on_delete=models.CASCADE, related_name="faixas")
    meta_minima = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    meta_maxima = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    premio_valor = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    ordem = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["ordem", "meta_minima"]

    def __str__(self):
        teto = self.meta_maxima if self.meta_maxima is not None else "sem teto"
        return f"{self.regra.nome}: {self.meta_minima} ate {teto} => {self.premio_valor}"


class PremioColaboradorCompetencia(models.Model):
    colaborador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="premios_competencia")
    regra = models.ForeignKey(RegraPremioMeta, on_delete=models.CASCADE, related_name="premios_competencia")
    faixa = models.ForeignKey(FaixaPremioMeta, on_delete=models.SET_NULL, null=True, blank=True, related_name="premios")
    competencia = models.DateField()
    valor_metrica = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    percentual_atingimento = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    premio_valor = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    observacao = models.CharField(max_length=180, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-competencia", "-id"]
        unique_together = [("colaborador", "regra", "competencia")]

    def __str__(self):
        return f"{self.colaborador} - {self.regra.nome} - {self.competencia:%m/%Y}"


class DespesaRecorrente(models.Model):
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="despesas_recorrentes",
    )
    nome = models.CharField(max_length=120)
    valor_mensal = models.DecimalField(max_digits=12, decimal_places=2)
    dia_vencimento = models.PositiveSmallIntegerField(default=10)
    ativo = models.BooleanField(default=True)
    ponto_operacional = models.ForeignKey("estoque.PontoOperacional", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} - {self.valor_mensal}"


class CustoFixoMensal(models.Model):
    STATUS_CHOICES = [
        ("pendente", "Pendente"),
        ("parcial", "Parcial"),
        ("pago", "Pago"),
        ("cancelado", "Cancelado"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="custos_fixos_mensais",
    )

    competencia = models.DateField(help_text="Informe o primeiro dia do mes de referencia.")
    descricao = models.CharField(max_length=140)
    categoria = models.CharField(max_length=80, blank=True)
    categoria_financeira = models.ForeignKey(
        "CategoriaFinanceira",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custos_fixos_mensais",
    )
    centro_custo = models.ForeignKey(
        "CentroCusto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custos_fixos_mensais",
    )
    valor_previsto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vencimento = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pendente")
    observacao = models.CharField(max_length=200, blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-competencia", "descricao", "-id"]
        indexes = [
            models.Index(fields=["competencia", "status"]),
        ]

    def __str__(self):
        return f"{self.descricao} ({self.competencia:%m/%Y})"

    @property
    def categoria_display(self):
        return getattr(self.categoria_financeira, "nome", "") or self.categoria or "-"

    def atualizar_status_automatico(self):
        if self.status == "cancelado":
            return
        valor_previsto = Decimal(self.valor_previsto or Decimal("0.00"))
        valor_pago = Decimal(self.valor_pago or Decimal("0.00"))
        if valor_pago <= Decimal("0.00"):
            self.status = "pendente"
        elif valor_pago < valor_previsto:
            self.status = "parcial"
        else:
            self.status = "pago"

    def clean(self):
        super().clean()
        if self.competencia:
            self.competencia = self.competencia.replace(day=1)
        if self.categoria_financeira:
            self.categoria = self.categoria_financeira.nome
        if (self.valor_previsto or Decimal("0.00")) < Decimal("0.00"):
            raise ValidationError({"valor_previsto": "Valor previsto nao pode ser negativo."})
        if (self.valor_pago or Decimal("0.00")) < Decimal("0.00"):
            raise ValidationError({"valor_pago": "Valor pago nao pode ser negativo."})
        if (
            self.vencimento
            and self.competencia
            and (
                self.vencimento.year != self.competencia.year
                or self.vencimento.month != self.competencia.month
            )
        ):
            raise ValidationError({"vencimento": "Vencimento deve estar no mesmo mes da competencia."})
        self.atualizar_status_automatico()

    def _recalcular_produtos_rateio(self):
        try:
            from estoque.models import Produto
        except Exception:
            return
        produtos_rateio = Produto.objects.filter(
            ativo=True,
            is_servico=False,
            incluir_rateio_custo_fixo=True,
        )
        for produto in produtos_rateio:
            produto.save(_skip_rateio_refresh=True)

    def save(self, *args, **kwargs):
        self.full_clean()
        result = super().save(*args, **kwargs)
        self._recalcular_produtos_rateio()
        return result

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        self._recalcular_produtos_rateio()
        return result


class AuditoriaGarantia(models.Model):
    STATUS_FATURAMENTO = [
        ("pendente", "Pendente"),
        ("enviado", "Enviado"),
        ("pago", "Pago"),
    ]

    ordem_servico = models.OneToOneField("ordens.OrdemServico", on_delete=models.CASCADE, related_name="auditoria_garantia")
    conta_receber = models.OneToOneField(
        "ContaReceber",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auditoria_garantia_vinculada",
    )
    fornecedor = models.ForeignKey("configuracoes.FornecedorGarantia", on_delete=models.SET_NULL, null=True, blank=True)
    marca = models.ForeignKey("configuracoes.MarcaGarantia", on_delete=models.SET_NULL, null=True, blank=True)
    regra_garantia = models.ForeignKey("configuracoes.RegraGarantiaMarca", on_delete=models.SET_NULL, null=True, blank=True)
    valor_previsto_fabricante = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_aprovado_fabricante = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_recebido_fabricante = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    comissao_prevista_tecnica = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    data_base_cobranca = models.DateField(null=True, blank=True)
    prazo_pagamento_dias = models.PositiveIntegerField(default=0)
    vencimento_previsto = models.DateField(null=True, blank=True)
    status_faturamento = models.CharField(max_length=20, choices=STATUS_FATURAMENTO, default="pendente")
    referencia_faturamento = models.CharField(max_length=80, blank=True)
    observacoes = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-atualizado_em", "-id"]

    def __str__(self):
        return f"Auditoria garantia {self.ordem_servico.numero_os} - {self.get_status_faturamento_display()}"

    @property
    def valor_em_aberto(self):
        alvo = self.conta_receber
        if alvo:
            return alvo.valor_aberto or Decimal("0.00")
        base = self.valor_aprovado_fabricante or self.valor_previsto_fabricante or Decimal("0.00")
        return max(Decimal("0.00"), Decimal(base) - Decimal(self.valor_recebido_fabricante or Decimal("0.00")))

    @property
    def dias_para_vencimento(self):
        if not self.vencimento_previsto:
            return None
        return (self.vencimento_previsto - timezone.localdate()).days

    @property
    def possui_divergencia(self):
        valor_previsto = Decimal(self.valor_previsto_fabricante or Decimal("0.00"))
        valor_aprovado = Decimal(self.valor_aprovado_fabricante or Decimal("0.00"))
        valor_recebido = Decimal(self.valor_recebido_fabricante or Decimal("0.00"))
        if valor_aprovado > Decimal("0.00") and valor_aprovado != valor_previsto:
            return True
        if valor_recebido > Decimal("0.00") and valor_aprovado > Decimal("0.00") and valor_recebido != valor_aprovado:
            return True
        return False


class ContaPagar(models.Model):
    STATUS = [
        ("aberta", "Aberta"),
        ("parcial", "Parcial"),
        ("paga", "Paga"),
        ("vencida", "Vencida"),
        ("cancelada", "Cancelada"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contas_pagar",
    )
    fornecedor = models.CharField(max_length=150, blank=True)
    descricao = models.CharField(max_length=220)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vencimento = models.DateField()
    categoria = models.ForeignKey(
        CategoriaFinanceira,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contas_pagar",
    )
    centro_custo = models.ForeignKey(CentroCusto, on_delete=models.SET_NULL, null=True, blank=True, related_name="contas_pagar")
    status = models.CharField(max_length=12, choices=STATUS, default="aberta")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-vencimento", "-id"]

    @property
    def valor_aberto(self):
        return max(Decimal("0.00"), (self.valor_total or Decimal("0.00")) - (self.valor_pago or Decimal("0.00")))

    def atualizar_status_automatico(self):
        if self.status == "cancelada":
            return
        if self.valor_aberto <= Decimal("0.00"):
            self.status = "paga"
        elif (self.valor_pago or Decimal("0.00")) > Decimal("0.00"):
            self.status = "parcial"
        elif self.vencimento < timezone.localdate():
            self.status = "vencida"
        else:
            self.status = "aberta"

    def __str__(self):
        return f"{self.descricao} - {self.get_status_display()}"

    def delete(self, *args, **kwargs):
        if self.pagamentos.exists():
            raise ValidationError("Não é permitido excluir conta a pagar com pagamentos vinculados.")
        return super().delete(*args, **kwargs)


class PagamentoContaPagar(models.Model):
    conta = models.ForeignKey(ContaPagar, on_delete=models.CASCADE, related_name="pagamentos")
    caixa = models.ForeignKey(Caixa, on_delete=models.SET_NULL, null=True, blank=True, related_name="pagamentos_conta_pagar")
    forma_pagamento = models.ForeignKey(FormaPagamento, on_delete=models.SET_NULL, null=True, blank=True, related_name="pagamentos_conta_pagar")
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    referencia = models.CharField(max_length=80, blank=True)
    observacao = models.TextField(blank=True)
    data = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"Pgto conta pagar #{self.conta_id} - {self.valor}"


class DREFechamento(models.Model):
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fechamentos_dre",
    )
    competencia = models.DateField(help_text="Primeiro dia do mes fechado.")
    periodo_inicio = models.DateField()
    periodo_fim = models.DateField()
    receita_bruta = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    receita_cliente = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    receita_garantia = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    impostos_estimados = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    taxas_recebimento = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cmv = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    lucro_bruto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    perdas_estoque = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    despesas_operacionais = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    resultado_operacional = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    margem = models.DecimalField(max_digits=9, decimal_places=4, default=0)
    dados = models.JSONField(default=dict, blank=True)
    fechado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fechamentos_dre_realizados",
    )
    fechado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-competencia", "-fechado_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "competencia"],
                condition=Q(empresa__isnull=False),
                name="dre_fechamento_empresa_competencia_unica",
            ),
            models.UniqueConstraint(
                fields=["competencia"],
                condition=Q(empresa__isnull=True),
                name="dre_fechamento_legado_competencia_unica",
            ),
        ]

    def clean(self):
        super().clean()
        if self.competencia and self.competencia.day != 1:
            raise ValidationError({"competencia": "A competencia deve ser o primeiro dia do mes."})
        if self.competencia and self.periodo_inicio != self.competencia:
            raise ValidationError({"periodo_inicio": "O periodo deve iniciar no primeiro dia da competencia."})
        if self.competencia and self.periodo_fim:
            ultimo_dia = monthrange(self.competencia.year, self.competencia.month)[1]
            if self.periodo_fim.day != ultimo_dia:
                raise ValidationError({"periodo_fim": "O periodo deve terminar no ultimo dia da competencia."})

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Um fechamento de DRE e imutavel e nao pode ser alterado.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Um fechamento de DRE e imutavel e nao pode ser excluido.")

    def __str__(self):
        return f"DRE {self.competencia:%m/%Y}"
