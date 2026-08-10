from django.db import migrations, models


def preencher_nivel_correspondencia(apps, schema_editor):
    ItemImportacaoXML = apps.get_model("estoque", "ItemImportacaoXML")
    ItemImportacaoXML.objects.filter(correspondencia__in=["gtin", "codigo_fornecedor", "manual"]).update(
        nivel_correspondencia="exato"
    )
    ItemImportacaoXML.objects.filter(correspondencia="novo").update(nivel_correspondencia="novo")
    ItemImportacaoXML.objects.filter(nivel_correspondencia="", produto__isnull=True).update(
        nivel_correspondencia="novo"
    )


class Migration(migrations.Migration):

    dependencies = [("estoque", "0052_lote_importacao_compra")]

    operations = [
        migrations.AddField(
            model_name="itemimportacaoxml",
            name="candidatos_correspondencia",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="itemimportacaoxml",
            name="nivel_correspondencia",
            field=models.CharField(
                blank=True,
                choices=[("exato", "Exato"), ("provavel", "Provavel"), ("novo", "Novo"), ("conflito", "Conflito")],
                max_length=12,
            ),
        ),
        migrations.RunPython(preencher_nivel_correspondencia, migrations.RunPython.noop),
    ]
