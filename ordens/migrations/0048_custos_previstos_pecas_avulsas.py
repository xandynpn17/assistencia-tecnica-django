from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ordens", "0047_pedidocompra_conta_pagar_and_more")]

    operations = [
        migrations.AddField(
            model_name="servicopeca", name="custo_previsto_final",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="servicopeca", name="situacao_custo",
            field=models.CharField(choices=[("nao_informado", "Não informado"), ("previsto_final", "Custo final previsto"), ("fornecido_cliente", "Fornecida pelo cliente"), ("sem_custo", "Sem custo para a empresa")], default="nao_informado", max_length=24),
        ),
        migrations.AddField(
            model_name="servicopeca", name="custo_previsto_observacao",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddField(
            model_name="custoordemservico", name="estado",
            field=models.CharField(choices=[("previsto", "Previsto"), ("realizado", "Realizado")], db_index=True, default="realizado", max_length=12),
        ),
    ]
