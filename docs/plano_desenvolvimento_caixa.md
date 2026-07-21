# Plano de Desenvolvimento do Caixa

## Objetivo

Evoluir o app `caixa` com foco em operacao diaria, confiabilidade financeira, venda a mostrador, comissoes, recebiveis/pagaveis, garantias por marca e leitura gerencial.

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
- Garantia fabricante ainda esta mais proxima de um painel de acompanhamento do que de uma carteira financeira completa por marca, com prazo, vencimento, divergencia e aging de cobranca.

### Oportunidades de melhoria

- Extrair services transacionais para pagamento de OS, pagamento de guia/venda mostrador, baixa de contas e fechamento de caixa.
- Melhorar a UX do pagamento para deixar origem, valor, descontos, garantia, troco e acao pos-pagamento mais claros.
- Consolidar a venda a mostrador com uma leitura melhor do artigo, do cesto e da guia.
- Criar camadas de conferencia mais fortes no fechamento por forma de pagamento, divergencias e justificativas.
- Ampliar relatorios executivos com filtros salvos, exportacoes e indicadores de risco.
- Homologar por perfil: atendente, tecnico, gerente e admin.
- Estruturar contas a receber por marca, porque cada fabricante pode ter prazos, regras documentais, referencias e ritmos de pagamento diferentes apos o fechamento da OS.

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
- dashboard operacional do caixa repaginado com foco em acao imediata, riscos do dia, filas de recebimento e despesas;
- telas `abrir_caixa` e `fechar_caixa` refinadas para leitura mais direta, com cards compactos e checklist visual do turno;
- validacao automatizada concluida para dashboard operacional, abertura sugerida e conferencia de fechamento.

Proximos itens:
- validar em homologacao a experiencia completa: consulta artigo -> cesto -> guia -> pagamento;
- registrar apenas ajustes finos que surgirem em uso real, sem reabrir a fase visual inteira.

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

### Fase C8 - Garantias por marca e carteira de cobranca
Status: concluida tecnicamente
Prioridade: alta

Objetivo:
- transformar garantia fabricante em carteira financeira real de contas a receber por marca;
- respeitar prazos de pagamento diferentes por fabricante apos o fechamento da OS;
- melhorar previsao de caixa, cobranca e leitura de divergencias.

Motivacao operacional:
- uma mesma garantia nao deve entrar apenas como "garantia fabricante" generica;
- cada marca pode pagar em prazos diferentes, com referencia propria, documentos exigidos e glosas;
- o financeiro precisa enxergar o que esta previsto, faturado, vencido e recebido por marca.

Escopo funcional previsto:
- vincular cada conta a receber de garantia a:
  - marca;
  - fornecedor/entidade pagadora;
  - regra de garantia aplicada;
  - OS de origem;
  - data base de cobranca;
  - prazo de pagamento em dias;
  - vencimento calculado;
  - valor previsto;
  - valor aprovado/aceito;
  - valor recebido;
  - status da cobranca;
  - referencia/documento de faturamento.
- permitir que a regra da marca defina o prazo padrao de recebimento;
- gerar conta a receber automaticamente quando a OS atingir o ponto faturavel da garantia;
- separar claramente:
  - previsto;
  - faturavel;
  - enviado/faturado;
  - aguardando pagamento;
  - pago;
  - divergente/glosado;
  - cancelado.

Telas e leituras desejadas:
- painel "Garantias por marca" com:
  - total previsto;
  - total vencido;
  - total recebido;
  - valor em divergencia;
  - aging por marca;
  - prazo medio contratado x prazo medio real.
- filtro por:
  - marca;
  - fornecedor;
  - competencia;
  - status;
  - vencimento;
  - OS;
  - referencia de faturamento.
- atalhos diarios:
  - vence hoje;
  - vencidas;
  - divergentes;
  - aguardando envio;
  - aguardando comprovacao.

Impactos tecnicos esperados:
- `caixa.models.ContaReceber`:
  - ganhar campos especificos de marca/fornecedor/regra quando `tipo_origem = garantia_fabricante`;
  - ou receber relacionamento complementar dedicado para nao poluir os demais tipos.
- `caixa.models.AuditoriaGarantia`:
  - deixar de ser apenas painel paralelo e passar a conversar diretamente com a conta a receber gerada;
  - manter historico de status, referencia e observacoes de divergencia.
- `configuracoes`:
  - permitir parametrizar prazo padrao por marca/regra;
  - evoluir cadastro de marcas/fornecedores para incluir procedimento de cobranca e documentos exigidos.
- `relatorios`:
  - incluir aging por marca;
  - atraso medio por marca;
  - valor glosado/divergente;
  - previsao de recebimento por semana/mes.

Regras de negocio sugeridas:
- a conta a receber de garantia nasce quando a OS estiver fechada no ponto definido pela politica comercial;
- o vencimento deve usar a regra da marca e nao um prazo fixo global;
- divergencia entre valor previsto e valor pago nao deve baixar a conta silenciosamente;
- recebimento parcial deve manter a conta em aberto com status apropriado;
- uma marca pode ter multiplas regras por tipo de produto/linha, mas a cobranca final deve apontar para uma unica referencia de regra aplicada.

Entregas planejadas:
- C8.1: modelagem de prazo e cobranca por marca/regra;
- C8.2: geracao automatica de conta a receber de garantia com vencimento calculado;
- C8.3: painel de garantias por marca com aging e prioridades;
- C8.4: fluxo de divergencia/glosa e recebimento parcial;
- C8.5: relatorios gerenciais por marca, fornecedor e atraso real.

Feito nesta etapa:
- `ContaReceber` passou a registrar fornecedor, marca, regra, valor aprovado, base de cobranca, prazo e referencia da garantia;
- `AuditoriaGarantia` passou a se vincular diretamente a conta a receber, com valor aprovado/recebido e vencimento previsto;
- sincronizacao de garantias fechadas agora gera/atualiza vencimento por regra da marca;
- painel de garantias ganhou filtros por marca e prioridade, com leitura de previsto, aprovado, recebido, vencidas e divergencias;
- `Contas a receber` passou a filtrar e listar garantias por marca/fornecedor, com exportacao enriquecida;
- detalhe da conta exibe bloco proprio de carteira de garantia;
- edicao manual de conta de garantia foi redirecionada para o painel correto, evitando inconsistencias;
- `aging` e dashboard financeiro passaram a destacar marcas com garantias em atraso.
- limpeza de encoding concluida nas telas principais desta frente (`garantias_fabricante` e `dashboard_caixa`);
- testes focados aprovados para conta, painel, filtros, detalhe, dashboard e aging da carteira de garantia.

Validacao manual recomendada:
- sincronizar uma OS de garantia fabricante real e conferir marca, fornecedor, regra, prazo e vencimento;
- marcar uma garantia como `enviado` e depois `pago`, confirmando a baixa parcial/total esperada;
- filtrar `Contas a receber` por marca e fornecedor, validando exportacao CSV;
- abrir o dashboard financeiro e confirmar leitura das marcas em atraso e dos totais de garantia.

## Fechamento do ciclo Caixa

Status geral: concluido para o ciclo original C1-C7, com expansao planejada em C8 para garantias por marca e carteira de cobranca.

Resumo:
- fases C1 a C7 registradas como concluidas;
- fluxos principais estabilizados: caixa diario, recebiveis, pagaveis, comissoes e venda a mostrador;
- documentacao do plano atualizada para continuidade de melhorias incrementais fora deste ciclo;
- proxima frente estruturante recomendada: garantias por marca com contas a receber, aging e divergencias.
