from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordens', '0036_alter_guiaexpedicaoparceiro_parceiro_nome_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='guiaexpedicaoparceiro',
            name='parceiro_nome',
            field=models.TextField(),
        ),
    ]
