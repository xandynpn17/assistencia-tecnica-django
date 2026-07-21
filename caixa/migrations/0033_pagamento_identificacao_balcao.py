from django.db import migrations, models


def adicionar_campos_identificacao(apps, schema_editor):
    table_name = "caixa_pagamento"
    connection = schema_editor.connection
    existing_tables = connection.introspection.table_names()
    if table_name not in existing_tables:
        return

    with connection.cursor() as cursor:
        descricao = connection.introspection.get_table_description(cursor, table_name)
    colunas = {col.name for col in descricao}

    definicoes = [
        ("cliente_nome", "varchar(120)", 120),
        ("cliente_documento", "varchar(30)", 30),
        ("cliente_telefone", "varchar(30)", 30),
    ]

    for nome, tipo_sql, _ in definicoes:
        if nome in colunas:
            continue
        schema_editor.execute(
            f"ALTER TABLE {schema_editor.quote_name(table_name)} ADD COLUMN {schema_editor.quote_name(nome)} {tipo_sql} NOT NULL DEFAULT ''"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("caixa", "0032_categoriafinanceira_caixa_categoria_financeira_nome_tipo_unico"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(adicionar_campos_identificacao, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="pagamento",
                    name="cliente_nome",
                    field=models.CharField(blank=True, max_length=120),
                ),
                migrations.AddField(
                    model_name="pagamento",
                    name="cliente_documento",
                    field=models.CharField(blank=True, max_length=30),
                ),
                migrations.AddField(
                    model_name="pagamento",
                    name="cliente_telefone",
                    field=models.CharField(blank=True, max_length=30),
                ),
            ],
        ),
    ]
