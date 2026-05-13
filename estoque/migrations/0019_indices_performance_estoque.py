from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("estoque", "0018_rateiocustofixoitemcompetencia_faturamento_realizado_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="movimentacaoestoque",
            index=models.Index(fields=["tipo", "-criado_em"], name="idx_mov_tipo_criado"),
        ),
        migrations.AddIndex(
            model_name="movimentacaoestoque",
            index=models.Index(fields=["produto", "-criado_em"], name="idx_mov_prod_criado"),
        ),
        migrations.AddIndex(
            model_name="movimentacaoestoque",
            index=models.Index(fields=["origem", "-criado_em"], name="idx_mov_origem_criado"),
        ),
        migrations.AddIndex(
            model_name="movimentacaoestoque",
            index=models.Index(fields=["destino", "-criado_em"], name="idx_mov_destino_criado"),
        ),
        migrations.AddIndex(
            model_name="reservaestoque",
            index=models.Index(fields=["status", "valido_ate"], name="idx_res_status_validade"),
        ),
        migrations.AddIndex(
            model_name="reservaestoque",
            index=models.Index(fields=["produto", "status"], name="idx_res_prod_status"),
        ),
        migrations.AddIndex(
            model_name="reservaestoque",
            index=models.Index(fields=["ponto_operacional", "status"], name="idx_res_ponto_status"),
        ),
        migrations.AddIndex(
            model_name="reservaestoque",
            index=models.Index(fields=["ordem_servico", "status"], name="idx_res_ordem_status"),
        ),
        migrations.AddIndex(
            model_name="reservaestoque",
            index=models.Index(fields=["-criado_em"], name="idx_res_criado_desc"),
        ),
        migrations.AddIndex(
            model_name="vendarapidaestoque",
            index=models.Index(fields=["status", "-criado_em"], name="idx_vr_status_criado"),
        ),
        migrations.AddIndex(
            model_name="vendarapidaestoque",
            index=models.Index(fields=["cesto_codigo", "status"], name="idx_vr_cesto_status"),
        ),
        migrations.AddIndex(
            model_name="vendarapidaestoque",
            index=models.Index(fields=["guia_pagamento", "status"], name="idx_vr_guia_status"),
        ),
        migrations.AddIndex(
            model_name="vendarapidaestoque",
            index=models.Index(fields=["produto", "-criado_em"], name="idx_vr_prod_criado"),
        ),
    ]
