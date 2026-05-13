from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estoque", "0019_indices_performance_estoque"),
        ("configuracoes", "0045_user_perm_estoque_granulares"),
        ("caixa", "0029_pagamento_desconto_pagamento_desconto_percentual"),
        ("ordens", "0032_status_recepcionado_expedicao"),
        ("orcamentos", "0006_itemorcamento_descontos"),
    ]

    operations = [
        migrations.CreateModel(
            name="EstoqueEvento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("evento", models.CharField(max_length=60)),
                ("quantidade", models.IntegerField(blank=True, null=True)),
                ("dados", models.JSONField(blank=True, default=dict)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("inventario", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to="estoque.inventarioestoque")),
                ("ponto_operacional", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to="estoque.pontooperacional")),
                ("produto", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to="estoque.produto")),
                ("reserva", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to="estoque.reservaestoque")),
                ("usuario", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to="configuracoes.user")),
                ("venda", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to="estoque.vendarapidaestoque")),
            ],
            options={
                "ordering": ["-criado_em", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="estoqueevento",
            index=models.Index(fields=["evento", "-criado_em"], name="idx_evt_evento_criado"),
        ),
        migrations.AddIndex(
            model_name="estoqueevento",
            index=models.Index(fields=["usuario", "-criado_em"], name="idx_evt_usuario_criado"),
        ),
        migrations.AddIndex(
            model_name="estoqueevento",
            index=models.Index(fields=["produto", "-criado_em"], name="idx_evt_produto_criado"),
        ),
        migrations.AddIndex(
            model_name="estoqueevento",
            index=models.Index(fields=["ponto_operacional", "-criado_em"], name="idx_evt_ponto_criado"),
        ),
        migrations.AddIndex(
            model_name="estoqueevento",
            index=models.Index(fields=["reserva", "-criado_em"], name="idx_evt_reserva_criado"),
        ),
        migrations.AddIndex(
            model_name="estoqueevento",
            index=models.Index(fields=["venda", "-criado_em"], name="idx_evt_venda_criado"),
        ),
        migrations.AddIndex(
            model_name="estoqueevento",
            index=models.Index(fields=["inventario", "-criado_em"], name="idx_evt_inv_criado"),
        ),
    ]
