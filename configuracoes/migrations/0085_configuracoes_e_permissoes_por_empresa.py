from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0084_backfill_usuarios_empresa_unica"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuarioempresa",
            name="tipo_usuario",
            field=models.CharField(
                blank=True,
                choices=[
                    ("adm", "Administrador"),
                    ("gerente", "Gerente"),
                    ("atendente", "Atendente"),
                    ("tecnico", "Técnico"),
                ],
                help_text="Perfil usado somente nesta empresa. Em branco, herda o perfil geral do usuario.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="usuarioempresa",
            name="permissoes",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Sobrescritas de permissoes por empresa no formato {"campo": true/false}.',
            ),
        ),
        migrations.AddField(
            model_name="configuracaoordemservico",
            name="empresa",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="configuracao_ordem_servico",
                to="configuracoes.empresa",
            ),
        ),
        migrations.AddField(
            model_name="sequenciaos",
            name="empresa",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sequencia_ordem_servico",
                to="configuracoes.empresa",
            ),
        ),
        migrations.AddField(
            model_name="configuracaosistema",
            name="empresa",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="configuracao_sistema",
                to="configuracoes.empresa",
            ),
        ),
    ]
