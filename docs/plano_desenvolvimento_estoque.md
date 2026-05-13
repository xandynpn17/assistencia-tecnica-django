# Plano de Desenvolvimento do Estoque

## Objetivo

Evoluir o app `estoque` com foco em operacao diaria, confiabilidade transacional, clareza visual e integracao segura com OS, caixa e reservas.

## Principios

- preservar os fluxos que ja funcionam antes de refatorar;
- melhorar primeiro o que impacta mais a rotina da equipe;
- centralizar regras criticas em services transacionais;
- manter a diferenca entre produto, peca, consumivel e servico sem prejudicar a conciliacao com orcamentos;
- documentar cada fase conforme for concluida.

## Diagnostico resumido

- o app ja cobre cadastro, saldo por ponto, movimentacoes, reservas, inventario, consulta de artigos e indicadores;
- ha boa cobertura de testes e varias operacoes criticas ja usam transacoes;
- parte das regras ainda esta espalhada entre models, helpers e views;
- ainda existem textos com encoding quebrado em models, services e templates;
- algumas telas operacionais ainda podem ficar mais claras e mais rapidas de usar;
- o model `Produto` concentra responsabilidades demais;
- `tipo_item` e `is_servico` coexistem e exigem disciplina para nao gerar ambiguidade.

## Fases

### Fase E1 - Estabilidade textual e refinamento visual
Status: concluida
Prioridade: alta

Objetivo:
- corrigir encoding/mojibake nas telas e textos do estoque;
- melhorar compreensao das telas mais usadas no dia a dia.

Escopo desta fase:
- normalizacao de labels, mensagens e `choices` visiveis;
- refinamento visual nas telas operacionais iniciais do estoque;
- documentacao formal do roadmap do modulo.

Feito nesta etapa:
- roadmap do estoque documentado neste arquivo;
- `docs/README.md` atualizado para incluir esta fonte ativa;
- correcoes de encoding aplicadas em modelos, services e templates visiveis do estoque;
- limpeza complementar feita nas telas de consulta de artigos e indicadores;
- tela de nova movimentacao refinada com melhor hierarquia visual, orientacao de uso e leitura mais rapida;
- tela de importacao em lote refinada com orientacoes operacionais, colunas recomendadas e leitura mais clara do preview;
- validacao tecnica concluida com `manage.py check`;
- tentativa de executar a suite automatizada bloqueada por problema local no Python launcher desta sessao.

### Fase E2 - Regras criticas em services
Status: concluida
Prioridade: alta

Objetivo:
- consolidar as regras de movimentacao, reserva, inventario e ajuste em services mais claros;
- reduzir duplicacao entre views, helpers e services.

Resultado esperado:
- uma trilha unica para operacoes sensiveis;
- menor risco de saldo inconsistente e regressao.

Andamento atual:
- `estoque/services.py` passou a concentrar registro transacional de movimentacao manual;
- criacao de reserva foi extraida para service dedicado;
- finalizacao de inventario agora usa service centralizado;
- transferencias por busca de artigo e reposicao inteligente passaram a reaproveitar a mesma trilha de movimentacao;
- fluxo de PDV/pre-reserva/cesto passou a usar services para criar item, resumir cesto, finalizar guia e remover item;
- views de estoque ficaram mais finas e menos acopladas a regra de saldo.

### Fase E3 - Clarificacao do dominio de produto
Status: concluida
Prioridade: alta

Objetivo:
- manter a distincao entre servico e peca/produto;
- reduzir ambiguidade entre `tipo_item` e `is_servico`;
- aliviar o peso do `Produto.save()`.

Resultado esperado:
- conciliacao mais segura com OS e orcamentos;
- dominio mais previsivel e facil de manter.

Feito nesta etapa:
- `tipo_item` passou a ser a fonte principal para distinguir servico e estoque fisico;
- `ProdutoQuerySet` ganhou atalhos semanticos como `servicos()` e `nao_servicos()`;
- filtros e regras de rateio, consulta, sugestao de pecas e movimentacao foram alinhados ao novo criterio;
- `is_servico` foi mantido apenas como espelho de compatibilidade para nao quebrar dados legados;
- o formulario de produto deixou de depender do campo oculto `is_servico`.

### Fase E4 - Permissoes granulares do estoque
Status: concluida
Prioridade: media/alta

Objetivo:
- separar permissao de consulta, cadastro e acao critica;
- proteger inventario, ajuste, transferencia e cancelamentos sensiveis.

Resultado esperado:
- mais seguranca sem travar a operacao.

Feito nesta etapa:
- novas permissoes granulares adicionadas ao usuario:
  - cadastro/edicao de produto;
  - exclusao de produto;
  - ajuste manual;
  - transferencia/reposicao;
  - finalizacao de inventario;
  - conversao de reserva;
  - cancelamento de reserva;
- formulario de usuarios atualizado para expor os controles no painel;
- endpoints sensiveis do estoque passaram a exigir permissao especifica;
- migracao de compatibilidade semeou os usuarios atuais de estoque para evitar regressao operacional imediata.

### Fase E5 - Performance e escala
Status: concluida
Prioridade: media

Objetivo:
- otimizar listas, indicadores e relatorios;
- revisar consultas mais pesadas com volume real.

Resultado esperado:
- navegacao mais fluida e menor custo em consultas recorrentes.

Andamento atual:
- reposicao inteligente deixou de consultar saldo produto a produto em loop;
- indicadores passaram a usar agregacoes para ruptura, abaixo do minimo, parados e valor de estoque;
- relatorio de divergencias passou a filtrar produtos abaixo do minimo direto em banco.
- indices de banco adicionados para filtros frequentes de movimentacoes, reservas e venda rapida.
- API de consulta de artigos passou a usar `values()` para reduzir materializacao de objetos.
- API de resumo do artigo passou a buscar apenas campos necessarios nas consultas relacionadas.

### Fase E6 - Auditoria operacional do estoque
Status: concluida
Prioridade: media

Objetivo:
- ampliar rastreabilidade de eventos do estoque;
- padronizar trilha de auditoria por produto, ponto e usuario.

Resultado esperado:
- investigacao e suporte mais rapidos;
- confianca maior em divergencias e ajustes.

Andamento atual:
- eventos de estoque passaram a usar uma trilha padronizada (`estoque_evento`) para transferencia, reserva, inventario e pre-reserva;
- o modulo ja combina essa trilha com historico de cadastro de produto, facilitando suporte e leitura operacional.
- eventos passaram a ser persistidos em banco (`EstoqueEvento`) com indices por evento, usuario, produto e ponto.
- pagina de auditoria operacional adicionada com filtros por evento, usuario, periodo e busca geral.

### Fase E7 - Homologacao e consolidacao final
Status: concluida (homologacao automatizada e consolidacao final)
Prioridade: media

Objetivo:
- validar fluxos completos por perfil;
- fechar checklist operacional do modulo.

Resultado esperado:
- modulo pronto para uso mais intenso e para evolucoes futuras no novo banco.

Andamento atual:
- checklist operacional de homologacao criado em `docs/checklist_homologacao_estoque.md`;
- homologacao automatizada concluida no PostgreSQL com suite principal (`core ordens estoque caixa orcamentos configuracoes`) sem falhas.
- consolidacao por perfil e auditoria encerrada com testes dedicados no modulo:
  - `estoque.tests` (`86 testes OK` em PostgreSQL 5433);
  - `configuracoes.tests.PermissoesSensiveisHelperTests` + `PermissoesConfiguracoesTests` (`37 testes OK`).
- eventos operacionais esperados passaram a ter assercao nominal em teste dedicado.
