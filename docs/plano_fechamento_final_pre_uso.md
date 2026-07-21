# Plano de Fechamento Final Antes do Uso

## Objetivo

Fechar os ultimos pontos tecnicos e operacionais antes de considerar o sistema pronto para uso local real na loja.

Este plano nao cria novos modulos grandes.
Ele organiza apenas o que ainda vale refinar para:

- reduzir risco operacional;
- evitar inconsistencias entre empresa, OS, caixa e estoque;
- estabilizar PDFs e configuracoes;
- facilitar manutencao futura;
- deixar o ambiente local mais previsivel.

---

## Escopo desta etapa

Esta etapa cobre:

1. endurecimento do contexto de empresa;
2. revisao de singletons e configuracoes globais;
3. estabilizacao final de PDFs;
4. tratamento melhor de erros e logs;
5. limpeza de debug residual no front;
6. pequenos ajustes de consistencia financeira;
7. reducao de acoplamento em arquivos maiores;
8. revisao final de performance em telas principais;
9. homologacao final orientada por checklist.

Nao faz parte desta etapa:

- novas features grandes;
- expansao SaaS completa;
- mudanca radical de design system;
- troca de stack.

---

## Fase F1 - Tenant e contexto de empresa

Status: concluida em 2026-07-04  
Prioridade: critica

### Objetivo

Garantir que o sistema nunca opere silenciosamente com a empresa errada.

### Escopo

- revisar `obter_empresa_ativa()` e remover fallback silencioso para `Empresa.objects.first()` em areas operacionais;
- usar modo estrito nas views autenticadas;
- manter fallback apenas em setup inicial, rotas publicas controladas ou manutencao guiada;
- revisar dashboards, clientes, ordens, estoque, caixa e configuracoes.

### Entregas

- tenant guard endurecido;
- views principais usando empresa explicita;
- erros controlados quando o contexto de empresa estiver ausente.

### Criterios de aceite

- nenhuma tela operacional carrega dados sem empresa ativa definida;
- o sistema falha de forma clara, sem misturar dados de empresas;
- os testes cobrindo tenant continuam verdes.

### Referencias

- `configuracoes/services/tenant_guard.py`
- `core/views.py`
- `clientes/views.py`
- `ordens/view_modules/*`
- `estoque/view_modules/*`

---

## Fase F2 - Configuracoes singleton e preview seguro

Status: concluida em 2026-07-04  
Prioridade: alta

### Objetivo

Eliminar pontos onde o sistema usa `.first()` ou "ultimo registro" como atalho global.

### Escopo

- revisar `ConfiguracaoOrdemServico.objects.first()`;
- revisar geracao de numeracao da OS;
- revisar setup inicial;
- revisar preview de documentos para nao depender da ultima OS/orcamento real do banco;
- usar mock por padrao quando nao houver objeto explicito selecionado.

### Entregas

- acesso centralizado e previsivel aos singletons;
- preview de documentos sem dependencia perigosa de dados reais;
- numeracao de OS com fonte de configuracao explicita.

### Criterios de aceite

- prefixo e numeracao nao dependem de registros arbitrarios;
- preview funciona mesmo com banco vazio;
- nenhuma configuracao critica usa `.first()` onde deveria haver singleton explicito.

### Referencias

- `configuracoes/view_modules/sistema.py`
- `configuracoes/view_modules/painel.py`
- `ordens/services/numeracao.py`

---

## Fase F3 - Padronizacao final de PDFs

Status: concluida em 2026-07-10  
Prioridade: alta

Atualizado em 2026-07-04:

- helper unico de rodape paginado criado em `ordens/view_modules/impressao.py`;
- helper unico para etiquetas de corte criado e aplicado na OS impressa;
- blocos duplicados de rodape da OS e do relatorio tecnico passaram a usar a mesma base.
- testes de OS, relatorio tecnico, guia de expedicao e orcamento longo aprovados no PostgreSQL local;
- cenarios de multipla pagina, total de paginas, preview e limite de paginas da OS permaneceram verdes.

### Objetivo

Reduzir o risco de sobreposicao e quebra visual em OS, relatorio tecnico e orcamento.

### Escopo

- mapear blocos ainda desenhados com coordenadas absolutas;
- mover rodapes, etiquetas e blocos repetitivos para componentes mais previsiveis;
- manter `canvas` apenas para numeracao, marcas leves e detalhes realmente necessarios;
- validar cenarios com texto longo, nomes grandes, logo variavel e multiplas linhas.

### Entregas

- padrao unico de construcao de rodape e blocos visuais;
- menos dependencia de `drawString/drawCentredString`;
- checklist de testes extremos de PDF.

### Criterios de aceite

- PDFs principais permanecem legiveis com dados extensos;
- logo, assinaturas e textos nao se sobrepoem;
- o layout continua profissional sem ajuste manual por caso.

### Referencias

- `ordens/view_modules/impressao.py`
- `orcamentos/views.py`

---

## Fase F4 - Tratamento de erro e observabilidade

Status: concluida em 2026-07-10  
Prioridade: alta

Atualizado em 2026-07-04:

- `caixa/services/pagamentos.py` passou a registrar falha de configuracao do talao com log estruturado;
- `clientes/views.py`, `configuracoes/middleware.py`, `configuracoes/view_modules/operacao.py`, `ordens/view_modules/common.py` e `ordens/view_modules/expedicao.py` tiveram pontos de `except Exception` substituidos por tratamento mais especifico.
- conversoes financeiras e relacoes opcionais de comissao passaram a capturar apenas erros esperados;
- inventario e conciliacao passaram a separar erros de negocio de falhas inesperadas de infraestrutura.

### Objetivo

Parar de mascarar erro real em fluxos criticos.

### Escopo

- substituir `except Exception` generico por excecoes especificas onde houver contexto funcional claro;
- adicionar logs estruturados com OS, cliente, pagamento, usuario e modulo;
- revisar principalmente caixa, ordens, estoque e configuracoes;
- diferenciar erro de negocio, erro de infraestrutura e erro inesperado.

### Entregas

- logs mais uteis;
- mensagens mais claras para suporte e operacao;
- menos falsos "funcionou mas nao sabemos o que houve".

### Criterios de aceite

- fluxos criticos registram contexto minimo no erro;
- excecoes genericas diminuem nas areas prioritarias;
- comportamento funcional continua igual para o usuario final.

### Referencias

- `caixa/services/pagamentos.py`
- `clientes/views.py`
- `configuracoes/view_modules/operacao.py`
- `ordens/view_modules/common.py`
- `ordens/view_modules/expedicao.py`

---

## Fase F5 - Limpeza de debug residual no front

Status: concluida em 2026-07-10  
Prioridade: media

Atualizado em 2026-07-04:

- `static/js/verificar-cliente.js` e `ordens/static/js/ordens/verificar_cliente_os.js` ficaram condicionados a `window.ABTECH_DEBUG === true`;
- log residual de modal foi removido de `ordens/templates/ordens/ordem_servico_detalhes.html`.
- verificacao visual no navegador terminou sem erros ou avisos de console nas telas principais de estoque.

### Objetivo

Limpar codigo de depuracao que nao deve ficar ativo no uso normal.

### Escopo

- desligar `DEBUG: true` em JS operacional;
- remover ou esconder helpers globais de teste;
- reduzir `console.log` residual;
- manter somente logs condicionais para ambiente local tecnico, se necessario.

### Entregas

- JS mais limpo e profissional;
- console sem ruido no dia a dia;
- menor risco de confusao durante suporte.

### Criterios de aceite

- telas principais nao poluem o console;
- funcoes de debug nao ficam expostas em producao local;
- comportamento funcional permanece intacto.

### Referencias

- `static/js/verificar-cliente.js`
- `ordens/static/js/ordens/verificar_cliente_os.js`

---

## Fase F6 - Consistencia financeira e cadastros-base

Status: concluida em 2026-07-10  
Prioridade: media

Atualizado em 2026-07-04:

- a regra de conta a receber da OS foi centralizada em `ordens/services/fechamento_os.py` via `garantir_conta_receber_os()`;
- `caixa/view_modules/helpers.py` passou a reutilizar a mesma regra, reduzindo divergencia entre fechamento da OS e pagamento.
- categoria financeira passou a ter unicidade de banco por nome e tipo, com migration defensiva para consolidar duplicados;
- total da OS e total liquidado passaram a usar agregacoes SQL no servico central;
- testes de fechamento, saldo pendente, caixa e comissoes permaneceram verdes.

### Objetivo

Evitar classificacoes financeiras ambiguas e garantir base minima consistente.

### Escopo

- revisar criacao automatica da categoria `Cliente OS`;
- definir melhor o seed ou regra de unicidade da categoria base;
- revisar relacao entre fechamento de OS, conta a receber e pagamentos;
- confirmar se os acompanhamentos de saldo pendente estao coerentes com os indicadores.

### Entregas

- categoria financeira base mais controlada;
- menor risco de duplicidade semantica;
- documentacao curta do fluxo financeiro da OS.

### Criterios de aceite

- fechamento da OS nao cria classificacoes soltas;
- indicadores financeiros batem com conta a receber e pagamento;
- base continua simples para uso local.

### Referencias

- `ordens/services/fechamento_os.py`
- `caixa/models.py`
- `caixa/services/pagamentos.py`

---

## Fase F7 - Refino tecnico leve dos arquivos maiores

Status: concluida em 2026-07-10  
Prioridade: media

### Objetivo

Melhorar manutencao sem mudar comportamento.

### Escopo

- quebrar os arquivos mais pesados por responsabilidade;
- priorizar:
  - `ordens/view_modules/impressao.py`
  - `caixa/view_modules/dashboard.py`
  - `configuracoes/forms.py`
  - eventualmente `clientes/views.py` e `estoque/services.py`
- preservar URLs, contratos e telas existentes.

### Entregas

- submodulos menores e mais legiveis;
- menos acoplamento;
- base mais amigavel para evolucao futura.

Atualizacao final:

- rastreabilidade de lote e serie extraida para `estoque/services_rastreabilidade.py`;
- `estoque/services.py` reduziu cerca de 200 linhas sem alterar a API usada pelas views;
- refatoracoes maiores de PDF/dashboard foram evitadas nesta fase para reduzir risco antes do uso real.

### Criterios de aceite

- nenhum fluxo funcional muda;
- arquivos grandes ficam mais claros por dominio;
- testes existentes continuam passando.

---

## Fase F8 - Performance de telas principais

Status: concluida em 2026-07-10  
Prioridade: media

### Objetivo

Fechar gargalos obvios antes do uso real com mais dados.

### Escopo

- revisar detalhes do cliente;
- revisar dashboard gerencial;
- revisar somas em Python sobre listas de OS e pagamentos;
- mover totais sensiveis para `annotate`, `Subquery` ou agregacoes mais economicas onde fizer sentido;
- manter paginação e `select_related/prefetch_related` nas telas mais usadas.

### Entregas

- menos custo nas telas de consulta;
- base pronta para crescer sem perder resposta cedo demais.

Atualizacao final:

- detalhe do cliente passou a agregar valores da OS no banco e a carregar linhas de retirada em um unico prefetch;
- painel gerencial passou a calcular receita mensal por agregacao SQL, eliminando consultas por OS;
- dashboard operacional ja mantinha `select_related`, `Prefetch` e limite de cinco ordens recentes.

### Criterios de aceite

- consultas principais continuam responsivas com volume moderado;
- N+1 obvio reduzido;
- nao ha regressao visual nem funcional.

### Referencias

- `clientes/views.py`
- `core/views.py`
- `ordens/models.py`

---

## Fase F9 - Homologacao final de encerramento

Status: pendente  
Prioridade: critica

### Objetivo

Validar o sistema apos os refinamentos finais e definir o ponto de liberacao.

### Escopo

- rodar checklist manual completo;
- validar backup e restore por UI e modo emergencial;
- validar fluxo principal de loja;
- validar 2 ou 3 acessos em rede local;
- validar PDFs e logo;
- validar operacao no PC servidor oficial.

### Entregas

- checklist preenchido;
- lista curta de pendencias reais restantes, se houver;
- decisao objetiva de liberacao.

### Criterios de aceite

- nenhum bloqueio critico no fluxo da loja;
- backup/restore confiavel;
- ambiente local previsivel para uso diario;
- operacao por navegador em rede local funcionando.

### Referencias

- `docs/checklist_homologacao_manual.md`
- `docs/checklist_go_live_local.md`
- `docs/homologacao_rede_local.md`
- `docs/backup_restore_local.md`

---

## Ordem recomendada de execucao

1. F1 - Tenant e contexto de empresa
2. F2 - Configuracoes singleton e preview seguro
3. F4 - Tratamento de erro e observabilidade
4. F3 - Padronizacao final de PDFs
5. F5 - Limpeza de debug residual no front
6. F6 - Consistencia financeira e cadastros-base
7. F8 - Performance de telas principais
8. F7 - Refino tecnico leve
9. F9 - Homologacao final de encerramento

---

## Definicao pratica de pronto

Podemos considerar o sistema pronto para a primeira operacao local real quando:

- o contexto de empresa estiver endurecido;
- configuracoes criticas nao dependerem de fallback silencioso;
- PDFs principais estiverem estaveis;
- os erros criticos estiverem rastreaveis;
- o front estiver limpo de debug residual;
- o fluxo OS > orcamento > servicos/pecas > caixa > fechamento > historico > backup passar integralmente;
- o acesso em rede local estiver validado com mais de um equipamento.

## Validacao automatizada de fechamento

Executada em 2026-07-10 no PostgreSQL local:

- `40 tests OK` para fechamento/caixa, PDFs de OS/orcamento, comissoes, inventario e conciliacao;
- `8 tests OK` para entrada de mercadoria e rastreabilidade antes do refinamento final de cancelamento;
- `manage.py check` sem erros;
- migrations aplicadas ate `caixa.0032`, `clientes.0013` e `configuracoes.0064`;
- F9 continua pendente apenas nas validacoes manuais em 2 ou 3 equipamentos e no PC servidor definitivo.
