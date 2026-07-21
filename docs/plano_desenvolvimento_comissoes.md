# Plano de Desenvolvimento de Comissoes

## Objetivo

Consolidar o modulo de comissoes para que ele reflita a operacao real da assistencia, fique auditavel e permita crescimento futuro sem gambiarra.

Este plano separa:

- comissao tecnica por servico;
- comissao opcional por peca;
- bonus e comissoes de venda mostrador;
- regras futuras para contratos, marcas e modos alternativos de apuracao.

---

## Regra operacional definida nesta fase

### Servicos

- a base principal da comissao tecnica continua correta quando nasce do servico executado e associado ao tecnico;
- a OS precisa estar com execucao tecnica concluida e pronta para apuracao;
- por padrao, a apuracao considera `pronto_contactado`;
- opcionalmente, a empresa pode exigir apuracao apenas em `concluida/entregue`;
- `autorizado` e `pronto_contactar` nao devem mais liberar comissao tecnica no motor principal.

### Pecas

- comissao sobre pecas aplicadas na OS passa a ser opcional por configuracao global;
- quando desligada, o motor tecnico ignora pecas mesmo que existam itens migrados.

### Bonus por retirada

- deixa de ser parte obrigatoria do modelo principal;
- permanece disponivel como incentivo opcional, desligado por padrao.

### Venda mostrador

- continua como trilha separada;
- deve usar vendedor responsavel, numero de vendedor e bonus por produto quando configurado;
- todos os usuarios operacionais devem poder ter numero de vendedor, inclusive tecnicos que vendem acessorios.

---

## Diagnostico atual

### O que ja estava bom

- o motor prioriza `ServicoPeca` migrado e usa `ItemOrcamento` como fallback, o que combina bem com a ideia de comissionar o que foi efetivamente executado;
- ja existe trilha separada para servico, peca, bonus e venda mostrador;
- ha boa base de testes no modulo `caixa`.

### Onde havia divergencia

- telas e filtros ainda aceitavam `autorizado` e `pronto_contactar` como se fossem etapa final valida;
- a politica de comissao ficava implicita em regras antigas e percentuais soltos;
- bonus por retirada parecia parte obrigatoria do modelo, quando hoje ele e apenas opcional;
- faltava uma configuracao global explicita para a regra de apuracao.

---

## Fase C1 - Politica explicita de comissao

Status: concluida nesta rodada  
Prioridade: critica

### Objetivo

Deixar claro, no sistema e na documentacao, quando a OS entra na apuracao da comissao tecnica.

### Escopo

- criar configuracao global para criterio da OS:
  - `pronto_contactado`
  - `entregue/concluida`
- criar configuracao global para:
  - aplicar ou nao comissao de pecas;
  - ativar ou nao bonus por retirada;
- refletir isso na tela de configuracao do sistema.

### Avanco atual

- campos globais adicionados em `ConfiguracaoSistema`;
- formulario e tela de configuracao ja passaram a expor a politica principal;
- criterios globais de OS, pecas e bonus ficaram cobertos pela suite automatizada do modulo `caixa`.

---

## Fase C2 - Alinhamento do motor e das telas

Status: concluida nesta rodada  
Prioridade: critica

### Objetivo

Garantir que o backend, os dashboards e as telas de conferenca usem exatamente a mesma regra.

### Escopo

- retirar `autorizado` e `pronto_contactar` da apuracao tecnica principal;
- usar helper unico de status validos para apuracao;
- alinhar:
  - pendencias de comissao;
  - tela administrativa;
  - tela de desempenho individual;
  - recalculos manuais.

### Avanco atual

- motor principal ja usa criterio configuravel;
- views principais passaram a usar o mesmo helper central de status validos;
- bonus de retirada passou a respeitar chave de ativacao propria;
- telas de pendencias, pagamento e desempenho individual ficaram alinhadas ao mesmo criterio operacional.

---

## Fase C3 - Homologacao de testes e regressao

Status: concluida nesta primeira rodada  
Prioridade: alta

### Objetivo

Atualizar a suite para o comportamento novo e proteger contra regressao.

### Escopo

- ajustar testes que ainda esperavam comissao em `autorizado` ou `pronto_contactar`;
- validar cenario com bonus por retirada ligado e desligado;
- validar cenario com pecas ligadas e desligadas;
- validar desempenho individual conforme criterio configurado.

---

## Fase C4 - Vendedor e bonus comercial

Status: concluida nesta rodada  
Prioridade: alta

### Objetivo

Separar claramente comissao tecnica de incentivo comercial.

### Escopo

- garantir que todo usuario operacional possa ter `numero_vendedor`;
- consolidar bonus por produto na venda mostrador;
- permitir bonus fixo por unidade vendida;
- manter tecnicos elegiveis a bonus comercial quando venderem acessorios.

### Avanco atual

- `numero_vendedor` ja e gerado automaticamente quando necessario;
- venda mostrador continua separada da comissao tecnica;
- bonus comercial por produto passou a poder ser desligado globalmente;
- bonus por produto agora considera quantidade vendida e registra isso na trilha da comissao;
- telas e fluxos deixaram de tratar vendedor como tecnico no PDV, preservando o numero de vendedor como trilha operacional.

---

## Fase C5 - Contratos, marcas e garantia

Status: concluida nesta primeira rodada  
Prioridade: media/alta

### Objetivo

Preparar o sistema para cenarios onde o valor pago pela marca nao e a base integral da comissao do tecnico.

### Escopo

- permitir tabela tecnica de base comissionavel por marca/fornecedor/contrato;
- separar:
  - valor faturado da marca;
  - base tecnica interna do colaborador;
- preservar excecoes de garantia de servico e retornos nao comissionaveis.

### Avanco atual

- garantias de fabricante agora podem usar a base tecnica interna definida em `RegraGarantiaMarca.valor_mao_obra_tecnico`;
- quando essa base tecnica existe, a comissao do tecnico passa a usar esse valor interno em vez do valor bruto faturado pela marca;
- a flag `comissionar_garantia` voltou a ser respeitada pelo motor principal, bloqueando comissao de garantia quando a regra do tecnico assim definir;
- retornos de garantia de servico continuam preservados como trilha separada, sem misturar com garantia de fabricante.

---

## Fase C6 - Competencia mensal e pagamento

Status: concluida nesta rodada  
Prioridade: media

### Objetivo

Deixar mais claro o ciclo `gerada -> liberada -> paga` para o uso mensal.

### Escopo

- definir quando a comissao entra na competencia;
- separar apuracao de pagamento;
- melhorar conferencia e lotes por periodo;
- reforcar rastreabilidade de cancelamento e recalculo.

### Avanco atual

- o modelo ja diferencia `GERADA`, `LIBERADA`, `PAGA` e `CANCELADA`;
- as telas de administracao e pagamento passaram a explicar melhor esse fluxo para o uso mensal;
- lotes, referencia de pagamento e trilha de auditoria continuam preservados como base da operacao;
- os cenarios de pendencias, competencia, filtros salvos, pagamento e desempenho fecharam com a mesma leitura de negocio na bateria automatizada.

---

## Fase C7 - Modo futuro configuravel

Status: futuro  
Prioridade: baixa por agora

### Objetivo

Permitir que o administrador escolha no futuro entre modelos diferentes de apuracao.

### Escopo futuro

- modo atual:
  - comissao tecnica quando a OS esta pronta para entrega ou entregue;
- modo alternativo:
  - comissao vinculada apenas ao recebimento/retirada via venda mostrador ou caixa.

---

## Checklist de homologacao desta etapa

1. Configurar a politica da OS para `pronto_contactado`.
2. Criar uma OS com relatorio tecnico e item de servico aprovado.
3. Confirmar que `autorizado` nao gera comissao.
4. Confirmar que `pronto_contactar` nao gera comissao.
5. Confirmar que `pronto_contactado` gera comissao.
6. Desligar comissao de pecas e validar que apenas servicos entram.
7. Ligar bonus por retirada e validar que ele so nasce apos quitacao total.
8. Conferir `Meu desempenho` e `Comissoes` com a mesma leitura operacional.

---

## Evidencia de fechamento tecnico

- suite `caixa.tests` executada em PostgreSQL local com `174/174` testes aprovados;
- cenarios de garantia, servico, pecas, bonus e `Meu desempenho` estabilizados;
- pendencias residuais desta frente passam a ser de homologacao manual e calibracao operacional, nao de regra-base do motor.

## Proximos passos recomendados

1. homologar manualmente a politica de comissao com casos reais de loja;
2. revisar, em segunda fase, contratos de marca sem misturar com a comissao tecnica base;
3. avaliar no futuro o modo alternativo de apuracao vinculado apenas a retirada/pagamento.
