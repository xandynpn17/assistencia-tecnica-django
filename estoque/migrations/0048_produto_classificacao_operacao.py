from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("estoque", "0047_produto_classificacao_tributaria"),
        ("fiscal", "0007_regra_classificacao_operacao"),
    ]

    operations = [
        migrations.AddField(model_name="produto", name="unidade_comercial", field=models.CharField(blank=True, default="UN", max_length=10)),
        migrations.AddField(model_name="produto", name="cfop_padrao", field=models.CharField(blank=True, max_length=4)),
        migrations.AddField(model_name="produto", name="cst_csosn", field=models.CharField(blank=True, max_length=4)),
        migrations.AddField(model_name="produto", name="codigo_beneficio_fiscal", field=models.CharField(blank=True, max_length=20)),
    ]
