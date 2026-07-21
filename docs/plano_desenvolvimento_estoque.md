# Plano de Desenvolvimento do Estoque

## Objetivo

Evoluir o app `estoque` para um padrão mais próximo de ERP operacional, mantendo uso simples no dia a dia da loja e reforçando confiabilidade de saldos, custos, inventários e integrações com OS, caixa e reservas.

## Princípios

- preservar fluxos que já funcionam antes de ampliar escopo;
- tratar estoque físico como estrutura obrigatória (`ponto operacional + ubicação`);
- manter regras críticas em services transacionais;
- separar claramente produto físico, peça, consumível e serviço;
- documentar o estado real do módulo ao fim de cada ciclo.

## Estado Atual do Módulo

O app já cobre:

- cadastro de produtos com modo simples e avançado;
- categorias, pontos operacionais e ubicações;
- saldo por ponto e por ubicação;
- movimentações operacionais guiadas;
- reservas, pré-reservas e integração com PDV/caixa;
- consulta de artigos com foco operacional;
- inventário operacional digital;
- auditoria e indicadores básicos;
- política oficial de custo `PMP` e `PEPS`;
- entrada de mercadoria, fornecedores por produto e reposição inteligente.

## Fases Concluídas

### Fase E1 - Estabilidade textual e refinamento visual
Status: concluída

Entregue:
- correções de encoding e limpeza de textos principais;
- refinamento visual das telas operacionais mais usadas;
- documentação inicial do roadmap do módulo.

### Fase E2 - Regras críticas em services
Status: concluída

Entregue:
- centralização de regras sensíveis em `services`;
- movimentação, reserva, inventário e PDV reaproveitando trilha transacional;
- views mais finas e menos acopladas à regra de saldo.

### Fase E3 - Clarificação do domínio de produto
Status: concluída

Entregue:
- `tipo_item` como base principal do domínio;
- distinção melhor entre serviço e item físico;
- compatibilidade preservada com legado de `is_servico`.

### Fase E4 - Permissões granulares do estoque
Status: concluída

Entregue:
- permissões específicas para cadastro, exclusão, ajuste, transferência, inventário e reservas;
- proteção de endpoints críticos;
- semeadura de compatibilidade para usuários já existentes.

### Fase E5 - Performance e escala
Status: concluída

Entregue:
- otimizações em listas, APIs e indicadores;
- uso maior de agregações em banco;
- índices para consultas frequentes.

### Fase E6 - Auditoria operacional do estoque
Status: concluída

Entregue:
- trilha `EstoqueEvento` consolidada;
- página de auditoria operacional com filtros;
- melhor rastreabilidade por usuário, produto, ponto e inventário.

### Fase E7 - Homologação e consolidação inicial
Status: concluída

Entregue:
- checklist operacional do estoque;
- homologação automatizada em PostgreSQL;
- cobertura de testes principal validada.

### Fase E8 - Estrutura física obrigatória
Status: concluída

Entregue:
- `ponto_operacional` e `ubicacao_padrao` como estrutura oficial do item físico;
- abandono operacional do campo livre `localizacao`;
- reflexo da estrutura física em cadastro, consulta e reserva.

### Fase E9 - Política de custo oficial
Status: concluída

Entregue:
- suporte oficial a `PMP` e `PEPS`;
- alinhamento da política de custo com entradas, saídas, reservas e consumo em OS.

### Fase E10 - Camadas de custo e entrada
Status: concluída

Entregue:
- camadas de custo por entrada;
- base para consumo conforme política `PMP`/`PEPS`;
- trilha compatível com saldos legados.

### Fase E11 - Inventário operacional digital
Status: concluída

Entregue:
- inventário com número próprio, escopo, snapshots e status operacionais;
- fluxo digital de geração, conferência e finalização;
- resumo com divergências e impacto operacional.

### Fase E12 - Confiabilidade de estrutura física
Status: concluída

Entregue:
- semeadura automática da estrutura mínima;
- proteção contra base nova sem `PO` e ubicação coerentes;
- reaproveitamento da mesma garantia no setup e no cadastro.

### Fase E13 - Reservas amarradas à posição e custo
Status: concluída

Entregue:
- reservas vinculadas a ponto e ubicação;
- leitura mais fiel do saldo disponível real;
- tela operacional de reservas com foco em vencimento e pendências.

### Fase E14 - Inventário por ponto e ubicação
Status: concluída

Entregue:
- inventário por ponto inteiro ou ubicação específica;
- divergência com causa operacional;
- impacto financeiro refletido nos indicadores.

### Fase E15 - Indicadores operacionais e financeiros
Status: concluída

Entregue:
- ruptura por ponto;
- valor de estoque por ponto e categoria;
- KPI de itens sem estrutura válida;
- impacto de avarias e divergências recentes.

### Fase E16 - Regras de proteção operacional
Status: concluída

Entregue:
- bloqueios contra inconsistências previsíveis;
- reforço de mensagens operacionais e regras mínimas de segurança do estoque.

## Ciclo 2 - Evolução estilo ERP

### Contexto

A partir daqui o módulo deixa de ser apenas cadastro e saldo. O foco passa a ser operação de compra, precificação, reposição, inventário auditável e leitura gerencial.

### Onde os impostos entram

Os impostos afetam o estoque em dois momentos:

- compra/entrada:
  - imposto que compõe custo deve entrar no custo real da mercadoria;
  - imposto recuperável não deve inflar `PMP` nem custo de reposição.
- venda:
  - influencia formação de preço, margem líquida e preço sugerido.

O sistema hoje já separa parte relevante disso na ficha do produto, mas ainda pode evoluir para deixar a distinção ainda mais evidente na operação.

## Fases Concluídas no Ciclo 2

### Fase E17 - Entrada de mercadoria profissional
Status: concluída em 2026-07-10
Prioridade: alta

Objetivo:
- formalizar o recebimento de mercadoria fora da movimentação manual.

Já entregue:
- `EntradaMercadoria` com cabeçalho, itens, recebimento e movimentação automática;
- telas para listar, criar, detalhar e receber entradas;
- rateio automático do cabeçalho quando o usuário não distribui os custos manualmente por item;
- testes automatizados cobrindo criação e recebimento em PostgreSQL.

Fechamento entregue:
- orientação explícita de imposto recuperável x imposto que compõe custo;
- edição integral enquanto a entrada estiver em rascunho;
- cancelamento auditado de rascunho, sem movimentar o saldo;
- política de consolidação: entrada recebida fica imutável e diferenças posteriores são corrigidas por inventário ou movimentação auditada;
- testes cobrindo criação, edição, cancelamento, recebimento e proteção da entrada consolidada.

### Fase E18 - Precificação 2.0
Status: concluída
Prioridade: alta

Objetivo:
- separar custo de compra, custo de venda e preço alvo.

Já entregue:
- aba de precificação reorganizada por blocos operacionais;
- resumo compacto com método de custo ativo e última compra;
- histórico curto de compras recentes na ficha do produto;
- esclarecimento visual de tributos de venda.
- presets operacionais de precificação para balcão, reposição/atacado, marketplace e serviço simples.
- simulador por canal com lucro, margem, valor recebido e preço mínimo estimado por forma de pagamento.
- contraste mais claro entre modo rápido e avançado no cadastro, com resumo guiado por uso operacional.
- ocultação da aba avançada de observações quando o usuário estiver no fluxo rápido, reduzindo ruído no primeiro cadastro.
- simulador comercial com desconto e comparação entre dinheiro, PIX, cartão e marketplace sem alterar o preço salvo.

### Fase E19 - Fornecedor por produto e histórico de compra
Status: concluída
Prioridade: média/alta

Objetivo:
- melhorar recompra, custo de referência e comparação de fornecedor.

Já entregue:
- múltiplos fornecedores relacionados por produto;
- fornecedor preferencial, código do fornecedor, custo de referência e prazo médio;
- comparativo visual de fornecedores com melhor custo, preferencial e diferença versus última compra;
- base pronta para evoluir comparações de recompra.
- quadro de recompra com fornecedor sugerido, economia potencial e variação versus última compra.
- atalho para abrir entrada de mercadoria já pré-preenchida a partir da estrutura do produto.
- leitura comercial por fornecedor indicando compra, negociação ou revisão de cadastro.

### Fase E20 - Reposição e compras sugeridas
Status: concluída
Prioridade: alta

Objetivo:
- transformar alertas em lista prática de ação.

Já entregue:
- reposição inteligente usando estoque mínimo e reservas ativas;
- demanda por giro real de 30 dias com janela curta de reposição;
- leitura de demanda por peças de OS pendentes sem duplicar reservas já abertas;
- leitura de faltante de compra;
- fornecedor preferencial, prazo e custo estimado por item;
- mapa consolidado por fornecedor;
- exportação CSV para cotação/compra.
- geração de entrada de mercadoria em rascunho por fornecedor, com produtos, quantidades, destino e custos sugeridos;
- revisão obrigatória do rascunho antes do recebimento e alteração do saldo.

### Fase E21 - Inventário profissional
Status: concluída
Prioridade: média/alta

Objetivo:
- tornar a conferência mais auditável e menos sujeita a viés.

Já entregue:
- contagem cega opcional;
- aprovação manual de divergências antes do fechamento;
- dupla conferência com recontagem registrada por usuário;
- filtros e resumo por divergências aprovadas x pendentes;
- paginação da área de inventários.

### Fase E22 - Lote e série opcional
Status: concluída
Prioridade: média

Objetivo:
- dar rastreabilidade a itens de maior risco ou maior valor.

Entregue:
- ativação opcional por produto, sem aumentar o preenchimento dos itens comuns;
- lote, validade e números de série informados na entrada de mercadoria;
- validação de uma série única por unidade e bloqueio de recebimento incompleto;
- saldo por lote e disponibilidade por número de série;
- consumo automático dos lotes mais antigos e das séries disponíveis em venda e consumo de OS;
- movimentação da rastreabilidade nas transferências e recomposição nas devoluções;
- consulta operacional de lotes e séries na estrutura do produto;
- edição controlada de entradas enquanto ainda estiverem em rascunho.

### Fase E23 - Indicadores gerenciais do estoque
Status: concluída
Prioridade: média

Objetivo:
- oferecer leitura gerencial além da operação do balcão.

Escopo:
- giro por período;
- cobertura em dias;
- estoque parado;
- margem real;
- ruptura prevista;
- curva ABC.

Já entregue:
- giro por período com leitura de cobertura em dias;
- KPI de estoque parado em 90 dias;
- curva ABC por valor em custo;
- ruptura prevista por cobertura x prazo do fornecedor preferencial;
- leitura de pressão de margem por item e margem bruta estimada do estoque.

## Validação Técnica Mais Recente

- `manage_local.ps1 migrate estoque` executado com sucesso no PostgreSQL local;
- suíte completa `estoque.tests` validada no PostgreSQL local (`135 tests OK`);
- os últimos avanços em reposição inteligente, fornecedores por produto e inventário profissional já foram cobertos por testes focados.
- fluxo focado de cadastro de produto, estrutura/recompra e entrada de mercadoria validado em PostgreSQL local (`27 tests OK`).
- migração `estoque.0032_rastreabilidade_lote_serie` aplicada no PostgreSQL local;
- fluxos de compra sugerida, edição de rascunho, lote, série, saída e devolução cobertos por testes automatizados.
- rastreabilidade separada em `estoque/services_rastreabilidade.py`, reduzindo o acoplamento do serviço geral;
- regressão focada de entrada e rastreabilidade aprovada no PostgreSQL local (`8 tests OK`) antes do cancelamento auditado.
- validacao de fechamento visual e operacional em 2026-07-17 com `estoque.tests` no PostgreSQL local (`156 tests OK`);
- telas de indicadores e auditoria alinhadas ao padrao visual atual do sistema;
- modulo tratado como `fechado tecnicamente`, restando homologacao manual em loja com dados e rotina reais.

## Próxima Sequência Recomendada

1. Homologar manualmente o recebimento de uma compra real com e sem rastreabilidade.
2. Confirmar na operação que diferenças de entrada consolidada serão tratadas por inventário ou movimentação auditada.
3. Executar o checklist final de uso local antes de cadastrar dados reais.


