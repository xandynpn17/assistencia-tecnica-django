# Checklist de Homologacao - Estoque (Fase E7)

## Objetivo

Validar o modulo `estoque` ponta a ponta apos as fases E1-E6, com foco em operacao diaria, permissoes granulares, consistencia de saldo e rastreabilidade.

## Preparacao

1. Aplicar migracoes:
   - `py manage.py migrate configuracoes estoque`
2. Garantir usuarios de teste:
   - `atendente_completo` (com permissoes granulares de estoque habilitadas)
   - `atendente_restrito` (sem permissoes granulares criticas)
   - `tecnico` (perfil tecnico padrao)
   - `gerente` (perfil gerencial)
3. Garantir dados minimos:
   - produtos ativos de tipos diferentes (`produto`, `peca`, `consumivel`, `servico`)
   - pontos operacionais `PO2` e `PO3`
   - reservas ativas e pre-reservas recentes

## Cenarios por Perfil

### 1. Atendente Completo

- criar e editar produto;
- importar produtos;
- registrar movimentacao manual;
- transferir estoque entre pontos;
- executar reposicao inteligente;
- iniciar e finalizar inventario;
- converter e cancelar reserva.

Resultado esperado:
- fluxo completo sem bloqueio;
- mensagens de sucesso coerentes;
- saldos finais consistentes.

### 2. Atendente Restrito

- tentar criar produto;
- tentar excluir produto;
- tentar registrar ajuste manual;
- tentar transferir/reposicao;
- tentar finalizar inventario;
- tentar converter/cancelar reserva.

Resultado esperado:
- retorno `403` ou bloqueio equivalente por permissao;
- leitura de listas/consulta continua disponivel quando aplicavel.

### 3. Tecnico

- consultar artigos;
- criar reserva via fluxo operacional permitido;
- tentar venda a mostrador (se bloqueada pelo perfil).

Resultado esperado:
- operacoes permitidas funcionam;
- operacoes nao permitidas bloqueiam com mensagem clara.

### 4. Gerente

- validar que todas as operacoes sensiveis funcionam;
- validar indicadores e relatorio de divergencias com volume.

Resultado esperado:
- acesso completo sem regressao funcional.

## Cenarios Funcionais Criticos

1. Venda rapida com cesto:
   - criar item;
   - finalizar guia;
   - remover item em pre-reserva.
2. Reserva:
   - criar;
   - expirar;
   - converter;
   - cancelar.
3. Inventario:
   - iniciar;
   - adicionar itens;
   - finalizar com ajuste.
4. Transferencia PO2/PO3:
   - validar saldo de origem;
   - validar destino e ubicacao.
5. Indicadores:
   - ruptura;
   - abaixo do minimo;
   - valor de estoque;
   - top saidas.

## Verificacoes de Integridade

1. `SaldoEstoquePonto` por produto/ponto bate com regras de negocio.
2. `Produto.quantidade` consistente com consolidacao por pontos.
3. Reservas vencidas nao ficam ativas apos rotina de expiracao.
4. Nao existem saldos negativos indevidos apos fluxos validos.

## Verificacoes de Auditoria

Eventos esperados no log operacional (`estoque_evento`):
- `venda_pre_reserva_criada`
- `reserva_criada`
- `reservas_expiradas_execucao`
- `reserva_convertida`
- `reserva_cancelada`
- `transferencia_estoque`
- `inventario_finalizado`

## Criterio de Aceite

Para considerar homologado:
- 100% dos cenarios criticos aprovados;
- sem divergencia de saldo em fluxos validos;
- permissoes granulares respeitadas;
- sem regressao visual relevante nas telas operacionais.
