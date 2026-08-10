import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("estoque", "0046_importacao_xml_compra"),
        ("fiscal", "0004_motor_tributario_versionado"),
    ]

    operations = [
        migrations.AddField(model_name="produto", name="ncm", field=models.CharField(blank=True, max_length=8)),
        migrations.AddField(model_name="produto", name="cest", field=models.CharField(blank=True, max_length=10)),
        migrations.AddField(model_name="produto", name="origem_mercadoria", field=models.CharField(blank=True, max_length=2)),
        migrations.AddField(model_name="produto", name="codigo_servico", field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="produto", name="regra_tributaria", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="produtos", to="fiscal.regratributaria")),
    ]
