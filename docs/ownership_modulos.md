# Ownership Tecnico dos Modulos

## Objetivo

Registrar de forma curta onde cada fluxo deve ser mantido hoje, para reduzir manutencao no arquivo errado.

## Ownership atual

- `core`
  - ownership: autenticacao, dashboard, base visual e mensagens globais.
  - evitar: colocar regra de negocio operacional aqui.

- `clientes`
  - ownership: cadastro, busca, consolidacao e historico basico de cliente.
  - evitar: espalhar regra de OS ou caixa no app.

- `ordens`
  - ownership: ponto principal de entrada visual e operacional da OS.
  - inclui: status, linha de trabalho, orientacao operacional, detalhes tecnicos, toolbars por aba e bloqueios de contexto.
  - evitar: duplicar logica sensivel que ja mora em services ou no app `orcamentos`.

- `ordens/services`
  - ownership: regras criticas da OS.
  - ponto oficial atual:
    - `fechamento_os.py`: fechamento, reabertura e transicoes sensiveis ligadas ao encerramento.
    - `resumo_operacional.py` e `fluxo_os_policy.py`: leitura operacional e matriz de status.

- `orcamentos`
  - ownership: logica oficial de aprovacao, recusa, migracao e manutencao de itens de orcamento.
  - regra pratica: a OS e a entrada visual; `orcamentos` e o dono da regra.

- `orcamentos/services`
  - ownership: fluxo central de orcamento.
  - ponto oficial atual:
    - `fluxo_orcamento.py`: aprovar, recusar e migrar itens aprovados.

- `estoque`
  - ownership: catalogo, saldo, reservas, inventario e sugestoes de pecas.
  - evitar: colocar regra de fechamento de OS aqui; integrar por service/helper.

- `caixa`
  - ownership: recebimentos, pagamentos, contas, comissoes, DRE e auditoria financeira.
  - regra pratica: operacoes financeiras sensiveis devem respeitar permissao granular e auditoria.

- `configuracoes`
  - ownership: usuario, perfil base, permissoes sensiveis e parametros globais.
  - ponto oficial atual:
    - `permissions.py`: helper central de permissao sensivel.

## Regras de manutencao

- Fluxo visual da OS: priorizar `ordens/templates` e `ordens/view_modules`.
- Regra sensivel: priorizar `services/` antes de crescer view.
- Permissao por acao: priorizar `configuracoes/permissions.py` e campos do usuario.
- Historico antigo: consultar `docs/legacy_code/`, mas nao usar como fonte de implementacao nova.

## Antipadroes a evitar

- reintroduzir rota duplicada de orcamento dentro de `ordens`;
- espalhar regra de aprovacao/recusa em multiplas views;
- reativar arquivo legado fora de `docs/legacy_code/`;
- misturar permissao de menu com permissao de acao sensivel.
