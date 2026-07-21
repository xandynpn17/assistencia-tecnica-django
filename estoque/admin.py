from django.contrib import admin
from .models import (
    CategoriaProduto,
    ConfiguracaoRateioCustoFixo,
    EstoqueLote,
    EstoqueSerie,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ProdutoHistorico,
    ProdutoEquivalente,
    ProdutoKitItem,
    ProdutoPrecoTabela,
    RateioCustoFixoCompetencia,
    RateioCustoFixoItemCompetencia,
    SaldoEstoquePonto,
    ServicoReferencia,
    TabelaPreco,
    UbicacaoEstoque,
)

@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ["nome", "tipo_item", "ean", "sku", "categoria", "quantidade", "preco_final", "custo_rateio_fixo", "ativo"]
    list_filter = ["tipo_item", "ativo", "permite_os", "categoria_config", "marca", "incluir_rateio_custo_fixo"]
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


@admin.register(EstoqueLote)
class EstoqueLoteAdmin(admin.ModelAdmin):
    list_display = ["produto", "codigo", "validade", "ponto_operacional", "ubicacao", "quantidade_disponivel"]
    list_filter = ["ponto_operacional", "validade"]
    search_fields = ["produto__nome", "produto__sku", "produto__ean", "codigo"]


@admin.register(EstoqueSerie)
class EstoqueSerieAdmin(admin.ModelAdmin):
    list_display = ["produto", "numero", "status", "ponto_operacional", "ubicacao", "atualizado_em"]
    list_filter = ["status", "ponto_operacional"]
    search_fields = ["produto__nome", "produto__sku", "produto__ean", "numero"]


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


@admin.register(ProdutoHistorico)
class ProdutoHistoricoAdmin(admin.ModelAdmin):
    list_display = ["produto", "acao", "usuario", "criado_em"]
    list_filter = ["acao", "criado_em"]
    search_fields = ["produto__nome", "observacao", "usuario__username"]


@admin.register(ConfiguracaoRateioCustoFixo)
class ConfiguracaoRateioCustoFixoAdmin(admin.ModelAdmin):
    list_display = ["criterio_rateio", "ativo", "atualizado_em"]


@admin.register(RateioCustoFixoCompetencia)
class RateioCustoFixoCompetenciaAdmin(admin.ModelAdmin):
    list_display = ["competencia", "criterio_rateio", "total_custos_fixos", "total_base_rateio", "total_produtos", "gerado_por", "fechado_em"]
    list_filter = ["criterio_rateio", "competencia"]
    search_fields = ["observacao", "gerado_por__username"]


@admin.register(RateioCustoFixoItemCompetencia)
class RateioCustoFixoItemCompetenciaAdmin(admin.ModelAdmin):
    list_display = ["snapshot", "produto_nome", "previsao_venda_mensal", "participacao_percentual", "custo_rateio_unitario", "custo_rateio_total"]
    list_filter = ["snapshot__competencia"]
    search_fields = ["produto_nome", "produto__nome"]
