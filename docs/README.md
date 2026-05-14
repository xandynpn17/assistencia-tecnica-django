# Documentacao Interna

## Fontes ativas

- `plano_desenvolvimento_sistema.md`: roadmap tecnico e status das fases.
- `plano_desenvolvimento_estoque.md`: roadmap tecnico especifico do modulo de estoque.
- `plano_desenvolvimento_caixa.md`: diagnostico e roadmap tecnico especifico do modulo de caixa.
- `plano_desenvolvimento_configuracoes.md`: diagnostico e roadmap tecnico da app configuracoes com foco em integracoes e preparacao SaaS.
- `entrega_1_fluxo_permissoes.md`: diagnostico inicial de fluxo e permissoes.
- `permissoes_por_perfil.md`: visao funcional de acessos por perfil.
- `revisao_arquitetura.md`: fotografia arquitetural atual do sistema.
- `ownership_modulos.md`: ownership tecnico atual por app e ponto oficial de manutencao.
- `checklist_homologacao_manual.md`: validacoes manuais de operacao.
- `checklist_homologacao_estoque.md`: roteiro de homologacao manual por perfil do estoque (Fase E7).
- `checklist_homologacao_configuracoes.md`: roteiro de homologacao manual por perfil da app configuracoes.
- `checklist_migracao_postgresql.md`: guia de validacao da futura migracao de banco.
- `relatorio_homologacao_estoque.md`: template operacional para registrar execucao manual da E7.
- `relatorio_homologacao_estoque_2026-05-13.md`: consolidacao da evidencia automatizada e pendencias manuais da E7.
- `relatorio_homologacao_postgresql_2026-05-12.md`: homologacao da migracao para PostgreSQL no ambiente de desenvolvimento.
- `relatorio_homologacao_configuracoes_2026-05-14.md`: consolidacao da evidencia automatizada da homologacao da configuracoes.

## Fontes historicas

- `legacy_code/`: codigo legado arquivado para consulta.
- `legacy_code/lista_funcoes_programa.txt`: inventario historico de funcoes (inclui legado).
- `legacy_code/resumo_funcoes_programa.txt`: resumo historico de contagem por modulo.

## Regra de uso

- Para manutencao e desenvolvimento, priorizar sempre as fontes ativas.
- Arquivos historicos devem ser tratados como referencia de auditoria, nao como fonte de implementacao.
- Quando houver duvida sobre "onde mexer", consultar primeiro `ownership_modulos.md`.
