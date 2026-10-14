from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ordens", "0053_ordemservico_equipamento_grupo")]
    operations = [migrations.AddField(model_name="configuracaooperacaoempresa", name="checklist_por_tipo", field=models.JSONField(blank=True, default=dict))]
