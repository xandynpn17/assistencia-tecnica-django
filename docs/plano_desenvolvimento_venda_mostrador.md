# Plano de Desenvolvimento da Venda a Mostrador

## Objetivo

Evoluir a venda a mostrador para um fluxo de balcao mais rapido, mais claro e menos sujeito a erro humano, sem perder a rastreabilidade entre estoque, guia, caixa, comissao e auditoria.

Este plano nao substitui os planos do `caixa` e do `estoque`.
Ele recorta apenas o subdominio de venda a mostrador para facilitar a priorizacao operacional.

---

## Diagnostico Atual

### O que ja esta bom

- a separacao entre consulta, cesto, guia e pagamento esta correta;
- a pre-reserva antes da baixa definitiva protege o estoque;
- a venda so baixa fisicamente no pagamento, o que reduz inconsistencias;
- o fluxo ja conversa com comissao, guia de pagamento e trilha de auditoria;
- existe boa cobertura de testes de backend para pre-reserva, guia, cancelamento e venda finalizada.

### Onde ainda esta abaixo do ideal

- a experiencia ainda parece "estoque + caixa" em vez de um PDV unico de balcao;
- o operador precisa entender etapas demais para concluir uma venda simples;
- o numero do vendedor digitado manualmente aumenta risco operacional;
- a regra de pontos permitidos esta fixa no codigo;
- o caixa mostra muita informacao de OS junto do fluxo de mostrador;
- faltam cestos em aberto mais visiveis e faceis de retomar;
- a venda pode ficar sem identificacao minima do cliente, dificultando pos-venda, devolucao e garantia;
- ainda falta leitura gerencial propria para abandono, divergencia e performance do balcao.

### Principios desta fase

- preservar o que ja esta estavel no backend;
- melhorar primeiro a operacao do atendente;
- manter rastreabilidade total de cesto, guia, pagamento e estorno;
- evitar criar atalhos que fragilizem estoque ou caixa;
- deixar o fluxo pronto para uso local em loja antes de sofisticar integracoes futuras.

---

## Metas Operacionais

Ao final deste plano, a venda a mostrador deve permitir:

1. buscar um artigo e entender rapidamente disponibilidade, preco e ponto;
2. montar o cesto com menos cliques e menos campos manuais;
3. retomar cestos em aberto sem confusao;
4. gerar guia e receber no caixa com clareza total do estado da venda;
5. registrar quem vendeu, para quem foi vendido e como foi pago;
6. investigar facilmente divergencias, cancelamentos, abandono e estornos.

---

## Fase VM1 - Fluxo unificado de balcao

Status: concluida  
Prioridade: critica

### Objetivo

Fazer a venda a mostrador parecer um unico fluxo continuo, mesmo continuando tecnicamente integrada entre estoque e caixa.

### Escopo

- reorganizar a tela de consulta para destacar as etapas:
  - `1. buscar artigo`
  - `2. montar cesto`
  - `3. revisar guia`
  - `4. receber no caixa`
- reduzir textos longos e blocos concorrentes na mesma dobra;
- reforcar visualmente o estado atual da operacao;
- deixar o caminho de "proximo passo" sempre explicito.

### Resultado esperado

- operador entende em segundos onde esta no fluxo;
- menos treinamento verbal para vender no balcao;
- menor risco de o usuario se perder entre guia e caixa.

### Avanco atual

- etapas `1-4` destacadas visualmente na tela principal;
- painel de "proximo passo" guiando o atendente;
- guia e caixa com copy mais alinhada ao fluxo de balcao;
- painel de cestos em aberto integrado na mesma tela para retomada rapida.
- resumo operacional vivo com artigo em foco, vendedor ativo, guia atual e estado do caixa;
- fechamento da venda orientado pelo proprio ecrã, sem depender de memoria do operador.

---

## Fase VM2 - Vendedor e identidade da venda

Status: concluida  
Prioridade: alta

### Objetivo

Reduzir erro humano na atribuicao da venda e melhorar a base para comissao e auditoria.

### Escopo

- preencher vendedor automaticamente a partir do usuario logado quando houver numero de vendedor;
- permitir troca manual apenas para perfis autorizados;
- mostrar vendedor atual de forma clara no cesto e na guia;
- registrar no log quando houver troca manual de vendedor;
- revisar consistencia entre `usuario`, `numero_vendedor` e leitura de comissao.

### Resultado esperado

- menos erro de digitacao;
- menos comissao atribuida ao colaborador errado;
- investigacao mais clara de quem operou a venda.

### Avanco atual

- vendedor padrao sugerido automaticamente quando o usuario logado possui numero de vendedor;
- linguagem da interface ajustada para "vendedor responsavel";
- cestos em aberto agora exibem vendedor e operador para dar contexto na retomada.
- operacao comum com numero de vendedor proprio passou a bloquear troca manual indevida;
- perfis de gestao podem trocar o vendedor com trilha operacional registrada.

---

## Fase VM3 - Cestos em aberto e retomada rapida

Status: concluida  
Prioridade: alta

### Objetivo

Transformar o cesto em uma entidade operacional visivel, e nao apenas um codigo interno.

### Escopo

- criar painel/lista de cestos em aberto;
- exibir:
  - codigo do cesto;
  - operador;
  - vendedor;
  - valor total;
  - quantidade de itens;
  - horario de criacao;
  - ultimo movimento;
  - tempo parado;
- permitir retomar, cancelar ou concluir um cesto;
- destacar cestos antigos, abandonados ou com risco de divergencia.

### Resultado esperado

- menos perda de venda por cesto esquecido;
- melhor visibilidade da operacao do balcao;
- limpeza operacional mais simples ao longo do dia.

### Avanco atual

- painel de cestos em aberto incorporado ao fluxo principal;
- retomada rapida por codigo e por lista;
- leitura de operador, vendedor, total, itens e tempo parado no mesmo ecra.

---

## Fase VM4 - Caixa dedicado para guia/venda mostrador

Status: concluida  
Prioridade: alta

### Objetivo

Separar melhor o fluxo de recebimento de OS do fluxo de recebimento de guia, mesmo reaproveitando o mesmo backend financeiro.

### Escopo

- simplificar o modo `guia/venda mostrador` dentro de `registrar_pagamento`;
- mostrar no resumo lateral apenas o que faz sentido para mostrador:
  - guia;
  - itens;
  - total;
  - valor em aberto;
  - status da guia;
  - operador/vendedor;
- esconder informacao tecnica de OS quando a origem for guia;
- reforcar estado de pagamento pendente, parcial, quitado ou divergente.

### Resultado esperado

- caixa mais rapido no balcao;
- menos poluicao visual;
- menos risco de confundir recebimento de OS com venda de pecas.

### Avanco atual

- tela de recebimento da guia agora usa resumo lateral proprio de balcao;
- card superior consolidando guia, total, pontos, operador e vendedor;
- textos e atalhos de valor adaptados ao fluxo de guia em vez de OS.

---

## Fase VM5 - Identificacao opcional do cliente do balcao

Status: concluida  
Prioridade: media/alta

### Objetivo

Permitir identificar o comprador quando fizer sentido, sem travar venda rapida simples.

### Escopo

- incluir captura opcional de:
  - nome;
  - telefone/celular;
  - CPF/CNPJ;
- permitir venda anonima quando a operacao nao exigir identificacao;
- usar esses dados em:
  - garantia de peca;
  - devolucao;
  - consulta futura;
  - contato pos-venda.

### Resultado esperado

- melhor suporte ao cliente;
- melhor rastreabilidade em trocas e garantias;
- sem sacrificar velocidade em venda simples.

### Avanco atual

- pagamento da guia passou a aceitar identificacao opcional do comprador;
- nome, documento e telefone/WhatsApp ficam gravados no pagamento;
- a 2a via do talao passou a exibir esses dados quando informados;
- o fluxo continua permitindo venda rapida sem identificacao obrigatoria.

---

## Fase VM6 - Politica configuravel de pontos e operacao

Status: concluida  
Prioridade: media/alta

### Objetivo

Remover regras engessadas de codigo e trazer a operacao de mostrador para configuracao.

### Escopo

- substituir a regra fixa de `PO2` e `PO3` por parametrizacao;
- permitir marcar pontos habilitados para venda mostrador;
- definir ponto padrao por operador ou por terminal, quando fizer sentido;
- validar se o ponto exige estoque positivo, conferencia extra ou permissao especial.

### Resultado esperado

- menor acoplamento no codigo;
- mais flexibilidade para loja, armazem e futuras expansoes;
- menos manutencao tecnica para ajuste operacional simples.

### Avanco atual

- pontos permitidos para venda a mostrador sairam da regra fixa em codigo;
- configuracao do sistema passou a aceitar lista de pontos habilitados para o balcao;
- backend e interface da venda a mostrador passaram a respeitar essa parametrizacao.

---

## Fase VM7 - Pagamento misto, troco e antifraude operacional

Status: concluida  
Prioridade: media

### Objetivo

Deixar o recebimento de balcao mais proximo da operacao real.

### Escopo

- suportar pagamento misto no mesmo documento;
- reforcar conferencias de troco e total recebido;
- revisar regras de desconto critico com dupla confirmacao;
- tratar melhor cancelamento e estorno de guia ja paga;
- mostrar historico curto da guia no ato do pagamento.

### Resultado esperado

- maior aderencia ao caixa real;
- menos improviso no recebimento;
- menor risco de fraude simples ou erro de fechamento.

### Avanco atual

- caixa passou a aceitar pagamento misto com forma secundaria opcional;
- troco agora considera apenas a parcela em dinheiro;
- composicao do recebimento fica salva no pagamento;
- comprovante/talao passou a exibir a composicao quando houver mais de uma forma.

---

## Fase VM8 - Relatorios e indicadores da venda a mostrador

Status: concluida  
Prioridade: media

### Objetivo

Dar leitura gerencial propria para o balcao.

### Escopo

- painel com:
  - ticket medio;
  - itens mais vendidos;
  - vendedor com maior volume;
  - cestos abandonados;
  - guias pendentes;
  - cancelamentos;
  - divergencias;
  - estornos;
- filtros por periodo, vendedor, ponto e operador;
- base para acompanhar conversao do balcao.

### Resultado esperado

- leitura clara de eficiencia comercial;
- visibilidade de perdas operacionais;
- apoio a premiacao e correcao de processo.

### Avanco atual

- criado painel proprio da venda a mostrador dentro do `estoque`;
- resumo gerencial com total vendido, ticket medio, guias pendentes/divergentes, cestos abandonados, cancelamentos e estornos;
- leitura de top produtos, top vendedores e top operadores;
- acesso direto ao painel a partir da tela principal do POS.

---

## Fase VM9 - Garantia, devolucao e pos-venda da peca

Status: concluida  
Prioridade: media

### Objetivo

Fechar o ciclo da venda a mostrador para alem do pagamento.

### Escopo

- padronizar garantia de peca vendida no balcao;
- vincular comprovante, item e comprador quando identificado;
- facilitar consulta de vendas anteriores;
- preparar base para futura comunicacao por WhatsApp e email.

### Resultado esperado

- menos improviso em garantia;
- melhor experiencia para o cliente;
- menos discussao manual sem historico.

### Avanco atual

- criada estrutura de `AtendimentoPosVendaBalcao` para garantia, troca, devolucao e orientacao;
- pagina de pos-venda com busca por guia, talao, comprador, documento, telefone e produto;
- abertura e conclusao de atendimentos com historico basico;
- garantia lida a partir do prazo da peca vendida, quando configurado.

---

## Ordem Recomendada de Execucao

1. `VM1` - fluxo unificado de balcao
2. `VM2` - vendedor e identidade da venda
3. `VM3` - cestos em aberto e retomada
4. `VM4` - caixa dedicado para guia/venda mostrador
5. `VM6` - politica configuravel de pontos
6. `VM7` - pagamento misto e antifraude operacional
7. `VM5` - identificacao opcional do cliente
8. `VM8` - relatorios e indicadores
9. `VM9` - garantia e pos-venda

---

## Criterios de Fechamento

Consideraremos a venda a mostrador madura para uso forte de loja quando:

- o operador conseguir vender do artigo ao recebimento sem precisar interpretar regras escondidas;
- vendedor, guia, pagamento e baixa ficarem rastreaveis em poucos cliques;
- cestos em aberto forem visiveis e faceis de limpar ou retomar;
- o caixa de mostrador ficar claramente distinto do caixa de OS;
- houver leitura minima de abandono, divergencia, estorno e performance do balcao.

---

## Referencias Tecnicas Atuais

- `estoque/view_modules/pdv.py`
- `estoque/services.py`
- `estoque/templates/estoque/consulta_artigos.html`
- `estoque/templates/estoque/guia_pagamento.html`
- `caixa/services/pagamentos.py`
- `caixa/templates/caixa/registrar_pagamento.html`
- `estoque/tests.py`
