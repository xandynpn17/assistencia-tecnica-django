# Plano de Desenvolvimento do Sistema

## Objetivo

Consolidar o sistema de assistencia tecnica sem reescrever o que ja funciona.
O foco e evoluir o fluxo operacional, endurecer regras criticas, granular permissões e limpar a base para a futura migracao para PostgreSQL.

## Principios

- preservar o comportamento atual antes de refatorar;
- mudar em pequenos blocos;
- centralizar regras sensiveis fora das views;
- usar a OS como centro operacional;
- permitir variacoes reais do negocio por status, sem forcar um fluxo linear unico.

## Estado atual resumido

- O fluxo principal existe: cliente -> OS -> orcamento -> servicos/pecas -> fechamento -> caixa.
- O sistema opera bem por status de OS, o que faz sentido para assistencia tecnica.
- Ja existem testes relevantes de permissao, OS, estoque, caixa e fluxo critico E2E.
- Ainda ha regras criticas espalhadas entre views, models, templates e helpers.
- O sistema de permissao ja tem perfil base por usuario e acessos extras por modulo.
- O modulo de orcamento funciona, mas o fluxo esta espalhado entre `ordens` e `orcamentos`.
- Havia codigo legado misturado aos apps ativos.

## Etapas feitas

### Fase 0 - Base de seguranca
Status: concluida

- Commit de backup criado antes de novas mudancas.
- Commit: `8395a3e` - `chore: backup current development state before roadmap`
- Arquivos `views_legacy.py` foram arquivados em `docs/legacy_code/`.
- Dependencia remanescente do legado foi corrigida em `caixa/services/garantias.py`.
- Validacao rapida executada com `python manage.py check`.

## Etapas pendentes

### Fase 1 - Mapa oficial do fluxo da OS
Status: diagnostico concluido / implementacao inicial concluida
Prioridade: alta

Objetivo:
- tornar a OS o centro operacional do sistema;
- unificar o fluxo por status e acoes permitidas, sem transformar a operacao em linha reta obrigatoria.

O que revisar:
- status existentes da OS;
- quais acoes cada status permite;
- quais campos e operacoes precisam estar bloqueados por contexto;
- quais alertas devem aparecer para orientar a equipe.

O que implementar:
- matriz `status -> acoes permitidas -> bloqueios -> proxima acao`;
- cabecalho operacional na tela de detalhes da OS;
- exibicao de proxima acao recomendada;
- exibicao de alertas operacionais por status;
- reducao de botoes dispersos e reforco de acoes principais.

Resultado esperado:
- o usuario trabalha pela situacao da OS, nao pela memoria de qual tela usar;
- o fluxo fica unico por regra, nao por sequencia rigida.

Feito nesta etapa:
- service `ordens/services/resumo_operacional.py` criado para centralizar leitura operacional por status;
- tela de detalhes da OS agora mostra:
  - proxima acao recomendada;
  - acoes recomendadas;
  - alertas operacionais principais;
  - situacao operacional resumida no topo.

Ainda pendente nesta fase:
- transformar a matriz `status -> acoes permitidas -> bloqueios` em regra formal reutilizavel;
- revisar quais botoes devem ficar em destaque por status;
- reduzir mais a dispersao de acoes entre abas.

### Fase 2 - Regras criticas em services
Status: implementacao concluida
Prioridade: alta

Objetivo:
- reduzir risco de quebra ao centralizar comportamento sensivel.

Primeiro bloco sugerido:
- fechamento e reabertura da OS.

Segundo bloco sugerido:
- aprovacao, recusa e migracao de itens de orcamento.

Terceiro bloco sugerido:
- efeitos em estoque, reservas, financeiro e comissao.

Como fazer sem quebrar:
- criar services novos com a mesma regra atual;
- fazer as views delegarem para esses services;
- manter a interface e o comportamento do usuario iguais no primeiro momento;
- so depois simplificar duplicacoes internas.

Implementacoes alvo:
- `ordens/services/fechamento_os.py`
- `orcamentos/services/fluxo_orcamento.py`
- transacoes atomicas nas operacoes compostas

Resultado esperado:
- regra unica para acoes sensiveis;
- menos logica espalhada em views;
- menor risco de inconsistencias.

Feito nesta etapa:
- `ordens/services/fechamento_os.py` criado e aplicado no fechamento, reabertura e finalizacao para caixa;
- `orcamentos/services/fluxo_orcamento.py` criado e aplicado na aprovacao, recusa e migracao de itens;
- helper de migracao de itens aprovados da OS passou a delegar para o service central;
- fluxo de orcamento em `ordens` e `orcamentos` passou a reutilizar a mesma camada de regra;
- testes focados de OS, caixa e orcamento executados com sucesso apos a refatoracao.

### Fase 3 - Permissoes granulares
Status: implementacao inicial concluida / ampliacao pendente
Prioridade: alta

Objetivo:
- permitir que `adm` e `gerente` deem acessos especiais por funcionario sem liberar modulos inteiros.

Estado atual:
- existe perfil base por tipo de usuario;
- existe acesso extra por modulo:
  - ordens
  - estoque
  - caixa operacional
  - caixa financeiro
  - configuracoes

Limite atual:
- a granularidade e por modulo, nao por acao critica.

O que implementar:
- permissao por acao sensivel no modelo de usuario;
- formulario de usuario com secoes claras de permissoes;
- helpers centralizados para checagem de permissao sensivel;
- remocao gradual de condicoes hardcoded em templates.

Feito nesta etapa:
- novos campos de permissao sensivel no usuario;
- formulario de usuario atualizado com permissoes sensiveis;
- helper central `has_sensitive_permission` / `require_sensitive_permission`;
- protecao aplicada em:
  - editar numero de serie da OS;
  - alterar tecnico responsavel;
  - concluir/fechar OS;
  - reabrir OS;
  - excluir item de orcamento;
  - excluir pagamento;
  - acessar DRE;
  - gerir comissoes;
  - acessar auditoria operacional;
- menus e botoes criticos ajustados para refletir as novas permissoes;
- migration `0038` aplicada com preenchimento inicial compativel ao acesso que ja existia.

Ainda pendente nesta fase:
- granularizar outras acoes sensiveis da OS e do caixa;
- reduzir mais verificacoes hardcoded em templates;
- adicionar testes especificos das novas permissoes granulares.

Permissoes sensiveis sugeridas:
- editar numero de serie;
- alterar tecnico responsavel;
- editar dados da OS apos confirmacao;
- reabrir OS fechada;
- excluir item de orcamento;
- aplicar desconto manual;
- excluir pagamento;
- editar conta a receber/pagar;
- acessar DRE;
- gerir comissoes;
- acessar auditoria operacional;
- editar configuracoes criticas.

Resultado esperado:
- tecnico ou atendente pode receber privilegios pontuais;
- seguranca melhora sem engessar a operacao.

### Fase 4 - Orcamento como extensao natural da OS
Status: implementacao tecnica inicial concluida / consolidacao visual pendente
Prioridade: media/alta

Objetivo:
- manter a boa logica atual, mas com ownership tecnico mais claro.

Estado atual:
- o orcamento funciona bem;
- a entrada visual e tecnica esta espalhada entre `ordens` e `orcamentos`.

O que revisar:
- rotas duplicadas;
- migracao de itens;
- mensagens e transicoes de status ligadas ao orcamento.

O que implementar:
- OS como ponto unico de entrada visual para orcamento;
- `orcamentos` como modulo oficial da logica;
- consolidacao da migracao de itens aprovados em um service unico.

Resultado esperado:
- o usuario sente que o orcamento mora dentro da OS;
- o codigo deixa de ter dois "donos" do mesmo fluxo.

Feito nesta etapa:
- a logica de aprovacao, recusa e migracao foi consolidada em `orcamentos/services/fluxo_orcamento.py`;
- os pontos ativos em `ordens` e `orcamentos` passaram a usar a mesma regra central.

Ainda pendente nesta fase:
- simplificar mais rotas e pontos de entrada visuais;
- revisar nomenclatura e mensagens para reforcar a OS como porta principal.

### Fase 5 - Revisao de encoding e textos
Status: pendente
Prioridade: media

Objetivo:
- corrigir textos quebrados e padronizar exibicao.

O que revisar:
- arquivos Python;
- templates HTML;
- mensagens do sistema;
- PDFs e documentos gerados.

O que implementar:
- padronizacao em UTF-8;
- correcao de textos com caracteres quebrados;
- revisao dos textos mais visiveis ao usuario.

Resultado esperado:
- interface mais profissional;
- menos risco em PDF, exportacao e renderizacao.

### Fase 6 - Limpeza tecnica e documental
Status: pendente
Prioridade: media

Objetivo:
- reduzir ruido e facilitar manutencao.

O que revisar:
- referencias antigas ao legado;
- documentacao desatualizada;
- funcoes mortas;
- imports antigos;
- arquivos utilitarios fora de lugar.

O que implementar:
- atualizar docs;
- remover referencias obsoletas;
- consolidar ownership dos modulos;
- manter historico arquivado apenas em `docs/legacy_code/`.

Resultado esperado:
- repositorio mais claro;
- menor risco de manutencao no arquivo errado.

### Fase 7 - Preparacao para PostgreSQL
Status: pendente
Prioridade: media

Contexto:
- migracao sera feita ainda em desenvolvimento;
- o banco atual podera ser resetado.

Objetivo:
- deixar o projeto pronto para trocar de SQLite para PostgreSQL com menor atrito.

O que revisar:
- compatibilidade das migrations;
- tipos decimais e datas;
- constraints e indices;
- pontos com consultas sensiveis a banco.

O que implementar:
- configuracao de ambiente PostgreSQL;
- validacao de migrations em base limpa;
- checklist de subida local e homologacao.

Resultado esperado:
- migracao previsivel e sem dependencia do banco antigo.

## Ordem recomendada de implementacao

1. Fase 1 - mapa oficial do fluxo da OS
2. Fase 3 - permissoes granulares
3. Fase 2 - services para regras criticas
4. Fase 4 - consolidacao do orcamento
5. Fase 5 - encoding e textos
6. Fase 6 - limpeza tecnica e documental
7. Fase 7 - preparacao para PostgreSQL

## Proxima entrega sugerida

Entrega 1:
- mapear status da OS e acoes permitidas;
- mapear permissoes sensiveis;
- definir estrutura tecnica das novas permissoes granulares.
Status: concluida em diagnostico/documentacao.
Referencia: `docs/entrega_1_fluxo_permissoes.md`

Entrega 2:
- implementar permissoes granulares nas acoes mais delicadas da OS e do caixa;
- bloquear operacoes sensiveis por helper central.
Status: concluida nesta rodada.

Entrega 3:
- extrair service de fechamento/reabertura da OS;
- extrair service do fluxo de orcamento.
Status: pendente.

Entrega 4:
- revisar encoding e limpar referencias restantes ao legado.
Status: pendente.
