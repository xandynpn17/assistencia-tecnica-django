# Changelog

## v0.1.0 - 2026-02-28

Snapshot completo do sistema com foco em operacao de assistencia tecnica.

### Principais entregas
- Fluxo financeiro de garantia integrado a contas a receber por marca/fornecedor.
- Separacao de receita cliente vs receita garantia no painel financeiro.
- Policy central para bloqueio de edicoes criticas da OS com log discreto.
- Orcamentos padronizados com origem automatica por EAN (estoque) e manual quando digitado.
- Dashboard de pedidos de compra com filtros por status, tecnico e OS.
- Estoque com painel de divergencias (negativo, sem ubicacao, reservas vencidas).
- Notificacoes com placeholders e normalizacao de encoding em mensagens.
- Suite de testes para fluxos criticos (incluindo E2E de OS -> confirmacao -> orcamento -> notificacao -> fechamento -> caixa).

### Commit de snapshot
- `cd249d1`
