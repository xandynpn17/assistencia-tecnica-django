# Checklist de Go-Live Local (Empresa Unica)

## 1) Ambiente
- Instalar Python 3.12+ e PostgreSQL 15+.
- Configurar variaveis de ambiente de banco (`DJANGO_DB_*`).
- Instalar dependencias: `pip install -r requirements.txt`.

## 2) Banco e aplicacao
- Rodar migracoes: `manage.py migrate`.
- Criar superusuario: `manage.py createsuperuser`.
- Executar validacoes:
  - `manage.py check_go_live`
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
- Testar backup/restore:
  - `manage.py backup_db`
  - `manage.py restore_db <arquivo> --force` (somente homologacao)

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
