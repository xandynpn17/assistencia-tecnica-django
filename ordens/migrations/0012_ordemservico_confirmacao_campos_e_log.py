# Generated manually for OS confirmation flow
import uuid

from django.conf import settings
from django.db import migrations, models


def preencher_tokens_confirmacao(apps, schema_editor):
    OrdemServico = apps.get_model('ordens', 'OrdemServico')
    used = set(
        OrdemServico.objects.exclude(token_confirmacao__isnull=True)
        .values_list('token_confirmacao', flat=True)
    )

    for ordem in OrdemServico.objects.filter(token_confirmacao__isnull=True).iterator():
        token = uuid.uuid4()
        while token in used:
            token = uuid.uuid4()
        ordem.token_confirmacao = token
        ordem.save(update_fields=['token_confirmacao'])
        used.add(token)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ordens', '0011_notificacaocliente_assunto'),
    ]

    operations = [
        migrations.AddField(
            model_name='ordemservico',
            name='assinatura_imagem',
            field=models.ImageField(blank=True, null=True, upload_to='ordens/assinaturas/'),
        ),
        migrations.AddField(
            model_name='ordemservico',
            name='confirmado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='ordemservico',
            name='confirmado_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='ordens_confirmadas', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='ordemservico',
            name='data_confirmacao',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ordemservico',
            name='ip_confirmacao',
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ordemservico',
            name='tipo_confirmacao',
            field=models.CharField(blank=True, choices=[('link', 'Confirmacao por link'), ('presencial_assinatura', 'Presencial com assinatura'), ('impresso', 'Impresso')], max_length=30, null=True),
        ),
        migrations.AddField(
            model_name='ordemservico',
            name='token_confirmacao',
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(preencher_tokens_confirmacao, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='ordemservico',
            name='token_confirmacao',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.CreateModel(
            name='LogConfirmacaoOS',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo_evento', models.CharField(max_length=60)),
                ('descricao', models.TextField()),
                ('data_evento', models.DateTimeField(auto_now_add=True)),
                ('ordem_servico', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='logs_confirmacao', to='ordens.ordemservico')),
                ('usuario_responsavel', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='logs_confirmacao_os', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-data_evento', '-id'],
            },
        ),
    ]
