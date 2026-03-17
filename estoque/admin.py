from django.contrib import admin
from .models import (
    CategoriaProduto,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ProdutoEquivalente,
    ProdutoKitItem,
    ProdutoPrecoTabela,
    SaldoEstoquePonto,
    ServicoReferencia,
    TabelaPreco,
    UbicacaoEstoque,
)

@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ["nome", "tipo_item", "ean", "sku", "categoria", "quantidade", "preco_final", "ativo"]
    list_filter = ["tipo_item", "ativo", "permite_os", "categoria_config", "marca"]
    search_fields = ["nome", "ean", "sku", "modelos_compativeis", "fornecedor"]


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
    list_display = ["produto", "tipo", "quantidade", "origem", "destino", "valor_unitario_custo", "criado_em"]
    list_filter = ["tipo", "origem", "destino"]
    search_fields = ["produto__nome", "observacao", "destino_ubicacao"]


@admin.register(CategoriaProduto)
class CategoriaProdutoAdmin(admin.ModelAdmin):
    list_display = ["nome", "margem_padrao", "ordem", "ativo"]
    list_filter = ["ativo"]
    search_fields = ["nome"]


@admin.register(ServicoReferencia)
class ServicoReferenciaAdmin(admin.ModelAdmin):
    list_display = ["nome", "ativo"]
    list_filter = ["ativo"]
    search_fields = ["nome"]


@admin.register(TabelaPreco)
class TabelaPrecoAdmin(admin.ModelAdmin):
    list_display = ["nome", "margem_extra", "ativo"]
    list_filter = ["ativo"]
    search_fields = ["nome"]


@admin.register(ProdutoPrecoTabela)
class ProdutoPrecoTabelaAdmin(admin.ModelAdmin):
    list_display = ["produto", "tabela", "preco"]
    list_filter = ["tabela"]
    search_fields = ["produto__nome", "tabela__nome"]


@admin.register(ProdutoEquivalente)
class ProdutoEquivalenteAdmin(admin.ModelAdmin):
    list_display = ["produto", "equivalente", "observacao"]
    search_fields = ["produto__nome", "equivalente__nome"]


@admin.register(ProdutoKitItem)
class ProdutoKitItemAdmin(admin.ModelAdmin):
    list_display = ["produto_kit", "componente", "quantidade"]
    search_fields = ["produto_kit__nome", "componente__nome"]
