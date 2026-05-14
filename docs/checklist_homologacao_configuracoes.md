# Checklist Homologacao Configuracoes

Data base: 14/05/2026

## Perfis

- Adm
- Gerente
- Atendente (com extra de configuracoes)
- Tecnico (sem acesso)

## Itens funcionais

- Acesso ao painel de configuracoes por perfis autorizados.
- Bloqueio por permissao para perfis sem acesso.
- Cadastro/edicao/inativacao de usuario.
- Aplicacao de preset de permissoes no formulario.
- Simulador de impacto de permissoes funcionando.
- Configuracao OS e configuracao de sistema persistindo dados.
- Cadastro de fornecedor, marca, parceiro e regras de garantia.
- Backup executando com sucesso no engine suportado.
- Restore via POST com confirmacao e validacao de caminho.
- Auditoria de configuracoes exibindo eventos com filtros.
- Contrato de webhooks internos acessivel.
- Busca de CEP funcionando com fallback de provedores.

## Itens tecnicos

- `python manage.py check`
- `python manage.py test configuracoes --keepdb --noinput`
- `python manage.py check_saas_readiness`
- `python manage.py check_postgres_ready --check-connection`

## Criterio de aceite

- Todos os testes automatizados da app `configuracoes` em verde.
- Sem erros de permissao nas rotas principais.
- Trilhas de auditoria registradas para eventos criticos.
- Tenant context ativo sem regressao funcional.
