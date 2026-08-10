from datetime import timedelta
from decimal import Decimal
import random
import string
import unicodedata
import uuid
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from .services_produto import (
    aplicar_custos_base_produto,
    aplicar_politica_tipo_item_produto,
    aplicar_precificacao_produto,
    atualizar_produtos_relacionados_rateio,
    calcular_aliquota_efetiva,
    preparar_cadastro_produto,
)


class PontoOperacional(models.Model):
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pontos_operacionais",
    )
    codigo = models.CharField(max_length=10)
    nome = models.CharField(max_length=80)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                condition=models.Q(empresa__isnull=False),
                name="estoque_ponto_empresa_codigo_unico",
            ),
            models.UniqueConstraint(
                fields=["codigo"],
                condition=models.Q(empresa__isnull=True),
                name="estoque_ponto_legado_codigo_unico",
            ),
        ]

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
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="categorias_produto",
    )
    nome = models.CharField(max_length=80)
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
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(empresa__isnull=False),
                name="estoque_categoria_empresa_nome_unico",
            ),
            models.UniqueConstraint(
                fields=["nome"],
                condition=models.Q(empresa__isnull=True),
                name="estoque_categoria_legado_nome_unico",
            ),
        ]

    @staticmethod
    def nome_canonico(valor):
        texto = " ".join(str(valor or "").strip().split())
        if not texto:
            return ""
        texto = unicodedata.normalize("NFKD", texto)
        texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
        return texto.casefold()

    @classmethod
    def encontrar_por_nome(cls, valor, *, incluir_inativas=True, empresa=None):
        canonico = cls.nome_canonico(valor)
        if not canonico:
            return None
        queryset = cls.objects.all() if incluir_inativas else cls.objects.filter(ativo=True)
        if empresa is not None:
            queryset = queryset.filter(models.Q(empresa=empresa) | models.Q(empresa__isnull=True))
        for categoria in queryset.only("id", "nome", "ativo").order_by("ordem", "nome"):
            if cls.nome_canonico(categoria.nome) == canonico:
                return categoria
        return None

    @classmethod
    def obter_ou_criar_por_nome(cls, valor, *, empresa=None):
        nome_limpo = " ".join(str(valor or "").strip().split())
        if not nome_limpo:
            raise ValidationError({"nome": "Informe o nome da categoria."})
        categoria = cls.encontrar_por_nome(nome_limpo, incluir_inativas=True, empresa=empresa)
        if categoria:
            if not categoria.ativo:
                categoria.ativo = True
                categoria.save(update_fields=["ativo"])
            return categoria, False
        return cls.objects.create(nome=nome_limpo, ativo=True, empresa=empresa), True

    def clean(self):
        super().clean()
        self.nome = " ".join(str(self.nome or "").strip().split())
        canonico = self.nome_canonico(self.nome)
        if not canonico:
            raise ValidationError({"nome": "Informe o nome da categoria."})
        equivalentes = CategoriaProduto.objects.exclude(pk=self.pk)
        equivalentes = (
            equivalentes.filter(empresa_id=self.empresa_id)
            if self.empresa_id
            else equivalentes.filter(empresa__isnull=True)
        )
        for categoria in equivalentes.only("id", "nome"):
            if self.nome_canonico(categoria.nome) == canonico:
                raise ValidationError({"nome": "Ja existe categoria equivalente (considerando acentos e caixa)."})

    def save(self, *args, **kwargs):
        self.nome = " ".join(str(self.nome or "").strip().split())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class ServicoReferencia(models.Model):
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="servicos_referencia_estoque",
    )
    nome = models.CharField(max_length=120)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(empresa__isnull=False),
                name="estoque_servico_ref_empresa_nome_unico",
            ),
            models.UniqueConstraint(
                fields=["nome"],
                condition=models.Q(empresa__isnull=True),
                name="estoque_servico_ref_legado_nome_unico",
            ),
        ]

    def __str__(self):
        return self.nome


class ProdutoQuerySet(models.QuerySet):
    def ativos(self):
        return self.filter(ativo=True)

    def servicos(self):
        return self.filter(tipo_item="servico")

    def nao_servicos(self):
        return self.exclude(tipo_item="servico")

    def estoque_fisico(self):
        return self.nao_servicos()


class Produto(models.Model):
    MODO_PRECO_CHOICES = [
        ("simples", "Simples"),
        ("avancado", "Avancado"),
    ]

    TIPO_ITEM_CHOICES = [
        ("produto", "Produto"),
        ("peca", "Peca"),
        ("consumivel", "Consumivel"),
        ("fabricado", "Produto fabricado / industrializado"),
        ("servico", "Servico"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produtos",
    )
    nome = models.CharField(max_length=100)
    sku = models.CharField(max_length=50, blank=True, null=True)
    ean = models.CharField(max_length=50, blank=True, null=True)
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
    custo_cac = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    custo_rateio_fixo = models.DecimalField(max_digits=10, decimal_places=2, default=0, editable=False)
    competencia_rateio = models.DateField(null=True, blank=True, editable=False)
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
    regra_tributaria = models.ForeignKey(
        "fiscal.RegraTributaria", on_delete=models.SET_NULL, null=True, blank=True, related_name="produtos"
    )
    ncm = models.CharField(max_length=8, blank=True)
    cest = models.CharField(max_length=10, blank=True)
    origem_mercadoria = models.CharField(max_length=2, blank=True)
    codigo_servico = models.CharField(max_length=20, blank=True)
    unidade_comercial = models.CharField(max_length=10, blank=True, default="UN")
    cfop_padrao = models.CharField(max_length=4, blank=True)
    cst_csosn = models.CharField(max_length=4, blank=True)
    codigo_beneficio_fiscal = models.CharField(max_length=20, blank=True)
    usar_aliquota_manual = models.BooleanField(default=False)
    aliquota_manual = models.DecimalField(max_digits=6, decimal_places=3, default=0, blank=True)
    preco_sugerido = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=0)
    preco_minimo = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=0)
    preco_final = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    precificacao_versao = models.PositiveIntegerField(default=1, editable=False)
    precificacao_atualizada_em = models.DateTimeField(null=True, blank=True, editable=False)
    precificacao_snapshot = models.JSONField(default=dict, blank=True, editable=False)

    preco = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    quantidade = models.PositiveIntegerField(default=0)
    estoque_minimo = models.PositiveIntegerField(default=0)
    controla_lote = models.BooleanField(default=False)
    controla_serie = models.BooleanField(default=False)
    previsao_venda_mensal = models.PositiveIntegerField(default=0)
    incluir_rateio_custo_fixo = models.BooleanField(default=False)
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
    ubicacao_padrao = models.ForeignKey(
        "estoque.UbicacaoEstoque",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produtos_padrao",
    )
    servicos_compativeis = models.ManyToManyField(
        "estoque.ServicoReferencia",
        blank=True,
        related_name="produtos",
    )
    objects = ProdutoQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "ean"],
                condition=models.Q(empresa__isnull=False, ean__isnull=False) & ~models.Q(ean=""),
                name="produto_empresa_ean_unico",
            ),
        ]

    def _gerar_codigo_ean(self):
        base_qs = Produto.objects.all()
        if self.empresa_id:
            base_qs = base_qs.filter(empresa_id=self.empresa_id)
        ultimo = base_qs.order_by("-id").first()
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

        base_qs = Produto.objects.all()
        if self.empresa_id:
            base_qs = base_qs.filter(empresa_id=self.empresa_id)
        ultimo = base_qs.order_by("-id").first()
        base = (ultimo.id + 1) if ultimo else 1
        while True:
            candidato = f"SKU-{base:06d}"
            sku_qs = Produto.objects.filter(sku=candidato)
            if self.empresa_id:
                sku_qs = sku_qs.filter(empresa_id=self.empresa_id)
            if not sku_qs.exclude(pk=self.pk).exists():
                return candidato
            base += 1

    def _aliquota_percentual(self):
        return calcular_aliquota_efetiva(
            empresa=self.empresa,
            tipo_item="servico" if self.eh_servico else self.tipo_item,
            produto=self,
            usar_aliquota_manual=self.usar_aliquota_manual,
            aliquota_manual=self.aliquota_manual,
            icms=self.icms,
            ipi=self.ipi,
            pis=self.pis,
            cofins=self.cofins,
            pis_cofins=self.pis_cofins,
        )

    def _competencia_rateio_atual(self):
        hoje = timezone.localdate()
        return hoje.replace(day=1)

    def custo_operacional_sem_rateio(self):
        custos_detalhados = (
            Decimal(str(self.custo_frete or 0))
            + Decimal(str(self.custo_impostos or 0))
            + Decimal(str(self.custo_comissao or 0))
            + Decimal(str(self.custo_marketplace or 0))
            + Decimal(str(self.custo_cac or 0))
        )
        if custos_detalhados > 0:
            return custos_detalhados
        return max(Decimal("0.00"), Decimal(str(self.custo_operacional or 0)) - Decimal(str(self.custo_rateio_fixo or 0)))

    def preco_referencia_rateio(self):
        preco = Decimal(str(self.preco_final or 0))
        if preco > 0:
            return preco
        preco_sugerido = Decimal(str(self.preco_sugerido or 0))
        if preco_sugerido > 0:
            return preco_sugerido
        return Decimal(str(self.custo_unitario or 0)) + self.custo_operacional_sem_rateio()

    def lucro_unitario_referencia_rateio(self):
        return max(
            Decimal("0.00"),
            self.preco_referencia_rateio() - (Decimal(str(self.custo_unitario or 0)) + self.custo_operacional_sem_rateio()),
        )

    def base_rateio_custo_fixo(self, criterio=None, previsao_override=None, incluir_override=None):
        criterio = criterio or ConfiguracaoRateioCustoFixo.get_solo(self.empresa).criterio_rateio
        incluir = self.incluir_rateio_custo_fixo if incluir_override is None else bool(incluir_override)
        previsao_atual = int(previsao_override if previsao_override is not None else (self.previsao_venda_mensal or 0))
        if self.eh_servico or not incluir or previsao_atual <= 0:
            return Decimal("0.00")

        previsao_decimal = Decimal(str(previsao_atual))
        if criterio == ConfiguracaoRateioCustoFixo.CRITERIO_FATURAMENTO:
            return self.preco_referencia_rateio() * previsao_decimal
        if criterio == ConfiguracaoRateioCustoFixo.CRITERIO_MARGEM:
            return self.lucro_unitario_referencia_rateio() * previsao_decimal
        return previsao_decimal

    def calcular_rateio_custo_fixo_unitario(
        self,
        competencia=None,
        previsao_override=None,
        incluir_override=None,
        criterio_override=None,
    ):
        competencia = competencia or self._competencia_rateio_atual()
        previsao_atual = int(previsao_override if previsao_override is not None else (self.previsao_venda_mensal or 0))
        criterio = criterio_override or ConfiguracaoRateioCustoFixo.get_solo(self.empresa).criterio_rateio
        base_atual = self.base_rateio_custo_fixo(
            criterio=criterio,
            previsao_override=previsao_override,
            incluir_override=incluir_override,
        )
        if base_atual <= 0 or previsao_atual <= 0:
            return Decimal("0.00")

        try:
            from caixa.models import CustoFixoMensal
        except Exception:
            return Decimal("0.00")

        custos_fixos_qs = CustoFixoMensal.objects.filter(competencia=competencia, ativo=True)
        if self.empresa_id:
            custos_fixos_qs = custos_fixos_qs.filter(models.Q(empresa=self.empresa) | models.Q(empresa__isnull=True))
        total_fixos = (
            custos_fixos_qs
            .exclude(status="cancelado")
            .aggregate(total=Sum("valor_previsto"))["total"]
            or Decimal("0.00")
        )
        if total_fixos <= 0:
            return Decimal("0.00")

        produtos_rateio = Produto.objects.ativos().nao_servicos().filter(
            incluir_rateio_custo_fixo=True,
            previsao_venda_mensal__gt=0,
        )
        if self.empresa_id:
            produtos_rateio = produtos_rateio.filter(empresa_id=self.empresa_id)
        if self.pk:
            produtos_rateio = produtos_rateio.exclude(pk=self.pk)

        total_base = Decimal("0.00")
        for produto_rateio in produtos_rateio:
            total_base += produto_rateio.base_rateio_custo_fixo(criterio=criterio)

        total_base += base_atual
        if total_base <= 0:
            return Decimal("0.00")
        alocacao_total = Decimal(total_fixos) * (base_atual / total_base)
        return alocacao_total / Decimal(str(previsao_atual))

    def save(self, *args, **kwargs):
        skip_rateio_refresh = kwargs.pop("_skip_rateio_refresh", False)
        if self.regra_tributaria_id and self.empresa_id and self.regra_tributaria.perfil.empresa_id != self.empresa_id:
            raise ValidationError("A regra tributária do produto pertence a outra empresa.")
        self.ncm = "".join(ch for ch in str(self.ncm or "") if ch.isdigit())[:8]
        self.cest = "".join(ch for ch in str(self.cest or "") if ch.isdigit())[:10]
        self.origem_mercadoria = str(self.origem_mercadoria or "").strip()[:2]
        self.cfop_padrao = "".join(ch for ch in str(self.cfop_padrao or "") if ch.isdigit())[:4]
        self.cst_csosn = "".join(ch for ch in str(self.cst_csosn or "") if ch.isdigit())[:4]
        preparar_cadastro_produto(self)
        aplicar_custos_base_produto(self)
        aplicar_politica_tipo_item_produto(self)
        aplicar_precificacao_produto(self)

        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                "preco_sugerido",
                "preco_minimo",
                "preco_final",
                "preco",
                "precificacao_versao",
                "precificacao_atualizada_em",
                "precificacao_snapshot",
            }

        super().save(*args, **kwargs)
        if not skip_rateio_refresh:
            atualizar_produtos_relacionados_rateio(self)

    def __str__(self):
        return self.nome

    @property
    def eh_servico(self):
        return self.tipo_item == "servico" or bool(self.is_servico)

    @property
    def custo_total(self):
        return self.custo_unitario + self.custo_operacional

    @property
    def lucro_estimado(self):
        preco = Decimal(str(self.preco_final or 0))
        return preco - Decimal(str(self.custo_total or 0)) - self.valor_impostos - self.valor_taxa_cartao

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
    def valor_taxa_cartao(self):
        taxa = Decimal(str(self.taxa_cartao or 0)) / Decimal("100")
        return Decimal(str(self.preco_final or 0)) * taxa

    @property
    def lucro_cartao(self):
        return self.valor_recebido_cartao - Decimal(str(self.custo_total or 0)) - self.valor_impostos

    @property
    def venda_abaixo_margem_minima(self):
        return bool(self.preco_final and self.preco_minimo and self.preco_final < self.preco_minimo)

    @property
    def valor_impostos(self):
        return Decimal(str(self.preco_final or 0)) * (self._aliquota_percentual() / Decimal("100"))

    @property
    def preco_sugerido_sem_margem(self):
        divisor = Decimal("1") - (self._aliquota_percentual() / Decimal("100")) - (
            Decimal(str(self.taxa_cartao or 0)) / Decimal("100")
        )
        return self.custo_total if divisor <= 0 else Decimal(str(self.custo_total or 0)) / divisor

    @property
    def lucro_reais(self):
        return self.preco_final - self.preco_sugerido_sem_margem

    @property
    def lucro_percentual(self):
        if self.preco_sugerido_sem_margem == 0:
            return 0
        return (self.lucro_reais / self.preco_sugerido_sem_margem) * 100


class ConfiguracaoRateioCustoFixo(models.Model):
    CRITERIO_UNIDADES = "unidades"
    CRITERIO_FATURAMENTO = "faturamento"
    CRITERIO_MARGEM = "margem"
    CRITERIO_CHOICES = [
        (CRITERIO_UNIDADES, "Unidades previstas"),
        (CRITERIO_FATURAMENTO, "Faturamento previsto"),
        (CRITERIO_MARGEM, "Margem prevista"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="configuracoes_rateio_estoque",
    )
    criterio_rateio = models.CharField(max_length=20, choices=CRITERIO_CHOICES, default=CRITERIO_UNIDADES)
    ativo = models.BooleanField(default=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracao de rateio de custo fixo"
        verbose_name_plural = "Configuracoes de rateio de custo fixo"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa"],
                condition=models.Q(empresa__isnull=False),
                name="estoque_rateio_config_empresa_unica",
            )
        ]

    def __str__(self):
        return f"Rateio por {self.get_criterio_rateio_display()}"

    @classmethod
    def get_solo(cls, empresa=None):
        if empresa is None:
            from configuracoes.models import Empresa

            empresas = list(Empresa.objects.order_by("id")[:2])
            if len(empresas) == 1:
                empresa = empresas[0]
        if empresa:
            configuracao, _ = cls.objects.get_or_create(
                empresa=empresa,
                defaults={"criterio_rateio": cls.CRITERIO_UNIDADES, "ativo": True},
            )
            return configuracao
        configuracao = cls.objects.filter(empresa__isnull=True).order_by("id").first()
        if not configuracao:
            configuracao = cls.objects.create(criterio_rateio=cls.CRITERIO_UNIDADES, ativo=True)
        return configuracao

    def save(self, *args, **kwargs):
        result = super().save(*args, **kwargs)
        produtos_rateio = Produto.objects.ativos().nao_servicos().filter(
            incluir_rateio_custo_fixo=True,
        )
        if self.empresa_id:
            produtos_rateio = produtos_rateio.filter(empresa_id=self.empresa_id)
        for produto in produtos_rateio:
            produto.save(_skip_rateio_refresh=True)
        return result


class RateioCustoFixoCompetencia(models.Model):
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="snapshots_rateio_estoque",
    )
    competencia = models.DateField()
    criterio_rateio = models.CharField(
        max_length=20,
        choices=ConfiguracaoRateioCustoFixo.CRITERIO_CHOICES,
        default=ConfiguracaoRateioCustoFixo.CRITERIO_UNIDADES,
    )
    total_custos_fixos = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_base_rateio = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_produtos = models.PositiveIntegerField(default=0)
    observacao = models.CharField(max_length=180, blank=True)
    gerado_por = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    fechado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-competencia", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "competencia"],
                condition=models.Q(empresa__isnull=False),
                name="estoque_rateio_snapshot_empresa_comp",
            )
        ]

    def __str__(self):
        return f"Rateio {self.competencia:%m/%Y}"

    @staticmethod
    def _intervalo_competencia(competencia):
        inicio = competencia.replace(day=1)
        proximo_mes = (inicio + timedelta(days=32)).replace(day=1)
        return inicio, proximo_mes

    @classmethod
    def _realizado_por_produto(cls, competencia, empresa=None):
        inicio, proximo_mes = cls._intervalo_competencia(competencia)
        realizado = {}

        vendas = VendaRapidaEstoque.objects.select_related("produto").filter(status="vendida")
        if empresa:
            vendas = vendas.filter(produto__empresa=empresa)
        for venda in vendas:
            data_ref = timezone.localtime(venda.concluido_em or venda.criado_em).date()
            if not (inicio <= data_ref < proximo_mes) or not venda.produto_id:
                continue
            custo_sem_rateio = Decimal(str(venda.produto.custo_unitario or 0)) + venda.produto.custo_operacional_sem_rateio()
            registro = realizado.setdefault(
                venda.produto_id,
                {"quantidade": 0, "faturamento": Decimal("0.00"), "margem": Decimal("0.00")},
            )
            registro["quantidade"] += int(venda.quantidade or 0)
            registro["faturamento"] += Decimal(str(venda.valor_total or 0))
            registro["margem"] += Decimal(str(venda.valor_total or 0)) - (custo_sem_rateio * Decimal(str(venda.quantidade or 0)))

        try:
            from ordens.models import ServicoPeca
        except Exception:
            return realizado

        itens_os = ServicoPeca.objects.select_related("produto_estoque").filter(
            tipo="peca",
            produto_estoque__isnull=False,
        )
        if empresa:
            itens_os = itens_os.filter(produto_estoque__empresa=empresa)
        for item in itens_os:
            data_base = item.estoque_consumido_em or item.criado_em
            data_ref = timezone.localtime(data_base).date()
            if not (inicio <= data_ref < proximo_mes) or not item.produto_estoque_id:
                continue
            produto = item.produto_estoque
            custo_sem_rateio = Decimal(str(produto.custo_unitario or 0)) + produto.custo_operacional_sem_rateio()
            receita = Decimal(str(item.valor_unitario or 0)) * Decimal(str(item.quantidade or 0))
            registro = realizado.setdefault(
                item.produto_estoque_id,
                {"quantidade": 0, "faturamento": Decimal("0.00"), "margem": Decimal("0.00")},
            )
            registro["quantidade"] += int(item.quantidade or 0)
            registro["faturamento"] += receita
            registro["margem"] += receita - (custo_sem_rateio * Decimal(str(item.quantidade or 0)))
        return realizado

    @classmethod
    def gerar_snapshot(cls, *, competencia, usuario=None, observacao="", sobrescrever=False, empresa=None):
        competencia = competencia.replace(day=1)
        from caixa.models import CustoFixoMensal

        configuracao = ConfiguracaoRateioCustoFixo.get_solo(empresa)
        realizado_por_produto = cls._realizado_por_produto(competencia, empresa=empresa)
        snapshot_qs = cls.objects.filter(competencia=competencia)
        snapshot_qs = snapshot_qs.filter(empresa=empresa) if empresa else snapshot_qs.filter(empresa__isnull=True)
        snapshot = snapshot_qs.first()
        criado = False
        if snapshot and not sobrescrever:
            return snapshot, False
        if not snapshot:
            snapshot = cls(competencia=competencia, empresa=empresa)
            criado = True

        custos_fixos_qs = CustoFixoMensal.objects.filter(competencia=competencia, ativo=True)
        if empresa:
            custos_fixos_qs = custos_fixos_qs.filter(models.Q(empresa=empresa) | models.Q(empresa__isnull=True))
        total_fixos = (
            custos_fixos_qs
            .exclude(status="cancelado")
            .aggregate(total=Sum("valor_previsto"))["total"]
            or Decimal("0.00")
        )
        produtos = list(
            Produto.objects.ativos().nao_servicos().filter(
                incluir_rateio_custo_fixo=True,
                previsao_venda_mensal__gt=0,
            ).order_by("nome")
        )
        if empresa:
            produtos = [produto for produto in produtos if produto.empresa_id == empresa.id]

        itens = []
        total_base = Decimal("0.00")
        for produto in produtos:
            base_rateio = produto.base_rateio_custo_fixo(criterio=configuracao.criterio_rateio)
            if base_rateio <= 0:
                continue
            total_base += base_rateio
            itens.append(
                {
                    "produto": produto,
                    "produto_nome": produto.nome,
                    "previsao_venda_mensal": int(produto.previsao_venda_mensal or 0),
                    "base_rateio": base_rateio,
                    "preco_referencia": produto.preco_referencia_rateio(),
                    "lucro_unitario_referencia": produto.lucro_unitario_referencia_rateio(),
                }
            )

        with transaction.atomic():
            snapshot.criterio_rateio = configuracao.criterio_rateio
            snapshot.total_custos_fixos = total_fixos
            snapshot.total_base_rateio = total_base
            snapshot.total_produtos = len(itens)
            snapshot.observacao = observacao
            snapshot.gerado_por = usuario
            snapshot.fechado_em = timezone.now()
            snapshot.save()
            snapshot.itens.all().delete()

            itens_modelo = []
            for item in itens:
                participacao = Decimal("0.00") if total_base <= 0 else (item["base_rateio"] / total_base) * Decimal("100")
                custo_total = Decimal("0.00") if total_base <= 0 else total_fixos * (item["base_rateio"] / total_base)
                previsao = Decimal(str(item["previsao_venda_mensal"] or 0))
                custo_unitario = Decimal("0.00") if previsao <= 0 else custo_total / previsao
                itens_modelo.append(
                    RateioCustoFixoItemCompetencia(
                        snapshot=snapshot,
                        produto=item["produto"],
                        produto_nome=item["produto_nome"],
                        previsao_venda_mensal=item["previsao_venda_mensal"],
                        base_rateio=item["base_rateio"],
                        participacao_percentual=participacao,
                        custo_rateio_unitario=custo_unitario,
                        custo_rateio_total=custo_total,
                        preco_referencia=item["preco_referencia"],
                        lucro_unitario_referencia=item["lucro_unitario_referencia"],
                        quantidade_realizada=realizado_por_produto.get(item["produto"].id, {}).get("quantidade", 0),
                        faturamento_realizado=realizado_por_produto.get(item["produto"].id, {}).get("faturamento", Decimal("0.00")),
                        margem_realizada=realizado_por_produto.get(item["produto"].id, {}).get("margem", Decimal("0.00")),
                    )
                )
            if itens_modelo:
                RateioCustoFixoItemCompetencia.objects.bulk_create(itens_modelo)

        return snapshot, criado


class RateioCustoFixoItemCompetencia(models.Model):
    snapshot = models.ForeignKey(
        RateioCustoFixoCompetencia,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    produto = models.ForeignKey(Produto, on_delete=models.SET_NULL, null=True, blank=True, related_name="rateios_competencia")
    produto_nome = models.CharField(max_length=120)
    previsao_venda_mensal = models.PositiveIntegerField(default=0)
    base_rateio = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    participacao_percentual = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    custo_rateio_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    custo_rateio_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    preco_referencia = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    lucro_unitario_referencia = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantidade_realizada = models.PositiveIntegerField(default=0)
    faturamento_realizado = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    margem_realizada = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["-custo_rateio_total", "produto_nome"]

    def __str__(self):
        return f"{self.snapshot.competencia:%m/%Y} - {self.produto_nome}"


class TabelaPreco(models.Model):
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tabelas_preco_estoque",
    )
    nome = models.CharField(max_length=80)
    ativo = models.BooleanField(default=True)
    margem_extra = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(200)],
    )

    class Meta:
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(empresa__isnull=False),
                name="estoque_tabela_preco_empresa_nome",
            )
        ]

    def __str__(self):
        return self.nome

class ProdutoHistorico(models.Model):
    ACAO_CHOICES = [
        ("CRIACAO", "Criacao"),
        ("EDICAO", "Edicao"),
        ("DUPLICACAO", "Duplicacao"),
        ("IMPORTACAO", "Importacao"),
    ]

    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="historicos")
    acao = models.CharField(max_length=20, choices=ACAO_CHOICES)
    dados_antes = models.JSONField(default=dict, blank=True)
    dados_depois = models.JSONField(default=dict, blank=True)
    observacao = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        return f"{self.produto.nome} - {self.get_acao_display()} ({self.criado_em:%d/%m/%Y %H:%M})"


class EstoqueEvento(models.Model):
    evento = models.CharField(max_length=60)
    usuario = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)
    produto = models.ForeignKey("estoque.Produto", on_delete=models.SET_NULL, null=True, blank=True)
    ponto_operacional = models.ForeignKey("estoque.PontoOperacional", on_delete=models.SET_NULL, null=True, blank=True)
    reserva = models.ForeignKey("estoque.ReservaEstoque", on_delete=models.SET_NULL, null=True, blank=True)
    venda = models.ForeignKey("estoque.VendaRapidaEstoque", on_delete=models.SET_NULL, null=True, blank=True)
    inventario = models.ForeignKey("estoque.InventarioEstoque", on_delete=models.SET_NULL, null=True, blank=True)
    quantidade = models.IntegerField(null=True, blank=True)
    dados = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["evento", "-criado_em"], name="idx_evt_evento_criado"),
            models.Index(fields=["usuario", "-criado_em"], name="idx_evt_usuario_criado"),
            models.Index(fields=["produto", "-criado_em"], name="idx_evt_produto_criado"),
            models.Index(fields=["ponto_operacional", "-criado_em"], name="idx_evt_ponto_criado"),
            models.Index(fields=["reserva", "-criado_em"], name="idx_evt_reserva_criado"),
            models.Index(fields=["venda", "-criado_em"], name="idx_evt_venda_criado"),
            models.Index(fields=["inventario", "-criado_em"], name="idx_evt_inv_criado"),
        ]

    def __str__(self):
        return f"{self.evento} ({self.criado_em:%d/%m/%Y %H:%M})"


class ProdutoPrecoTabela(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="precos_tabela")
    tabela = models.ForeignKey(TabelaPreco, on_delete=models.CASCADE, related_name="itens_preco")
    preco = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        unique_together = [("produto", "tabela")]
        ordering = ["tabela__nome"]

    def __str__(self):
        return f"{self.produto.nome} - {self.tabela.nome}"

    def clean(self):
        if (
            self.produto_id
            and self.tabela_id
            and self.tabela.empresa_id
            and self.tabela.empresa_id != self.produto.empresa_id
        ):
            raise ValidationError("A tabela de preco e o produto devem pertencer a mesma empresa.")


class ProdutoEquivalente(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="equivalentes_principais")
    equivalente = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="equivalente_de")
    observacao = models.CharField(max_length=160, blank=True)

    class Meta:
        unique_together = [("produto", "equivalente")]
        ordering = ["produto__nome", "equivalente__nome"]

    def clean(self):
        if self.produto_id and self.equivalente_id and self.produto_id == self.equivalente_id:
            raise ValidationError("Produto equivalente nao pode ser o mesmo produto.")

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
            raise ValidationError("Componente do kit nao pode ser o mesmo produto.")
        if self.produto_kit_id and self.componente_id and self.produto_kit.empresa_id != self.componente.empresa_id:
            raise ValidationError("Kit e componente devem pertencer a mesma empresa.")
        if self.componente_id and not self.componente.ativo:
            raise ValidationError({"componente": "Um componente inativo nao pode ser incluido em um kit."})
        if self.componente_id and self.componente.kit_componentes.exists():
            raise ValidationError(
                {"componente": "Kits aninhados nao sao permitidos; inclua diretamente os componentes fisicos."}
            )
        if self.quantidade and Decimal(str(self.quantidade)) % 1 != 0:
            raise ValidationError({"quantidade": "Componentes controlados em estoque exigem quantidade inteira."})

    def __str__(self):
        return f"{self.produto_kit.nome} -> {self.componente.nome} ({self.quantidade})"


class ProdutoFornecedor(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="fornecedores_relacionados")
    fornecedor_config = models.ForeignKey(
        "configuracoes.FornecedorGarantia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="produtos_relacionados_estoque",
    )
    fornecedor_manual = models.CharField(max_length=120, blank=True)
    codigo_fornecedor = models.CharField(max_length=60, blank=True)
    custo_referencia = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    prazo_medio_dias = models.PositiveIntegerField(null=True, blank=True)
    preferencial = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)
    observacao = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-preferencial", "fornecedor_manual", "id"]

    @property
    def fornecedor_nome(self):
        return (self.fornecedor_config.nome if self.fornecedor_config_id else self.fornecedor_manual) or "Sem fornecedor"

    def clean(self):
        if not self.fornecedor_config_id and not (self.fornecedor_manual or "").strip():
            raise ValidationError({"fornecedor_manual": "Informe um fornecedor do catalogo ou manual."})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.preferencial:
            ProdutoFornecedor.objects.filter(produto=self.produto, preferencial=True).exclude(pk=self.pk).update(preferencial=False)

    def __str__(self):
        return f"{self.produto.nome} - {self.fornecedor_nome}"


class MovimentacaoEstoque(models.Model):
    TIPO_CHOICES = [
        ("entrada", "Entrada de estoque"),
        ("transferencia", "Transferencia"),
        ("avaria", "Avaria"),
        ("perda", "Perda / extravio"),
        ("vencimento", "Vencimento / validade expirada"),
        ("uso_interno", "Uso / consumo interno"),
        ("ajuste", "Ajuste"),
        ("venda", "Venda"),
        ("oferta", "Oferta / brinde"),
        ("cedencia", "Cedencia interna"),
        ("reserva", "Reserva"),
        ("consumo_os", "Consumo em OS"),
        ("devolucao_reserva", "Devolucao de reserva"),
        ("inventario", "Inventario"),
        ("transferencia_interempresa_saida", "Transferência entre empresas - saída"),
        ("transferencia_interempresa_entrada", "Transferência entre empresas - entrada"),
    ]

    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="movimentacoes")
    tipo = models.CharField(max_length=40, choices=TIPO_CHOICES, default="transferencia")
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
    origem_ubicacao = models.ForeignKey(
        "estoque.UbicacaoEstoque",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes_origem",
    )
    destino_ubicacao_ref = models.ForeignKey(
        "estoque.UbicacaoEstoque",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes_destino",
    )
    destino_ubicacao = models.CharField(max_length=80, blank=True)
    valor_unitario_custo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_total_custo = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    referencia_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    chave_idempotencia = models.CharField(max_length=120, null=True, blank=True, unique=True)
    origem_tipo = models.CharField(max_length=30, default="manual")
    origem_referencia = models.CharField(max_length=120, blank=True)
    movimento_estornado = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movimentos_de_estorno",
    )
    observacao = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["tipo", "-criado_em"], name="idx_mov_tipo_criado"),
            models.Index(fields=["produto", "-criado_em"], name="idx_mov_prod_criado"),
            models.Index(fields=["origem", "-criado_em"], name="idx_mov_origem_criado"),
            models.Index(fields=["destino", "-criado_em"], name="idx_mov_destino_criado"),
        ]

    def __str__(self):
        return f"{self.produto.nome} - {self.get_tipo_display()} ({self.quantidade})"


class TransferenciaEstoqueInterempresa(models.Model):
    empresa_origem = models.ForeignKey("configuracoes.Empresa", on_delete=models.PROTECT, related_name="transferencias_estoque_saida")
    empresa_destino = models.ForeignKey("configuracoes.Empresa", on_delete=models.PROTECT, related_name="transferencias_estoque_entrada")
    produto_origem = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="transferencias_interempresa_saida")
    produto_destino = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="transferencias_interempresa_entrada")
    origem = models.ForeignKey(PontoOperacional, on_delete=models.PROTECT, related_name="transferencias_interempresa_saida")
    origem_ubicacao = models.ForeignKey(UbicacaoEstoque, on_delete=models.PROTECT, related_name="transferencias_interempresa_saida")
    destino = models.ForeignKey(PontoOperacional, on_delete=models.PROTECT, related_name="transferencias_interempresa_entrada")
    destino_ubicacao = models.ForeignKey(UbicacaoEstoque, on_delete=models.PROTECT, related_name="transferencias_interempresa_entrada")
    quantidade = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    documento_fiscal = models.CharField(max_length=120, help_text="Chave/número do documento fiscal que autoriza a operação.")
    natureza_operacao = models.CharField(max_length=160)
    data_operacao = models.DateField(default=timezone.localdate)
    observacao = models.CharField(max_length=240, blank=True)
    movimento_saida = models.OneToOneField(MovimentacaoEstoque, on_delete=models.PROTECT, null=True, blank=True, related_name="transferencia_interempresa_saida")
    movimento_entrada = models.OneToOneField(MovimentacaoEstoque, on_delete=models.PROTECT, null=True, blank=True, related_name="transferencia_interempresa_entrada")
    executado_por = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)
    executado_em = models.DateTimeField(auto_now_add=True)
    chave_idempotencia = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["-data_operacao", "-id"]

    def clean(self):
        super().clean()
        if self.empresa_origem_id == self.empresa_destino_id:
            raise ValidationError("Use a transferência comum quando origem e destino forem a mesma empresa.")
        if self.produto_origem_id and self.produto_origem.empresa_id != self.empresa_origem_id:
            raise ValidationError("O produto de origem não pertence à empresa de origem.")
        if self.produto_destino_id and self.produto_destino.empresa_id != self.empresa_destino_id:
            raise ValidationError("O produto de destino não pertence à empresa de destino.")
        if not (self.documento_fiscal or "").strip():
            raise ValidationError("Informe o documento fiscal antes de movimentar estoque entre CNPJs.")


class SolicitacaoSaidaEstoque(models.Model):
    TIPO_CHOICES = [
        ("oferta", "Oferta / brinde"),
        ("cedencia", "Cedência"),
    ]
    FINALIDADE_CHOICES = [
        ("brinde_comercial", "Brinde comercial"),
        ("cortesia_pos_venda", "Cortesia de pós-venda"),
        ("uso_interno", "Uso interno"),
        ("demonstracao", "Demonstração"),
        ("doacao", "Doação"),
        ("cedencia_temporaria", "Cedência temporária"),
        ("cedencia_definitiva", "Cedência definitiva"),
        ("outro", "Outro"),
    ]
    STATUS_CHOICES = [
        ("pendente", "Pendente de aprovação"),
        ("executada", "Aprovada e executada"),
        ("devolvida", "Cedência devolvida"),
        ("rejeitada", "Rejeitada"),
        ("cancelada", "Cancelada"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        related_name="solicitacoes_saida_estoque",
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    finalidade = models.CharField(max_length=30, choices=FINALIDADE_CHOICES)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="solicitacoes_saida")
    quantidade = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    origem = models.ForeignKey(PontoOperacional, on_delete=models.PROTECT, related_name="solicitacoes_saida")
    origem_ubicacao = models.ForeignKey(UbicacaoEstoque, on_delete=models.PROTECT, related_name="solicitacoes_saida")
    beneficiario_nome = models.CharField(max_length=160)
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitacoes_saida_estoque",
    )
    campanha = models.CharField(max_length=120, blank=True)
    centro_custo = models.ForeignKey(
        "caixa.CentroCusto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitacoes_saida_estoque",
    )
    centro_custo_nome = models.CharField(max_length=120, blank=True)
    documento_autorizacao = models.CharField(max_length=120, blank=True)
    observacao = models.CharField(max_length=240)
    valor_unitario_custo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_total_custo = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    exige_aprovacao = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pendente")
    solicitado_por = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.PROTECT,
        related_name="solicitacoes_saida_estoque",
    )
    aprovado_por = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="saidas_estoque_aprovadas",
    )
    aprovado_em = models.DateTimeField(null=True, blank=True)
    rejeitado_por = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="saidas_estoque_rejeitadas",
    )
    rejeitado_em = models.DateTimeField(null=True, blank=True)
    motivo_rejeicao = models.CharField(max_length=240, blank=True)
    movimento = models.OneToOneField(
        MovimentacaoEstoque,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitacao_saida",
    )
    movimento_retorno = models.OneToOneField(
        MovimentacaoEstoque,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retorno_solicitacao_saida",
    )
    devolvido_por = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cedencias_estoque_devolvidas",
    )
    devolvido_em = models.DateTimeField(null=True, blank=True)
    observacao_devolucao = models.CharField(max_length=240, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["empresa", "status", "-criado_em"], name="idx_sol_saida_emp_status"),
            models.Index(fields=["tipo", "-criado_em"], name="idx_sol_saida_tipo_data"),
        ]

    def clean(self):
        super().clean()
        if self.produto_id and self.produto.empresa_id != self.empresa_id:
            raise ValidationError({"produto": "O produto deve pertencer à empresa da solicitação."})
        if self.origem_ubicacao_id and self.origem_id and self.origem_ubicacao.ponto_operacional_id != self.origem_id:
            raise ValidationError({"origem_ubicacao": "A localização não pertence ao ponto de origem."})
        if self.cliente_id and self.cliente.empresa_id and self.cliente.empresa_id != self.empresa_id:
            raise ValidationError({"cliente": "O cliente deve pertencer à mesma empresa."})
        if self.tipo == "oferta" and self.finalidade in {"cedencia_temporaria", "cedencia_definitiva"}:
            raise ValidationError({"finalidade": "Use uma finalidade de oferta ou cortesia."})
        if self.tipo == "cedencia" and self.finalidade in {"brinde_comercial", "cortesia_pos_venda", "doacao"}:
            raise ValidationError({"finalidade": "Use uma finalidade compatível com cedência."})

    def __str__(self):
        return f"#{self.pk or '-'} {self.get_tipo_display()} - {self.produto.nome} ({self.quantidade})"


class SaldoEstoquePonto(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="saldos_por_ponto")
    ponto_operacional = models.ForeignKey(PontoOperacional, on_delete=models.CASCADE, related_name="saldos")
    quantidade = models.IntegerField(default=0)

    class Meta:
        unique_together = [("produto", "ponto_operacional")]
        ordering = ["ponto_operacional__codigo"]

    def __str__(self):
        return f"{self.produto.nome} @ {self.ponto_operacional.codigo}: {self.quantidade}"


class SaldoEstoqueUbicacao(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="saldos_por_ubicacao")
    ponto_operacional = models.ForeignKey(PontoOperacional, on_delete=models.CASCADE, related_name="saldos_ubicacao")
    ubicacao = models.ForeignKey(UbicacaoEstoque, on_delete=models.CASCADE, related_name="saldos_produto")
    quantidade = models.IntegerField(default=0)

    class Meta:
        unique_together = [("produto", "ubicacao")]
        ordering = ["ponto_operacional__codigo", "ubicacao__codigo", "produto__nome"]

    def __str__(self):
        return f"{self.produto.nome} @ {self.ponto_operacional.codigo}/{self.ubicacao.codigo}: {self.quantidade}"


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
    tabela_preco = models.ForeignKey(
        TabelaPreco,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendas_rapidas",
    )
    tabela_preco_nome = models.CharField(max_length=80, blank=True)
    composicao_kit_snapshot = models.JSONField(default=list, blank=True)
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
        indexes = [
            models.Index(fields=["status", "-criado_em"], name="idx_vr_status_criado"),
            models.Index(fields=["cesto_codigo", "status"], name="idx_vr_cesto_status"),
            models.Index(fields=["guia_pagamento", "status"], name="idx_vr_guia_status"),
            models.Index(fields=["produto", "-criado_em"], name="idx_vr_prod_criado"),
        ]

    def __str__(self):
        return f"{self.produto.nome} - {self.quantidade} - {self.get_status_display()}"

    @property
    def comprador_nome(self):
        return getattr(self.pagamento, "cliente_nome", "") or ""

    @property
    def garantia_ate(self):
        if self.status != "vendida" or not self.pagamento_id:
            return None
        dias = int(getattr(self.produto, "garantia_peca_dias", 0) or 0)
        if dias <= 0:
            return None
        data_ref = (self.pagamento.data or self.concluido_em or self.criado_em)
        if not data_ref:
            return None
        return (timezone.localtime(data_ref).date() + timedelta(days=dias))

    @property
    def em_garantia(self):
        limite = self.garantia_ate
        return bool(limite and limite >= timezone.localdate())


class AtendimentoPosVendaBalcao(models.Model):
    TIPO_CHOICES = [
        ("garantia", "Garantia"),
        ("devolucao", "Devolucao"),
        ("troca", "Troca"),
        ("orientacao", "Orientacao"),
    ]
    STATUS_CHOICES = [
        ("aberto", "Aberto"),
        ("concluido", "Concluido"),
        ("cancelado", "Cancelado"),
    ]

    venda = models.ForeignKey(VendaRapidaEstoque, on_delete=models.PROTECT, related_name="atendimentos_pos_venda")
    pagamento = models.ForeignKey("caixa.Pagamento", on_delete=models.SET_NULL, null=True, blank=True, related_name="atendimentos_pos_venda")
    cliente_nome_snapshot = models.CharField(max_length=120, blank=True)
    cliente_documento_snapshot = models.CharField(max_length=30, blank=True)
    cliente_telefone_snapshot = models.CharField(max_length=30, blank=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="orientacao")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="aberto")
    motivo = models.CharField(max_length=160, blank=True)
    observacao = models.TextField(blank=True)
    criado_por = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="atendimentos_pos_venda_criados")
    criado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["tipo", "status"], name="idx_posvenda_tipo_status"),
            models.Index(fields=["criado_em"], name="idx_posvenda_criado"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.venda.produto.nome} - {self.get_status_display()}"


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
    ubicacao = models.ForeignKey(
        UbicacaoEstoque,
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
        indexes = [
            models.Index(fields=["status", "valido_ate"], name="idx_res_status_validade"),
            models.Index(fields=["produto", "status"], name="idx_res_prod_status"),
            models.Index(fields=["ponto_operacional", "status"], name="idx_res_ponto_status"),
            models.Index(fields=["ordem_servico", "status"], name="idx_res_ordem_status"),
            models.Index(fields=["-criado_em"], name="idx_res_criado_desc"),
        ]

    def __str__(self):
        return f"{self.codigo_reserva} - {self.produto.nome} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.codigo_reserva:
            while True:
                codigo = "RES-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
                if not ReservaEstoque.objects.filter(codigo_reserva=codigo).exclude(pk=self.pk).exists():
                    self.codigo_reserva = codigo
                    break
        super().save(*args, **kwargs)


class EstoqueCamadaCusto(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="camadas_custo")
    ponto_operacional = models.ForeignKey(PontoOperacional, on_delete=models.CASCADE, related_name="camadas_custo")
    ubicacao = models.ForeignKey(UbicacaoEstoque, on_delete=models.SET_NULL, null=True, blank=True, related_name="camadas_custo")
    movimento_entrada = models.ForeignKey(
        "estoque.MovimentacaoEstoque",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="camadas_geradas",
    )
    quantidade_entrada = models.PositiveIntegerField(default=0)
    quantidade_saldo = models.PositiveIntegerField(default=0)
    custo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["criado_em", "id"]
        indexes = [
            models.Index(fields=["produto", "criado_em"], name="idx_camada_prod_criada"),
            models.Index(fields=["ponto_operacional", "criado_em"], name="idx_camada_ponto_criada"),
        ]

    def __str__(self):
        return f"{self.produto.nome} camada {self.quantidade_saldo}/{self.quantidade_entrada} @ {self.custo_unitario}"


class InventarioEstoque(models.Model):
    STATUS_CHOICES = [
        ("aberto", "Aberto"),
        ("em_conferencia", "Em conferência"),
        ("fechado", "Fechado"),
        ("cancelado", "Cancelado"),
    ]
    TIPO_ESCOPO_CHOICES = [
        ("ponto", "Ponto operacional"),
        ("ubicacao", "Ubicação"),
    ]

    numero = models.CharField(max_length=30, unique=True, blank=True, editable=False)
    ponto_operacional = models.ForeignKey(PontoOperacional, on_delete=models.PROTECT, related_name="inventarios")
    ubicacao = models.ForeignKey(
        UbicacaoEstoque,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventarios",
    )
    tipo_escopo = models.CharField(max_length=20, choices=TIPO_ESCOPO_CHOICES, default="ponto")
    categoria = models.ForeignKey(
        "estoque.CategoriaProduto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventarios",
    )
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventarios_estoque",
    )
    modo_contagem_cega = models.BooleanField(default=False)
    exige_dupla_conferencia = models.BooleanField(default=False)
    exige_aprovacao_divergencia = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="aberto")
    observacao = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    fechado_em = models.DateTimeField(null=True, blank=True)
    usuario = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-id"]

    def __str__(self):
        sufixo = f" / {self.ubicacao.codigo}" if self.ubicacao_id else ""
        return f"{self.numero or f'INV-{self.id:06d}'} - {self.ponto_operacional.codigo}{sufixo} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.numero:
            data_ref = timezone.localdate().strftime("%Y%m%d")
            prefixo = f"INV-{data_ref}-"
            ultimo = (
                InventarioEstoque.objects.filter(numero__startswith=prefixo)
                .order_by("-numero")
                .values_list("numero", flat=True)
                .first()
            )
            sequencia = 1
            if ultimo:
                try:
                    sequencia = int(str(ultimo).split("-")[-1]) + 1
                except (TypeError, ValueError):
                    sequencia = InventarioEstoque.objects.filter(numero__startswith=prefixo).count() + 1
            self.numero = f"{prefixo}{sequencia:03d}"
        super().save(*args, **kwargs)


class ItemInventarioEstoque(models.Model):
    SITUACAO_CHOICES = [
        ("pendente", "Pendente"),
        ("conferido", "Confere"),
        ("divergencia", "Divergência"),
    ]
    MOTIVO_CHOICES = [
        ("", "Sem motivo"),
        ("falta", "Falta"),
        ("sobra", "Sobra"),
        ("local_errado", "Item em local errado"),
        ("sem_etiqueta", "Sem etiqueta"),
        ("outro", "Outro"),
    ]

    inventario = models.ForeignKey(InventarioEstoque, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="itens_inventario")
    ubicacao = models.ForeignKey(
        UbicacaoEstoque,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="itens_inventario",
    )
    quantidade_sistema = models.IntegerField(default=0)
    quantidade_contada = models.IntegerField(default=0)
    ajuste = models.IntegerField(default=0)
    ean_snapshot = models.CharField(max_length=50, blank=True)
    nome_snapshot = models.CharField(max_length=160, blank=True)
    modelos_compativeis_snapshot = models.TextField(blank=True)
    ponto_operacional_snapshot = models.CharField(max_length=30, blank=True)
    ubicacao_snapshot = models.CharField(max_length=30, blank=True)
    pmp_snapshot = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pvp_snapshot = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    margem_snapshot = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    situacao = models.CharField(max_length=20, choices=SITUACAO_CHOICES, default="pendente")
    motivo_divergencia = models.CharField(max_length=30, choices=MOTIVO_CHOICES, blank=True)
    observacao = models.CharField(max_length=160, blank=True)
    conferido_em = models.DateTimeField(null=True, blank=True)
    conferido_por = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_inventario_conferidos",
    )
    quantidade_recontada = models.IntegerField(null=True, blank=True)
    recontado_em = models.DateTimeField(null=True, blank=True)
    recontado_por = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_inventario_recontados",
    )
    divergencia_aprovada_em = models.DateTimeField(null=True, blank=True)
    divergencia_aprovada_por = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_inventario_aprovados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("inventario", "produto", "ubicacao")]
        ordering = ["produto__nome"]

    def __str__(self):
        return f"{self.produto.nome} ({self.ajuste:+d})"


class EntradaMercadoria(models.Model):
    STATUS_CHOICES = [
        ("rascunho", "Rascunho"),
        ("recebida", "Recebida"),
        ("cancelada", "Cancelada"),
    ]

    numero = models.CharField(max_length=30, unique=True, blank=True, editable=False)
    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entradas_mercadoria",
    )
    fornecedor_config = models.ForeignKey(
        "configuracoes.FornecedorGarantia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entradas_mercadoria",
    )
    fornecedor_manual = models.CharField(max_length=120, blank=True)
    documento_numero = models.CharField(max_length=40, blank=True)
    serie_documento = models.CharField(max_length=20, blank=True)
    chave_acesso_nfe = models.CharField(max_length=44, blank=True, db_index=True)
    xml_arquivo = models.FileField(upload_to="estoque/xml_compras/%Y/%m/", blank=True, null=True)
    xml_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    xml_resumo = models.JSONField(default=dict, blank=True)
    xml_divergencias_fornecedor = models.JSONField(default=dict, blank=True)
    importada_xml = models.BooleanField(default=False)
    gerar_conta_pagar = models.BooleanField(default=False)
    vencimento_conta_pagar = models.DateField(null=True, blank=True)
    conta_pagar = models.OneToOneField(
        "caixa.ContaPagar",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entrada_mercadoria",
    )
    data_emissao = models.DateField(default=timezone.localdate)
    data_entrada = models.DateField(default=timezone.localdate)
    ponto_operacional = models.ForeignKey(
        PontoOperacional,
        on_delete=models.PROTECT,
        related_name="entradas_mercadoria",
    )
    ubicacao = models.ForeignKey(
        UbicacaoEstoque,
        on_delete=models.PROTECT,
        related_name="entradas_mercadoria",
    )
    frete_total = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    seguro_total = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    outras_despesas_total = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    desconto_total = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    observacao = models.CharField(max_length=220, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="rascunho")
    usuario = models.ForeignKey("configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    recebido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["status", "-criado_em"], name="idx_entmerc_status_criado"),
            models.Index(fields=["empresa", "-criado_em"], name="idx_entmerc_empresa_criado"),
            models.Index(fields=["ponto_operacional", "status"], name="idx_entmerc_ponto_status"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "chave_acesso_nfe"],
                condition=models.Q(empresa__isnull=False) & ~models.Q(chave_acesso_nfe=""),
                name="entrada_empresa_chave_nfe_unica",
            ),
        ]

    def __str__(self):
        return f"{self.numero or f'ENT-{self.id:06d}'} - {self.fornecedor_nome}"

    @property
    def fornecedor_nome(self):
        return (self.fornecedor_config.nome if self.fornecedor_config_id else self.fornecedor_manual) or "Sem fornecedor"

    @property
    def total_despesas_rateio(self):
        return (self.frete_total or 0) + (self.seguro_total or 0) + (self.outras_despesas_total or 0) - (self.desconto_total or 0)

    @property
    def possui_rateio_manual_itens(self):
        return any(
            (
                Decimal(str(item.frete_rateado_unitario or 0)) > 0
                or Decimal(str(item.outras_despesas_rateadas_unitario or 0)) > 0
                or Decimal(str(item.desconto_unitario or 0)) > 0
            )
            for item in self.itens.all()
        )

    @property
    def usar_rateio_automatico(self):
        return Decimal(str(self.total_despesas_rateio or 0)) != Decimal("0.00") and not self.possui_rateio_manual_itens

    def rateio_automatico_totais_por_item(self):
        itens = list(self.itens.all())
        if not itens or not self.usar_rateio_automatico:
            return {item.id: Decimal("0.00") for item in itens if item.id}

        total_rateio = Decimal(str(self.total_despesas_rateio or 0)).quantize(Decimal("0.01"))
        pesos = []
        for item in itens:
            peso = Decimal(str(item.custo_unitario or 0)) * Decimal(int(item.quantidade or 0))
            if peso <= 0:
                peso = Decimal(int(item.quantidade or 0))
            pesos.append(peso)

        soma_pesos = sum(pesos, Decimal("0.00"))
        if soma_pesos <= 0:
            return {item.id: Decimal("0.00") for item in itens if item.id}

        rateios = {}
        acumulado = Decimal("0.00")
        ultimo_item_id = None
        for idx, item in enumerate(itens):
            ultimo_item_id = item.id
            if idx == len(itens) - 1:
                valor_item = total_rateio - acumulado
            else:
                valor_item = ((total_rateio * pesos[idx]) / soma_pesos).quantize(Decimal("0.01"))
                acumulado += valor_item
            rateios[item.id] = valor_item
        if ultimo_item_id is not None and ultimo_item_id not in rateios:
            rateios[ultimo_item_id] = total_rateio - acumulado
        return rateios

    @property
    def quantidade_total_itens(self):
        return sum(int(item.quantidade or 0) for item in self.itens.all())

    @property
    def subtotal_produtos(self):
        return sum((item.subtotal_base_item for item in self.itens.all()), Decimal("0.00"))

    @property
    def total_geral(self):
        if self.usar_rateio_automatico:
            return self.subtotal_produtos + Decimal(str(self.total_despesas_rateio or 0))
        return sum((item.subtotal_item for item in self.itens.all()), Decimal("0.00"))

    def clean(self):
        if self.ubicacao_id and self.ponto_operacional_id and self.ubicacao.ponto_operacional_id != self.ponto_operacional_id:
            raise ValidationError({"ubicacao": "A ubicacao informada nao pertence ao ponto operacional."})

    def save(self, *args, **kwargs):
        if not self.numero:
            data_ref = timezone.localdate().strftime("%Y%m%d")
            prefixo = f"ENT-{data_ref}-"
            ultimo = (
                EntradaMercadoria.objects.filter(numero__startswith=prefixo)
                .order_by("-numero")
                .values_list("numero", flat=True)
                .first()
            )
            sequencia = 1
            if ultimo:
                try:
                    sequencia = int(str(ultimo).split("-")[-1]) + 1
                except (TypeError, ValueError):
                    sequencia = EntradaMercadoria.objects.filter(numero__startswith=prefixo).count() + 1
            self.numero = f"{prefixo}{sequencia:03d}"
        super().save(*args, **kwargs)


class ParcelaEntradaMercadoria(models.Model):
    entrada = models.ForeignKey(EntradaMercadoria, on_delete=models.CASCADE, related_name="parcelas_financeiras")
    numero = models.CharField(max_length=30)
    vencimento = models.DateField()
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    origem = models.CharField(max_length=12, choices=[("xml", "XML"), ("manual", "Manual")], default="manual")
    revisada = models.BooleanField(default=False)
    conta_pagar = models.OneToOneField(
        "caixa.ContaPagar",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parcela_entrada_mercadoria",
    )

    class Meta:
        ordering = ["vencimento", "id"]
        constraints = [
            models.UniqueConstraint(fields=["entrada", "numero"], name="entrada_parcela_numero_unico")
        ]

    def clean(self):
        super().clean()
        if self.valor is not None and self.valor <= 0:
            raise ValidationError({"valor": "O valor da parcela deve ser positivo."})

    def __str__(self):
        return f"{self.entrada.numero} · parcela {self.numero} · {self.vencimento:%d/%m/%Y}"


class ItemEntradaMercadoria(models.Model):
    entrada = models.ForeignKey(EntradaMercadoria, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="itens_entrada_mercadoria")
    quantidade = models.PositiveIntegerField(default=1)
    custo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    impostos_entrada_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    frete_rateado_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    outras_despesas_rateadas_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    desconto_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    lote_codigo = models.CharField(max_length=60, blank=True)
    lote_validade = models.DateField(null=True, blank=True)
    numeros_serie = models.TextField(blank=True)
    observacao = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.produto.nome} x {self.quantidade}"

    @property
    def custo_base_unitario(self):
        valor = (
            Decimal(str(self.custo_unitario or 0))
            + Decimal(str(self.impostos_entrada_unitario or 0))
            + Decimal(str(self.frete_rateado_unitario or 0))
            + Decimal(str(self.outras_despesas_rateadas_unitario or 0))
            - Decimal(str(self.desconto_unitario or 0))
        )
        return valor if valor > 0 else Decimal("0.00")

    @property
    def subtotal_base_item(self):
        return self.custo_base_unitario * Decimal(int(self.quantidade or 0))

    @property
    def rateio_automatico_total(self):
        if not self.entrada_id or not self.id:
            return Decimal("0.00")
        return self.entrada.rateio_automatico_totais_por_item().get(self.id, Decimal("0.00"))

    @property
    def rateio_automatico_unitario(self):
        quantidade = int(self.quantidade or 0)
        if quantidade <= 0:
            return Decimal("0.00")
        return (self.rateio_automatico_total / Decimal(quantidade)).quantize(Decimal("0.01"))

    @property
    def custo_entrada_unitario(self):
        valor = self.custo_base_unitario + Decimal(str(self.rateio_automatico_unitario or 0))
        return valor if valor > 0 else Decimal("0.00")

    @property
    def subtotal_item(self):
        return self.custo_entrada_unitario * Decimal(int(self.quantidade or 0))

    @property
    def numeros_serie_lista(self):
        texto = str(self.numeros_serie or "").replace(";", "\n").replace(",", "\n")
        return [linha.strip() for linha in texto.splitlines() if linha.strip()]


class ItemImportacaoXML(models.Model):
    NIVEL_CORRESPONDENCIA_CHOICES = [
        ("exato", "Exato"),
        ("provavel", "Provavel"),
        ("novo", "Novo"),
        ("conflito", "Conflito"),
    ]
    STATUS_PRE_CADASTRO_CHOICES = [
        ("nao_iniciado", "Não iniciado"),
        ("rascunho", "Rascunho incompleto"),
        ("pronto", "Pronto para aprovação"),
        ("aprovado", "Aprovado"),
        ("nao_aplicavel", "Produto existente"),
    ]
    entrada = models.ForeignKey(EntradaMercadoria, on_delete=models.CASCADE, related_name="itens_xml")
    numero_item = models.PositiveIntegerField()
    codigo_fornecedor = models.CharField(max_length=60, blank=True)
    gtin = models.CharField(max_length=50, blank=True)
    descricao = models.CharField(max_length=255)
    ncm = models.CharField(max_length=10, blank=True)
    cest = models.CharField(max_length=10, blank=True)
    cfop = models.CharField(max_length=10, blank=True)
    unidade = models.CharField(max_length=10, blank=True)
    quantidade = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=6)
    valor_produtos = models.DecimalField(max_digits=14, decimal_places=2)
    desconto_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tributos_informados = models.JSONField(default=dict, blank=True)
    impostos_custo_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tributos_recuperaveis_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    revisao_tributaria_confirmada = models.BooleanField(default=False)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, null=True, blank=True, related_name="itens_xml_compra")
    item_entrada = models.OneToOneField(ItemEntradaMercadoria, on_delete=models.SET_NULL, null=True, blank=True, related_name="origem_xml")
    correspondencia = models.CharField(max_length=20, blank=True, choices=[("gtin", "GTIN"), ("codigo_fornecedor", "Código no fornecedor"), ("manual", "Manual"), ("novo", "Produto novo")])
    nivel_correspondencia = models.CharField(
        max_length=12, blank=True, choices=NIVEL_CORRESPONDENCIA_CHOICES
    )
    candidatos_correspondencia = models.JSONField(default=list, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    status_pre_cadastro = models.CharField(
        max_length=20, choices=STATUS_PRE_CADASTRO_CHOICES, default="nao_iniciado"
    )
    nome_proposto = models.CharField(max_length=100, blank=True)
    tipo_item_proposto = models.CharField(
        max_length=20, choices=Produto.TIPO_ITEM_CHOICES, default="produto"
    )
    categoria_proposta = models.ForeignKey(
        CategoriaProduto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_xml_propostos",
    )
    marca_proposta = models.ForeignKey(
        "configuracoes.MarcaGarantia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itens_xml_propostos",
    )
    ncm_proposto = models.CharField(max_length=8, blank=True)
    margem_lucro_proposta = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    margem_minima_proposta = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    preco_final_proposto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sugestoes_cadastro = models.JSONField(default=dict, blank=True)
    pendencias_cadastro = models.JSONField(default=list, blank=True)
    rascunho_salvo_em = models.DateTimeField(null=True, blank=True)
    rascunho_salvo_por = models.ForeignKey(
        "configuracoes.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rascunhos_produto_xml_salvos",
    )

    class Meta:
        ordering = ["numero_item"]
        constraints = [models.UniqueConstraint(fields=["entrada", "numero_item"], name="entrada_xml_numero_item_unico")]

    @property
    def resolvido(self):
        return bool(self.produto_id and self.revisao_tributaria_confirmada)


class LoteImportacaoCompra(models.Model):
    ORIGEM_CHOICES = [("xml", "XML"), ("zip_xml", "Lote ZIP de XML")]
    STATUS_CHOICES = [
        ("em_revisao", "Em revisao"),
        ("concluido", "Concluido"),
        ("cancelado", "Cancelado"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa", on_delete=models.PROTECT, related_name="lotes_importacao_compra"
    )
    codigo = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    origem = models.CharField(max_length=12, choices=ORIGEM_CHOICES)
    arquivo_nome = models.CharField(max_length=255)
    arquivo_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="em_revisao")
    total_documentos = models.PositiveIntegerField(default=0)
    documentos_novos = models.PositiveIntegerField(default=0)
    documentos_existentes = models.PositiveIntegerField(default=0)
    criado_por = models.ForeignKey(
        "configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="lotes_importacao_compra",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "arquivo_sha256"], name="lote_compra_empresa_arquivo_unico"
            )
        ]

    @property
    def pendencias(self):
        return ItemImportacaoXML.objects.filter(
            entrada__documentos_lote__lote=self
        ).filter(models.Q(produto__isnull=True) | models.Q(revisao_tributaria_confirmada=False)).count()

    def __str__(self):
        return f"{str(self.codigo)[:8]} - {self.arquivo_nome}"


class DocumentoLoteImportacao(models.Model):
    lote = models.ForeignKey(
        LoteImportacaoCompra, on_delete=models.CASCADE, related_name="documentos"
    )
    entrada = models.ForeignKey(
        EntradaMercadoria, on_delete=models.PROTECT, related_name="documentos_lote"
    )
    criada_na_importacao = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["entrada__documento_numero", "id"]
        constraints = [
            models.UniqueConstraint(fields=["lote", "entrada"], name="lote_compra_entrada_unica")
        ]


class MapeamentoImportacaoProduto(models.Model):
    FORMATO_CHOICES = [("csv", "CSV"), ("xlsx", "XLSX")]

    empresa = models.ForeignKey(
        "configuracoes.Empresa", on_delete=models.PROTECT, related_name="mapeamentos_importacao_produto"
    )
    fornecedor = models.ForeignKey(
        "configuracoes.FornecedorGarantia", on_delete=models.CASCADE, null=True, blank=True,
        related_name="mapeamentos_importacao_produto",
    )
    nome = models.CharField(max_length=100)
    formato = models.CharField(max_length=8, choices=FORMATO_CHOICES)
    mapeamento = models.JSONField(default=dict)
    padroes = models.JSONField(default=dict, blank=True)
    ativo = models.BooleanField(default=True)
    criado_por = models.ForeignKey(
        "configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mapeamentos_importacao_produto_criados",
    )
    ultimo_uso_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fornecedor__nome", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "fornecedor", "nome"],
                condition=models.Q(fornecedor__isnull=False),
                name="map_importacao_empresa_fornecedor_nome_unico",
            ),
            models.UniqueConstraint(
                fields=["empresa", "nome"],
                condition=models.Q(fornecedor__isnull=True),
                name="map_importacao_empresa_geral_nome_unico",
            ),
        ]

    def __str__(self):
        return f"{self.nome} - {self.fornecedor.nome if self.fornecedor_id else 'Geral'}"


class DocumentoFiscalConferencia(models.Model):
    TIPO_CHOICES = [("cte", "CT-e"), ("nfse", "NFS-e"), ("sped", "SPED/EFD")]
    STATUS_CHOICES = [("conferir", "A conferir"), ("conferido", "Conferido"), ("rejeitado", "Rejeitado")]

    empresa = models.ForeignKey(
        "configuracoes.Empresa", on_delete=models.PROTECT, related_name="documentos_fiscais_conferencia"
    )
    tipo = models.CharField(max_length=8, choices=TIPO_CHOICES)
    arquivo = models.FileField(upload_to="estoque/documentos_conferencia/%Y/%m/")
    arquivo_nome = models.CharField(max_length=255)
    arquivo_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="conferir")
    numero_documento = models.CharField(max_length=60, blank=True)
    chave_documento = models.CharField(max_length=60, blank=True)
    emitente_documento = models.CharField(max_length=30, blank=True)
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    data_documento = models.DateField(null=True, blank=True)
    resumo = models.JSONField(default=dict, blank=True)
    observacao = models.CharField(max_length=240, blank=True)
    criado_por = models.ForeignKey(
        "configuracoes.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="documentos_fiscais_conferencia_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    conferido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo", "arquivo_sha256"],
                name="doc_conferencia_empresa_tipo_hash_unico",
            )
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.numero_documento or self.arquivo_nome}"


class EstoqueLote(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="lotes_estoque")
    codigo = models.CharField(max_length=60)
    validade = models.DateField(null=True, blank=True)
    ponto_operacional = models.ForeignKey(PontoOperacional, on_delete=models.PROTECT, related_name="lotes_estoque")
    ubicacao = models.ForeignKey(UbicacaoEstoque, on_delete=models.PROTECT, related_name="lotes_estoque")
    quantidade_disponivel = models.PositiveIntegerField(default=0)
    entrada_item = models.ForeignKey(
        ItemEntradaMercadoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lotes_gerados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["validade", "criado_em", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["produto", "codigo", "ponto_operacional", "ubicacao"],
                name="uniq_lote_prod_ponto_ubic",
            )
        ]
        indexes = [
            models.Index(fields=["produto", "quantidade_disponivel"], name="idx_lote_prod_saldo"),
            models.Index(fields=["validade"], name="idx_lote_validade"),
        ]

    def __str__(self):
        return f"{self.produto.nome} - lote {self.codigo} ({self.quantidade_disponivel})"


class EstoqueSerie(models.Model):
    STATUS_DISPONIVEL = "disponivel"
    STATUS_BAIXADA = "baixada"
    STATUS_AVARIA = "avaria"
    STATUS_CHOICES = [
        (STATUS_DISPONIVEL, "Disponivel"),
        (STATUS_BAIXADA, "Baixada"),
        (STATUS_AVARIA, "Avaria"),
    ]

    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="series_estoque")
    numero = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DISPONIVEL)
    ponto_operacional = models.ForeignKey(
        PontoOperacional,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="series_estoque",
    )
    ubicacao = models.ForeignKey(
        UbicacaoEstoque,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="series_estoque",
    )
    entrada_item = models.ForeignKey(
        ItemEntradaMercadoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="series_geradas",
    )
    movimento_saida = models.ForeignKey(
        MovimentacaoEstoque,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="series_baixadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["produto__nome", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["produto", "numero"], name="uniq_serie_prod_numero")
        ]
        indexes = [
            models.Index(fields=["produto", "status"], name="idx_serie_prod_status"),
            models.Index(fields=["numero"], name="idx_serie_numero"),
        ]

    def __str__(self):
        return f"{self.produto.nome} - serie {self.numero}"


class ExecucaoAuditoriaEstoque(models.Model):
    STATUS_CHOICES = [
        ("ok", "Sem divergencias"),
        ("divergencia", "Com divergencias"),
        ("erro", "Erro de execucao"),
    ]
    ORIGEM_CHOICES = [
        ("agendada", "Agendada"),
        ("manual", "Manual"),
        ("sistema", "Sistema"),
    ]

    empresa = models.ForeignKey(
        "configuracoes.Empresa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="execucoes_auditoria_estoque",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, default="agendada")
    apenas_ativos = models.BooleanField(default=True)
    total_divergencias = models.PositiveIntegerField(default=0)
    resumo = models.JSONField(default=dict, blank=True)
    detalhes = models.JSONField(default=dict, blank=True)
    mensagem_erro = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["empresa", "-criado_em"], name="idx_audest_emp_criado"),
            models.Index(fields=["status", "-criado_em"], name="idx_audest_status_criado"),
        ]

    def __str__(self):
        empresa = getattr(self.empresa, "nome", None) or "Todas as empresas"
        return f"Auditoria {empresa} - {self.get_status_display()} - {self.criado_em:%d/%m/%Y %H:%M}"







