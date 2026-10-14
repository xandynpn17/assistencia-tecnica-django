from django.db import migrations

PERMISSOES = ("perm_cliente_ver_dados", "perm_cliente_ver_historico", "perm_cliente_ver_financeiro", "perm_cliente_editar")


def preservar_acesso(apps, schema_editor):
    # Preserva apenas o acesso que a equipa de atendimento já tinha à ficha.
    apps.get_model("configuracoes", "User").objects.filter(tipo_usuario__in=["adm", "gerente", "atendente"]).update(**{p: True for p in PERMISSOES})
    Vinculo = apps.get_model("configuracoes", "UsuarioEmpresa")
    for vinculo in Vinculo.objects.select_related("usuario").all().iterator():
        permissoes = dict(vinculo.permissoes or {})
        perfil = vinculo.tipo_usuario or vinculo.usuario.tipo_usuario
        for nome in PERMISSOES:
            # Técnicos noutras empresas não herdam privilégios do perfil global.
            permissoes.setdefault(nome, perfil in {"adm", "gerente", "atendente"})
        Vinculo.objects.filter(pk=vinculo.pk).update(permissoes=permissoes)


class Migration(migrations.Migration):
    dependencies = [("configuracoes", "0098_user_perm_cliente_editar_user_perm_cliente_ver_dados_and_more")]
    operations = [migrations.RunPython(preservar_acesso, migrations.RunPython.noop)]
