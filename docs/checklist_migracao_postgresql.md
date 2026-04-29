# Checklist de Migracao para PostgreSQL

Objetivo: trocar SQLite por PostgreSQL em ambiente de desenvolvimento, com reset de base, de forma previsivel.

## 1) Pre-requisitos

- PostgreSQL instalado e em execucao.
- Banco criado (exemplo: `assistencia_dev`).
- Usuario e senha com permissao de acesso ao banco.
- Dependencias do projeto instaladas (`pip install -r requirements.txt`).

## 2) Variaveis de ambiente

Definir:

- `DJANGO_DB_ENGINE=postgres`
- `DJANGO_DB_NAME=assistencia_dev`
- `DJANGO_DB_USER=<usuario>`
- `DJANGO_DB_PASSWORD=<senha>`
- `DJANGO_DB_HOST=127.0.0.1`
- `DJANGO_DB_PORT=5432` (opcional, padrao 5432)
- `DJANGO_DB_CONN_MAX_AGE=60` (opcional)

## 3) Validacoes iniciais

1. `python manage.py check`
2. `python manage.py showmigrations`

Se houver erro de conexao, revisar host/porta/usuario/senha e se o banco existe.

## 4) Reset e subida da base (desenvolvimento)

1. Garantir que esta em ambiente de desenvolvimento.
2. Executar:
   - `python manage.py migrate`
3. Criar usuario admin:
   - `python manage.py createsuperuser`

## 5) Smoke test funcional

Executar validacoes minimas apos migrar:

1. Login no admin e sistema principal.
2. Criar cliente.
3. Abrir OS.
4. Adicionar item/servico.
5. Fechar OS e validar reflexo em caixa.

## 6) Pos-migracao imediata

- Rodar testes automatizados principais.
- Conferir consultas de listagem (OS, clientes, estoque, caixa).
- Revisar performance inicial e necessidade de indices adicionais.

## 7) Rollback rapido (somente desenvolvimento)

Se precisar voltar temporariamente:

- `DJANGO_DB_ENGINE=sqlite`
- remover variaveis `DJANGO_DB_*` de postgres
- executar novamente com `db.sqlite3`
