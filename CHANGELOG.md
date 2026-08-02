# Changelog

## v1.0.0 - 2026-08-02

Primeira versao oficial padronizada do ABGest para uso local e em rede interna, com numero de release centralizado no codigo.

### Principais entregas
- versao oficial centralizada em `assistencia/version.py`;
- rodape e telas principais lendo a mesma referencia de versao;
- login exibindo release atual de forma discreta;
- alinhamento entre codigo, interface e changelog para futuras atualizacoes.

## v0.2.0 - 2026-05-13

Consolidacao do ciclo de evolucao operacional com foco em PostgreSQL, permissoes granulares, expedicoes e amadurecimento de estoque/caixa.

### Principais entregas
- Migracao e homologacao em PostgreSQL com `check_postgres_ready`, ajustes de compatibilidade e suite principal validada.
- Setup inicial orientado ao primeiro uso com catalogo de linhas/tipos de equipamento e fluxo de configuracao de empresa.
- Expedicoes de ordens com fluxo de envio/recepcao por parceiro, guias e status operacional dedicados.
- Permissoes granulares ampliadas por acao sensivel (ordens, estoque, caixa, configuracoes) com bloqueios consistentes.
- Estoque evoluido com services transacionais, auditoria operacional (`EstoqueEvento`), indicadores e testes reforcados.
- Caixa evoluido em services, comissoes, recebiveis/pagaveis, dashboards e cobertura de testes ampliada.
- Fechamento da Fase E7 do estoque com relatorios de homologacao e evidencias em PostgreSQL.

### Validacao
- Regressao principal em PostgreSQL: `478 testes OK` (`core ordens estoque caixa orcamentos configuracoes`).

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
