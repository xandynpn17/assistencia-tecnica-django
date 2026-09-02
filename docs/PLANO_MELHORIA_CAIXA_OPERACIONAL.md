# Plano de melhoria — Caixa operacional e fluxo de pagamentos

Data do plano: 30/08/2026

Status: núcleo da Fase 1 concluído em 30/08/2026; complementos da Fase 1 e Fases 2 a 6 permanecem planejados.

## Objetivo

Tornar recebimento, fechamento e conciliação mais rápidos no balcão, sem confundir:

- valor vendido;
- dinheiro físico;
- recebível de cartão;
- taxa financeira;
- depósito previsto;
- depósito efetivamente conciliado no banco.

## Situação já disponível

- Pagamento único e misto.
- Dinheiro recebido e cálculo de troco.
- Taxa percentual e fixa por modalidade, bandeira, parcelas e vigência.
- Previsão de bruto, taxa, líquido e prazo D+.
- Conta bancária de liquidação vinculada à maquininha.
- Separação de cobrança entre cliente, fabricante e item sem cobrança.
- Proteção contra duplicidade e registro técnico de falhas inesperadas.

## Modelo profissional para taxas de cartão

### Hierarquia de configuração

1. Adquirente: Stone, Rede, Cielo, Mercado Pago ou outro provedor.
2. Maquininha/contrato: identifica o terminal ou plano comercial.
3. Conta bancária de liquidação: conta que receberá os depósitos.
4. Regra de taxa: modalidade, bandeira, parcelas, vigência e prazo de recebimento.

### Campos da regra

- Modalidade: PIX, débito ou crédito.
- Bandeira: opcional; vazio significa regra geral.
- Parcelas inicial e final.
- MDR/taxa de processamento percentual.
- Tarifa fixa por transação.
- Regime de recebimento: normal ou antecipado.
- Taxa de antecipação, quando aplicável.
- Prazo de liquidação em dias.
- Data inicial e final de vigência.
- Situação ativa/inativa.

### Prioridade de aplicação

O sistema deverá buscar a regra nesta ordem:

1. Mesma maquininha + modalidade + bandeira + quantidade de parcelas + vigência.
2. Mesma maquininha + modalidade + regra geral sem bandeira + parcelas + vigência.
3. Regra geral legada da forma de pagamento, somente durante a transição.

Se a maquininha estiver configurada, mas não existir regra compatível, o pagamento deverá ser bloqueado ou exigir autorização gerencial explícita. Não deve assumir taxa zero silenciosamente.

### Cálculo básico

`taxa = valor bruto × percentual ÷ 100 + tarifa fixa`

`valor líquido previsto = valor bruto − taxa`

Exemplo:

- Venda: R$ 460,00
- Taxa efetiva: 3,913%
- Taxa calculada e arredondada: R$ 18,00
- Líquido previsto: R$ 442,00

A antecipação deverá aparecer separada da MDR, mesmo quando o sistema também mostrar uma taxa efetiva total. Isso facilita conferir o contrato e identificar alterações da adquirente.

### Exemplo de tabela

| Maquininha | Modalidade | Bandeira | Parcelas | MDR | Antecipação | Fixa | Prazo |
|---|---|---|---:|---:|---:|---:|---:|
| Stone Balcão | Débito | Geral | 1x | 1,49% | 0% | R$ 0,00 | D+1 |
| Stone Balcão | Crédito | Visa | 1x | 2,99% | 0% | R$ 0,00 | D+30 |
| Stone Balcão | Crédito | Visa | 2x–6x | 3,79% | 0% | R$ 0,00 | D+30 |
| Stone Balcão | Crédito | Geral | 7x–12x | 4,99% | 1,50% a.m. | R$ 0,00 | D+1 antecipado |

Os percentuais acima são apenas exemplos de estrutura; os valores reais devem vir do contrato, portal ou relatório da adquirente.

## Fase 1 — Recebimento rápido

Prioridade: alta.

### Entregue em 30/08/2026

- Bloco único de balcão com valor, forma, condições, troco, resumo e conclusão.
- Valor total carregado e protegido, com escolha explícita de pagamento parcial para OS.
- Formas de pagamento em atalhos; a última forma usada fica memorizada por empresa no navegador.
- Referência/NSU exibida somente para modalidades pertinentes.
- Bandeiras filtradas pela forma, maquininha, parcelas e vigência.
- Parcelas exibidas apenas quando possuem condição vigente.
- Bloqueio visual e de servidor quando faltar taxa compatível ou conta de liquidação.
- Previsão de bruto, taxa, líquido e data de crédito.
- Atalhos de cédulas aplicados ao valor entregue pelo cliente, sem alterar a dívida.
- F2 para valor, F3 para forma, F4 para concluir, proteção contra duplo envio e foco na próxima OS após sucesso.

Validação: 257 testes da aplicação Caixa aprovados; `manage.py check` e `makemigrations --check` sem pendências.

### Complementos planejados

- Busca por OS, cliente, telefone e referência de parceiro.
- Ordenação completa das formas de pagamento por frequência histórica, além da memória da última forma.
- Atalho “Salvar e próxima operação”.
- Substituição de confirmações do navegador por modal integrado.

### Critérios de aceite

- Um pagamento simples deve ser concluído sem rolagem excessiva.
- O operador não deve digitar novamente o saldo completo da OS.
- Uma taxa ausente não pode ser interpretada silenciosamente como zero.
- Reenvio da mesma operação não pode duplicar o pagamento.

## Fase 2 — Recebíveis de adquirente

Prioridade: alta.

### Desenvolvimento

- Criar entidade de recebível para cada parcela ou lote da adquirente.
- Status: previsto, pendente, liquidado, liquidado com divergência, estornado e chargeback.
- Registrar venda bruta e taxa no momento do pagamento.
- Manter o valor líquido como recebível previsto, sem tratá-lo imediatamente como saldo bancário confirmado.
- Transformar ou vincular o recebível ao movimento bancário quando houver conciliação.
- Suportar diferença de centavos, taxa divergente e depósito agrupado.

### Critérios de aceite

- Venda de R$ 460,00 gera R$ 18,00 de taxa e R$ 442,00 a receber.
- O saldo bancário confirmado só aumenta após liquidação/conciliação.
- O sistema consegue explicar qualquer diferença entre previsto e depositado.

## Fase 3 — Fechamento profissional

Prioridade: alta.

### Desenvolvimento

- Conferência física obrigatória apenas para dinheiro.
- PIX e transferência comparados com movimentos/extrato bancário.
- Cartão apresentado como bruto vendido, taxas, líquido previsto e situação de liquidação.
- Remover valores eletrônicos “conferidos” automaticamente sem ação real do usuário.
- Lista de pendências antes do fechamento: taxa ausente, forma sem conta, pagamento sem referência necessária e divergência não justificada.
- Fechamento em três estados: pronto, com pendências autorizáveis ou bloqueado.

### Critérios de aceite

- Taxa de maquininha nunca aparece como falta de caixa.
- Cartão ainda não depositado não altera a contagem física.
- O operador consegue identificar a causa da divergência antes de justificar.

## Fase 4 — Garantia e múltiplos pagadores

Prioridade: média-alta.

### Desenvolvimento

- Resumo único com saldo do cliente e saldo do fabricante.
- Botões distintos “Receber cliente” e “Registrar crédito do fabricante”.
- Geração automática da conta do fabricante no fechamento da OS.
- Repasse técnico exibido apenas na área interna.
- Indicador de margem: recebido do fabricante menos repasse e custos internos.

## Fase 5 — Cancelamentos, estornos e chargebacks

Prioridade: média-alta.

### Desenvolvimento

- Fluxo único de correção com justificativa obrigatória.
- Mostrar antes da confirmação os efeitos em caixa, banco, conta a receber, estoque e comissão.
- Diferenciar erro de lançamento, pagamento recusado, devolução ao cliente e chargeback.
- Preservar trilha de auditoria; não apagar silenciosamente fatos financeiros confirmados.

## Fase 6 — Dashboard e produtividade

Prioridade: média.

### Desenvolvimento

- Dashboard operacional por perfil.
- Operador: abrir caixa, receber, lançar saída e fechar.
- Financeiro: conciliar, tratar divergências e contas vencidas.
- Gestor: margens, taxas, recebíveis, DRE e alertas.
- Favoritos e ordem das formas de pagamento por frequência.
- Indicadores visuais com ação direta, evitando cartões meramente informativos.

## Sequência recomendada

1. Fase 1 — recebimento rápido.
2. Fase 2 — recebíveis da adquirente.
3. Fase 3 — fechamento e conciliação.
4. Fase 4 — experiência de garantia mista.
5. Fase 5 — estornos e chargebacks.
6. Fase 6 — personalização do dashboard.

## Migração e compatibilidade

- Preservar pagamentos, taxas e movimentos já registrados.
- Converter liquidações futuras não conciliadas em recebíveis pendentes, quando possível.
- Não alterar movimentos bancários já conciliados.
- Manter a taxa atual como “taxa efetiva total” durante a transição.
- Introduzir MDR e antecipação separadas sem obrigar recadastro imediato de todo o histórico.

## Testes obrigatórios

- Dinheiro exato e com troco.
- PIX bancário e PIX cobrado pela maquininha.
- Débito e crédito por bandeira.
- Crédito em diferentes faixas de parcelas.
- Tarifa percentual mais fixa.
- Pagamento misto com dinheiro e cartão.
- Regra de taxa ausente, vencida ou sobreposta.
- Liquidação D+1, D+30 e antecipada.
- Depósito agrupando várias vendas.
- Divergência entre líquido previsto e extrato.
- Estorno antes e depois da liquidação.
- Chargeback após fechamento do caixa.
- OS de garantia com cliente e fabricante como pagadores.
