# Entrega 1 - Mapa de Fluxo e Permissoes

## Objetivo

Levantar como o sistema funciona hoje em dois eixos:

- fluxo operacional da OS por status;
- permissao atual por modulo e por acoes sensiveis.

Este documento nao muda comportamento. Ele serve para preparar as fases de implementacao com baixo risco.

## 1. Fluxo atual da OS

### 1.1 Status existentes na OS

Os status validos hoje sao:

- `diagnosticar`
- `em_andamento`
- `pendente_tecnico`
- `pendente_cliente`
- `pendente_marca`
- `pendente_pecas`
- `pendente_orcamento`
- `autorizado`
- `recusado`
- `devolucao`
- `pronto_contactado`
- `concluida`

### 1.2 Leitura real do fluxo no codigo

O modelo `OrdemServico` hoje aceita transicao livre entre qualquer status valido.

Na pratica:

- o sistema nao impoe uma sequencia fixa entre os status;
- o usuario consegue mudar a OS para qualquer status valido;
- a principal restricao operacional forte hoje nao e o status;
- a principal restricao forte hoje e se a OS esta `confirmada` ou `fechada`.

### 1.3 Regras fortes ja existentes

#### Fechamento da OS

Para concluir/fechar a OS, o sistema exige:

- `relatorio_tecnico`
- `tipo_reparacao`

Ao concluir:

- `status = concluida`
- `fechada = True`
- `data_conclusao` preenchida

Ao reabrir:

- `status = em_andamento`
- `fechada = False`
- `data_conclusao = None`

#### OS fechada

Quando `fechada = True`, o sistema bloqueia:

- linha de trabalho
- servico/peca
- relatorio
- finalizar no caixa
- pedido de compra
- linha de pedido
- alerta
- orcamento
- item de orcamento
- editar local
- editar observacoes
- editar tecnico
- editar serie
- adicionar talao

#### OS confirmada

Hoje existe uma protecao planejada para bloquear edicao critica apos confirmacao.

Problema atual:

- a politica bloqueia apenas `edicao_os_critica`;
- esse `form_type` nao aparece no fluxo ativo encontrado;
- na pratica, a protecao de confirmacao esta subutilizada.

Isso significa:

- o sistema tem a ideia certa;
- mas ela ainda nao esta ligada nas acoes sensiveis reais.

### 1.4 Proxima acao por status

Ja existe um rascunho bom no resumo da OS:

- `diagnosticar`: registrar diagnostico inicial
- `em_andamento`: seguir execucao tecnica
- `pendente_tecnico`: aguardar retorno tecnico
- `pendente_cliente`: cobrar retorno/aprovacao
- `pendente_marca`: acompanhar marca/parceiro
- `pendente_pecas`: acompanhar chegada de pecas
- `pendente_orcamento`: concluir e enviar orcamento
- `autorizado`: executar servico autorizado
- `pronto_contactado`: organizar retirada e fechamento financeiro
- `recusado`: registrar devolucao e finalizar tratativas
- `devolucao`: concluir entrega sem reparo
- `concluida`: ordem finalizada

Esse mapa ja e a base ideal para a futura tela operacional da OS.

### 1.5 Acoes reais disponiveis hoje na tela de detalhes da OS

Enquanto a OS nao esta fechada, o fluxo atual permite:

- adicionar linha de trabalho;
- mudar status via linha de trabalho;
- adicionar servico/peca;
- excluir servico/peca;
- atualizar taloes por item;
- adicionar talao manual;
- finalizar no caixa;
- enviar mensagem por modelo;
- criar pedido de compra;
- atualizar pedido de compra;
- criar alerta;
- anexar arquivo;
- encerrar alerta;
- registrar confirmacao impressa/presencial;
- registrar assinatura de saida;
- editar relatorio tecnico;
- editar local;
- editar observacoes;
- alterar tecnico responsavel;
- alterar numero de serie;
- editar orcamento;
- aprovar item de orcamento;
- recusar item de orcamento;
- migrar item aprovado;
- excluir item de orcamento.

### 1.6 Como o fluxo se comporta de fato hoje

O fluxo atual e coerente com assistencia tecnica porque:

- ele trabalha por status;
- ele aceita desvios;
- ele nao exige uma linha reta artificial.

O que falta para ficar mais forte:

- mapear acoes permitidas por status;
- mapear bloqueios por status;
- destacar proxima acao recomendada;
- separar melhor acoes normais de acoes sensiveis.

### 1.7 Matriz inicial de status x acao recomendada

| Status | Papel operacional | Proxima acao recomendada | Acoes que deveriam ser destaque |
|---|---|---|---|
| `diagnosticar` | entrada tecnica | registrar diagnostico | linha de trabalho, tecnico, serie, observacoes |
| `em_andamento` | execucao | seguir reparo | linha, servicos/pecas, pedidos, alertas |
| `pendente_tecnico` | dependencia interna | cobrar retorno tecnico | linha, alerta, tecnico |
| `pendente_cliente` | dependencia externa | cobrar aprovacao/retorno | mensagem, alerta, linha |
| `pendente_marca` | dependencia parceiro | acompanhar fabricante | mensagem, pedido, linha |
| `pendente_pecas` | dependencia de material | acompanhar chegada | pedido, linha, alerta |
| `pendente_orcamento` | aguardando proposta | montar/enviar orcamento | orcamento, mensagem |
| `autorizado` | aprovado para executar | executar e registrar itens | servicos/pecas, relatorio |
| `recusado` | sem aprovacao | organizar devolucao | linha, mensagem, devolucao |
| `devolucao` | encerramento sem reparo | finalizar entrega | relatorio, assinatura, fechamento |
| `pronto_contactado` | pronto para retirar/pagar | caixa e retirada | finalizar caixa, assinatura de saida |
| `concluida` | ordem fechada | apenas consulta/financeiro residual | caixa residual, logs, impressao |

## 2. Permissoes atuais

### 2.1 Modelo atual de controle

Hoje o sistema mistura tres camadas:

1. perfil base por tipo de usuario
2. acesso extra por modulo no usuario
3. regras soltas em templates e trechos de view

### 2.2 Perfis base

Perfis identificados:

- `adm`
- `gerente`
- `atendente`
- `tecnico`
- `portal`

### 2.3 Acessos extras por modulo ja existentes no usuario

Campos atuais no usuario:

- `acesso_ordens_extra`
- `acesso_estoque_extra`
- `acesso_caixa_operacional_extra`
- `acesso_caixa_financeiro_extra`
- `acesso_configuracoes_extra`

### 2.4 Regras de modulo em runtime

Hoje o sistema usa principalmente:

- `ORDER_ROLES`
- `ORDER_CREATION_ROLES`
- `STOCK_VIEW_ROLES`
- `STOCK_MANAGE_ROLES`
- `CAIXA_OPERATIONAL_ROLES`
- `CAIXA_FINANCIAL_ROLES`
- `MANAGER_ROLES`

### 2.5 Lacuna estrutural importante

Existe um modelo `PermissaoModulo`, mas ele nao aparece nas regras de runtime encontradas.

Hoje ele esta:

- modelado;
- migrado;
- no admin;

Mas nao esta:

- participando das autorizacoes reais das views.

### 2.6 Acoes sensiveis que hoje estao largas demais

Estas acoes hoje estao protegidas basicamente por acesso amplo ao modulo, nao por permissao fina:

| Acao sensivel | Protecao atual | Observacao |
|---|---|---|
| editar numero de serie | `ORDER_ROLES` | tecnico tambem pode |
| alterar tecnico responsavel | `ORDER_ROLES` | amplo demais |
| editar local da OS | `ORDER_ROLES` | amplo demais |
| editar observacoes internas | `ORDER_ROLES` | amplo demais |
| adicionar/excluir servico ou peca | `ORDER_ROLES` | amplo demais |
| aprovar/recusar item de orcamento | `ORDER_ROLES` | amplo demais |
| excluir item de orcamento | `ORDER_ROLES` | amplo demais |
| aplicar desconto em pagamento/orcamento | por modulo | sem permissao especifica |
| finalizar/reabrir OS | `ORDER_ROLES` | amplo demais |
| registrar pagamento | `CAIXA_OPERATIONAL_ROLES` | atendente pode, o que pode ser correto para negocio |
| excluir pagamento | `CAIXA_FINANCIAL_ROLES` | melhor que os demais, mas ainda sem permissao especifica |
| criar/baixar conta a receber | `CAIXA_FINANCIAL_ROLES` | sem granularidade por acao |
| criar/baixar conta a pagar | `CAIXA_FINANCIAL_ROLES` | sem granularidade por acao |
| acessar DRE | `CAIXA_FINANCIAL_ROLES` | modulo amplo |
| gerir comissoes | `CAIXA_FINANCIAL_ROLES` | modulo amplo |
| acessar auditoria operacional | `CAIXA_FINANCIAL_ROLES` | modulo amplo |

### 2.7 Regras hardcoded em templates

Ainda existem varias decisoes de acesso feitas direto em template com verificacoes como:

- `user.tipo_usuario == 'adm'`
- `user.tipo_usuario == 'gerente'`
- `user.tipo_usuario != 'tecnico'`
- `user.is_superuser`

Isso gera tres problemas:

- a regra fica duplicada;
- a seguranca fica menos previsivel;
- a granularidade nova fica mais dificil de aplicar.

### 2.8 Acoes que ja tem algum recorte melhor

Alguns pontos ja estao mais alinhados:

- ver logs da OS: apenas `adm` ou `gerente`
- excluir pagamento: caixa financeiro
- painel/configuracoes: gerente/admin ou extra
- cliente excluir/unificar: gerente/admin

Esses pontos podem virar padrao para o resto.

## 3. Permissoes granulares sugeridas

### 3.1 Grupo OS

- `perm_os_editar_numero_serie`
- `perm_os_alterar_tecnico`
- `perm_os_editar_observacoes_internas`
- `perm_os_editar_local_armazenamento`
- `perm_os_excluir_servico_peca`
- `perm_os_reabrir`
- `perm_os_concluir`
- `perm_os_editar_relatorio_pos_confirmacao`
- `perm_os_registrar_assinatura_saida`

### 3.2 Grupo Orcamento

- `perm_orcamento_editar`
- `perm_orcamento_aprovar_item`
- `perm_orcamento_recusar_item`
- `perm_orcamento_excluir_item`
- `perm_orcamento_aplicar_desconto`
- `perm_orcamento_migrar_item`

### 3.3 Grupo Caixa

- `perm_caixa_registrar_pagamento`
- `perm_caixa_excluir_pagamento`
- `perm_caixa_registrar_saida`
- `perm_caixa_criar_conta_receber`
- `perm_caixa_baixar_conta_receber`
- `perm_caixa_aplicar_desconto`
- `perm_caixa_criar_conta_pagar`
- `perm_caixa_baixar_conta_pagar`
- `perm_caixa_ver_dre`
- `perm_caixa_gerir_comissoes`
- `perm_caixa_ver_auditoria`

### 3.4 Grupo Configuracoes

- `perm_config_editar_usuarios`
- `perm_config_editar_parametros_criticos`
- `perm_config_backup_restore`

## 4. Recomendacao tecnica para a Fase 3

### 4.1 Sem quebrar o que existe

Implementar em camadas:

1. manter perfis base e acessos extras por modulo;
2. adicionar permissao granular por acao sensivel;
3. criar helper central de checagem;
4. migrar primeiro as acoes mais delicadas;
5. depois remover condicoes hardcoded em templates.

### 4.2 Primeiras acoes para granularizar

Ordem recomendada:

1. editar numero de serie
2. alterar tecnico responsavel
3. reabrir/concluir OS
4. excluir item de orcamento
5. excluir pagamento
6. aplicar desconto em orcamento e caixa
7. ver DRE / comissoes / auditoria

## 5. Feito x pendente

### Feito nesta entrega

- mapa dos status atuais da OS;
- identificacao das regras fortes atuais;
- identificacao das acoes reais da OS;
- mapa das permissoes de modulo atuais;
- identificacao das acoes sensiveis sem granularidade;
- identificacao de gaps estruturais nas permissoes;
- matriz de bloqueio por status da OS;
- helper central para permissao por acao sensivel;
- campos de permissao granular para acoes sensiveis ja priorizadas;
- aplicacao das permissoes granulares em editar serie, alterar tecnico, concluir/reabrir OS, excluir item de orcamento, excluir pagamento, DRE, comissoes, auditoria e descontos;
- consolidacao das acoes de orcamento dentro da aba da OS.

### Pendente para implementacao

- remocao gradual de regras hardcoded em templates;
- ampliar permissoes granulares para criar/baixar contas a receber e contas a pagar;
- revisar exclusoes e edicoes destrutivas fora de OS/orcamento/caixa;
- reorganizacao visual fina da OS em torno de status e proxima acao, mantendo o layout atual.
