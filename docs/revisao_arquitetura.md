# Revisao da Arquitetura Atual

## Estado atual

O projeto ja possui uma base funcional acima do escopo inicial, com os apps:

- `core`: autenticacao, dashboard e templates base.
- `clientes`: cadastro, busca, edicao e historico do cliente.
- `ordens`: abertura e acompanhamento da OS, linhas de trabalho, notificacoes e impressao.
- `estoque`: produtos, pecas, servicos, movimentacoes, reservas e inventario.
- `orcamentos`: itens de orcamento vinculados a OS.
- `caixa`: recebimentos, contas, comissoes e relatorios financeiros.
- `configuracoes`: usuarios, empresa, marcas, fornecedores, permissoes e parametros do sistema.

## Mapeamento para o negocio

O sistema ja cobre boa parte do fluxo da assistencia tecnica:

- clientes cadastrados em `clientes.Cliente`
- servicos e pecas concentrados em `estoque.Produto`
- tecnicos representados por `configuracoes.User` com `tipo_usuario="tecnico"`
- ordens de servico em `ordens.OrdemServico`
- itens executados na OS em `ordens.ServicoPeca`
- financeiro em `caixa`

Isso significa que hoje o projeto esta mais proximo de uma arquitetura "integrada" do que da divisao idealizada em apps separados `servicos`, `tecnicos` e `financeiro`.

## Principais pontos de atencao

### 1. Escopo misturado entre basico e avancado

O projeto ja inclui recursos avancados como:

- portal do cliente
- confirmacao digital
- pedidos de compra
- controle operacional por ponto de estoque
- regras de comissao
- auditorias e relatorios adicionais

Para a fase atual, vale priorizar o fluxo essencial:

1. cliente
2. abertura da OS
3. diagnostico
4. adicionar servicos e pecas
5. totalizacao
6. aprovacao
7. conclusao
8. recebimento

### 2. Cadastro de servicos esta embutido no estoque

Hoje `estoque.Produto` suporta `tipo_item="servico"` e `is_servico=True`.
Isso funciona, mas pode confundir manutencao futura. A recomendacao e manter esse modelo por agora e tratar o modulo "servicos" como uma visao do estoque filtrada por tipo.

### 3. Tecnicos nao estao em app proprio

Os tecnicos estao no usuario customizado em `configuracoes`.
Isso e suficiente para a fase atual e evita duplicacao de cadastro. Se no futuro houver agenda, produtividade ou especialidades tecnicas mais complexas, ai sim vale um app proprio.

### 4. Ambiente local quebrado

A virtualenv atual aponta para um Python removido durante a reinstalacao do ambiente. Antes de retomar execucao de testes e servidor, o ambiente deve ser recriado.

## Recomendacao arquitetural para agora

### Manter

- `clientes`
- `ordens`
- `estoque`
- `orcamentos`
- `caixa`
- `configuracoes`
- `core`

### Nao criar agora

- app `servicos`
- app `tecnicos`

### Renomear por conceito, nao por codigo

- "Servicos" = produtos do estoque com `tipo_item="servico"`
- "Tecnicos" = usuarios com perfil tecnico
- "Financeiro" = app `caixa`

## Proxima fase recomendada

### Fase 1

- estabilizar ambiente Python
- validar formularios, rotas e templates principais
- garantir fluxo completo cliente -> OS -> servicos/pecas -> total

### Fase 2

- simplificar telas mais carregadas da OS
- revisar regras de estoque automatico ao usar peca na OS
- revisar calculo de totais e comissoes

### Fase 3

- relatorios financeiros essenciais
- melhorias de usabilidade
- preparacao para PostgreSQL

## Decisao pratica

Para continuar o desenvolvimento, a melhor estrategia e evoluir a base atual em vez de recriar o projeto do zero. O ganho agora vem mais de consolidar o fluxo principal e reduzir complexidade acidental do que de abrir novos apps.
