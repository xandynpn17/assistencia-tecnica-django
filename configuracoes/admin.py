from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    User, Empresa, ModuloSistema, Aliquota, PermissaoModulo,
    ConfiguracaoOrdemServico
)

# ------------------------------
# Admin helper: SingletonModelAdmin
# ------------------------------
class SingletonModelAdmin(admin.ModelAdmin):
    """
    Admin que permite apenas 1 instância do modelo.
    - Impede adicionar se já existir 1
    - Impede excluir
    """
    def has_add_permission(self, request):
        # Se já existe um registro, não permite adicionar outro.
        count = self.model.objects.count()
        if count >= 1:
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        # Não permitir exclusão pelo admin (evita deixar o sistema sem config)
        return False

    def changelist_view(self, request, extra_context=None):
        """
        Redireciona o changelist para a página de edição do único objeto (se existir),
        tornando a UX mais natural para singletons.
        """
        from django.shortcuts import redirect
        qs = self.model.objects.all()
        if qs.exists():
            obj = qs.first()
            return redirect(f'../{obj.pk}/change/')
        return super().changelist_view(request, extra_context=extra_context)


# ------------------------------
# User admin
# ------------------------------
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Informações pessoais", {"fields": ("first_name", "last_name", "email", "telefone", "empresa")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions", "tipo_usuario")}),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "tipo_usuario", "password1", "password2"),
        }),
    )
    list_display = ("username", "email", "first_name", "last_name", "tipo_usuario", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("username",)


# ------------------------------
# Registros regulares
# ------------------------------
@admin.register(ModuloSistema)
class ModuloSistemaAdmin(admin.ModelAdmin):
    list_display = ("nome",)

@admin.register(Aliquota)
class AliquotaAdmin(admin.ModelAdmin):
    list_display = ("descricao", "aliquota")
    search_fields = ("descricao", )

@admin.register(PermissaoModulo)
class PermissaoModuloAdmin(admin.ModelAdmin):
    list_display = ("tipo_usuario", "modulo", "nivel_permissao")
    list_filter = ("tipo_usuario", "nivel_permissao")


# ------------------------------
# Empresa como singleton
# ------------------------------
@admin.register(Empresa)
class EmpresaAdmin(SingletonModelAdmin):
    list_display = ("nome", "cnpj", "email")
    readonly_fields = ()

# ------------------------------
# Configuração da Ordem de Serviço (singleton)
# ------------------------------
@admin.register(ConfiguracaoOrdemServico)
class ConfiguracaoOrdemServicoAdmin(SingletonModelAdmin):
    list_display = ("prefixo_os", "inicio_id_ordem", "gerar_numero_automatico")
    fieldsets = (
        ("Numeração", {
            "fields": ("prefixo_os", "inicio_id_ordem", "gerar_numero_automatico"),
            "description": "Configurações de geração automática de número da OS"
        }),
        ("Relatórios", {
            "fields": ("rodape_relatorio",),
            "description": "Texto exibido no rodapé dos PDFs e impressões."
        }),
    )
