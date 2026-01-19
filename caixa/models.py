from django.db import models
from django.conf import settings

class Caixa(models.Model):
    data = models.DateField(auto_now_add=True)
    aberto = models.BooleanField(default=True)
    saldo_inicial = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    saldo_final = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"Caixa {self.data} - {'Aberto' if self.aberto else 'Fechado'}"

class Pagamento(models.Model):
    METODOS = [
        ('pix', 'PIX'),
        ('dinheiro', 'Dinheiro'),
        ('credito', 'Cartão de Crédito'),
        ('debito', 'Cartão de Débito'),
        ('loja', 'Custo da Loja'),
    ]

    caixa = models.ForeignKey("Caixa", on_delete=models.CASCADE, related_name="pagamentos", null=True, blank=True)
    ordem_servico = models.ForeignKey("ordens.OrdemServico", on_delete=models.SET_NULL, null=True, blank=True)
    stock_item = models.ForeignKey("estoque.Produto", on_delete=models.SET_NULL, null=True, blank=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    metodo = models.CharField(max_length=30, choices=METODOS)
    referencia = models.CharField(max_length=50, blank=True, null=True, help_text="Nº do talão ou comprovante")
    data = models.DateTimeField(auto_now_add=True)
    observacao = models.TextField(blank=True, null=True)

    def __str__(self):
        origem = (
            f"OS {self.ordem_servico.numero_os}" if self.ordem_servico else
            f"Venda #{self.stock_item.id}" if self.stock_item else
            "Avulso"
        )
        return f"{origem} - {self.metodo} - €{self.valor}"


class LancamentoCaixa(models.Model):
    TIPOS = [
        ('entrada', 'Entrada'),
        ('saida', 'Saída'),
    ]

    caixa = models.ForeignKey(Caixa, on_delete=models.CASCADE, related_name="lancamentos")
    descricao = models.CharField(max_length=200)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    tipo = models.CharField(max_length=10, choices=TIPOS)
    data = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.tipo} - R${self.valor}"