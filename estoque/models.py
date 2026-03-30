from datetime import timedelta
from decimal import Decimal
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
    preparar_cadastro_produto,
)


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
    usar_aliquota_manual = models.BooleanField(default=False)
    aliquota_manual = models.DecimalField(max_digits=6, decimal_places=3, default=0, blank=True)
    preco_sugerido = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=0)
    preco_minimo = models.DecimalField(max_digits=10, decimal_places=2, editable=False, default=0)
    preco_final = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    preco = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    quantidade = models.PositiveIntegerField(default=0)
    estoque_minimo = models.PositiveIntegerField(default=0)
    previsao_venda_mensal = models.PositiveIntegerField(default=0)
    incluir_rateio_custo_fixo = models.BooleanField(default=False)
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
        criterio = criterio or ConfiguracaoRateioCustoFixo.get_solo().criterio_rateio
        incluir = self.incluir_rateio_custo_fixo if incluir_override is None else bool(incluir_override)
        previsao_atual = int(previsao_override if previsao_override is not None else (self.previsao_venda_mensal or 0))
        if self.tipo_item == "servico" or not incluir or previsao_atual <= 0:
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
        criterio = criterio_override or ConfiguracaoRateioCustoFixo.get_solo().criterio_rateio
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

        total_fixos = (
            CustoFixoMensal.objects.filter(
                competencia=competencia,
                ativo=True,
            )
            .exclude(status="cancelado")
            .aggregate(total=Sum("valor_previsto"))["total"]
            or Decimal("0.00")
        )
        if total_fixos <= 0:
            return Decimal("0.00")

        produtos_rateio = Produto.objects.filter(
            ativo=True,
            is_servico=False,
            incluir_rateio_custo_fixo=True,
            previsao_venda_mensal__gt=0,
        )
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
        preparar_cadastro_produto(self)
        aplicar_custos_base_produto(self)
        aplicar_politica_tipo_item_produto(self)
        aplicar_precificacao_produto(self)

        super().save(*args, **kwargs)
        if not skip_rateio_refresh:
            atualizar_produtos_relacionados_rateio(self)

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


class ConfiguracaoRateioCustoFixo(models.Model):
    CRITERIO_UNIDADES = "unidades"
    CRITERIO_FATURAMENTO = "faturamento"
    CRITERIO_MARGEM = "margem"
    CRITERIO_CHOICES = [
        (CRITERIO_UNIDADES, "Unidades previstas"),
        (CRITERIO_FATURAMENTO, "Faturamento previsto"),
        (CRITERIO_MARGEM, "Margem prevista"),
    ]

    criterio_rateio = models.CharField(max_length=20, choices=CRITERIO_CHOICES, default=CRITERIO_UNIDADES)
    ativo = models.BooleanField(default=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracao de rateio de custo fixo"
        verbose_name_plural = "Configuracoes de rateio de custo fixo"

    def __str__(self):
        return f"Rateio por {self.get_criterio_rateio_display()}"

    @classmethod
    def get_solo(cls):
        configuracao, _ = cls.objects.get_or_create(pk=1, defaults={"criterio_rateio": cls.CRITERIO_UNIDADES, "ativo": True})
        return configuracao

    def save(self, *args, **kwargs):
        self.pk = 1
        result = super().save(*args, **kwargs)
        produtos_rateio = Produto.objects.filter(
            ativo=True,
            is_servico=False,
            incluir_rateio_custo_fixo=True,
        )
        for produto in produtos_rateio:
            produto.save(_skip_rateio_refresh=True)
        return result


class RateioCustoFixoCompetencia(models.Model):
    competencia = models.DateField(unique=True)
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

    def __str__(self):
        return f"Rateio {self.competencia:%m/%Y}"

    @staticmethod
    def _intervalo_competencia(competencia):
        inicio = competencia.replace(day=1)
        proximo_mes = (inicio + timedelta(days=32)).replace(day=1)
        return inicio, proximo_mes

    @classmethod
    def _realizado_por_produto(cls, competencia):
        inicio, proximo_mes = cls._intervalo_competencia(competencia)
        realizado = {}

        vendas = VendaRapidaEstoque.objects.select_related("produto").filter(status="vendida")
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
    def gerar_snapshot(cls, *, competencia, usuario=None, observacao="", sobrescrever=False):
        competencia = competencia.replace(day=1)
        from caixa.models import CustoFixoMensal

        configuracao = ConfiguracaoRateioCustoFixo.get_solo()
        realizado_por_produto = cls._realizado_por_produto(competencia)
        snapshot = cls.objects.filter(competencia=competencia).first()
        criado = False
        if snapshot and not sobrescrever:
            return snapshot, False
        if not snapshot:
            snapshot = cls(competencia=competencia)
            criado = True

        total_fixos = (
            CustoFixoMensal.objects.filter(competencia=competencia, ativo=True)
            .exclude(status="cancelado")
            .aggregate(total=Sum("valor_previsto"))["total"]
            or Decimal("0.00")
        )
        produtos = list(
            Produto.objects.filter(
                ativo=True,
                is_servico=False,
                incluir_rateio_custo_fixo=True,
                previsao_venda_mensal__gt=0,
            ).order_by("nome")
        )

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


class ProdutoHistorico(models.Model):
    ACAO_CHOICES = [
        ("CRIACAO", "Criação"),
        ("EDICAO", "Edição"),
        ("DUPLICACAO", "Duplicação"),
        ("IMPORTACAO", "Importação"),
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






