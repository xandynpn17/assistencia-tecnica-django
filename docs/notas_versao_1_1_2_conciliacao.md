# Versão 1.1.2 — conciliação e correção financeira

## O que foi corrigido

- A criação de um movimento a partir de uma linha do extrato passa a gerar um único movimento bancário.
- Movimentos conciliados, divergentes ou neutralizados não voltam a aparecer entre os candidatos de conciliação.
- Tentativas repetidas ou simultâneas de conciliar o mesmo fato retornam uma mensagem controlada, sem erro 500.
- Antes de criar um fato novo com a mesma data e valor de um movimento existente, o sistema alerta sobre a possível duplicidade e exige confirmação expressa.

## Correção e cancelamento

Na tela **Caixa > Corrigir lançamentos**, o usuário autorizado pode:

- mostrar todos os lançamentos manuais ativos;
- corrigir descrição, valor, datas, meio de pagamento, conta/caixa, categoria e centro de custo;
- cancelar um lançamento manual com justificativa de pelo menos 12 caracteres;
- neutralizar duplicidades comprovadamente geradas pelo fluxo antigo de importação de extrato.

O cancelamento é lógico: o registro original permanece no banco, recebe status de cancelado e gera os estornos/contrapartidas necessários. O histórico registra usuário, data, motivo e valores anteriores/corrigidos.

## Datas retroativas

- Banco: o lançamento usa a conta e a data real informadas.
- Dinheiro: somente pode usar um caixa existente da mesma data do movimento.
- Uma correção retroativa não é transferida para o caixa aberto atual.
- Quando o caixa histórico está fechado, seu saldo final e diferença de conferência são recalculados com auditoria.

## Atualização técnica

Depois de atualizar o código, execute as migrações. A versão inclui a migração `caixa.0057`.

