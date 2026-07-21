# Plano de Correcao - App Caixa

## Objetivo da fase

Refinar a app `caixa` para que ela fique:

- rapida no balcao;
- clara para abertura e fechamento;
- previsivel para cobranca e pagamento;
- menos poluida visualmente;
- melhor separada entre operacao e gestao.

## Fase C1 - Navegacao e Estrutura

Tela principal:
- `caixa/templates/caixa/_subnav_caixa.html`

Problemas atuais:
- opcoes demais no mesmo nivel;
- textos quebrados;
- mistura de operacao, gestao, cadastros e comissoes.

Tarefas:
1. corrigir mojibake e labels quebrados;
2. reorganizar a navegacao em 3 grupos:
   - Operacao
   - Financeiro
   - Apoio e cadastros
3. destacar melhor a tela ativa;
4. reduzir peso visual dos itens secundarios;
5. manter itens sensiveis mais discretos para perfis operacionais.

Entrega esperada:
- subnav mais curta, limpa e intuitiva.

## Fase C2 - Dashboard Operacional

Tela principal:
- `caixa/templates/caixa/dashboard_caixa_operacional.html`

Problemas atuais:
- muita informacao no topo;
- excesso de leitura antes da acao;
- KPIs competem com tarefas urgentes.

Tarefas:
1. reduzir altura visual do hero;
2. trocar parte dos KPIs por filas operacionais;
3. criar bloco `Acoes do turno`;
4. criar bloco `Pendencias agora`;
5. deixar os KPIs gerenciais em area secundaria;
6. revisar microcopy para linguagem mais direta.

Entrega esperada:
- dashboard dizendo o que fazer agora, nao apenas o que aconteceu.

## Fase C3 - Registrar Pagamento em Modo Balcao

Tela principal:
- `caixa/templates/caixa/registrar_pagamento.html`

Problemas atuais:
- tela poderosa, mas densa;
- fluxo principal nao domina visualmente;
- blocos secundarios competem com a acao principal.

Tarefas:
1. separar o fluxo principal em 4 passos:
   - origem
   - valor
   - forma
   - concluir
2. recolher blocos avancados:
   - desconto critico
   - composicao de pagamento
   - fiscal
   - identificacao opcional
   - observacoes
3. reduzir o volume do resumo lateral;
4. destacar total, pago e saldo;
5. reforcar estado de entrega/liberacao;
6. melhorar foco e leitura da proxima etapa.

Entrega esperada:
- pagamento simples concluido em poucos segundos e com menos erro visual.

## Fase C4 - Abrir Caixa

Tela principal:
- `caixa/templates/caixa/abrir_caixa.html`

Tarefas:
1. destacar valor sugerido;
2. transformar valores rapidos em seletor mais visual;
3. reforcar checklist de abertura;
4. diferenciar melhor cada estado da tela;
5. melhorar destaque do proximo passo apos abertura.

## Fase C5 - Fechar Caixa

Tela principal:
- `caixa/templates/caixa/fechar_caixa.html`

Tarefas:
1. aumentar destaque de saldo esperado, contado e diferenca;
2. reforcar badge de estado;
3. tornar justificativa mais evidente quando obrigatoria;
4. destacar divergencias por forma;
5. revisar ordem e peso dos ultimos movimentos.

## Fase C6 - Contas a Receber

Tela principal:
- `caixa/templates/caixa/contas_receber_list.html`

Tarefas:
1. manter visiveis apenas filtros essenciais;
2. mover filtros restantes para `Filtros avancados`;
3. reduzir altura dos resumos;
4. destacar filas por prioridade;
5. simplificar leitura das linhas;
6. rever a posicao de exportacoes.

## Fase C7 - Contas a Pagar

Tela principal:
- `caixa/templates/caixa/contas_pagar_list.html`

Tarefas:
1. aplicar o mesmo padrao de filtro reduzido;
2. esconder filtros complementares;
3. destacar prioridades;
4. simplificar leitura da tabela;
5. tornar `Pagar` mais evidente;
6. revisar modal de pagamento rapido.

## Fase C8 - Financeiro Gerencial

Telas:
- `caixa/templates/caixa/dashboard_caixa.html`
- `caixa/templates/caixa/dre.html`
- `caixa/templates/caixa/fluxo_projetado.html`
- `caixa/templates/caixa/relatorios.html`

Tarefas:
1. diferenciar visualmente area gerencial da operacional;
2. revisar densidade dos cards;
3. padronizar cabecalhos e acoes;
4. manter relatorios com cara de analise, nao de operacao.

## Fase C9 - Garantias e Cobrancas por Marca

Tela:
- `caixa/templates/caixa/garantias_fabricante.html`

Tarefas:
1. reforcar leitura de status;
2. destacar vencidas, divergentes e prontas para cobranca;
3. deixar marca e fornecedor mais visiveis;
4. revisar fluxo de baixa ou atualizacao.

## Fase C10 - Taloes, Formas e Apoio

Telas:
- `caixa/templates/caixa/taloes_list.html`
- `caixa/templates/caixa/formas_pagamento.html`
- `caixa/templates/caixa/centros_custo.html`
- `caixa/templates/caixa/categorias_financeiras.html`
- `caixa/templates/caixa/custos_fixos.html`

Tarefas:
1. revisar consistencia visual;
2. simplificar headers e acoes;
3. padronizar tabelas e formularios;
4. corrigir textos quebrados;
5. manter estas telas como apoio, nao operacao principal.

## Fase C11 - Padrao Visual e Linguagem

Escopo transversal:
1. corrigir mojibake em toda a app `caixa`;
2. padronizar termos;
3. padronizar cores por urgencia;
4. revisar cabecalhos, subtitulos e botoes;
5. revisar mensagens de sucesso, erro e alerta.

## Fase C12 - Ergonomia e Velocidade

Escopo transversal:
1. foco automatico no primeiro campo util;
2. Enter com progressao logica;
3. atalhos consistentes;
4. reduzir necessidade de scroll;
5. remover botoes duplicados ou pouco usados.

## Ordem Recomendada

1. C1 - Navegacao e Estrutura
2. C3 - Registrar Pagamento em Modo Balcao
3. C2 - Dashboard Operacional
4. C4 - Abrir Caixa
5. C5 - Fechar Caixa
6. C6 - Contas a Receber
7. C7 - Contas a Pagar
8. C11 - Padrao Visual e Linguagem
9. C12 - Ergonomia e Velocidade
10. C8, C9 e C10 - Gerencial e Apoio

## Situacao desta rodada

Nesta rodada, o foco e:

- documentar este plano;
- executar `C1 - Navegacao e Estrutura`;
- executar `C3 - Registrar Pagamento em Modo Balcao`.
