# Entrega — pessoas financeiras, investimentos, estornos e adquirentes

Data: 13/10/2026

## Resultado

Foi criada uma área separada em **Caixa > Pessoas e patrimônio**. Ela não altera o
fluxo rápido de pagamentos e saídas e não converte lançamentos históricos.

## Funcionalidades

### Pessoas e conta-corrente

- cadastro por empresa de sócio formal, ex-sócio, colaborador, pessoa relacionada e terceiro;
- conta-corrente imutável por pessoa;
- retirada aguardando classificação;
- despesa pessoal paga pela empresa;
- remuneração pendente de regularização;
- aporte, AFAC e empréstimos separados;
- bloqueio de aporte como saída;
- bloqueio de pró-labore e distribuição de lucros para pessoa não sócia;
- idempotência para impedir repetição do mesmo lançamento.
- vínculo de movimento bancário antigo sem criar outra entrada ou saída.

### Fechamento mensal

- filtro por competência;
- lista das movimentações da competência;
- classificação posterior sem modificar o fato financeiro original;
- classificação parcial ou integral;
- documento e justificativa;
- aprovação sujeita à permissão de correção financeira;
- relatório de saldo “empresa deve” e “pessoa deve”.

### Investimentos

- cadastro de conta de investimento vinculada ao banco;
- aplicação e resgate do principal como movimentação patrimonial;
- rendimento como resultado financeiro;
- IR, IOF e tarifa como custos financeiros;
- saldo de principal e rendimento líquido separados;
- proteção contra resgate superior ao principal disponível.
- reclassificação de aplicação/resgate antigo reutilizando o movimento bancário existente.

### Estornos

- estorno total ou parcial vinculado ao movimento financeiro original;
- estorno inicialmente sem origem, com vínculo posterior;
- contrapartida financeira auditável;
- proteção contra valor superior ao saldo da origem;
- idempotência contra repetição.

### SumUp e adquirentes

- importação CSV/PDF passa a preservar bruto, taxa, deduções e líquido;
- cada transação externa é única por conta de liquidação;
- repetições do arquivo não duplicam transações;
- painel apresenta totais e detalhamento;
- transferência SumUp para Nubank continua sendo registrada como transferência,
  sem reconhecer a venda novamente.

## Migração

Migração aditiva: `caixa.0072_patrimonio_pessoas_investimentos_estornos`.

Ela cria tabelas e índices e acrescenta a natureza `financeiro` ao livro financeiro.
Não remove colunas nem atualiza registros existentes.

## Implantação

1. criar backup completo;
2. atualizar o código;
3. executar o atualizador administrativo, que aplica as migrações;
4. confirmar `showmigrations caixa` com a migração 0072 marcada;
5. entrar em **Caixa > Pessoas e patrimônio**;
6. cadastrar primeiro as pessoas e contas de investimento;
7. registrar novos fatos financeiros somente após conferir o vínculo da pessoa;
8. revisar lançamentos históricos manualmente, sem duplicar o movimento bancário já existente.

## Reversão segura

Se a interface nova precisar ser temporariamente retirada, o código pode voltar à
versão anterior mantendo as novas tabelas no banco. Não se recomenda reverter a
migração depois que houver registros, pois isso eliminaria as tabelas novas.

Nenhuma correção de setembro deve ser feita por script. Use a interface e preserve o
lançamento original, a justificativa e a classificação correspondente.

## Validação

- `manage.py check`: aprovado;
- consistência de migrações: nenhuma alteração pendente;
- 11 testes específicos da nova área: aprovados;
- suíte completa da Caixa: 328 testes aprovados.

Casos cobertos: aporte em saída, vínculo societário, idempotência, RDB, rendimento,
estorno parcial, vínculo posterior de chargeback e importação SumUp sem duplicação.

Revisão final de pré-publicação em 14/10/2026: 110 testes integrados e 177 testes de
risco específico aprovados, além da suíte completa da Caixa já registrada. Não foram
encontradas operações destrutivas nas novas migrações nem credenciais nos arquivos da
entrega.
