from django.contrib import admin

from .models import (
    AuditoriaFinanceira,
    AporteCapital,
    AuditoriaGarantia,
    Caixa,
    ConciliacaoBancaria,
    ConciliacaoBancariaLinha,
    ConciliacaoBancariaMovimento,
    CategoriaFinanceira,
    CentroCusto,
    ComissaoItemOrcamento,
    Comissao,
    ComissaoTecnico,
    ContaPagar,
    ContaBancaria,
    ContaReceber,
    CustoFixoMensal,
    DespesaRecorrente,
    FaixaPremioMeta,
    FormaPagamento,
    LancamentoCaixa,
    LinhaExtratoBancario,
    MovimentoFinanceiro,
    MovimentoBancario,
    Pagamento,
    PagamentoContaPagar,
    PremioColaboradorCompetencia,
    RecebimentoConta,
    RegraComissaoTecnico,
    RegraPremioMeta,
    TransferenciaTesouraria,
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
admin.site.register(ContaBancaria)
admin.site.register(TransferenciaTesouraria)
admin.site.register(AporteCapital)
admin.site.register(LinhaExtratoBancario)
admin.site.register(ConciliacaoBancaria)
admin.site.register(ConciliacaoBancariaLinha)
admin.site.register(ConciliacaoBancariaMovimento)


@admin.register(MovimentoBancario)
class MovimentoBancarioAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "conta", "tipo", "valor", "data_movimento", "origem_tipo")
    readonly_fields = tuple(field.name for field in MovimentoBancario._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MovimentoFinanceiro)
class MovimentoFinanceiroAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "tipo", "valor", "descricao", "data_movimento", "data_competencia", "status")
    list_filter = ("empresa", "tipo", "status", "data_movimento", "data_competencia")
    search_fields = ("descricao", "origem_referencia", "chave_idempotencia")
    readonly_fields = tuple(field.name for field in MovimentoFinanceiro._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
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
admin.site.register(CustoFixoMensal)
admin.site.register(AuditoriaGarantia)
