# ABGest / ABTech Service Center

Sistema Django para assistencia tecnica, vendas, caixa, estoque e operacao local em rede.

Este projeto esta preparado para uso:

- local em um unico PC;
- local em rede interna com 2 a 3 computadores;
- PC definitivo da loja com servicos Windows;
- PostgreSQL como banco principal;
- backup e restore por interface e por terminal.

## Fluxo recomendado para uso real

Hoje existem dois modos oficiais de uso:

1. Desenvolvimento, testes e homologacao:
   - usar PostgreSQL local no PC principal;
   - subir o sistema com `run_local.ps1`;
   - acessar pelos outros PCs via navegador.
2. PC definitivo da loja:
   - PostgreSQL como servico do Windows;
   - Django servido por `waitress`;
   - proxy local por `Caddy`;
   - inicializacao automatica ao ligar o Windows.

Para a operacao real da loja, o caminho mais seguro e o modo com servicos Windows.

## Requisitos

- Windows 10/11
- Python 3.12+
- PostgreSQL 15+
- PowerShell habilitado

## Primeira instalacao local

No diretorio do projeto:

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_novo_computador.ps1
```

Esse script:

- cria a `.venv`, se necessario;
- instala dependencias;
- gera `.env.local`;
- aplica migracoes;
- executa `collectstatic`;
- roda validacoes basicas;
- deixa pronto para subir o sistema.

Se quiser habilitar recuperacao local antes do login:

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_novo_computador.ps1 -RecoveryKey "SUA_CHAVE_LOCAL"
```

## Restaurar backup em um novo computador

Se o novo PC ja vai entrar com uma base existente:

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_novo_computador.ps1 `
  -RecoveryKey "SUA_CHAVE_LOCAL" `
  -RestoreBackup "backups\backup_AAAAMMDD_HHMMSS" `
  -RestoreMedia
```

Para bases antigas, locais ou vindas de testes, o fluxo ja suporta reparo de empresa unica.

## Subir o sistema

Com o ambiente local pronto:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

No PyCharm, use a configuracao compartilhada `Run Local Server` para executar esse mesmo fluxo sem voltar ao `manage.py runserver` antigo.

O `run_local.ps1` agora encerra automaticamente instancias antigas de `runserver` do mesmo projeto antes de subir uma nova, evitando ficar com 2, 3 ou 4 servidores concorrendo na porta `8000`.

Ou usando um arquivo de ambiente especifico:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1 -EnvPath .\.env.local
```

## Modo oficial do PC da loja

No PC definitivo, o sistema pode ficar rodando sem terminal aberto usando:

- PostgreSQL como servico;
- `waitress` para servir o Django;
- `Caddy` como proxy local para acesso pela rede e HTTPS interno, se configurado.

Nesse modo, o projeto nao deve depender de `manage.py runserver`.

Depois de um `git pull` no PC da loja, o fluxo recomendado e:

```cmd
ATUALIZAR-APOS-GIT-PULL-COMO-ADMIN.cmd
```

Esse script:

- instala dependencias novas, incluindo `waitress`;
- aplica migrations;
- roda `collectstatic`;
- valida o projeto;
- reinicia o servico `ABGestWaitress`;
- mantem o `ABGestCaddy` disponivel.

## Comandos operacionais principais

### Validacoes

```powershell
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 check
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 check_go_live
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 check_postgres_ready --check-connection
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 check_tenant_data --strict
```

### Backup

```powershell
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 backup_db --include-media
```

ou:

```powershell
powershell -ExecutionPolicy Bypass -File .\backup_local_postgres.ps1
```

### Restore

```powershell
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 restore_db "backups\backup_AAAAMMDD_HHMMSS" --force --restore-media
```

## Recuperacao sem login

Se o sistema abrir, mas o login ou alguma parte da interface estiver indisponivel, existe um modo de recuperacao local:

- configurar `DJANGO_LOCAL_RECOVERY_KEY`;
- abrir a tela de login;
- usar o link de restauracao local sem login.

Isso foi pensado justamente para cenarios de falha operacional no PC principal.

## Documentacao complementar

- [Instalacao em novo computador](C:\Users\Xandy\Documents\projetodjango\assistencia\docs\instalacao_local_novo_computador.md)
- [Backup e restore local](C:\Users\Xandy\Documents\projetodjango\assistencia\docs\backup_restore_local.md)
- [Checklist de go-live local](C:\Users\Xandy\Documents\projetodjango\assistencia\docs\checklist_go_live_local.md)
- [Homologacao de rede local](C:\Users\Xandy\Documents\projetodjango\assistencia\docs\homologacao_rede_local.md)
- [Operacao do PC da loja com servicos](C:\Users\Xandy\Documents\projetodjango\assistencia\docs\operacao_pc_loja_servicos.md)

## Observacao importante

Para uso real, prefira sempre PostgreSQL. O SQLite deve ficar restrito a cenarios de desenvolvimento, testes rapidos ou recuperacao pontual.
