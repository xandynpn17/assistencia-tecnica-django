from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Caixa(models.Model):
    data = models.DateField(auto_now_add=True)
    aberto = models.BooleanField(default=True)
    saldo_inicial = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    saldo_final = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"Caixa {self.data} - {'Aberto' if self.aberto else 'Fechado'}"


class Pagamento(models.Model):
    METODOS = [
        ("pix", "PIX"),
        ("dinheiro", "Dinheiro"),
        ("credito", "Cartao de Credito"),
        ("debito", "Cartao de Debito"),
        ("garantia_fabricante", "Garantia Fabricante"),
        ("loja", "Custo da Loja"),
    ]

    caixa = models.ForeignKey("Caixa", on_delete=models.CASCADE, related_name="pagamentos", null=True, blank=True)
    ordem_servico = models.ForeignKey("ordens.OrdemServico", on_delete=models.SET_NULL, null=True, blank=True)
    stock_item = models.ForeignKey("estoque.Produto", on_delete=models.SET_NULL, null=True, blank=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    metodo = models.CharField(max_length=30, choices=METODOS)
    referencia = models.CharField(max_length=50, blank=True, null=True, help_text="Numero do talao ou comprovante")
    data = models.DateTimeField(auto_now_add=True)
    observacao = models.TextField(blank=True, null=True)

    def __str__(self):
        origem = (
            f"OS {self.ordem_servico.numero_os}" if self.ordem_servico else
            f"Venda #{self.stock_item.id}" if self.stock_item else
            "Avulso"
        )
        return f"{origem} - {self.metodo} - {self.valor}"


class CategoriaFinanceira(models.Model):
    TIPOS = [
        ("entrada", "Entrada"),
        ("saida", "Saida"),
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
        ("saida", "Saida"),
    ]

    caixa = models.ForeignKey(Caixa, on_delete=models.CASCADE, related_name="lancamentos")
    descricao = models.CharField(max_length=200)
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


class RegraComissaoTecnico(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="regra_comissao")
    percentual_servico = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    percentual_peca = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    comissionar_garantia = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["usuario__username"]

    def __str__(self):
        return f"Comissao {self.usuario} ({self.percentual_servico}%/{self.percentual_peca}%)"


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
        return f"Comissao {self.tecnico} - OS {self.ordem_servico.numero_os} - {self.valor_comissao}"


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
        return f"Comissao item #{self.item_orcamento_id} - {self.tecnico} - {self.valor_comissao}"


class RegraPremioMeta(models.Model):
    METRICA_CHOICES = [
        ("margem_loja", "Margem da loja"),
        ("faturamento_loja", "Faturamento da loja"),
    ]
    PUBLICO_CHOICES = [
        ("tecnico", "Tecnicos"),
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
    nome = models.CharField(max_length=120)
    valor_mensal = models.DecimalField(max_digits=12, decimal_places=2)
    dia_vencimento = models.PositiveSmallIntegerField(default=10)
    ativo = models.BooleanField(default=True)
    ponto_operacional = models.ForeignKey("estoque.PontoOperacional", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} - {self.valor_mensal}"


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
