from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("caixa", "0034_pagamento_formas_pagamento_compostas"),
        ("estoque", "0032_rastreabilidade_lote_serie"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AtendimentoPosVendaBalcao",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cliente_nome_snapshot", models.CharField(blank=True, max_length=120)),
                ("cliente_documento_snapshot", models.CharField(blank=True, max_length=30)),
                ("cliente_telefone_snapshot", models.CharField(blank=True, max_length=30)),
                ("tipo", models.CharField(choices=[("garantia", "Garantia"), ("devolucao", "Devolucao"), ("troca", "Troca"), ("orientacao", "Orientacao")], default="orientacao", max_length=20)),
                ("status", models.CharField(choices=[("aberto", "Aberto"), ("concluido", "Concluido"), ("cancelado", "Cancelado")], default="aberto", max_length=20)),
                ("motivo", models.CharField(blank=True, max_length=160)),
                ("observacao", models.TextField(blank=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("concluido_em", models.DateTimeField(blank=True, null=True)),
                ("criado_por", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="atendimentos_pos_venda_criados", to=settings.AUTH_USER_MODEL)),
                ("pagamento", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="atendimentos_pos_venda", to="caixa.pagamento")),
                ("venda", models.ForeignKey(on_delete=models.PROTECT, related_name="atendimentos_pos_venda", to="estoque.vendarapidaestoque")),
            ],
            options={
                "ordering": ["-criado_em", "-id"],
                "indexes": [models.Index(fields=["tipo", "status"], name="idx_posvenda_tipo_status"), models.Index(fields=["criado_em"], name="idx_posvenda_criado")],
            },
        ),
    ]
