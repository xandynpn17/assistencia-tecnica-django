# Instalacao Local em Novo Computador

Este guia foi feito para colocar o sistema a funcionar em outro PC da empresa com o minimo de friccao.

## 1) Pre-requisitos

Instale no novo computador:

- Python 3.12+
- PostgreSQL 15+
- Git, se for clonar o projeto

Tenha em maos:

- a pasta do projeto;
- o backup mais recente em `backups/`;
- os dados de acesso do PostgreSQL;
- a chave de recuperacao local, se quiser habilitar restore sem login.

## 2) Preparar o banco

Crie a base local no PostgreSQL e confirme:

- host;
- porta;
- nome da base;
- usuario;
- senha.

Se estiver a usar o mesmo padrao do projeto, ajuste `.env.postgres.local`.

## 3) Rodar a preparacao automatica

No diretorio `assistencia`:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\prepare_novo_computador.ps1 `
  -RecoveryKey "SUA_CHAVE_LOCAL"
```

Se quiser ja restaurar a base:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\prepare_novo_computador.ps1 `
  -RecoveryKey "SUA_CHAVE_LOCAL" `
  -RestoreBackup "backups\backup_AAAAMMDD_HHMMSS" `
  -RestoreMedia
```

## 4) Subir o sistema

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\run_local.ps1
```

Depois aceda no navegador do proprio PC:

```text
http://127.0.0.1:8000
```

## 5) Liberar acesso para outros PCs

Use o IP do computador servidor. Exemplo:

```text
http://192.168.1.114:8000
```

Nos outros PCs, teste conectividade com:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\test_local_network.ps1 -ServerIp 192.168.1.114 -OpenBrowser
```

## 6) Se o login ou a interface falhar

Se a tela de login abrir, mas o sistema estiver inconsistente:

- use o link de recuperacao local sem login;
- informe a chave configurada em `DJANGO_LOCAL_RECOVERY_KEY`;
- selecione um backup oficial da pasta `backups/`.

Se a interface nao abrir:

- pare o servidor;
- rode o restore por terminal:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 restore_db "backups\backup_AAAAMMDD_HHMMSS" --force --restore-media --repair-single-tenant
```

Ou use o assistente interativo:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\restore_emergencial_local.ps1 -RestoreMedia
```

## 7) Validacao final

Rode:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 check
powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 check_go_live
powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 check_postgres_ready --check-connection
powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 check_tenant_data --strict
```

Valide tambem:

- login;
- dashboard;
- abertura de OS;
- orcamento;
- pagamento;
- backup;
- restore.
