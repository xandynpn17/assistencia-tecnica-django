from django.contrib import admin

from .models import LinhaTrabalho, LogConfirmacaoOS, LogOS, NotificacaoCliente, OrdemServico

for model in (OrdemServico, LinhaTrabalho, NotificacaoCliente, LogConfirmacaoOS, LogOS):
    try:
        admin.site.unregister(model)
    except admin.sites.NotRegistered:
        pass


@admin.register(OrdemServico)
class OrdemServicoAdmin(admin.ModelAdmin):
    list_display = ("numero_os", "cliente", "status", "confirmado", "tipo_confirmacao", "data_confirmacao")
    list_filter = ("status", "confirmado", "tipo_confirmacao")
    search_fields = ("numero_os", "cliente__nome", "cliente__documento")
    readonly_fields = ("token_confirmacao", "data_confirmacao", "ip_confirmacao")


@admin.register(LinhaTrabalho)
class LinhaTrabalhoAdmin(admin.ModelAdmin):
    list_display = ("ordem", "status", "tipo_evento", "criado_em", "usuario")
    list_filter = ("status", "tipo_evento")
    search_fields = ("ordem__numero_os", "descricao")


@admin.register(NotificacaoCliente)
class NotificacaoClienteAdmin(admin.ModelAdmin):
    list_display = ("ordem", "tipo", "canal", "status", "criado_em")
    list_filter = ("tipo", "canal", "status")
    search_fields = ("ordem__numero_os", "destinatario", "mensagem")


@admin.register(LogConfirmacaoOS)
class LogConfirmacaoOSAdmin(admin.ModelAdmin):
    list_display = ("ordem_servico", "tipo_evento", "data_evento", "usuario_responsavel")
    list_filter = ("tipo_evento", "data_evento")
    search_fields = ("ordem_servico__numero_os", "descricao")
    readonly_fields = ("ordem_servico", "tipo_evento", "descricao", "data_evento", "usuario_responsavel")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(LogOS)
class LogOSAdmin(admin.ModelAdmin):
    list_display = ("ordem_servico", "tipo_evento", "data_evento", "usuario_responsavel")
    list_filter = ("tipo_evento", "data_evento")
    search_fields = ("ordem_servico__numero_os", "descricao")
    readonly_fields = ("ordem_servico", "tipo_evento", "descricao", "dados_extras", "data_evento", "usuario_responsavel")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
