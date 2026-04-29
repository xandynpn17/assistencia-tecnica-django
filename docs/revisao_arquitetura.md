# Revisao da Arquitetura Atual

## Estado atual

O sistema esta organizado em apps alinhados ao dominio:

- `core`: autenticacao, dashboard e base de templates.
- `clientes`: cadastro, busca e consolidacao de clientes.
- `ordens`: abertura e operacao da OS, historico e fluxo tecnico.
- `orcamentos`: itens, aprovacao/recusa e migracao para execucao.
- `estoque`: catalogo, movimentacao, reservas e inventario.
- `caixa`: recebimentos, contas, comissoes e relatorios.
- `configuracoes`: usuarios, perfis, permissoes e parametros globais.

## Consolidacoes ja aplicadas

- Fluxos criticos de OS centralizados em `ordens/services/fechamento_os.py`.
- Fluxo de orcamento centralizado em `orcamentos/services/fluxo_orcamento.py`.
- Permissoes sensiveis estruturadas em helper central (`has_sensitive_permission` / `require_sensitive_permission`).
- Codigo legado removido da area ativa e arquivado em `docs/legacy_code/`.

## Pontos que ainda exigem evolucao

1. Formalizar matriz de status da OS: `status -> acoes permitidas -> bloqueios`.
2. Expandir granularidade de permissoes para outras acoes sensiveis.
3. Consolidar entrada visual do orcamento para reduzir caminhos duplicados.
4. Fechar revisao de textos/encoding em todo fluxo de interface.
5. Preparar migracao para PostgreSQL com checklist tecnico reproducivel.

## Decisao tecnica vigente

- Manter arquitetura modular atual e evoluir por refatoracoes incrementais.
- Evitar criacao de novos apps enquanto houver ganho maior em consolidacao dos fluxos existentes.
- Tratar `docs/legacy_code/` apenas como historico de consulta.
