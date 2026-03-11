from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Aliquota,
    ConfiguracaoOrdemServico,
    Empresa,
    ModuloSistema,
    PermissaoModulo,
    User,
    UsuarioArquivo,
    UsuarioLog,
)


class SingletonModelAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return self.model.objects.count() < 1 and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.shortcuts import redirect

        obj = self.model.objects.first()
        if obj:
            return redirect(f"../{obj.pk}/change/")
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Informacoes pessoais",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "nome_completo",
                    "email",
                    "telefone",
                    "data_nascimento",
                    "foto_perfil",
                    "empresa",
                )
            },
        ),
        ("Documentacao", {"fields": ("tipo_pessoa", "documento_cpf_cnpj", "endereco", "numero_vendedor")}),
        (
            "Dados trabalhistas",
            {
                "fields": (
                    "cargo",
                    "departamento",
                    "regime_contratacao",
                    "data_admissao",
                    "data_demissao",
                    "pis_pasep",
                    "ctps",
                    "salario_base",
                    "observacoes_internas",
                )
            },
        ),
        ("Permissoes", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions", "tipo_usuario")}),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "tipo_usuario", "password1", "password2"),
            },
        ),
    )
    list_display = ("username", "email", "nome_completo", "tipo_usuario", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "nome_completo", "email", "documento_cpf_cnpj")
    ordering = ("username",)


@admin.register(ModuloSistema)
class ModuloSistemaAdmin(admin.ModelAdmin):
    list_display = ("nome",)


@admin.register(Aliquota)
class AliquotaAdmin(admin.ModelAdmin):
    list_display = ("descricao", "aliquota")
    search_fields = ("descricao",)


@admin.register(PermissaoModulo)
class PermissaoModuloAdmin(admin.ModelAdmin):
    list_display = ("tipo_usuario", "modulo", "nivel_permissao")
    list_filter = ("tipo_usuario", "nivel_permissao")


@admin.register(Empresa)
class EmpresaAdmin(SingletonModelAdmin):
    list_display = ("nome", "cnpj", "email")


@admin.register(ConfiguracaoOrdemServico)
class ConfiguracaoOrdemServicoAdmin(SingletonModelAdmin):
    list_display = ("prefixo_os", "inicio_id_ordem", "gerar_numero_automatico")
    fieldsets = (
        (
            "Numeracao",
            {
                "fields": ("prefixo_os", "inicio_id_ordem", "gerar_numero_automatico"),
                "description": "Configuracoes de geracao automatica de numero da OS",
            },
        ),
        (
            "Relatorios",
            {
                "fields": ("rodape_relatorio",),
                "description": "Texto exibido no rodape dos PDFs e impressoes.",
            },
        ),
    )


@admin.register(UsuarioArquivo)
class UsuarioArquivoAdmin(admin.ModelAdmin):
    list_display = ("usuario", "categoria", "descricao", "enviado_por", "criado_em")
    list_filter = ("categoria", "criado_em")
    search_fields = ("usuario__username", "usuario__nome_completo", "descricao")


@admin.register(UsuarioLog)
class UsuarioLogAdmin(admin.ModelAdmin):
    list_display = ("usuario_alvo", "acao", "usuario_responsavel", "data_evento")
    list_filter = ("acao", "data_evento")
    search_fields = ("usuario_alvo__username", "descricao", "usuario_responsavel__username")
    readonly_fields = ("usuario_alvo", "acao", "descricao", "usuario_responsavel", "data_evento")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
