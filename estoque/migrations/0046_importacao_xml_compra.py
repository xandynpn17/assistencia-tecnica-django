import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("caixa", "0046_tesouraria_e_conciliacao"),
        ("configuracoes", "0088_fornecedor_comercial_cnpj"),
        ("estoque", "0045_servicoreferencia_empresa_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(name="ItemImportacaoXML", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("numero_item", models.PositiveIntegerField()), ("codigo_fornecedor", models.CharField(blank=True, max_length=60)),
            ("gtin", models.CharField(blank=True, max_length=50)), ("descricao", models.CharField(max_length=255)),
            ("ncm", models.CharField(blank=True, max_length=10)), ("cest", models.CharField(blank=True, max_length=10)),
            ("cfop", models.CharField(blank=True, max_length=10)), ("unidade", models.CharField(blank=True, max_length=10)),
            ("quantidade", models.DecimalField(decimal_places=4, max_digits=14)), ("valor_unitario", models.DecimalField(decimal_places=6, max_digits=14)),
            ("valor_produtos", models.DecimalField(decimal_places=2, max_digits=14)), ("desconto_total", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
            ("tributos_informados", models.JSONField(blank=True, default=dict)), ("impostos_custo_total", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
            ("tributos_recuperaveis_total", models.DecimalField(decimal_places=2, default=0, max_digits=14)), ("revisao_tributaria_confirmada", models.BooleanField(default=False)),
            ("correspondencia", models.CharField(blank=True, choices=[("gtin", "GTIN"), ("codigo_fornecedor", "Código no fornecedor"), ("manual", "Manual"), ("novo", "Produto novo")], max_length=20)),
            ("dados_originais", models.JSONField(blank=True, default=dict)),
        ], options={"ordering": ["numero_item"]}),
        migrations.AddField(model_name="entradamercadoria", name="chave_acesso_nfe", field=models.CharField(blank=True, db_index=True, max_length=44)),
        migrations.AddField(model_name="entradamercadoria", name="conta_pagar", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="entrada_mercadoria", to="caixa.contapagar")),
        migrations.AddField(model_name="entradamercadoria", name="gerar_conta_pagar", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="entradamercadoria", name="importada_xml", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="entradamercadoria", name="vencimento_conta_pagar", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="entradamercadoria", name="xml_arquivo", field=models.FileField(blank=True, null=True, upload_to="estoque/xml_compras/%Y/%m/")),
        migrations.AddField(model_name="entradamercadoria", name="xml_divergencias_fornecedor", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="entradamercadoria", name="xml_resumo", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="entradamercadoria", name="xml_sha256", field=models.CharField(blank=True, db_index=True, max_length=64)),
        migrations.AlterField(model_name="produto", name="ean", field=models.CharField(blank=True, max_length=50, null=True)),
        migrations.AddConstraint(model_name="entradamercadoria", constraint=models.UniqueConstraint(condition=models.Q(("empresa__isnull", False), models.Q(("chave_acesso_nfe", ""), _negated=True)), fields=("empresa", "chave_acesso_nfe"), name="entrada_empresa_chave_nfe_unica")),
        migrations.AddConstraint(model_name="produto", constraint=models.UniqueConstraint(condition=models.Q(("ean__isnull", False), ("empresa__isnull", False), models.Q(("ean", ""), _negated=True)), fields=("empresa", "ean"), name="produto_empresa_ean_unico")),
        migrations.AddField(model_name="itemimportacaoxml", name="entrada", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="itens_xml", to="estoque.entradamercadoria")),
        migrations.AddField(model_name="itemimportacaoxml", name="item_entrada", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="origem_xml", to="estoque.itementradamercadoria")),
        migrations.AddField(model_name="itemimportacaoxml", name="produto", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="itens_xml_compra", to="estoque.produto")),
        migrations.AddConstraint(model_name="itemimportacaoxml", constraint=models.UniqueConstraint(fields=("entrada", "numero_item"), name="entrada_xml_numero_item_unico")),
    ]
