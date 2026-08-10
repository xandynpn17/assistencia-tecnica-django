# Atualização do PC definitivo — 10/08/2026

## Objetivo

Instalar a versão consolidada do sistema no computador servidor definitivo com PostgreSQL, arquivos de mídia, configurações locais e possibilidade de retorno ao estado anterior.

## Antes da atualização

1. Interromper o uso nos demais computadores.
2. Confirmar que o backup completo realizado pelo responsável está fora da pasta do projeto e inclui banco e `media`.
3. Guardar cópia do `.env.local` do servidor anterior em local protegido.
4. Registrar o commit/tag da versão anterior para permitir rollback.
5. Confirmar espaço livre e acesso administrativo no computador definitivo.

## Instalação do código

1. Instalar Python 3.12 e PostgreSQL 16.
2. Obter o repositório na versão marcada para go-live.
3. Criar o ambiente virtual e instalar `requirements.txt`.
4. Criar `.env.local` próprio para o computador definitivo; nunca copiar esse arquivo para o Git.
5. Definir uma `SECRET_KEY` forte e estável e uma `FISCAL_CREDENTIAL_KEY` forte, exclusiva e guardada fora do computador.
6. Configurar banco, porta, IP/host local, `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS`.

## Banco e arquivos

1. Iniciar o PostgreSQL.
2. Restaurar o backup no banco definitivo.
3. Restaurar a pasta `media`.
4. Executar:

```powershell
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 migrate
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 check
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 check_tenant_data --strict
```

5. Confirmar que `migrate --plan` retorna `No planned migration operations`.

## Homologação mínima

1. Entrar como administrador.
2. Conferir empresa ativa, usuários e permissões.
3. Abrir cliente e ordem antigos.
4. Conferir estoque, custos, entradas XML e saldos.
5. Abrir e fechar um caixa de teste.
6. Conferir contas bancárias, contas a pagar/receber e DRE.
7. Gerar os PDFs principais.
8. Testar de outro computador da rede usando o IP do servidor.
9. Somente depois liberar o uso normal.

O certificado A1 pode ser cadastrado posteriormente. A ausência dele não impede estoque, caixa ou importação manual de XML.

## Inicialização operacional

Subir a aplicação apenas pelo fluxo oficial:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

Configurar inicialização automática do PostgreSQL e da aplicação somente depois da homologação manual.

## Rollback

Se ocorrer falha crítica:

1. Interromper o uso imediatamente.
2. Parar a aplicação.
3. Guardar uma cópia do banco com falha para diagnóstico.
4. Voltar o código para a tag/commit anterior.
5. Restaurar o backup completo anterior à atualização.
6. Executar `manage_local.ps1 check` e validar uma OS, um produto e um lançamento financeiro antes de reabrir o acesso.

Nunca tentar rollback apenas revertendo migrations em um banco que já recebeu dados reais sem análise técnica.
