import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estoque", "0054_mapeamento_importacao_produto"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentoFiscalConferencia",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tipo", models.CharField(choices=[("cte", "CT-e"), ("nfse", "NFS-e"), ("sped", "SPED/EFD")], max_length=8)),
                ("arquivo", models.FileField(upload_to="estoque/documentos_conferencia/%Y/%m/")),
                ("arquivo_nome", models.CharField(max_length=255)),
                ("arquivo_sha256", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("conferir", "A conferir"), ("conferido", "Conferido"), ("rejeitado", "Rejeitado")], default="conferir", max_length=12)),
                ("numero_documento", models.CharField(blank=True, max_length=60)),
                ("chave_documento", models.CharField(blank=True, max_length=60)),
                ("emitente_documento", models.CharField(blank=True, max_length=30)),
                ("valor_total", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("data_documento", models.DateField(blank=True, null=True)),
                ("resumo", models.JSONField(blank=True, default=dict)),
                ("observacao", models.CharField(blank=True, max_length=240)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("conferido_em", models.DateTimeField(blank=True, null=True)),
                ("criado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="documentos_fiscais_conferencia_criados", to=settings.AUTH_USER_MODEL)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="documentos_fiscais_conferencia", to="configuracoes.empresa")),
            ],
            options={"ordering": ["-criado_em", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="documentofiscalconferencia",
            constraint=models.UniqueConstraint(fields=("empresa", "tipo", "arquivo_sha256"), name="doc_conferencia_empresa_tipo_hash_unico"),
        ),
    ]
