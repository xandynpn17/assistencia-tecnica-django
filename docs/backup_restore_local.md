# Backup e Restore Local

Este fluxo foi pensado para uso local/interno da empresa, com PostgreSQL como banco principal.

## Backup

### Pela interface

- `Configuracoes -> Backup`
- botao `Gerar backup agora`

### Pelo terminal

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 backup_db --include-media
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

### Pela interface administrativa

- `Configuracoes -> Restauracao`
- selecione o backup da pasta oficial
- confirme `RESTAURAR`

### Recuperacao local antes do login

- configure `DJANGO_LOCAL_RECOVERY_KEY` no ambiente local;
- abra a tela de login e use o link `Recuperacao local: restaurar backup sem login`;
- esse modo aceita apenas backups da pasta oficial `backups/`;
- a tela publica de recuperacao tambem mostra um comando de fallback por terminal, caso a interface principal nao carregue.

### Pelo terminal

Execute preferencialmente com o servidor Django parado.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 restore_db "backups\backup_AAAAMMDD_HHMMSS" --force
```

Para restaurar tambem os arquivos enviados:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 restore_db "backups\backup_AAAAMMDD_HHMMSS" --force --restore-media
```

Ao restaurar media, a pasta atual e arquivada antes da substituicao.

Para backups antigos ou vindos de testes, use tambem o reparo de empresa unica:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 restore_db "backups\backup_AAAAMMDD_HHMMSS" --force --restore-media --repair-single-tenant
```

Esse reparo associa clientes, OS, orcamentos, produtos e contas sem empresa a empresa ativa. Isso evita que dados restaurados existam no banco, mas fiquem invisiveis em telas filtradas pela empresa local.

Se o `pg_restore` nao estiver no PATH, defina:

```powershell
$env:PG_RESTORE = "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe"
```

## Novo computador

Se a ideia for preparar um novo PC ja com a base restaurada, prefira este fluxo:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\prepare_novo_computador.ps1 `
  -RecoveryKey "SUA_CHAVE_LOCAL" `
  -RestoreBackup "backups\backup_AAAAMMDD_HHMMSS" `
  -RestoreMedia
```

Esse script:

- prepara a `.venv`;
- instala dependencias;
- gera `.env.local`;
- aplica migracoes;
- restaura o backup informado;
- roda validacoes finais.

## Rotina recomendada

- Backup diario no fim do expediente.
- Copia semanal para disco externo, NAS ou nuvem.
- Teste mensal de restore em uma base separada.
- Nunca confiar em backup que ainda nao foi testado.
- Depois de restaurar em outro PC, rode `powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 check_tenant_data --strict`.

## Agendamento no Windows

Depois de validar manualmente, crie uma tarefa diaria no Agendador de Tarefas apontando para:

```powershell
powershell.exe
```

Argumentos:

```powershell
-ExecutionPolicy Bypass -File "C:\Users\Xandy\Documents\projetodjango\assistencia\backup_local_postgres.ps1"
```
