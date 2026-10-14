from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ordens", "0052_configuracao_operacao_checklist_entrega")]
    operations = [migrations.AddField(model_name="ordemservico", name="equipamento_grupo", field=models.UUIDField(blank=True, db_index=True, help_text="Identificador interno atribuído após revisão humana do histórico.", null=True))]
