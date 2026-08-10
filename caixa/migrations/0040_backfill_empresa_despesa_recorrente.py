from django.db import migrations


def vincular_empresa_unica(apps, schema_editor):
    Empresa = apps.get_model("configuracoes", "Empresa")
    DespesaRecorrente = apps.get_model("caixa", "DespesaRecorrente")
    empresas = list(Empresa.objects.values_list("id", flat=True)[:2])
    if len(empresas) == 1:
        DespesaRecorrente.objects.filter(empresa__isnull=True).update(empresa_id=empresas[0])


class Migration(migrations.Migration):
    dependencies = [
        ("caixa", "0039_despesarecorrente_empresa"),
        ("configuracoes", "0077_empresa_limite_cedencia_sem_aprovacao_and_more"),
    ]

    operations = [migrations.RunPython(vincular_empresa_unica, migrations.RunPython.noop)]
