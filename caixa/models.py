from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils import timezone

from .services.pagamentos import gerar_numero_talao_pagamento


class Caixa(models.Model):
    data = models.DateField(auto_now_add=True)
    aberto = models.BooleanField(default=True)
    saldo_inicial = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    saldo_final = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_contado_fisico = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    diferenca_fechamento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    justificativa_diferenca = models.TextField(blank=True)

    class Meta:
        ordering = ["-data", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["data"], name="caixa_unico_por_data"),
            models.UniqueConstraint(
                fields=["aberto"],
                condition=Q(aberto=True),
                name="caixa_apenas_um_aberto",
            ),
        ]

    def clean(self):
        super().clean()
        if self.data and Caixa.objects.exclude(pk=self.pk).filter(data=self.data).exists():
            raise ValidationError({"data": "Ja existe um caixa registrado para esta data."})
        if self.aberto and Caixa.objects.exclude(pk=self.pk).filter(aberto=True).exists():
            raise ValidationError("Ja existe um caixa aberto.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Caixa {self.data} - {'Aberto' if self.aberto else 'Fechado'}"


class Pagamento(models.Model):
    caixa = models.ForeignKey("Caixa", on_delete=models.CASCADE, related_name="pagamentos", null=True, blank=True)
    ordem_servico = models.ForeignKey("ordens.OrdemServico", on_delete=models.SET_NULL, null=True, blank=True)
    stock_item = models.ForeignKey("estoque.Produto", on_delete=models.SET_NULL, null=True, blank=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
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
    data_emissao_talao = models.DateTimeField(null=True, blank=True)
    data = models.DateTimeField(auto_now_add=True)
    observacao = models.TextField(blank=True, null=True)

    @property
    def metodo_display(self):
        if self.forma_pagamento:
            return self.forma_pagamento.nome
        return self.metodo or "-"

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
        super().save(*args, **kwargs)
        if not self.numero_talao and self.pk:
            self.numero_talao = self._gerar_numero_talao()
            if not self.data_emissao_talao:
                self.data_emissao_talao = self.data or timezone.now()
            super().save(update_fields=["numero_talao", "data_emissao_talao"])


class FormaPagamento(models.Model):
    TIPO_CHOICES = [
        ("avista", "À vista"),
        ("aprazo", "A prazo"),
    ]

    nome = models.CharField(max_length=60, unique=True)
    codigo = models.SlugField(max_length=40, unique=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default="avista")
    taxa_percentual = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    dias_recebimento = models.PositiveIntegerField(default=0)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class CategoriaFinanceira(models.Model):
    TIPOS = [
        ("entrada", "Entrada"),
        ("saida", "Saída"),
        ("receber", "Contas a Receber"),
    ]
    nome = models.CharField(max_length=80)
    tipo = models.CharField(max_length=10, choices=TIPOS, default="receber")
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

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
    ordem_servico = models.ForeignKey("ordens.OrdemServico", on_delete=models.SET_NULL, null=True, blank=True)
    ponto_operacional = models.ForeignKey("estoque.PontoOperacional", on_delete=models.SET_NULL, null=True, blank=True)
    categoria = models.ForeignKey(CategoriaFinanceira, on_delete=models.SET_NULL, null=True, blank=True)
    descricao = models.CharField(max_length=200)
    tipo_origem = models.CharField(max_length=24, choices=TIPO_ORIGEM, default="avulso", db_index=True)
    cliente_nome = models.CharField(max_length=120, blank=True)
    valor_original = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_aberto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vencimento = models.DateField()
    status = models.CharField(max_length=12, choices=STATUS, default="aberta")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-vencimento", "-id"]

    def __str__(self):
        return f"{self.descricao} - {self.get_status_display()} - {self.valor_aberto}"

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
    TIPOS = [
        ("entrada", "Entrada"),
        ("saida", "Saída"),
    ]

    caixa = models.ForeignKey(Caixa, on_delete=models.CASCADE, related_name="lancamentos")
    pagamento = models.OneToOneField(
        "Pagamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamento_caixa",
    )
    descricao = models.CharField(max_length=200)
    centro_custo = models.ForeignKey(
        "CentroCusto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos",
    )
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    tipo = models.CharField(max_length=10, choices=TIPOS)
    data = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.tipo} - R${self.valor}"


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

    nome = models.CharField(max_length=120, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="variavel")
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

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
        return f"{self.regra.nome}: {self.meta_minima} até {teto} => {self.premio_valor}"


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

    competencia = models.DateField(help_text="Informe o primeiro dia do mes de referencia.")
    descricao = models.CharField(max_length=140)
    categoria = models.CharField(max_length=80, blank=True)
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
    fornecedor = models.ForeignKey("configuracoes.FornecedorGarantia", on_delete=models.SET_NULL, null=True, blank=True)
    marca = models.ForeignKey("configuracoes.MarcaGarantia", on_delete=models.SET_NULL, null=True, blank=True)
    regra_garantia = models.ForeignKey("configuracoes.RegraGarantiaMarca", on_delete=models.SET_NULL, null=True, blank=True)
    valor_previsto_fabricante = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    comissao_prevista_tecnica = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status_faturamento = models.CharField(max_length=20, choices=STATUS_FATURAMENTO, default="pendente")
    referencia_faturamento = models.CharField(max_length=80, blank=True)
    observacoes = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-atualizado_em", "-id"]

    def __str__(self):
        return f"Auditoria garantia {self.ordem_servico.numero_os} - {self.get_status_faturamento_display()}"


class ContaPagar(models.Model):
    STATUS = [
        ("aberta", "Aberta"),
        ("parcial", "Parcial"),
        ("paga", "Paga"),
        ("vencida", "Vencida"),
        ("cancelada", "Cancelada"),
    ]

    fornecedor = models.CharField(max_length=150, blank=True)
    descricao = models.CharField(max_length=220)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vencimento = models.DateField()
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
