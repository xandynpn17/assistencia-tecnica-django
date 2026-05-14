# Plano de Desenvolvimento da App Configuracoes

## Objetivo

Evoluir a app `configuracoes` para ser o nucleo administrativo do sistema, com foco em:
- governanca de parametros criticos;
- seguranca operacional;
- escalabilidade para integracoes externas (APIs);
- preparo progressivo para modelo SaaS.

## Principios

- preservar os fluxos ja validados em producao local antes de refatorar;
- separar regras de negocio de views gradualmente;
- priorizar trilha de auditoria e rastreabilidade de mudancas;
- preparar a base para multiempresa/multitenancy sem ruptura;
- tratar configuracoes como produto: claras, versionadas e testaveis.

## Diagnostico resumido

### Pontos fortes

- cobertura de testes ampla em permissoes, formularios, comandos e setup inicial;
- modelo de permissoes granulares consistente e reutilizavel;
- setup inicial orientado a catalogo e primeira configuracao de empresa;
- comandos utilitarios robustos para readiness, backup, restore e importacao;
- boa base de formularios com validacoes de seguranca e consistencia.

### Pontos fracos

- concentracao excessiva de logica em `views.py`;
- modelo `User` com muitas flags booleanas de permissao sensivel;
- pontos de encoding quebrado em textos visiveis;
- restore operacional sensivel por querystring;
- dependencia sincrona de APIs externas (CEP) sem camada dedicada de resiliencia;
- pouca visibilidade consolidada de alteracoes criticas (auditoria de configuracoes).

### Oportunidades

- modularizar dominios internos da app (`usuarios`, `empresa`, `catalogo`, `sistema`, `integracoes`, `operacao`);
- criar versionamento de configuracoes e trilha de alteracoes com rollback;
- preparar contrato tecnico para integracoes futuras (webhooks, mensageria, provedores externos);
- introduzir base de isolamento por tenant para futura transicao SaaS.

## Fases

### Fase Cfg1 - Estabilidade textual e UX de configuracoes
Status: concluida
Prioridade: alta

Objetivo:
- corrigir textos com encoding quebrado;
- melhorar clareza visual do painel e formularios mais usados.

Escopo:
- normalizar labels/mensagens (UTF-8) em models, forms, views e templates;
- revisar microcopias de permissoes e mensagens de erro;
- padronizar layout das telas de configuracao para leitura administrativa rapida.

Resultado esperado:
- experiencia de administracao mais profissional;
- menos ruido e menor risco de erro operacional.

### Fase Cfg2 - Refatoracao modular da app
Status: concluida
Prioridade: alta

Objetivo:
- reduzir acoplamento e facilitar manutencao.

Escopo:
- quebrar `views.py` em modulos por dominio:
  - `view_modules/painel.py`
  - `view_modules/usuarios.py`
  - `view_modules/empresa.py`
  - `view_modules/catalogo.py`
  - `view_modules/integracoes.py`
  - `view_modules/operacao.py`
- mover regras nao-visuais para services dedicados;
- manter rotas e comportamento atual para nao causar regressao funcional.

Resultado esperado:
- codigo mais legivel e escalavel;
- menor risco em futuras evolucoes de API e SaaS.

### Fase Cfg3 - Governanca de permissoes e acessos
Status: concluida
Prioridade: alta

Objetivo:
- consolidar um modelo de permissao mais escalavel que dezenas de flags no `User`.

Escopo:
- manter compatibilidade com flags atuais e introduzir camada de capabilities;
- criar presets por funcao operacional (ex.: atendente caixa, tecnico campo, gerente filial);
- adicionar simulador de impacto de permissao no cadastro de usuario.

Resultado esperado:
- gestao de acessos mais simples para operacao;
- trilha mais segura para crescimento de funcionalidades.

### Fase Cfg4 - Seguranca operacional e auditoria de configuracoes
Status: concluida
Prioridade: alta

Objetivo:
- fortalecer operacoes criticas e rastreabilidade.

Escopo:
- endurecer fluxo de backup/restore:
  - restore apenas por POST com confirmacao explicita;
  - validacao de caminho/arquivo permitidos;
- criar trilha de auditoria de configuracoes:
  - quem alterou;
  - quando;
  - antes/depois;
  - origem (UI/comando/API);
- painel de eventos criticos para administracao.

Resultado esperado:
- menor risco de operacao sensivel;
- governanca forte para ambientes multiusuario.

### Fase Cfg5 - Integracoes e camada de APIs
Status: concluida
Prioridade: media/alta

Objetivo:
- preparar a app para crescimento de integracoes externas.

Escopo:
- criar service de integracoes (inicio com CEP):
  - timeout/config central;
  - fallback entre provedores;
  - cache curto e telemetria de falhas;
- estruturar base para novos conectores:
  - WhatsApp API;
  - Email transacional;
  - gateways financeiros;
  - ERPs/parceiros.
- definir contrato de webhooks internos (eventos de OS, expedicao, pagamento).

Resultado esperado:
- integracoes mais confiaveis;
- base tecnica pronta para ampliar ecossistema.

### Fase Cfg6 - Preparacao SaaS (foundation)
Status: concluida
Prioridade: media/alta

Objetivo:
- iniciar fundacao tecnica para evolucao futura SaaS.

Escopo:
- definir estrategia de isolamento:
  - single DB com coluna `tenant_id` (fase inicial) ou schema por tenant (avaliacao);
- mapear modelos que exigem escopo de tenant;
- introduzir camada de resolucao de tenant (subdominio/chave de acesso);
- checklist de readiness SaaS:
  - seguranca de sessao;
  - limites por plano;
  - auditoria e LGPD;
  - observabilidade por tenant.

Resultado esperado:
- caminho de migracao para SaaS com menor retrabalho;
- arquitetura orientada a crescimento.

### Fase Cfg7 - Homologacao final e governanca continua
Status: concluida
Prioridade: media

Objetivo:
- validar ponta a ponta a app `configuracoes` apos refatoracoes;
- institucionalizar rotina de governanca tecnica.

Escopo:
- checklist de homologacao por perfil (adm, gerente, atendente, tecnico);
- regressao automatizada obrigatoria em PostgreSQL;
- validacao de comandos operacionais (backup, restore, check_go_live, check_postgres_ready);
- playbook de operacao e incidentes.

Resultado esperado:
- modulo pronto para operacao robusta;
- base segura para novas fases de integracao e SaaS.

## Roadmap sugerido

1. Cfg1 - estabilidade textual e UX
2. Cfg2 - refatoracao modular
3. Cfg4 - seguranca operacional e auditoria
4. Cfg3 - governanca de permissoes (modelo escalavel)
5. Cfg5 - integracoes e camada de APIs
6. Cfg6 - preparacao SaaS foundation
7. Cfg7 - homologacao final e governanca continua

## Entregas incrementais sugeridas

Entrega A:
- Cfg1 concluida + baseline visual e textual da app.

Entrega B:
- Cfg2 concluida com `views` modularizadas e services centrais.

Entrega C:
- Cfg4 + Cfg3 com trilha de auditoria e permissoes evoluidas.

Entrega D:
- Cfg5 + Cfg6 com fundacao de integracoes e readiness SaaS.

Entrega E:
- Cfg7 com homologacao formal e playbook operacional.

## Progresso executado

Atualizado em 14/05/2026

- Cfg2: `configuracoes/views.py` modularizada em `view_modules` por dominio (painel, usuarios, empresa, sistema, catalogo, operacao, integracoes), mantendo as mesmas rotas.
- Cfg4: fluxo de restore endurecido para POST com confirmacao explicita e validacao de caminho permitido.
- Cfg4: modelo de auditoria de configuracoes criado (`ConfiguracaoAuditoria`) com migracao aplicada.
- Cfg4: tela administrativa de auditoria criada (`/configuracoes/auditoria/`) com filtro por acao/origem e paginacao.
- Cfg5: consulta de CEP extraida para service dedicado com fallback de provedores e cache curto.
- Cfg3: base de presets/capabilities iniciada com service e aplicacao opcional no formulario de usuario.
- Cfg3: simulador de impacto de permissoes por preset disponivel no cadastro de usuario.
- Cfg6: TenantContextMiddleware introduzido com resolucao por query/header/subdominio e fallback seguro.
- Cfg6/Cfg7: comando `check_saas_readiness` adicionado para diagnostico de prontidao tenant em modelos criticos.
- Cfg6/Cfg7: escopo explicito por `empresa` aplicado nos modelos criticos `Cliente`, `OrdemServico`, `Orcamento`, `Produto`, `ContaReceber` e `ContaPagar`, com migracoes e validacao em PostgreSQL.
- Cfg4: trilha de auditoria expandida para operacoes de usuarios e catalogo administrativo.
- Cfg5: contrato de webhooks internos publicado em `/configuracoes/integracoes/webhooks/contrato/`.
- Cfg7: checklist e relatorio de homologacao dedicados para configuracoes adicionados em `docs/`.
