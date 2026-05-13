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
- Ownership tecnico dos apps documentado em `docs/ownership_modulos.md`.
- Interface principal da OS refinada para reduzir dispersao de acoes entre abas e reforcar a OS como centro operacional.

## Pontos que ainda exigem evolucao

1. Expandir a disciplina de services para novos fluxos compostos que ainda crescerem nas views.
2. Concluir refinamentos funcionais finos antes da rodada final de banco.
3. Preparar migracao para PostgreSQL com validacao real em base limpa.

## Decisao tecnica vigente

- Manter arquitetura modular atual e evoluir por refatoracoes incrementais.
- Evitar criacao de novos apps enquanto houver ganho maior em consolidacao dos fluxos existentes.
- Tratar `docs/legacy_code/` apenas como historico de consulta.
- Usar `docs/ownership_modulos.md` como referencia curta antes de qualquer refatoracao transversal.
