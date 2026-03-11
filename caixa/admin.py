from django.contrib import admin

from .models import (
    AuditoriaFinanceira,
    AuditoriaGarantia,
    Caixa,
    CategoriaFinanceira,
    CentroCusto,
    ComissaoItemOrcamento,
    Comissao,
    ComissaoTecnico,
    ContaPagar,
    ContaReceber,
    DespesaRecorrente,
    FaixaPremioMeta,
    FormaPagamento,
    LancamentoCaixa,
    Pagamento,
    PagamentoContaPagar,
    PremioColaboradorCompetencia,
    RecebimentoConta,
    RegraComissaoTecnico,
    RegraPremioMeta,
)

admin.site.register(Caixa)
admin.site.register(FormaPagamento)
admin.site.register(CentroCusto)
@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = ("id", "numero_talao", "ordem_servico", "valor", "metodo_display", "data")
    search_fields = ("numero_talao", "referencia", "ordem_servico__numero_os")
    list_filter = ("forma_pagamento", "data")
admin.site.register(LancamentoCaixa)
admin.site.register(CategoriaFinanceira)
admin.site.register(ContaReceber)
admin.site.register(RecebimentoConta)
admin.site.register(ContaPagar)
admin.site.register(PagamentoContaPagar)
admin.site.register(AuditoriaFinanceira)
admin.site.register(RegraComissaoTecnico)
admin.site.register(ComissaoTecnico)
admin.site.register(ComissaoItemOrcamento)
@admin.register(Comissao)
class ComissaoAdmin(admin.ModelAdmin):
    list_display = ("id", "tipo", "tecnico", "ordem_servico", "valor_comissao", "status", "evento_gerador", "data_criacao")
    list_filter = ("tipo", "status", "evento_gerador")
    search_fields = ("ordem_servico__numero_os", "tecnico__username", "descricao", "chave_unica")
admin.site.register(RegraPremioMeta)
admin.site.register(FaixaPremioMeta)
admin.site.register(PremioColaboradorCompetencia)
admin.site.register(DespesaRecorrente)
admin.site.register(AuditoriaGarantia)
