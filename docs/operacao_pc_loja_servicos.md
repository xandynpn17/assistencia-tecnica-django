# Operacao Do PC Da Loja Com Servicos

Este documento registra o modo oficial de operacao do ABGest no PC definitivo da loja.

## Arquitetura recomendada

- PostgreSQL como servico do Windows;
- `waitress` para servir o Django localmente;
- `Caddy` como proxy reverso local;
- projeto em `C:\ABGest\assistencia`;
- ambiente em `C:\ABGest\assistencia\.venv`.

## Comportamento esperado

Ao ligar o Windows:

1. o PostgreSQL sobe primeiro;
2. o servico `ABGestWaitress` inicia o Django;
3. o servico `ABGestCaddy` publica o acesso local pela rede;
4. os usuarios entram pelo navegador, sem abrir terminal.

## Portas tipicas

- `5432`: PostgreSQL
- `8001`: Waitress em loopback/local
- `80` e `443`: Caddy

## Atualizacao apos git pull

Depois de atualizar o codigo no PC da loja:

```cmd
ATUALIZAR-APOS-GIT-PULL-COMO-ADMIN.cmd
```

Esse script:

- instala dependencias novas;
- aplica migrations;
- executa `collectstatic`;
- roda `check`;
- reinicia o servico `ABGestWaitress`;
- garante o `ABGestCaddy` ativo.

## O que evitar

- nao usar `manage.py runserver` no PC definitivo;
- nao deixar varios launchers antigos ativos ao mesmo tempo;
- nao misturar `run_local.ps1` com os servicos da loja no mesmo PC sem necessidade;
- nao atualizar codigo sem rodar o script de pos-pull.

## Quando usar run_local.ps1

`run_local.ps1` continua sendo o fluxo oficial para:

- desenvolvimento;
- homologacao;
- testes manuais;
- uso temporario em outro computador ainda sem os servicos Windows.
