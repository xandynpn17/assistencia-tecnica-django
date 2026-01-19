from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone



class Produto(models.Model):
    nome = models.CharField(max_length=100)
    sku = models.CharField(max_length=50, blank=True, null=True)
    ean = models.CharField(max_length=50, blank=True, null=True, unique=True)
    descricao = models.TextField(blank=True)
    categoria = models.CharField(max_length=50, blank=True)
    fornecedor = models.CharField(max_length=50, blank=True)

    # Novos campos para cálculo de preço
    custo_unitario = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    custo_operacional = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    margem_lucro = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    icms = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    ipi = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    pis_cofins = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    preco_sugerido = models.DecimalField(
        max_digits=10, decimal_places=2, editable=False, default=0
    )
    preco_final = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )

    preco = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # mantém compatibilidade
    quantidade = models.PositiveIntegerField(default=0)
    ativo = models.BooleanField(default=True)
    data_entrada = models.DateField(
        default=timezone.now,  # preenche com a data atual
        blank=True,  # permite deixar em branco no form
    )

    is_servico = models.BooleanField(default=False, verbose_name="É um serviço")

    def save(self, *args, **kwargs):
        # Gera EAN automático se estiver vazio
        if not self.ean:
            ultimo_produto = Produto.objects.order_by('-id').first()
            if ultimo_produto and ultimo_produto.ean:
                try:
                    self.ean = str(int(ultimo_produto.ean) + 1)
                except ValueError:
                    self.ean = '2200000000000'
            else:
                self.ean = '2200000000000'

        # Calcula preço sugerido
        impostos_totais = (self.icms + self.ipi + self.pis_cofins) / 100
        self.preco_sugerido = (self.custo_unitario + self.custo_operacional) * (1 + self.margem_lucro / 100) * (
                    1 + impostos_totais)

        # Define preco_final como preco_sugerido se não informado
        if not self.preco_final or self.preco_final <= 0:
            self.preco_final = self.preco_sugerido

        # Mantém compatibilidade com campo preco
        self.preco = self.preco_final

        if not self.data_entrada:
            self.data_entrada = timezone.now().date()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} - R$ {self.preco_final:.2f}"

    @property
    def custo_total(self):
        """Custo unitário + custo operacional"""
        return self.custo_unitario + self.custo_operacional

    @property
    def valor_impostos(self):
        """Valor total dos impostos em reais"""
        impostos_totais = (self.icms + self.ipi + self.pis_cofins) / 100
        return self.custo_total * impostos_totais

    @property
    def preco_sugerido_sem_margem(self):
        """Preço com despesas e impostos, mas sem margem"""
        return self.custo_total * (1 + (self.icms + self.ipi + self.pis_cofins) / 100)

    @property
    def lucro_reais(self):
        """Lucro em reais"""
        return self.preco_final - self.preco_sugerido_sem_margem

    @property
    def lucro_percentual(self):
        """Lucro em percentual sobre o preço sem margem"""
        if self.preco_sugerido_sem_margem == 0:
            return 0
        return (self.lucro_reais / self.preco_sugerido_sem_margem) * 100