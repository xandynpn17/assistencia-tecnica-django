from django.db import migrations


TABELAS_COM_SEQUENCIA = (
    "configuracoes_configuracaosistema",
    "configuracoes_configuracaoordemservico",
    "configuracoes_sequenciaos",
    "configuracoes_setupinicialsistema",
)


def realinhar_sequencias_postgresql(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return

    quote_name = connection.ops.quote_name
    with connection.cursor() as cursor:
        for tabela in TABELAS_COM_SEQUENCIA:
            cursor.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence(%s, 'id'),
                    COALESCE(MAX(id), 1),
                    COUNT(*) > 0
                )
                FROM {quote_name(tabela)}
                """,
                [tabela],
            )


class Migration(migrations.Migration):

    dependencies = [
        ("configuracoes", "0085_configuracoes_e_permissoes_por_empresa"),
    ]

    operations = [
        migrations.RunPython(realinhar_sequencias_postgresql, migrations.RunPython.noop),
    ]
