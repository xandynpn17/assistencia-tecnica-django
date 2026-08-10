from django.contrib import admin

from .models import ConfiguracaoFiscal, DocumentoDistribuicaoDFe, DocumentoFiscal, ExecucaoSincronizacaoDFe, FaixaTributaria, PerfilTributario, RegraTributaria, TributoParametrizado


class FaixaTributariaInline(admin.TabularInline):
    model = FaixaTributaria
    extra = 0


class TributoParametrizadoInline(admin.TabularInline):
    model = TributoParametrizado
    extra = 0


@admin.register(PerfilTributario)
class PerfilTributarioAdmin(admin.ModelAdmin):
    list_display = ("empresa", "nome", "regime", "inicio_vigencia", "fim_vigencia", "status", "rbt12")
    list_filter = ("empresa", "regime", "status")
    search_fields = ("nome", "cnae_principal")


@admin.register(RegraTributaria)
class RegraTributariaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome", "perfil", "tipo_item", "finalidade", "tratamento", "prioridade", "status")
    list_filter = ("perfil__empresa", "perfil", "tipo_item", "finalidade", "tratamento", "status")
    search_fields = ("codigo", "nome", "ncm_prefixo", "cest", "codigo_servico", "cfop", "cst_csosn")
    inlines = [FaixaTributariaInline, TributoParametrizadoInline]


@admin.register(ConfiguracaoFiscal)
class ConfiguracaoFiscalAdmin(admin.ModelAdmin):
    list_display = ("empresa", "ambiente", "modo_integracao", "fornecedor_api", "cnpj_emitente", "nfse_habilitada", "atualizado_em")
    list_filter = ("empresa", "ambiente", "modo_integracao")


@admin.register(DocumentoFiscal)
class DocumentoFiscalAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "tipo", "origem", "origem_referencia", "status", "numero", "serie", "valor_total", "criado_em")
    list_filter = ("empresa", "tipo", "status", "origem")
    search_fields = ("origem_referencia", "chave_acesso", "protocolo_autorizacao")


@admin.register(DocumentoDistribuicaoDFe)
class DocumentoDistribuicaoDFeAdmin(admin.ModelAdmin):
    list_display = ("nsu", "empresa", "numero", "serie", "nome_emitente", "disponibilidade", "valor_total", "recebido_em")
    list_filter = ("empresa", "tipo", "disponibilidade")
    search_fields = ("nsu", "numero", "chave_acesso", "cnpj_emitente", "nome_emitente")
    readonly_fields = ("xml_protegido", "xml_sha256")


@admin.register(ExecucaoSincronizacaoDFe)
class ExecucaoSincronizacaoDFeAdmin(admin.ModelAdmin):
    list_display = ("empresa", "ambiente", "status", "codigo_status", "documentos_novos", "iniciado_em", "concluido_em")
    list_filter = ("empresa", "ambiente", "status")
    readonly_fields = ("iniciado_em", "concluido_em")
