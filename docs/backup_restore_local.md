# Backup e Restore Local

Este fluxo foi pensado para uso local/interno da empresa, com PostgreSQL como banco principal.

## Backup

```powershell
python manage.py backup_db --include-media
```

Ou use o script operacional local:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\backup_local_postgres.ps1
```

O comando gera uma pasta em `backups/`:

```text
backup_AAAAMMDD_HHMMSS/
  database.dump
  media.zip
  manifest.json
```

- `database.dump`: dump nativo do PostgreSQL em formato custom.
- `media.zip`: logos, assinaturas, anexos e demais uploads, quando `--include-media` for usado.
- `manifest.json`: metadados do backup.

Se o `pg_dump` nao estiver no PATH, defina:

```powershell
$env:PG_DUMP = "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"
```

## Restore

Execute preferencialmente com o servidor Django parado.

```powershell
python manage.py restore_db "backups\backup_AAAAMMDD_HHMMSS" --force
```

Para restaurar tambem os arquivos enviados:

```powershell
python manage.py restore_db "backups\backup_AAAAMMDD_HHMMSS" --force --restore-media
```

Ao restaurar media, a pasta atual e arquivada antes da substituicao.

Para backups antigos ou vindos de testes, use tambem o reparo de empresa unica:

```powershell
python manage.py restore_db "backups\backup_AAAAMMDD_HHMMSS" --force --restore-media --repair-single-tenant
```

Esse reparo associa clientes, OS, orcamentos, produtos e contas sem empresa a empresa ativa. Isso evita que dados restaurados existam no banco, mas fiquem invisiveis em telas filtradas pela empresa local.

Se o `pg_restore` nao estiver no PATH, defina:

```powershell
$env:PG_RESTORE = "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe"
```

## Rotina Recomendada

- Backup diario no fim do expediente.
- Copia semanal para disco externo, NAS ou nuvem.
- Teste mensal de restore em uma base separada.
- Nunca confiar em backup que ainda nao foi testado.
- Depois de restaurar em outro PC, rode `python manage.py check_tenant_data --strict`.

## Agendamento no Windows

Depois de validar manualmente, crie uma tarefa diaria no Agendador de Tarefas apontando para:

```powershell
powershell.exe
```

Argumentos:

```powershell
-ExecutionPolicy Bypass -File "C:\Users\Xandy\Documents\projetodjango\assistencia\backup_local_postgres.ps1"
```
