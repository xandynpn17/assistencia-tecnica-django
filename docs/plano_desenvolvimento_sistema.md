# Plano de Desenvolvimento do Sistema

## Objetivo

Consolidar o sistema de assistencia tecnica sem reescrever o que ja funciona.
O foco e evoluir o fluxo operacional, endurecer regras criticas, granular permissoes e limpar a base para a futura migracao para PostgreSQL.

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
Status: concluida
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
- matriz formal de fluxo criada em `ordens/services/fluxo_os_policy.py` (`status -> proxima acao -> acoes recomendadas -> bloqueios -> destaques`);
- tela de detalhes da OS agora mostra:
  - proxima acao recomendada;
  - acoes recomendadas;
  - alertas operacionais principais;
  - situacao operacional resumida no topo.
- destaques de acoes por status aplicados no cabecalho e no bloco de Servicos & Pecas (ex.: fechar e ir ao caixa, abrir orcamento, abrir pedido).
- destaques e botoes prioritarios por status foram revisados nas abas principais da OS;
- dispersao operacional foi reduzida com tooltips compactos, toolbars por aba e headers mais consistentes.

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
  - criar conta a receber;
  - baixar conta a receber;
  - cancelar conta a receber;
  - editar conta a receber;
  - criar conta a pagar;
  - baixar conta a pagar;
  - cancelar conta a pagar;
  - editar conta a pagar;
  - excluir pagamento;
  - acessar DRE;
  - gerir comissoes;
  - acessar auditoria operacional;
- menus e botoes criticos ajustados para refletir as novas permissoes;
- migration `0038` aplicada com preenchimento inicial compativel ao acesso que ja existia.
- migration `0041` amplia a cobertura de contas a receber com permissao especifica de cancelamento.
- edicao controlada de contas a receber/pagar adicionada, com bloqueio de campos financeiros quando ja existe movimentacao.
- testes de helper de permissao sensivel adicionados em `configuracoes/tests.py`.

Fase 03 concluida:
- acoes sensiveis restantes da OS e do orcamento agora usam permissoes granulares;
- verificacoes hardcoded remanescentes do caixa foram substituidas por helpers reutilizaveis;
- testes especificos das permissoes granulares cobrem rotas criticas de OS, orcamentos e helper central.

Permissoes sensiveis sugeridas:
- editar numero de serie;
- alterar tecnico responsavel;
- editar dados da OS apos confirmacao;
- reabrir OS fechada;
- excluir item de orcamento;
- aplicar desconto manual;
- excluir pagamento;
- editar conta a receber/pagar;
- cancelar conta a receber/pagar;
- acessar DRE;
- gerir comissoes;
- acessar auditoria operacional;
- editar configuracoes criticas.

Resultado esperado:
- tecnico ou atendente pode receber privilegios pontuais;
- seguranca melhora sem engessar a operacao.

### Fase 4 - Orcamento como extensao natural da OS
Status: concluida
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
- aba de orcamento da OS passou a ter painel operacional com totais, pendencias, aprovados, recusados e acoes diretas.
- envio de orcamento por WhatsApp/E-mail e impressao passaram a ficar disponiveis diretamente na aba de orcamento.
- notificacao de orcamento pode retornar para a propria aba `orcamentos`, mantendo o usuario no contexto da OS.

Ainda pendente nesta fase:
- nenhuma pendencia critica aberta nesta fase.

Feito nesta etapa:
- rotas duplicadas de orcamento em `ordens` foram removidas;
- `orcamentos` permaneceu como modulo oficial da logica e a OS virou o ponto principal de entrada visual;
- acessos GET de criacao/edicao de orcamento passaram a redirecionar para a aba da OS;
- textos da aba de orcamento foram ajustados para reforcar o ownership da OS.

### Fase 5 - Revisao de encoding e textos
Status: concluida
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

Feito nesta etapa:
- correcoes de mojibake aplicadas nos fluxos de OS, orcamento e caixa;
- labels das abas da OS normalizados;
- modais principais de servicos, orcamentos e pedidos passaram por limpeza visual e textual;
- textos operacionais mais expostos da OS foram estabilizados em formato seguro para evitar regressao de encoding;
- testes focados atualizados para refletir a nova interface;
- teste de guarda anti-mojibake adicionado em `core/tests.py`.

### Fase 6 - Limpeza tecnica e documental
Status: concluida
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

Feito nesta etapa:
- `docs/revisao_arquitetura.md` atualizado para o estado tecnico atual;
- `docs/README.md` criado como indice de fontes ativas vs historicas;
- inventarios historicos mantidos, mas tratados como referencia de auditoria.
- inventarios tecnicos consolidados em `docs/legacy_code/` para reduzir ruido na raiz de documentacao.
- `docs/ownership_modulos.md` criado para registrar ownership tecnico atual por app e service.
- `docs/legacy_code/README.md` reforcado para desencorajar manutencao em arquivos arquivados.
- referencias documentais ativas alinhadas para separar melhor fonte viva vs historico.

### Fase 7 - Preparacao para PostgreSQL
Status: concluida
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

Feito nesta etapa:
- `assistencia/settings.py` com selecao de banco por ambiente:
  - `DJANGO_DB_ENGINE=sqlite` (padrao atual);
  - `DJANGO_DB_ENGINE=postgres` com vars obrigatorias de conexao.
- validacao defensiva para evitar subir PostgreSQL sem variaveis minimas.
- dependencia `psycopg[binary]` adicionada em `requirements.txt`.
- checklist tecnico criado em `docs/checklist_migracao_postgresql.md`.
- arquivo `.env.postgres.example` criado para acelerar setup local.
- comando `check_postgres_ready` criado para pre-validar ambiente e conexao.
- migracao real aplicada em base PostgreSQL limpa (`assistencia_dev`).
- conexao validada com `check_postgres_ready --check-connection`.
- correcoes de compatibilidade SQLite/PostgreSQL aplicadas no setup inicial:
  - aumento do campo `TipoEquipamentoConfig.codigo` para `max_length=80`;
  - migration `configuracoes.0048` aplicada.
- homologacao automatizada concluida em PostgreSQL:
  - suite completa `core ordens estoque caixa orcamentos configuracoes` com 472 testes OK.

Pendencias residuais (nao bloqueantes):
- padronizar, quando desejado, uma unica instancia local em `5432` (hoje ambiente homologado em `5433`);
- validar indices/constraints com carga operacional real (dados de uso).

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
Status: concluida.

Entrega 4:
- revisar encoding e limpar referencias restantes ao legado.
Status: concluida.

