from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fiscal", "0006_migrar_configuracao_tributaria_legada")]

    operations = [
        migrations.AddField(model_name="regratributaria", name="cfop", field=models.CharField(blank=True, max_length=4)),
        migrations.AddField(model_name="regratributaria", name="cst_csosn", field=models.CharField(blank=True, max_length=4)),
        migrations.AddField(model_name="regratributaria", name="codigo_beneficio", field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="regratributaria", name="natureza_operacao", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(
            model_name="regratributaria",
            name="destinatario_contribuinte",
            field=models.CharField(
                choices=[("qualquer", "Qualquer"), ("sim", "Contribuinte"), ("nao", "Não contribuinte")],
                default="qualquer",
                max_length=8,
            ),
        ),
    ]
