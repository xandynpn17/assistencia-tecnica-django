import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0088_fornecedor_comercial_cnpj"),
        ("estoque", "0053_item_xml_confianca_correspondencia"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MapeamentoImportacaoProduto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100)),
                ("formato", models.CharField(choices=[("csv", "CSV"), ("xlsx", "XLSX")], max_length=8)),
                ("mapeamento", models.JSONField(default=dict)),
                ("padroes", models.JSONField(blank=True, default=dict)),
                ("ativo", models.BooleanField(default=True)),
                ("ultimo_uso_em", models.DateTimeField(blank=True, null=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("criado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="mapeamentos_importacao_produto_criados", to=settings.AUTH_USER_MODEL)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="mapeamentos_importacao_produto", to="configuracoes.empresa")),
                ("fornecedor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="mapeamentos_importacao_produto", to="configuracoes.fornecedorgarantia")),
            ],
            options={"ordering": ["fornecedor__nome", "nome"]},
        ),
        migrations.AddConstraint(
            model_name="mapeamentoimportacaoproduto",
            constraint=models.UniqueConstraint(condition=models.Q(("fornecedor__isnull", False)), fields=("empresa", "fornecedor", "nome"), name="map_importacao_empresa_fornecedor_nome_unico"),
        ),
        migrations.AddConstraint(
            model_name="mapeamentoimportacaoproduto",
            constraint=models.UniqueConstraint(condition=models.Q(("fornecedor__isnull", True)), fields=("empresa", "nome"), name="map_importacao_empresa_geral_nome_unico"),
        ),
    ]
