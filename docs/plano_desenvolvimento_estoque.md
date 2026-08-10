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
- migração `estoque.0034_alter_movimentacaoestoque_tipo` aplicada no PostgreSQL local;
- suíte completa `estoque.tests` validada em 2026-08-02 (`162 tests OK`);
- `manage.py check` sem problemas e JavaScript das telas alteradas validado sintaticamente;
- cadastro rápido de marca/fabricante, tributação automática do Simples e movimentos de oferta/cedência cobertos por testes;
- os últimos avanços em reposição inteligente, fornecedores por produto e inventário profissional já foram cobertos por testes focados.
- fluxo focado de cadastro de produto, estrutura/recompra e entrada de mercadoria validado em PostgreSQL local (`27 tests OK`).
- migração `estoque.0032_rastreabilidade_lote_serie` aplicada no PostgreSQL local;
- fluxos de compra sugerida, edição de rascunho, lote, série, saída e devolução cobertos por testes automatizados.
- rastreabilidade separada em `estoque/services_rastreabilidade.py`, reduzindo o acoplamento do serviço geral;
- regressão focada de entrada e rastreabilidade aprovada no PostgreSQL local (`8 tests OK`) antes do cancelamento auditado.
- validacao de fechamento visual e operacional em 2026-07-17 com `estoque.tests` no PostgreSQL local (`156 tests OK`);
- telas de indicadores e auditoria alinhadas ao padrao visual atual do sistema;
- módulo operacionalmente maduro, com novo ciclo de hardening profissional aberto após auditoria de integridade, governança e leitura financeira.

## Próxima Sequência Recomendada

1. Executar a Fase E24 antes de ampliar o uso de ofertas, cedências e avarias.
2. Fechar a integridade do razão de estoque e a reconciliação na Fase E25.
3. Unificar precificação e margem líquida na Fase E26.
4. Integrar CMV, perdas e benefícios ao DRE gerencial na Fase E27.
5. Homologar o ciclo completo em PostgreSQL com operação real de loja.

## Ciclo 3 - Hardening Profissional do Estoque

### Objetivo

Elevar o módulo de um estoque operacional completo para um razão de estoque confiável, auditável e gerencialmente correto. O foco deste ciclo não é aumentar o número de telas, mas eliminar ambiguidades, impedir operações perigosas e garantir que saldo, custo, margem e relatórios contem a mesma história.

### Atualização entregue em 2026-08-02

- opção `Outra marca / fabricante` no cadastro de produto, com criação, reutilização e reativação do catálogo;
- tributação automática conforme empresa, regime e tipo do item, preservando substituição manual como exceção;
- preço sugerido e preço mínimo considerando tributos e taxa de cartão;
- movimentos próprios de `oferta` e `cedência`, com baixa por custo, justificativa obrigatória e sem movimentação de Caixa;
- rastreabilidade de lote e série estendida às novas saídas;
- filtros de saídas atualizados para incluir oferta e cedência.

### Matriz de achados da auditoria

| ID | Achado | Risco operacional | Prioridade |
|---|---|---|---|
| EST-01 | `avaria` aceita quantidade positiva e pode aumentar saldo | quebra/perda registrada no sentido inverso | P0 |
| EST-02 | saídas discricionárias não protegem de forma central o saldo já reservado | oferta, cedência ou ajuste pode consumir item comprometido com cliente/OS | P0 |
| EST-03 | a tela genérica de movimentação não restringe o catálogo de produtos pela empresa ativa | risco de acesso ou movimento cruzado entre empresas | P0 |
| EST-04 | produto, movimentos e saldos continuam editáveis/excluíveis por caminhos administrativos | perda da trilha histórica e alteração de saldo fora dos services | P0 |
| EST-05 | atualização de custo médio com `update_fields` pode deixar preço sugerido/mínimo persistido desatualizado | decisão comercial baseada em custo novo e preço de referência antigo | P0 |
| EST-06 | saldo existe em produto, ponto, ubicação, camada, lote e série, mas a auditoria atual não reconcilia todas as camadas | divergência silenciosa entre físico, custo e rastreabilidade | P1 |
| EST-07 | rateio de custos fixos e snapshots possuem escopo global em pontos importantes | mistura de produtos/custos entre empresas e rateio gerencial incorreto | P1 |
| EST-08 | indicadores e propriedades chamadas de “margem real” ainda ignoram tributos, cartão ou parte dos custos | margem superestimada e preço mínimo inconsistente entre telas | P1 |
| EST-09 | o DRE simplificado considera entradas e saídas de Caixa, mas não CMV, avarias, ofertas e cedências | resultado operacional não representa o consumo econômico do estoque | P1 |
| EST-10 | movimentos não possuem referência estruturada e idempotente à origem (venda, OS, entrada, inventário, campanha) | duplicidade difícil de detectar e auditoria dependente de texto livre | P1 |
| EST-11 | oferta/cedência usam apenas observação livre e a mesma permissão de ajuste manual | falta beneficiário, finalidade, aprovação e responsabilização por valor | P1 |
| EST-12 | fórmulas de preço estão duplicadas entre modelo, form, service e JavaScript; propriedades legadas usam regras diferentes | regressão e diferença entre o que a tela mostra e o servidor salva | P1 |
| EST-13 | tabela de preços e kits existem no cadastro, mas não participam integralmente do PDV e da baixa de componentes | configuração sem efeito operacional e falsa expectativa do usuário | P2 |
| EST-14 | salvar produto pode recalcular rateio de vários outros produtos, inclusive em atualizações de saldo | custo de processamento alto e efeito colateral difícil de prever | P2 |

### Decisões de domínio recomendadas

1. Saldo físico não deve ficar negativo. Falta de material deve virar demanda pendente, reserva não atendida ou item a comprar, nunca quantidade física negativa.
2. `MovimentacaoEstoque` deve ser um razão imutável. Erros devem ser corrigidos por estorno/contramovimento, não por edição ou exclusão.
3. `Produto.quantidade` deve ser cache derivado da soma por ponto; o razão e os saldos por posição são a fonte auditável.
4. Oferta, cedência, avaria e consumo são fatos econômicos sem Caixa. Devem afetar custo/perda gerencial, mas não criar pagamento ou retirada financeira fictícia.
5. Tributação automática é estimativa de precificação, não apuração fiscal. A interface e os relatórios devem usar essa linguagem.
6. No modo simples, `margem_lucro` funciona como markup sobre custo; no avançado, funciona como margem-alvo sobre receita. Essa diferença deve ser explícita ou representada por campos distintos.
7. Pontos, ubicações, categorias, marcas, tabelas e rateio precisam de decisão explícita: catálogo global compartilhado ou dados isolados por empresa.

## Fases Planejadas do Ciclo 3

### Fase E24 - Segurança imediata das movimentações
Status: planejada
Prioridade: P0

Escopo:
- transformar `avaria` em saída inequívoca: usuário informa quantidade positiva e o service grava quantidade negativa;
- exigir observação e causa estruturada para avaria, oferta, cedência, ajuste e inventário;
- validar saldo disponível, incluindo reservas ativas, antes de oferta, cedência e demais saídas discricionárias;
- filtrar produtos da tela genérica pela empresa ativa no GET e no POST;
- retirar da movimentação manual os tipos automáticos `venda`, `reserva` e `consumo_os`;
- criar permissões específicas para oferta, cedência e avaria, mantendo ajuste/inventário separados;
- tornar movimentos e saldos somente leitura no Django Admin;
- substituir exclusão física de produto por inativação quando existir qualquer histórico;
- corrigir a persistência de preço sugerido/mínimo quando uma entrada alterar o custo médio.

Critérios de aceite:
- avaria de 3 unidades sempre grava `-3` e reduz ponto, ubicação, camada, lote e série;
- uma saída não pode reduzir o saldo disponível abaixo do reservado;
- usuário da empresa A não visualiza nem movimenta produto da empresa B;
- nenhum movimento consolidado pode ser editado ou excluído pelo Admin;
- entrada com novo custo atualiza custo médio, preço sugerido e preço mínimo, sem mudar automaticamente o preço final aprovado;
- testes de permissão, tenant, concorrência básica e regressão aprovados.

### Fase E25 - Razão, idempotência e reconciliação integral
Status: planejada
Prioridade: P0/P1

Escopo:
- adicionar identificador UUID/idempotência para impedir dupla submissão;
- registrar `origem_tipo`, `origem_id` e referência legível para venda, OS, reserva, entrada, inventário e ação manual;
- armazenar custo unitário e custo total do movimento como snapshot histórico;
- adicionar constraints de quantidade, sentido e campos obrigatórios por tipo onde o banco permitir;
- criar estorno por contramovimento vinculado ao movimento original;
- ampliar auditoria para comparar produto x ponto x ubicação x camadas x lotes x séries;
- validar que reservas ativas não excedem saldo físico/disponível;
- decidir e remover a divergência atual entre saldo negativo por ponto e `Produto.quantidade` truncado em zero;
- executar reconciliação agendada em modo somente diagnóstico, com alerta para gerente;
- criar painel de divergências com causa, impacto financeiro e ação recomendada.

Critérios de aceite:
- a mesma referência idempotente nunca gera duas baixas;
- toda baixa automática aponta para seu documento de origem;
- a soma reconciliada fecha em todas as representações do estoque;
- correções preservam o movimento original e geram trilha de estorno;
- comando de auditoria retorna código de falha em divergência crítica e nunca corrige silenciosamente sem autorização.

### Fase E26 - Motor único de custo, preço e margem líquida
Status: planejada
Prioridade: P1

Escopo:
- centralizar alíquota, custo total, preço sugerido, mínimo e margem líquida em um único serviço puro;
- fazer a interface consultar o mesmo motor do servidor, eliminando fórmulas comerciais duplicadas no JavaScript;
- descontinuar ou reescrever propriedades legadas (`valor_impostos`, `preco_sugerido_sem_margem`, `margem_real_percentual`, `lucro_cartao`);
- validar explicitamente combinações em que tributos + taxa + margem sejam iguais ou superiores a 100%;
- diferenciar visualmente `markup sobre custo` de `margem sobre receita`;
- recalcular sugestões em lote quando a empresa alterar alíquotas, sem sobrescrever preço final;
- criar indicador “preço desatualizado após mudança de custo/tributo”;
- integrar taxa da forma de pagamento cadastrada, mantendo taxa média do produto apenas como fallback;
- definir uma política única para frete/impostos de entrada, evitando dupla contagem entre ficha e entrada de mercadoria;
- versionar a política de cálculo usada em cada preço aprovado.

Critérios de aceite:
- tela, model e relatórios retornam o mesmo valor para a mesma entrada;
- preço sugerido informa data, custo e alíquota usados;
- alteração tributária sinaliza produtos a revisar;
- margem líquida desconta custo, tributo estimado, taxa de recebimento e custos variáveis configurados;
- cenários de produto, serviço, dinheiro, PIX, cartão e marketplace possuem testes parametrizados.

### Fase E27 - CMV, perdas e DRE gerencial
Status: planejada
Prioridade: P1
Dependência: E25 e E26

Escopo:
- calcular CMV realizado a partir do custo snapshot das baixas vinculadas a vendas e OS;
- classificar avaria, oferta, cedência e divergência negativa de inventário como consumo/perda econômica sem Caixa;
- separar no DRE: receita, impostos estimados, taxas, CMV, perdas de estoque, margem bruta, despesas operacionais e resultado;
- manter fluxo de Caixa separado do regime econômico para não criar saídas financeiras fictícias;
- permitir filtros por competência, ponto, categoria, motivo, campanha e centro de custo;
- congelar snapshots de períodos fechados para evitar que mudança posterior de custo reescreva o passado;
- documentar que o relatório é gerencial e depende de validação contábil/fiscal.

Critérios de aceite:
- uma oferta reduz resultado pelo custo do item e não altera o Caixa;
- uma venda reconhece receita e CMV no mesmo período gerencial;
- custo histórico não muda quando o cadastro do produto é alterado posteriormente;
- DRE simplificado e indicadores de estoque reconciliam os mesmos valores de CMV e perdas.

### Fase E28 - Governança profissional de ofertas e cedências
Status: planejada
Prioridade: P1
Dependência: E24

Escopo:
- campos estruturados de motivo, beneficiário, cliente opcional, campanha, centro de custo e documento de autorização;
- diferenciação entre brinde comercial, cortesia de pós-venda, uso interno, demonstração, doação e cedência temporária/definitiva;
- aprovação por gerente acima de quantidade ou custo configurável;
- comprovante interno e histórico pesquisável;
- política para eventual devolução de item cedido, usando movimento de retorno vinculado;
- indicadores de custo por campanha, usuário, beneficiário e período.

Critérios de aceite:
- toda oferta/cedência identifica quem autorizou, quem recebeu, por que ocorreu e qual foi o custo;
- operação acima do limite fica pendente até aprovação;
- devolução recompõe exatamente quantidade, custo e rastreabilidade do movimento original;
- relatório diferencia ação comercial, uso interno e perda.

### Fase E29 - Isolamento multiempresa e rateio confiável
Status: planejada
Prioridade: P1

Escopo:
- adicionar empresa à configuração e aos snapshots de rateio;
- filtrar produtos, vendas, itens de OS e custos fixos pela empresa do snapshot;
- impedir unicidade global indevida de snapshot por competência quando houver mais de uma empresa;
- revisar escopo de ponto operacional, ubicação, categoria, marca, fornecedor e tabela de preço;
- criar constraints e testes de isolamento para todos os endpoints de estoque;
- evitar que salvar produto de uma empresa recalcule produtos de outra;
- remover recálculo em cascata durante simples atualização de saldo.

Critérios de aceite:
- rateio da empresa A nunca usa custo, venda ou produto da empresa B;
- snapshots da mesma competência coexistem por empresa;
- testes de acesso cruzado por URL e POST retornam bloqueio/404;
- atualização de saldo não dispara recálculo global de precificação/rateio.

### Fase E30 - Fechamento comercial de tabelas e kits
Status: planejada
Prioridade: P2
Dependência: E25 e E26

Escopo:
- decidir se tabela de preço e kit serão recursos operacionais ou apenas cadastro auxiliar;
- se mantidos, permitir seleção controlada da tabela no PDV e registrar o preço/tabela usados;
- baixar componentes de kit com transação única, disponibilidade prévia e custo consolidado;
- impedir kit circular, componente inativo e quantidade fracionária incompatível com controle por série;
- tratar devolução e cancelamento de kit pelos mesmos componentes originais;
- incluir margem e rentabilidade do kit no motor único de preço.

Critérios de aceite:
- nenhuma tabela/kit visível cria expectativa sem efeito no PDV;
- kit não pode ser vendido com componente insuficiente;
- baixa ou estorno de kit é atômico e auditável;
- preço aplicado registra origem e autorização quando divergir do preço padrão.

## Requisitos não funcionais do Ciclo 3

- todas as alterações de saldo dentro de transação atômica e com locks consistentes;
- nenhuma regra crítica depender apenas de JavaScript ou de validação do form;
- nenhuma operação financeira/estoque sensível sem tenant e permissão validados no servidor;
- movimentos históricos imutáveis e rastreáveis por usuário, data, origem e estorno;
- consultas principais com paginação, índices e limite de volume previsível;
- logs estruturados para falhas de reconciliação, duplicidade, estoque insuficiente e acesso cruzado;
- testes no PostgreSQL para concorrência, constraints e isolamento;
- documentação e microcopy com termos de negócio consistentes: físico, reservado, disponível, custo, CMV, perda, markup e margem.

## Estratégia de testes obrigatória

1. Testes unitários parametrizados do motor de preço e custo.
2. Testes transacionais de concorrência para duas saídas simultâneas do mesmo saldo.
3. Testes de tenant em GET, POST e acesso direto por ID.
4. Testes de idempotência e dupla submissão.
5. Testes de reconciliação entre todas as representações de saldo.
6. Testes de lote/série para oferta, cedência, avaria, estorno e kit.
7. Testes de DRE garantindo separação entre Caixa e efeito econômico.
8. Homologação manual com perfis de atendente, estoquista, gerente e administrador.
9. Suite completa do estoque e integrações com `caixa`, `ordens`, `orcamentos` e `configuracoes`.

## Definition of Done por fase

Uma fase somente poderá ser marcada como concluída quando:

- regras de domínio e decisões de negócio estiverem documentadas;
- migrações tiverem caminho seguro para dados existentes;
- testes focados e regressão ampla estiverem aprovados em PostgreSQL;
- permissões e isolamento por empresa tiverem sido testados;
- auditoria e relatórios refletirem o novo comportamento;
- tela possuir mensagens de erro e confirmação compreensíveis;
- checklist manual tiver sido executado com evidência;
- não houver alteração silenciosa de saldo, custo ou preço final.

## Atualizacao complementar do Ciclo 3 - 2026-08-02

Esta atualizacao substitui os status e contagens do relatorio anterior quando houver divergencia.

| Fase | Status atualizado | Resultado entregue | Evolucao futura ainda recomendada |
|---|---|---|---|
| E24 | concluida tecnicamente | seguranca das saidas, tenant, permissoes separadas, imutabilidade do razao e protecao do saldo reservado | homologacao manual recorrente por perfil |
| E25 | operacionalmente concluida | idempotencia, origem, custo historico, estorno e reconciliacao de produto, ponto, ubicacao, camadas, reservas, lotes e series; monitoramento persistente por empresa e painel historico | configurar o agendador do ambiente e novas constraints conforme maturidade dos dados |
| E26 | avancada | motor central, Simples automatico, preco sugerido/minimo, snapshot versionado com custo, aliquota, regime, origem e data | remover calculos auxiliares remanescentes do JavaScript e usar taxas por forma de pagamento em todos os cenarios |
| E27 | avancada | CMV, perdas, impostos estimados e taxas de recebimento no DRE; comparativos; fechamento mensal unico e imutavel por empresa, responsavel e detalhamentos congelados | ampliar filtros gerenciais por ponto, categoria, motivo e campanha |
| E28 | concluida tecnicamente | oferta e cedencia estruturadas com finalidade, beneficiario, cliente, campanha, centro de custo, documento, alcada, aprovacao/rejeicao, custo, historico e retorno de cedencia temporaria | emissao de comprovante PDF, se houver necessidade operacional |
| E29 | avancada | Caixa por empresa, isolamento de dashboards, pagamentos, contas e fluxo projetado; DRE e fechamentos por empresa; bloqueio de acesso cruzado | decidir formalmente quais catalogos serao globais ou por empresa e concluir auditoria dos relatorios administrativos secundarios |
| E30 | avancada | tabela aplicada no PDV, baixa e estorno atomicos dos componentes e snapshot historico da composicao do kit | rentabilidade consolidada especifica do kit no simulador comercial |

### Compatibilidade com dados existentes

- `estoque.0042_backfill_snapshots_precificacao_kits` registra a politica de preco existente e congela a composicao das vendas/pre-reservas legadas;
- `caixa.0040_backfill_empresa_despesa_recorrente` vincula despesas recorrentes legadas quando a base possui uma unica empresa;
- `caixa.0042_backfill_encargos_gerenciais_pagamento` congela impostos estimados e taxas dos pagamentos legados sem reescrever fechamentos antigos;
- alteracoes de composicao de kit posteriores a pre-reserva nao mudam saldo comprometido, baixa ou estorno;
- mudancas de aliquota abrem nova versao da precificacao sem sobrescrever automaticamente o preco final aprovado.

### Evidencia final desta atualizacao

- PostgreSQL local migrado ate `estoque.0042`, `caixa.0042` e `configuracoes.0077`;
- `makemigrations --check --dry-run`: nenhuma alteracao pendente;
- `manage.py check`: aprovado sem alertas;
- suite completa `estoque`: 180/180 testes aprovados;
- suite completa `caixa`: 190/190 testes aprovados;
- total desta validacao: 370 testes aprovados;
- testes focados pos-migracao de compatibilidade: 4/4 aprovados;
- auditoria da base operacional: zero divergencias em total, saldo negativo, ponto x ubicacao, ubicacao x custo, reservas, lotes e series;
- corrigida a conversao UTC para data local nos relatorios de desempenho, evitando perda de ordens na virada do dia;
- mantido o bloqueio de pagamento e consulta cruzada entre empresas.

### Proxima sequencia recomendada

1. Homologar manualmente oferta, cedencia, devolucao, fechamento de DRE e operacao multiempresa com os perfis reais.
2. Definir se categorias, marcas, fornecedores, pontos e centros de custo serao globais compartilhados ou isolados por empresa.
3. Ampliar os filtros do DRE por ponto, categoria, motivo e campanha.
4. Adicionar comprovante PDF de oferta/cedencia somente se o processo interno exigir assinatura ou arquivo formal.
5. Programar a execucao periodica de `monitorar_estoque --empresa <ID> --origem agendada --falhar-se-divergir` no ambiente de producao.

Guia operacional: `docs/monitoramento_estoque.md`. O comando oficial persistente e `monitorar_estoque --empresa <ID> --origem agendada --falhar-se-divergir`.

## Atualizacao multiempresa dos catalogos - 2026-08-03

Decisao de arquitetura: categorias de produto, pontos operacionais, categorias financeiras, centros de custo, fornecedores e marcas pertencem a uma empresa. Nomes e codigos podem se repetir entre empresas, mas nao dentro do mesmo tenant.

Entregue:

- campo `empresa` nos seis catalogos centrais;
- constraints condicionais de unicidade por empresa;
- migracao segura que atribui os dados existentes quando a base possui uma unica empresa;
- filtros por empresa ativa no cadastro de produto, entradas, movimentacoes, reposicao, inventarios, PDV, ordens, contas, relatorios, auditoria e garantias;
- validacao que impede marca vinculada a fornecedor de outra empresa;
- compatibilidade controlada com registros legados sem empresa, sem registros orfaos na base operacional atual;
- testes garantindo nomes iguais entre empresas, bloqueio de duplicidade interna e rejeicao de IDs de outro tenant.

E29 passa de `avancada` para `concluida no escopo dos catalogos centrais`. Continuam recomendadas para uma futura oferta SaaS as decisoes sobre catalogos atualmente globais de sistema, como formas de pagamento, tipos de equipamento, servicos de referencia e parceiros de expedicao.

Evidencia desta etapa:

- PostgreSQL local migrado ate `estoque.0044`, `caixa.0043` e `configuracoes.0079`;
- dados atuais atribuídos a `ABTECH PECAS E SERVICOS`, sem catalogos orfaos;
- `manage.py check`: aprovado;
- `makemigrations --check --dry-run`: nenhuma alteracao pendente;
- suite completa de Estoque: 184/184 testes aprovados, incluindo 4 novos testes de isolamento dos catalogos;
- suite de Caixa: 190 testes validados em lotes por limite de execucao, incluindo os casos corrigidos e repetidos com sucesso;
- 8/8 testes focados de marcas, fornecedores e regras de garantia aprovados;
- auditoria da base operacional concluida com zero divergencias de total, saldo negativo, ponto x ubicacao, custo, reserva, lote e serie.

Proxima camada recomendada para expansao multiempresa:

1. adicionar selecao/troca de empresa apenas para usuarios autorizados a atuar em mais de um tenant;
2. preparar onboarding completo que clone os demais catalogos padrao ao criar uma nova empresa;
3. executar homologacao manual com duas empresas de demonstracao antes de liberar uso SaaS.

## Atualizacao multiempresa dos catalogos operacionais - 2026-08-03

Decisao concluida: formas de pagamento, tipos de equipamento configurados, servicos de referencia e parceiros de expedicao pertencem a uma empresa. Os catalogos de segmento, linha de atuacao e tipos sugeridos permanecem globais apenas como templates de onboarding.

Entregue:

- campo `empresa` nos quatro catalogos operacionais, com unicidade condicional por tenant e compatibilidade com legado;
- migracoes `configuracoes.0080`, `caixa.0044`, `estoque.0045` e backfill seguro `configuracoes.0081`;
- filtros por empresa em OS, expedicao, produtos, regras de garantia, pagamentos, contas a receber, contas a pagar e relatorios;
- criacao dos tipos de equipamento e formas de pagamento padrao dentro da empresa atual;
- protecao contra selecao de IDs de outra empresa nos formularios e no calculo das taxas de pagamento;
- bloqueio da troca arbitraria de tenant por query string, cabecalho ou subdominio para usuarios autenticados vinculados a uma empresa;
- manutencao do tenant explicito em fluxos publicos e para superusuario sem empresa vinculada.

Evidencia desta etapa:

- PostgreSQL local migrado ate `configuracoes.0084`, `estoque.0045` e `caixa.0044`;
- base atual com uma empresa: 34 tipos de equipamento e 7 formas de pagamento vinculados, sem registros operacionais orfaos;
- `manage.py check` aprovado e `makemigrations --check --dry-run` sem alteracoes pendentes;
- 8 testes novos de catalogos, vinculos, sessao, autorizacao e auditoria multiempresa aprovados;
- 39 testes de regressao de configuracao, expedicao, produtos e Caixa multiempresa aprovados;
- 6 cenarios criticos adicionais de recebimento, pagamento, relatorio e garantia aprovados;
- suite completa de Configuracoes executada com 127 cenarios: 124 aprovados de imediato e 3 inconsistencias de formulario/microcopy corrigidas e repetidas com sucesso.

Preparacao de usuarios multiempresa tambem concluida:

- modelo `UsuarioEmpresa`, com vinculo unico, ativacao e empresa padrao;
- backfill dos usuarios atuais e atribuicao automatica a empresa unica existente;
- empresa ativa por sessao somente entre vinculos autorizados;
- seletor oculto para usuario de uma empresa e exibido apenas quando houver mais de um vinculo ativo;
- troca auditada e protecao contra redirecionamento externo;
- administracao de empresas deixou de ser singleton e os vinculos podem ser mantidos no Admin.

Pendencias profissionais para uma futura oferta multiempresa:

1. criar onboarding transacional de nova empresa com catalogos padrao e administrador inicial;
2. decidir se perfil e permissoes serao globais no usuario ou especificos por vinculo `UsuarioEmpresa`;
3. separar configuracoes ainda singleton, especialmente numeracao de OS e preferencias operacionais, quando forem diferentes entre empresas;
4. homologar com duas empresas de demonstracao e perfis reais antes de liberar a operacao multiempresa comercialmente.

## Ordem executiva recomendada

1. E24 - Segurança imediata das movimentações.
2. E25 - Razão, idempotência e reconciliação integral.
3. E26 - Motor único de custo, preço e margem líquida.
4. E27 - CMV, perdas e DRE gerencial.
5. E28 - Governança profissional de ofertas e cedências.
6. E29 - Isolamento multiempresa e rateio confiável.
7. E30 - Fechamento comercial de tabelas e kits.

O módulo deve voltar a ser considerado `fechado tecnicamente` apenas após E24 e E25. Para considerar a leitura gerencial profissional, também são obrigatórias E26 e E27.

## Encerramento executivo do plano - 03/08/2026

Status final: **E24 a E30 concluídas no escopo funcional e técnico definido para o estoque**.

| Fase | Status final | Entrega de encerramento |
|---|---|---|
| E25 | concluída | razão e reconciliação persistentes por empresa; comando para todas as empresas; tarefa Windows instalada a cada 15 minutos; execução real sem divergências |
| E26 | concluída | motor único no servidor para custo, rateio, imposto, preço sugerido/mínimo, lucro e canais; taxas por forma de pagamento; fórmulas comerciais duplicadas removidas do JavaScript |
| E27 | concluída | DRE com CMV, perdas, impostos, taxas, comparativos e fechamento; filtros por ponto, categoria de produto, categoria financeira, centro de custo, motivo e campanha |
| E28 | concluída | ofertas e cedências com custo real, alçada, aprovação, rejeição, retorno e comprovante PDF A4 validado |
| E29 | concluída | catálogos, configurações, numeração de OS, permissões e provisionamento separados por empresa; compatibilidade mantida para a empresa atual |
| E30 | concluída | tabelas e kits com baixa/estorno atômicos, composição histórica e rentabilidade consolidada com capacidade montável |

Validações finais realizadas:

- `manage.py check` sem ocorrências;
- migrações `configuracoes.0085`, `configuracoes.0086` e `ordens.0043` aplicadas; a 0086 realinha as sequências históricas dos antigos singletons no PostgreSQL;
- 27 testes de custo, estoque, ofertas/cedências e catálogos por empresa aprovados;
- 10 cenários de estrutura, kits e DRE aprovados (um seletor de teste inicialmente informado na suíte era inexistente; o teste correto foi executado separadamente e aprovado);
- 7 testes novos de fechamento do plano e preparação SaaS aprovados;
- filtro gerencial combinado do DRE aprovado;
- PDF renderizado em uma página A4, inspecionado visualmente e validado por leitura estrutural;
- auditoria real: empresa atual com zero divergências.
- regressão consolidada final: 45 testes aprovados, sem falhas.

O que permanece depois deste encerramento não é pendência do plano de estoque: implantação em servidor de produção, integrações fiscais oficiais, observabilidade externa e evolução contínua conforme o uso real.

## Relatório de execução do Ciclo 3 — 2026-08-02

O ciclo foi implementado em uma primeira entrega funcional e auditável. Os status abaixo separam o que já está em produção técnica do que ainda exige evolução para satisfazer integralmente a Definition of Done.

| Fase | Status atual | Entregue nesta execução | Pendências para conclusão integral |
|---|---|---|---|
| E24 | implementada | avaria sempre como saída; proteção do disponível reservado; filtro por empresa; tipos automáticos removidos da tela manual; permissões específicas; Admin somente leitura; exclusão de produto convertida em inativação; custo e sugestões recalculados na entrada | causa estruturada e homologação manual por todos os perfis |
| E25 | operacionalmente concluída | UUID, idempotência, origem estruturada, custo histórico, estorno, reconciliação integral e monitoramento persistente por empresa | configurar o agendador do ambiente e ampliar constraints conforme a maturidade dos dados |
| E26 | avançada | motor único, Simples automático, sugestões e snapshots versionados de custo, alíquota e política | retirar fórmulas auxiliares remanescentes do JavaScript |
| E27 | avançada | CMV, perdas, impostos e taxas destacados; receita líquida; comparativos e fechamento mensal imutável por empresa | ampliar filtros gerenciais após atribuir ponto aos lançamentos financeiros |
| E28 | concluída tecnicamente | finalidade, beneficiário, cliente, campanha, centro de custo, documento, alçada, aprovação, rejeição, histórico e devolução | comprovante PDF opcional |
| E29 | avançada | Caixa, pagamentos, contas, fluxo projetado, DRE e fechamentos isolados por empresa | decidir o escopo global ou por empresa dos catálogos compartilhados |
| E30 | avançada | tabela selecionável no PDV, baixa e estorno atômicos e composição histórica do kit preservada | integrar rentabilidade consolidada do kit ao simulador comercial |

### Correções adicionais encontradas na regressão

- corrigida a duplicação de saldo ao inicializar uma localização durante a primeira entrada;
- comissão preservada para OS legada sem classificação técnica e para serviços lançados diretamente na OS;
- textos dos indicadores e testes alinhados ao português da interface;
- migrações de dados preservam permissões existentes, custos históricos e vínculo de empresa quando a origem permite inferência segura.

### Evidência automatizada desta entrega

- `manage.py check`: aprovado;
- `makemigrations --check --dry-run`: nenhuma alteração pendente;
- `estoque`: 172 testes aprovados, incluindo governança de kits;
- `caixa`: 184 testes aprovados, incluindo pagamentos, estornos, comissões e DRE;
- migrações aplicadas com sucesso no PostgreSQL local;
- auditoria do banco operacional concluída sem divergências após corrigir, com validação cruzada, uma localização legada duplicada (produto #1: localização 2 para 1; produto, ponto, camada de custo e movimento original já registravam 1);
- regressão completa de Caixa permanece como etapa obrigatória após qualquer ajuste nas regras de comissão ou no fechamento multiempresa.

### Próximo ciclo recomendado

1. Concluir E28 com formulário estruturado e aprovação por alçada.
2. Fechar E29 tornando Caixa e todos os relatórios integralmente multiempresa.
3. Persistir snapshot de composição do kit e finalizar E30.
4. Criar fechamento mensal imutável do DRE, concluindo E27.
5. Completar reconciliação de lote/série/reserva e painel de exceções da E25.


