from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("caixa", "0061_pagamento_origens_compostas"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CheckoutRascunho",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(blank=True, max_length=120)),
                ("contas_ids", models.JSONField(blank=True, default=list)),
                ("valores_contas", models.JSONField(blank=True, default=dict)),
                ("guia_codigo", models.CharField(blank=True, max_length=32)),
                ("dados_pagamento", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("ativo", "Ativo"), ("concluido", "Concluído"), ("cancelado", "Cancelado")], db_index=True, default="ativo", max_length=12)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("criado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="checkouts_rascunho", to=settings.AUTH_USER_MODEL)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checkouts_rascunho", to="configuracoes.empresa")),
            ],
            options={"ordering": ["-atualizado_em", "-id"]},
        ),
    ]
