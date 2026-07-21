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

## Ciclo 2 - Produto interno, venda local e preparacao progressiva para SaaS

Atualizado em 16/05/2026

### Contexto de produto

Nesta fase, o sistema sera usado inicialmente de forma interna na empresa principal e possivelmente em uma segunda empresa familiar, com instalacao local ou ambiente online apenas para teste/homologacao.

Render, neste momento, deve ser tratado como ambiente de teste e demonstracao, nao como operacao SaaS definitiva.

Direcao recomendada:
- manter uma versao local/interna robusta e vendavel para empresas pequenas;
- preparar o sistema para instalacao assistida com PostgreSQL, backup, usuario admin inicial e checklist de atualizacao;
- evoluir para SaaS apenas depois de validar o uso real, endurecer tenant obrigatorio e amadurecer suporte, billing, observabilidade e isolamento de dados.

### Principios do ciclo 2

- Operacao da loja nao deve ser travada: atendente e tecnico precisam abrir, tratar, vender, finalizar e acompanhar sua rotina.
- Risco financeiro e fraude devem ser protegidos: faturamento, DRE, comissoes gerais, exclusao de pagamentos e configuracoes criticas ficam restritos.
- Dados que comprometem rastreabilidade do equipamento devem ser protegidos: numero de serie, identificadores sensiveis e dados confirmados da OS exigem permissao especifica.
- Configuracoes devem virar o painel de controle do produto: regras, documentos, alertas, garantias, integracoes, usuarios e readiness comercial.
- SaaS deve ser preparado em camadas, sem obrigar complexidade antes de o produto estar validado em operacao real.

## Fases do ciclo 2

### Fase Cfg8 - Higiene tecnica, textos e preparo para internacionalizacao
Status: concluida
Prioridade: alta

Objetivo:
- eliminar mojibake e textos quebrados remanescentes;
- padronizar labels, mensagens e textos administrativos;
- preparar o caminho para traducao futura, moedas e formatos internacionais.

Escopo:
- varrer models, forms, templates, services, commands e PDFs em busca de caracteres quebrados;
- corrigir labels como `Usuário`, `Técnico`, `Configurações`, `Crédito`, `Número` e similares;
- criar teste de guarda mais abrangente contra mojibake;
- documentar padrao UTF-8 e regra de escrita de novos textos;
- iniciar convencao para futura extracao de textos com `gettext`, sem traduzir tudo agora.

Resultado esperado:
- interface mais profissional;
- menor risco de regressao textual;
- base pronta para idioma, moeda e tributacao por pais em ciclo futuro.

Progresso atual:
- varredura inicial de mojibake executada nos fontes da app `configuracoes` (excluindo migrations);
- correcoes aplicadas em `configuracoes/forms.py` para labels, mensagens de validacao e help texts quebrados;
- ajuste em `configuracoes/tests.py` para manter o teste anti-mojibake sem depender de literal corrompido.
- refinamento visual da app `configuracoes` iniciado com centrais de navegacao por contexto:
  - `Central Operacional` para empresa, OS e sistema;
  - `Catálogo e Atendimento` para marcas, tipos e mensagens;
  - `Operação e Recuperação` para painel, backup, restore, auditoria e logs.
- painel principal reorganizado com:
  - resumo rapido de saude operacional;
  - bloco “como usar” para orientar o gestor;
  - atalhos criticos para backup, restore, auditoria e integracoes;
  - cobertura automatizada adicional para garantir a renderizacao desses atalhos.
- recuperacao local sem login refinada com:
  - tela publica de restore mais orientada para contingencia;
  - link visivel no login, painel, backup e restore quando habilitada;
  - fallback por terminal documentado na propria interface e na documentacao operacional.

### Fase Cfg9 - Permissoes 2.0: perfis operacionais e riscos
Status: concluida
Prioridade: alta

Objetivo:
- reduzir confusao entre tipo de usuario, preset e permissoes individuais;
- preservar liberdade operacional para atendente e tecnico;
- proteger dados financeiros, configuracoes e acoes com risco de fraude.

Modelo funcional desejado:
- `Atendente`: pode abrir, tratar e finalizar OS, realizar venda, cancelar venda operacional dentro de regra, consultar seu desempenho/comissao individual.
- `Tecnico`: pode tratar OS, registrar diagnostico/servico, finalizar etapa tecnica e consultar sua comissao individual.
- `Gerente`: ve financeiro, indicadores, comissoes da equipe e pode liberar excecoes.
- `Administrador`: controla configuracoes criticas, usuarios, regras e auditoria.

Permissoes sensiveis por categoria:
- Financeiro: DRE, faturamento, relatorios financeiros, comissoes gerais, excluir pagamento, cancelar conta, aplicar desconto critico.
- Rastreabilidade da OS: alterar numero de serie, dados confirmados, tecnico responsavel, reabrir OS fechada, excluir servico/peca.
- Estoque: ajuste manual, inventario, transferencia, cancelamento de reserva, exclusao de produto.
- Sistema: configuracoes gerais, documentos, integracoes, backup/restore, usuarios e permissoes.

Entregas:
- tela de usuario reorganizada por `Perfil operacional`, `Acessos da rotina`, `Permissoes sensiveis` e `Risco liberado`;
- resumo antes de salvar indicando impactos reais do perfil;
- presets renomeados para linguagem de loja;
- testes de permissao para garantir que atendente/tecnico operam a loja sem ver faturamento ou alterar dados criticos.

Resultado esperado:
- permissao fica compreensivel para o dono/gerente;
- operacao nao trava;
- riscos financeiros e de rastreabilidade ficam explicitamente protegidos.

Progresso atual:
- simulador de permissoes evoluido para aceitar overrides do formulario e calcular risco consolidado;
- resumo de risco por categoria implementado (`financeiro`, `rastreabilidade_os`, `estoque_critico`, `sistema`);
- tela de cadastro/edicao de usuario reorganizada por perfil operacional, acessos da rotina e permissoes sensiveis por categoria;
- resumo dinamico \"antes de salvar\" com nivel de risco (`baixo`, `moderado`, `alto`, `critico`) e lista de permissoes ativas;
- testes expandidos para cobrir retorno de `resumo_risco` e aplicacao de overrides no simulador.

### Fase Cfg10 - Documentos e PDFs profissionais configuraveis
Status: concluida
Prioridade: alta

Objetivo:
- padronizar PDFs sem gambiarras visuais;
- permitir escolha de layout pelo usuario nas configuracoes;
- tornar documentos claros para atendente, cliente e parceiro.

Layouts sugeridos:
- `Classico`: completo, formal, adequado para cliente.
- `Compacto`: economico, ideal para impressao rapida.
- `Parceiro`: foco em expedicao, retorno e dados tecnicos.
- `Tecnico`: foco em diagnostico, servicos, pecas e assinatura.

Configuracoes por layout:
- logo e logo PDF;
- cor principal;
- rodape e termos;
- campos visiveis;
- exibicao de etiqueta/corte;
- assinatura de entrada/saida;
- observacoes e clausulas.

Entregas:
- service/base de PDF com componentes reutilizaveis: cabecalho, bloco de dados, tabela, status, assinatura, rodape;
- truncamento/quebra de texto por largura real;
- preview visual nas configuracoes quando viavel;
- testes com nomes longos, textos longos e campos vazios.

Resultado esperado:
- PDFs consistentes e profissionais;
- menor risco de sobreposicao;
- documentos com percepcao de produto maduro.

Progresso atual:
- presets de documento ampliados com opcoes `tecnico` e `parceiro` para contexto operacional distinto;
- tema visual e perfil tipografico/espacamento dos novos presets implementados em `core/pdf_theme.py`;
- comparador de presets na configuracao do sistema atualizado para incluir os novos presets nas duas colunas de preview.

### Fase Cfg11 - SLA, alertas e painel de pendencias
Status: concluida
Prioridade: alta

Objetivo:
- transformar tempo parado em alerta acionavel;
- reduzir esquecimento operacional;
- alimentar indicadores da gestao.

Regras configuraveis iniciais:
- OS parada sem movimentacao;
- orcamento sem resposta;
- peca reservada vencendo;
- equipamento pronto ha muitos dias;
- parceiro externo atrasado.

Configuracoes por regra:
- ativo/inativo;
- prazo em horas/dias;
- severidade;
- responsavel padrao;
- acao sugerida;
- canal futuro de notificacao.

Entregas:
- modelos de regra de SLA/alerta;
- service para calcular pendencias;
- painel operacional de alertas;
- badges nas telas de OS, estoque e expedicao;
- integracao com indicadores.

Resultado esperado:
- equipe sabe o que esta atrasado antes do cliente reclamar;
- indicadores passam a mostrar gargalos reais.

Progresso atual:
- modelo `RegraSLAAlerta` criado em `configuracoes` para regras configuraveis com prazo, severidade, responsavel, acao e canal;
- service de calculo em `configuracoes/services/sla.py` cobrindo:
  - OS sem movimentacao;
  - orcamento sem resposta;
  - peca reservada vencendo;
  - equipamento pronto parado;
  - parceiro externo atrasado;
- tela de configuracao das regras: `configuracoes:regras_sla`;
- painel operacional com filtros e paginacao: `configuracoes:painel_sla`;
- atalhos adicionados no painel de configuracoes e menu lateral.
- badges de SLA adicionadas no menu lateral e cards de pendencia no dashboard gerencial.

### Fase Cfg12 - Garantia pos-servico e reincidencia
Status: concluida
Prioridade: alta

Objetivo:
- controlar garantia por item/servico;
- identificar reincidencia por cliente/equipamento;
- vincular OS de garantia a OS original.

Escopo:
- prazo de garantia por servico, peca, tipo de reparo ou regra geral;
- OS de garantia vinculada a OS original;
- classificacao de retorno: mesmo defeito, novo defeito, mau uso, garantia de peca, garantia de mao de obra;
- indicador de retorno por tecnico, peca, marca e tipo de equipamento.

Entregas:
- campos/modelos para vinculo de garantia;
- alerta de OS em garantia ao abrir nova ordem para mesmo cliente/equipamento;
- painel de reincidencias;
- indicadores de qualidade tecnica e produto.

Resultado esperado:
- melhor controle de custo de garantia;
- leitura clara de problemas recorrentes;
- base para melhorar qualidade e treinamento.

Progresso atual:
- abertura de OS agora aceita vinculo com OS original de garantia de servico;
- classificacao de retorno adicionada (mesmo defeito, novo defeito, mau uso, garantia de peca, garantia de mao de obra);
- deteccao automatica de possivel reincidencia na abertura quando ha OS fechada recente similar;
- configuracao de garantias padrao e janela de reincidencia adicionada em Configuracoes do Sistema;
- resumo da OS exibe vinculo de garantia/reincidencia para o atendente.
- painel de reincidencias por tecnico, marca, tipo de equipamento, item e classificacao de retorno em `configuracoes:painel_reincidencias`.

### Fase Cfg13 - Integracoes, mensagens e automacoes
Status: concluida
Prioridade: media/alta

Objetivo:
- centralizar canais e logs de comunicacao;
- manter WhatsApp Web como caminho atual;
- preparar troca futura para API/automatizacoes sem reescrever fluxos.

Progresso atual:
- log estruturado de integracoes criado (`IntegracaoEventoLog`) com canal, evento, status, destino e resposta;
- envio de notificacoes (sistema, e-mail e WhatsApp) agora registra sucesso/falha em log de integracao;
- emissao de webhook interno passou a registrar tentativas e falhas com rastreabilidade;
- tela gerencial `configuracoes:logs_integracoes` adicionada com filtros e paginacao;
- atalhos adicionados no painel e menu de Configuracoes.
- catalogo de eventos operacionais publicado na tela de modelos de mensagem;
- carregamento automatico de modelos por evento implementado com atualizacao em lote.

Escopo:
- catalogo de eventos: OS criada, orcamento pronto, orcamento aprovado, equipamento pronto, expedicao criada, retorno de parceiro, garantia aberta;
- templates por evento;
- canal configuravel: WhatsApp Web, email, API futura, webhook;
- log de envio/tentativa;
- fallback manual quando API falhar.

Resultado esperado:
- comunicacao deixa de depender de memoria do atendente;
- autorizacoes e assinaturas futuras entram por evento, nao por improviso.

### Fase Cfg14 - SaaS-ready e modo comercial local
Status: concluida
Prioridade: media/alta

Objetivo:
- preparar o produto para venda local agora e SaaS depois;
- fortalecer tenant sem obrigar operacao SaaS imediata.

Escopo local/comercial:
- checklist de instalacao local;
- modo empresa unica;
- backup/restore orientado;
- atualizacao assistida;
- verificacao de ambiente (`check_go_live`, `check_postgres_ready`, `check_saas_readiness`);
- remocao de `staticfiles` versionado e uso correto de `collectstatic`.

Escopo SaaS futuro:
- tenant obrigatorio em queries e services;
- comandos para detectar objetos sem empresa;
- limites por plano;
- auditoria por tenant;
- resolucao por dominio/subdominio;
- politica de dados, LGPD e exportacao por cliente.

Resultado esperado:
- produto vendavel localmente com manutencao previsivel;
- caminho SaaS tecnico claro, sem pular etapas.

Progresso atual:
- `staticfiles/` adicionado ao `.gitignore` como artefato de deploy;
- arquivos de `staticfiles/` removidos do versionamento com `git rm -r --cached staticfiles`;
- projeto alinhado ao fluxo correto de publicacao com `collectstatic` no build/deploy.
- comando `check_tenant_data` criado para validar registros sem `empresa` nos modelos criticos;
- `check_go_live` reforcado com validacao de `SECRET_KEY`, conectividade do banco ativo e alerta de `STATIC_ROOT`.
- checklist operacional local documentado em `docs/checklist_go_live_local.md`.

## Ordem recomendada do ciclo 2

1. Cfg8 - Higiene tecnica e textos.
2. Cfg9 - Permissoes 2.0.
3. Cfg14 - Staticfiles, modo local comercial e readiness.
4. Cfg10 - PDFs profissionais configuraveis.
5. Cfg11 - SLA e alertas.
6. Cfg12 - Garantia pos-servico e reincidencia.
7. Cfg13 - Integracoes e automacoes.
8. Revisao SaaS final dentro da Cfg14, somente apos validacao em uso real.

## Criterios de aceite do ciclo 2

- Atendente e tecnico conseguem operar loja sem acesso a faturamento, DRE, comissoes gerais ou configuracoes criticas.
- Acoes de risco ficam bloqueadas por permissao sensivel e registradas em auditoria quando aplicavel.
- Textos visiveis nao apresentam mojibake.
- PDFs principais usam padrao profissional e suportam textos longos.
- Alertas mostram OS/orcamentos/reservas/parceiros atrasados de forma acionavel.
- Garantia pos-servico identifica reincidencia e vincula OS original.
- `staticfiles` deixa de ser fonte versionada e passa a ser artefato de deploy.
- SaaS permanece como caminho preparado, nao como dependencia para vender localmente.





