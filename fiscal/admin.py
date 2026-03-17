from django.contrib import admin

from .models import ConfiguracaoFiscal, DocumentoFiscal


@admin.register(ConfiguracaoFiscal)
class ConfiguracaoFiscalAdmin(admin.ModelAdmin):
    list_display = ("ambiente", "modo_integracao", "fornecedor_api", "cnpj_emitente", "nfse_habilitada", "atualizado_em")


@admin.register(DocumentoFiscal)
class DocumentoFiscalAdmin(admin.ModelAdmin):
    list_display = ("id", "tipo", "origem", "origem_referencia", "status", "numero", "serie", "valor_total", "criado_em")
    list_filter = ("tipo", "status", "origem")
    search_fields = ("origem_referencia", "chave_acesso", "protocolo_autorizacao")

