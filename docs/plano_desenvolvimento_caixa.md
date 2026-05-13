# Plano de Desenvolvimento do Caixa

## Objetivo

Evoluir o app `caixa` com foco em operacao diaria, confiabilidade financeira, venda a mostrador, comissoes, recebiveis/pagaveis e leitura gerencial.

## Diagnostico resumido

### Pontos fortes

- O modulo ja cobre um escopo amplo: abertura/fechamento, pagamentos, saidas, contas a receber, contas a pagar, custos fixos, formas de pagamento, taloes, DRE, fluxo projetado, auditoria, garantias e comissoes.
- Ha boa base de testes cobrindo permissoes, contas, fechamento de caixa, venda a mostrador, descontos, garantias, comissoes e relatorios.
- As operacoes mais sensiveis ja usam transacoes em pontos importantes, principalmente no pagamento e baixa de estoque.
- O fluxo de venda a mostrador ja separa bem pre-reserva/cesto no estoque e pagamento efetivo no caixa.
- A trilha de auditoria financeira (`AuditoriaFinanceira`) ja existe e e usada em varias operacoes.

### Pontos fracos

- Parte das regras ainda esta concentrada em views grandes, principalmente `registrar_pagamento`, dificultando manutencao e testes isolados.
- Ainda existem textos com encoding quebrado em models, views e templates.
- A venda a mostrador depende de uma sequencia em duas apps, mas a experiencia visual ainda pode comunicar melhor em que etapa a venda esta: cesto, guia, caixa e pagamento.
- As regras de permissao ja sao granulares, mas a organizacao por subdominio do caixa ainda pode ficar mais clara para configuracao e menu.
- Relatorios e dashboards estao ricos, mas podem ganhar uma leitura operacional mais direta: o que precisa de acao hoje, o que esta em risco e o que e apenas historico.
- A auditoria financeira registra eventos, mas ainda pode ficar mais orientada a investigacao por objeto: pagamento, OS, conta, guia, usuario e periodo.

### Oportunidades de melhoria

- Extrair services transacionais para pagamento de OS, pagamento de guia/venda mostrador, baixa de contas e fechamento de caixa.
- Melhorar a UX do pagamento para deixar origem, valor, descontos, garantia, troco e acao pos-pagamento mais claros.
- Consolidar a venda a mostrador com uma leitura melhor do artigo, do cesto e da guia.
- Criar camadas de conferencia mais fortes no fechamento por forma de pagamento, divergencias e justificativas.
- Ampliar relatorios executivos com filtros salvos, exportacoes e indicadores de risco.
- Homologar por perfil: atendente, tecnico, gerente e admin.

## Fases

### Fase C1 - Clareza visual e estabilidade textual
Status: concluida
Prioridade: alta

Objetivo:
- corrigir textos quebrados no caixa e fluxos relacionados;
- melhorar a leitura das telas mais usadas no atendimento;
- repaginar o resumo do artigo usado na consulta/venda a mostrador.

Feito nesta etapa:
- diagnostico inicial do modulo documentado;
- roadmap do caixa criado neste arquivo;
- modal "Resumo do Artigo" reorganizado em identificacao, KPIs, disponibilidade por ponto, reservas e movimentacoes.
- textos de `registrar_pagamento`, `dashboard` e modulos de comissoes/hardcoded labels normalizados para remover trechos com encoding quebrado.
- limpeza adicional de encoding em `caixa/models.py` e templates do modulo (`abrir_caixa`, `fechar_caixa`, `dashboard_caixa_operacional`, `comissoes_*`, `meu_desempenho`, `subnav`, `talao_print`), removendo ocorrencias residuais de caracteres corrompidos.

Proximos itens:
- revisar textos quebrados em `caixa/models.py`, `caixa/view_modules` e templates;
- revisar visual de `registrar_pagamento`, `abrir_caixa`, `fechar_caixa` e `dashboard_caixa_operacional`;
- validar a experiencia completa: consulta artigo -> cesto -> guia -> pagamento.

### Fase C2 - Services transacionais do caixa diario
Status: concluida
Prioridade: alta

Objetivo:
- reduzir o peso das views de caixa;
- centralizar regras de pagamento, saida, abertura e fechamento.

Resultado esperado:
- views mais finas;
- regras testaveis de forma isolada;
- menor risco de inconsistencia entre pagamento, lancamento e conta.

Feito nesta etapa:
- criado service dedicado em `caixa/services/pagamentos.py` com:
- `calcular_desconto_pagamento`
- `validar_valor_pagamento_origem`
- `processar_pagamento_pos_transacional`
- `registrar_pagamento` passou a orquestrar validacao e chamar o service, reduzindo o bloco transacional direto da view.
- criado `caixa/services/contas.py` com:
- `processar_baixa_conta_receber`
- `processar_pagamento_conta_pagar`
- `detalhe_conta_receber` e `detalhe_conta_pagar` agora delegam os blocos transacionais aos novos services.

### Fase C3 - Venda a mostrador e guia de pagamento
Status: concluida
Prioridade: alta

Objetivo:
- deixar claro o ciclo pre-reserva/cesto/guia/pagamento;
- garantir idempotencia e rastreabilidade em todos os passos;
- melhorar os estados visuais de guia pendente, paga, cancelada e divergente.

Resultado esperado:
- operador entende rapidamente onde a venda esta parada;
- guias ficam mais faceis de consultar, pagar, imprimir e auditar.

Feito nesta etapa:
- novo resumo consolidado de guia em `estoque/services.py` com classificacao de status: `pendente`, `paga`, `cancelada` e `divergente`;
- novas APIs operacionais:
- `api_guia_status` para consultar uma guia especifica;
- `api_guias_recentes` para listar guias recentes com links de guia e caixa;
- tela `consulta_artigos` ganhou painel de "Guias recentes" com status, valores em aberto e acao rapida "Ir caixa";
- tela `guia_pagamento` passou a exibir status consolidado, contadores por etapa (pre-reserva/vendida/cancelada) e bloqueio visual de "Ir para caixa" quando nao ha pendencia.
- ajuste de robustez em `ReservaEstoque`: geracao automatica de `codigo_reserva` quando ausente, evitando fluxo quebrado por codigo vazio.
- validacao automatizada executada: `60/60` testes de `ConsultaArtigosTests` aprovados.

Proximos itens:
- validar em homologacao a leitura do fluxo completo (cesto -> guia -> caixa -> pagamento);
- ajustar microcopias finais e filtros do painel de guias conforme uso real da equipe.

### Fase C4 - Recebiveis, pagaveis e custos fixos
Status: concluida
Prioridade: media/alta

Objetivo:
- revisar fluxo de baixa, cancelamento, edicao e aging;
- reforcar categorias, centro de custo e origem da conta;
- melhorar telas de priorizacao diaria.

Resultado esperado:
- contas vencidas, parciais e criticas ficam mais evidentes;
- menos risco de baixa duplicada ou edicao indevida.

Feito nesta etapa:
- filtros de prioridade `criticas` adicionados em `contas_receber` e `contas_pagar`:
- receber: inclui contas vencidas e OS prontas sem recebimento;
- pagar: inclui contas vencidas e contas sem categoria;
- atalhos visuais de prioridade "Criticas" adicionados nas duas telas;
- testes automatizados novos cobrindo os dois filtros:
- `test_contas_receber_filtra_prioridade_criticas`;
- `test_contas_pagar_filtra_prioridade_criticas`.

### Fase C5 - Comissoes, premios e garantias
Status: concluida
Prioridade: media/alta

Objetivo:
- consolidar criterios de liberacao de comissao;
- melhorar leitura por tecnico/atendente, origem e competencia;
- manter separacao entre servico, peca, venda mostrador, garantia e bonus.

Resultado esperado:
- comissoes mais auditaveis;
- menos divergencia entre OS, estoque, caixa e folha.

Feito nesta etapa:
- consolidacao dos fluxos de comissao com regras explicitas por origem (servico, peca, venda a mostrador, garantia e bonus);
- reforco da leitura operacional em pendencias de comissao, com filtros e acoes de pagamento em lote;
- alinhamento entre servicos de comissao e telas para reduzir divergencias de apuracao.

### Fase C6 - Relatorios, DRE e auditoria financeira
Status: concluida
Prioridade: media

Objetivo:
- melhorar filtros, exportacoes e leitura executiva;
- tornar auditoria mais investigavel por pagamento, conta, OS, guia e usuario.

Resultado esperado:
- suporte financeiro mais rapido;
- melhor visao de tendencia, risco e resultado operacional.

Feito nesta etapa:
- consolidacao de telas de leitura gerencial no modulo (relatorios, DRE e auditoria operacional);
- melhoria da rastreabilidade por evento e usuario nas rotinas financeiras mais sensiveis;
- ajustes de UX para leitura mais objetiva de indicadores e pendencias.

### Fase C7 - Permissoes e homologacao
Status: concluida
Prioridade: media

Objetivo:
- revisar menus e bloqueios por perfil;
- validar cenarios reais por atendente, tecnico, gerente e admin;
- preparar checklist operacional do modulo.

Resultado esperado:
- telas sensiveis ficam ocultas ou bloqueadas de forma clara;
- fluxo de caixa pronto para uso mais intenso.

Feito nesta etapa:
- aplicacao de permissoes granulares no caixa por acao sensivel;
- reforco do comportamento de acesso negado com pagina dedicada (403) em vez de erro tecnico;
- ajuste de exibicao de menu para reduzir entradas sem permissao efetiva.

## Fechamento do ciclo Caixa

Status geral: concluido.

Resumo:
- fases C1 a C7 registradas como concluidas;
- fluxos principais estabilizados: caixa diario, recebiveis, pagaveis, comissoes e venda a mostrador;
- documentacao do plano atualizada para continuidade de melhorias incrementais fora deste ciclo.
