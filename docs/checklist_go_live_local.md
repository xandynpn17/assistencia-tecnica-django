# Checklist de Go-Live Local (Empresa Unica)

## 1) Ambiente
- Instalar Python 3.12+ e PostgreSQL 15+.
- Configurar variaveis de ambiente de banco (`DJANGO_DB_*`).
- Instalar dependencias: `pip install -r requirements.txt`.
- Para um novo computador, prefira o script unico:
  - `powershell.exe -ExecutionPolicy Bypass -File .\prepare_novo_computador.ps1`

## 2) Banco e aplicacao
- Rodar migracoes: `manage.py migrate`.
- Criar superusuario: `manage.py createsuperuser`.
- Para comandos administrativos no PostgreSQL local, prefira: `powershell.exe -ExecutionPolicy Bypass -File .\manage_local.ps1 <comando>`.
- Gerar ambiente local em rede: `powershell.exe -ExecutionPolicy Bypass -File .\setup_local_env.ps1 -Overwrite`.
- Iniciar em modo local em rede: `powershell.exe -ExecutionPolicy Bypass -File .\run_local.ps1`.
- Executar validacoes:
  - `manage.py check_go_live`
  - `manage.py check_go_live --strict`
  - `manage.py check_postgres_ready --check-connection`
  - `manage.py check_tenant_data --strict`
  - `manage.py check_saas_readiness`

## 3) Static e deploy
- Gerar arquivos estaticos: `manage.py collectstatic --noinput`.
- Garantir `STATIC_ROOT` configurado.
- Nao versionar `staticfiles/` (artefato de deploy).

## 4) Operacao e seguranca
- Configurar `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS`.
- Confirmar `DEBUG=False` no ambiente de producao.
- Garantir `SECRET_KEY` forte e exclusiva.
- Configurar `DJANGO_LOCAL_RECOVERY_KEY` para permitir restore sem login no PC principal.
- Testar backup/restore:
  - SQLite: `manage.py backup_db --gzip --include-media`
  - PostgreSQL: `manage.py backup_db --include-media`
  - Restore: `manage.py restore_db <arquivo-ou-pasta-backup> --force`
  - Restore com uploads/logos/anexos: `manage.py restore_db <arquivo-ou-pasta-backup> --force --restore-media`
  - Restore de backup antigo/local: `manage.py restore_db <arquivo-ou-pasta-backup> --force --restore-media --repair-single-tenant`
  - Em PostgreSQL, prefira executar restore com o servidor Django parado.

## 4.1) Rede local
- No PC servidor: `powershell.exe -ExecutionPolicy Bypass -File .\run_local.ps1 -CheckOnly`.
- Nos PCs clientes: `powershell.exe -ExecutionPolicy Bypass -File .\test_local_network.ps1 -ServerIp <IP_DO_SERVIDOR> -OpenBrowser`.
- Validar os fluxos do documento `docs/homologacao_rede_local.md`.
- Se o `check_go_live` avisar que `ALLOWED_HOSTS` esta limitado ao proprio servidor, recrie `.env.local` com o IP correto usando `setup_local_env.ps1 -Overwrite`.

## 5) Parametros de negocio
- Revisar `Configuracoes do Sistema`:
  - SLA, garantias padrao, mensagens, layouts de documento.
- Revisar perfis de usuario e permissoes sensiveis.
- Validar fluxo completo:
  - abrir OS -> orcamento -> aprovacao -> conclusao -> caixa.

## 6) Pos go-live
- Definir rotina de backup diario e retencao.
- Revisar painel de SLA diariamente.
- Revisar logs de integracoes semanalmente.
- Manter pelo menos um teste mensal de restauracao em outro computador ou base separada.
