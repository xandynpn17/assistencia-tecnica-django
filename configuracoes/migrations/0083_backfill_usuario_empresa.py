from django.db import migrations


def criar_vinculos_dos_usuarios_atuais(apps, schema_editor):
    User = apps.get_model("configuracoes", "User")
    UsuarioEmpresa = apps.get_model("configuracoes", "UsuarioEmpresa")
    for usuario in User.objects.exclude(empresa__isnull=True).iterator():
        UsuarioEmpresa.objects.get_or_create(
            usuario_id=usuario.id,
            empresa_id=usuario.empresa_id,
            defaults={"ativo": True, "padrao": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("configuracoes", "0082_usuarioempresa"),
    ]

    operations = [
        migrations.RunPython(criar_vinculos_dos_usuarios_atuais, migrations.RunPython.noop),
    ]
