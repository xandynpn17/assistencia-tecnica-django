from django.db import migrations


def vincular_usuarios_a_empresa_unica(apps, schema_editor):
    Empresa = apps.get_model("configuracoes", "Empresa")
    User = apps.get_model("configuracoes", "User")
    UsuarioEmpresa = apps.get_model("configuracoes", "UsuarioEmpresa")

    empresas = list(Empresa.objects.order_by("id").values_list("id", flat=True)[:2])
    if len(empresas) != 1:
        return

    empresa_id = empresas[0]
    User.objects.filter(empresa__isnull=True).update(empresa_id=empresa_id)
    for usuario_id in User.objects.values_list("id", flat=True).iterator():
        UsuarioEmpresa.objects.update_or_create(
            usuario_id=usuario_id,
            empresa_id=empresa_id,
            defaults={"ativo": True, "padrao": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("configuracoes", "0083_backfill_usuario_empresa"),
    ]

    operations = [
        migrations.RunPython(vincular_usuarios_a_empresa_unica, migrations.RunPython.noop),
    ]
