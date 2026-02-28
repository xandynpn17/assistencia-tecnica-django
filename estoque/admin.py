from django.contrib import admin
from .models import Produto, PontoOperacional, UbicacaoEstoque, SaldoEstoquePonto, MovimentacaoEstoque

@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ['nome', 'preco', 'quantidade', 'ativo']
    search_fields = ['nome']


@admin.register(PontoOperacional)
class PontoOperacionalAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nome", "ativo"]
    search_fields = ["codigo", "nome"]


@admin.register(UbicacaoEstoque)
class UbicacaoEstoqueAdmin(admin.ModelAdmin):
    list_display = ["ponto_operacional", "codigo", "descricao", "ativo"]
    list_filter = ["ponto_operacional", "ativo"]
    search_fields = ["codigo", "descricao", "ponto_operacional__codigo"]


@admin.register(SaldoEstoquePonto)
class SaldoEstoquePontoAdmin(admin.ModelAdmin):
    list_display = ["produto", "ponto_operacional", "quantidade"]
    list_filter = ["ponto_operacional"]
    search_fields = ["produto__nome", "produto__ean", "ponto_operacional__codigo"]


@admin.register(MovimentacaoEstoque)
class MovimentacaoEstoqueAdmin(admin.ModelAdmin):
    list_display = ["produto", "tipo", "quantidade", "origem", "destino", "criado_em"]
    list_filter = ["tipo", "origem", "destino"]
    search_fields = ["produto__nome", "observacao", "destino_ubicacao"]
