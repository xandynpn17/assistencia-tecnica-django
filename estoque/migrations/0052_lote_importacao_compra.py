import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estoque", "0051_alter_movimentacaoestoque_tipo_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LoteImportacaoCompra",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("origem", models.CharField(choices=[("xml", "XML"), ("zip_xml", "Lote ZIP de XML")], max_length=12)),
                ("arquivo_nome", models.CharField(max_length=255)),
                ("arquivo_sha256", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("em_revisao", "Em revisao"), ("concluido", "Concluido"), ("cancelado", "Cancelado")], default="em_revisao", max_length=15)),
                ("total_documentos", models.PositiveIntegerField(default=0)),
                ("documentos_novos", models.PositiveIntegerField(default=0)),
                ("documentos_existentes", models.PositiveIntegerField(default=0)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("criado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lotes_importacao_compra", to=settings.AUTH_USER_MODEL)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lotes_importacao_compra", to="configuracoes.empresa")),
            ],
            options={"ordering": ["-criado_em", "-id"]},
        ),
        migrations.CreateModel(
            name="DocumentoLoteImportacao",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("criada_na_importacao", models.BooleanField(default=False)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("entrada", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="documentos_lote", to="estoque.entradamercadoria")),
                ("lote", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documentos", to="estoque.loteimportacaocompra")),
            ],
            options={"ordering": ["entrada__documento_numero", "id"]},
        ),
        migrations.AddConstraint(
            model_name="loteimportacaocompra",
            constraint=models.UniqueConstraint(fields=("empresa", "arquivo_sha256"), name="lote_compra_empresa_arquivo_unico"),
        ),
        migrations.AddConstraint(
            model_name="documentoloteimportacao",
            constraint=models.UniqueConstraint(fields=("lote", "entrada"), name="lote_compra_entrada_unica"),
        ),
    ]
