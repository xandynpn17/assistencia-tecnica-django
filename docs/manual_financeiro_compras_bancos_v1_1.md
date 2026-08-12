# Manual operacional — compras, custos, caixa, bancos e contabilidade gerencial

Versão 1.1.1 — 12/08/2026

## Regra central

O sistema separa competência (quando pertence ao resultado), vencimento (quando deve ser pago), movimento (quando caixa/banco muda) e registro (quando o usuário realizou a ação). Use sempre as datas reais.

## Compra específica para uma OS

Em **OS > Compras da OS**, crie o pedido e vincule internamente peça do orçamento, produto, fornecedor, quantidade, custo estimado e conta a pagar.

- **Uso direto na OS** cria custo real sem aumentar estoque.
- **Entrada no estoque** exige produto, ponto e localização; aumenta saldo e atualiza custo médio. A conta a pagar deve ser **Compra para estoque (ativo)**.

Recebimentos podem ser parciais. Estornos preservam o original e revertem custo ou estoque. Custos e margem nunca aparecem para o cliente. Uma peça manual precisa ter custo real confirmado antes do fechamento; quando for legitimamente zero, registre R$ 0,00 explicitamente.

## Contas a pagar

Informe emissão, competência, vencimento, natureza econômica, categoria, centro, documento e comprovante.

- **Despesa operacional** entra na DRE na competência.
- **Compra para estoque** permanece como ativo até consumo/venda.
- **Imobilizado** não vira despesa operacional imediata.
- Tributos, despesas financeiras e não operacionais ficam separados.

Ao pagar, escolha explicitamente caixa ou banco e a data real. Pagamentos parciais preservam o saldo. Estorno cria contrapartida; não apaga o histórico.

## Cartão corporativo

Em **Caixa > Cartões da empresa**, cadastre o cartão e registre compras com competência, categoria, centro, parcelas e eventual OS. A compra reconhece a despesa sem reduzir o banco. O banco é reduzido uma única vez ao pagar a fatura.

## Bancos e conciliação

Em **Bancos e conciliação**, importe OFX/CSV. Cada arquivo recebe hash e lote; repetir o mesmo arquivo não duplica linhas. Concilie individualmente ou em grupo. Ignorar exige justificativa.

O mês só fecha sem linhas pendentes e quando saldo do sistema e extrato são iguais. Após o fechamento, movimentos naquela data ficam bloqueados; correções exigem reabertura com permissão e motivo.

## Correção de lançamentos retroativos

Em **Caixa > Corrigir lançamentos**, o sistema lista entradas e saídas manuais cuja data do movimento não corresponde ao caixa físico vinculado. Selecione o item, informe a data real, meio de pagamento, banco ou caixa histórico, categoria, centro de custo e justificativa.

- correção para banco retira o valor do caixa indevido e gera o movimento na conta correta;
- correção para dinheiro exige que exista um caixa na mesma data;
- caixa histórico fechado tem saldo contábil e diferença recalculados, sem alterar o valor contado original;
- movimentos anteriores recebem contrapartida e permanecem na auditoria;
- período bancário fechado precisa ser reaberto antes da correção.

Novas saídas retroativas em dinheiro não podem mais ser vinculadas ao caixa atualmente aberto quando as datas forem diferentes.

## Capital e sócios

Capital social, AFAC e empréstimo de sócio aumentam caixa/banco, mas não receita. Devolução, amortização e redução de capital reduzem principal sem virar despesa. Juros são classificados separadamente. O sistema impede devolver mais que o saldo do aporte.

## Relatórios

O relatório gerencial mostra rentabilidade por OS (receita, custo, impostos, taxas, comissão e margem) e pendências de qualidade: peças sem custo, custos sem vínculo, banco sem conciliação e contas sem fechamento. A DRE usa competência e evita duplicar pagamento, custo da OS e aquisição de estoque.

## Contabilidade gerencial

Crie a estrutura inicial em **Contabilidade gerencial**, revise-a com o contador e só então ative registrando a validação. Novos eventos configurados passam a gerar partidas dobradas balanceadas. Correções usam estorno por partidas inversas. O módulo não substitui escrituração oficial.

## Checklist de homologação

- pagar obrigação parcialmente por banco e estornar;
- receber compra de OS para uso direto e para estoque;
- confirmar bloqueio de peça manual sem custo real;
- registrar compra parcelada e pagar fatura;
- importar o mesmo extrato duas vezes;
- conciliar e fechar um mês com diferença zero;
- corrigir uma saída retroativa ligada ao caixa atual e confirmar que ela passou para o banco ou caixa histórico;
- registrar AFAC e devolução parcial;
- testar permissões sensíveis;
- confirmar que PDFs do cliente não mostram custos;
- comparar tela, DRE e relatórios no mesmo período;
- ativar plano contábil somente após validação profissional.
