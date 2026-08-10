from django.contrib import admin
from .models import (
    CategoriaProduto,
    ConfiguracaoRateioCustoFixo,
    EstoqueLote,
    EstoqueSerie,
    ExecucaoAuditoriaEstoque,
    EntradaMercadoria,
    DocumentoLoteImportacao,
    DocumentoFiscalConferencia,
    ItemImportacaoXML,
    LoteImportacaoCompra,
    MapeamentoImportacaoProduto,
    MovimentacaoEstoque,
    PontoOperacional,
    ParcelaEntradaMercadoria,
    Produto,
    ProdutoHistorico,
    ProdutoEquivalente,
    ProdutoKitItem,
    ProdutoPrecoTabela,
    RateioCustoFixoCompetencia,
    RateioCustoFixoItemCompetencia,
    SaldoEstoquePonto,
    ServicoReferencia,
    SolicitacaoSaidaEstoque,
    TabelaPreco,
    TransferenciaEstoqueInterempresa,
    UbicacaoEstoque,
)

admin.site.register(ParcelaEntradaMercadoria)
admin.site.register(TransferenciaEstoqueInterempresa)


class DocumentoLoteImportacaoInline(admin.TabularInline):
    model = DocumentoLoteImportacao
    extra = 0
    readonly_fields = ["entrada", "criada_na_importacao", "criado_em"]


@admin.register(LoteImportacaoCompra)
class LoteImportacaoCompraAdmin(admin.ModelAdmin):
    list_display = ["codigo", "empresa", "origem", "arquivo_nome", "status", "total_documentos", "criado_em"]
    list_filter = ["empresa", "origem", "status"]
    search_fields = ["codigo", "arquivo_nome", "arquivo_sha256"]
    readonly_fields = ["codigo", "arquivo_sha256", "total_documentos", "documentos_novos", "documentos_existentes", "criado_em", "atualizado_em"]
    inlines = [DocumentoLoteImportacaoInline]


@admin.register(MapeamentoImportacaoProduto)
class MapeamentoImportacaoProdutoAdmin(admin.ModelAdmin):
    list_display = ["nome", "empresa", "fornecedor", "formato", "ativo", "ultimo_uso_em"]
    list_filter = ["empresa", "formato", "ativo"]
    search_fields = ["nome", "fornecedor__nome"]


@admin.register(DocumentoFiscalConferencia)
class DocumentoFiscalConferenciaAdmin(admin.ModelAdmin):
    list_display = ["tipo", "numero_documento", "empresa", "valor_total", "status", "criado_em"]
    list_filter = ["empresa", "tipo", "status"]
    search_fields = ["numero_documento", "chave_documento", "arquivo_nome", "emitente_documento"]
    readonly_fields = ["arquivo_sha256", "resumo", "criado_em", "conferido_em"]


@admin.register(EntradaMercadoria)
class EntradaMercadoriaAdmin(admin.ModelAdmin):
    list_display = ["numero", "empresa", "fornecedor_config", "documento_numero", "importada_xml", "status", "criado_em"]
    list_filter = ["empresa", "importada_xml", "status"]
    search_fields = ["numero", "documento_numero", "chave_acesso_nfe", "fornecedor_config__nome"]


@admin.register(ItemImportacaoXML)
class ItemImportacaoXMLAdmin(admin.ModelAdmin):
    list_display = ["entrada", "numero_item", "descricao", "produto", "nivel_correspondencia", "correspondencia", "revisao_tributaria_confirmada"]
    list_filter = ["nivel_correspondencia", "correspondencia", "revisao_tributaria_confirmada"]
    readonly_fields = ["dados_originais", "tributos_informados", "candidatos_correspondencia"]


@admin.register(ExecucaoAuditoriaEstoque)
class ExecucaoAuditoriaEstoqueAdmin(admin.ModelAdmin):
    list_display = ["id", "empresa", "status", "origem", "total_divergencias", "criado_em"]
    list_filter = ["empresa", "status", "origem", "apenas_ativos"]
    readonly_fields = [field.name for field in ExecucaoAuditoriaEstoque._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MovimentacaoEstoque)
class MovimentacaoEstoqueAdmin(admin.ModelAdmin):
    list_display = [
        "produto", "tipo", "quantidade", "origem", "destino",
        "valor_unitario_custo", "valor_total_custo", "origem_tipo", "criado_em",
    ]
    list_filter = ["tipo", "origem", "destino"]
    search_fields = ["produto__nome", "observacao", "destino_ubicacao"]
    readonly_fields = [
        "produto",
        "tipo",
        "quantidade",
        "origem",
        "destino",
        "origem_ubicacao",
        "destino_ubicacao_ref",
        "destino_ubicacao",
        "valor_unitario_custo",
        "valor_total_custo",
        "referencia_uuid",
        "chave_idempotencia",
        "origem_tipo",
        "origem_referencia",
        "movimento_estornado",
        "observacao",
        "usuario",
        "criado_em",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SolicitacaoSaidaEstoque)
class SolicitacaoSaidaEstoqueAdmin(admin.ModelAdmin):
    list_display = ["id", "empresa", "tipo", "produto", "quantidade", "beneficiario_nome", "valor_total_custo", "status", "criado_em"]
    list_filter = ["empresa", "tipo", "finalidade", "status"]
    search_fields = ["produto__nome", "beneficiario_nome", "campanha", "documento_autorizacao", "observacao"]
    readonly_fields = [field.name for field in SolicitacaoSaidaEstoque._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
