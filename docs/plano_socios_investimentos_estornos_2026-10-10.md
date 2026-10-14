# Plano de melhoria — sócios, pessoas relacionadas, investimentos e estornos

Data de referência: 10/10/2026

## 1. Objetivo

Evoluir o financeiro do ABGest para registrar corretamente:

- transferências recorrentes da empresa para o sócio;
- despesas pessoais pagas pela empresa;
- aportes e devoluções de valores;
- pagamentos a pessoas que trabalham na empresa, mas não são sócias formais;
- aplicações e resgates RDB;
- estornos e chargebacks vinculados ao recebimento original;
- classificação contábil posterior sem apagar ou reescrever o histórico.

O sistema deve registrar primeiro o fato financeiro comprovado. A classificação fiscal
definitiva pode ficar pendente até a validação do contador, sem inventar aporte, lucro,
pró-labore ou despesa operacional.

## 2. Evidências encontradas em setembro de 2026

### Alexandre

- 28 transferências bancárias para a conta pessoal: R$ 4.092,00;
- conta de energia residencial paga pela empresa: R$ 242,90;
- total atualmente identificado como benefício/retirada pessoal: R$ 4.334,90;
- duas saídas em dinheiro, R$ 20,00 e R$ 100,00, estão descritas como “Aporte de
  sócio”, embora aporte seja uma entrada. Precisam de confirmação humana;
- algumas transferências bancárias foram divididas em várias linhas contábeis. O
  relatório não deve confundir quantidade de transferências com quantidade de
  classificações.

### Diana

- três saídas totalizando R$ 260,00;
- R$ 200,00 descritos como pagamento administrativo;
- R$ 50,00 descritos como pagamento pessoal;
- R$ 10,00 sem finalidade suficientemente clara;
- uma entrada de R$ 300,00 enviada por Diana para a empresa;
- Diana não é sócia formal e, portanto, não deve aparecer como destinatária de
  distribuição de lucros, retirada de capital ou pró-labore de sócio.

### Investimentos e estornos

- aplicação RDB de R$ 1.050,00 foi classificada como despesa operacional;
- resgate RDB de R$ 980,00 foi classificado como receita operacional;
- aplicação RDB posterior de R$ 1.300,00 já foi registrada como transferência,
  demonstrando comportamento inconsistente entre períodos;
- estorno de cobrança de R$ 976,60 foi lançado como Despesas Gerais, quando deveria
  neutralizar o recebimento original;
- o primeiro repasse SumUp de R$ 415,94 foi tratado como receita, enquanto os demais
  foram tratados como transferência;
- linhas detalhadas e linhas-resumo da SumUp foram ignoradas com justificativa “erro
  sistema”, impedindo uma memória confiável de bruto, taxa e líquido.

## 3. Princípios funcionais

1. Aporte sempre representa recurso entrando na empresa.
2. Saída para sócio nunca pode receber automaticamente o nome “aporte”.
3. Transferência para conta pessoal nasce como “retirada aguardando classificação”,
   salvo quando já existir documento que determine outra natureza.
4. Distribuição de lucros só é liberada quando houver competência e lucro disponível
   informado ou validado.
5. Pró-labore, distribuição, devolução de aporte e adiantamento permanecem separados.
6. Pessoas não sócias não podem usar classificações exclusivas de sócios.
7. Aplicação e resgate movimentam patrimônio, não resultado operacional.
8. Somente rendimentos, impostos e tarifas do investimento afetam o resultado.
9. Estorno neutraliza a origem; não cria uma despesa genérica.
10. Correções preservam o lançamento original e criam eventos auditáveis.

## 4. Modelo funcional proposto

### 4.1 Pessoas financeiras

Criar cadastro `PessoaFinanceira` por empresa:

- nome e documento;
- tipo: sócio formal, ex-sócio, colaborador, pessoa relacionada ou terceiro;
- data de início e fim do vínculo;
- participação societária opcional;
- situação ativa/inativa;
- observações e documentos comprobatórios.

O cadastro não substitui clientes, fornecedores ou usuários. Ele define apenas a
relação financeira e quais naturezas podem ser utilizadas.

### 4.2 Conta-corrente de sócio ou pessoa relacionada

Criar um livro imutável com:

- pessoa;
- data de competência e data financeira;
- direção: empresa deve à pessoa ou pessoa deve à empresa;
- natureza provisória e natureza definitiva;
- valor;
- movimento bancário/caixa de origem;
- comprovante e documento de referência;
- status: pendente, classificado, aprovado, compensado ou estornado;
- usuário, aprovador e histórico de alterações.

Exemplos:

- empresa paga energia residencial: pessoa deve à empresa;
- sócio transfere dinheiro para a empresa: empresa deve ao sócio até a classificação;
- empresa transfere valor para conta pessoal: retirada pendente de classificação;
- pessoa devolve valor anteriormente retirado: compensação da conta-corrente.

### 4.3 Naturezas permitidas

Para sócio formal:

- retirada aguardando classificação;
- pró-labore;
- adiantamento de pró-labore;
- distribuição de lucros;
- adiantamento de distribuição, se autorizado pelo contador;
- aporte de capital;
- AFAC;
- empréstimo do sócio à empresa;
- devolução/amortização;
- reembolso de despesa comprovada;
- despesa pessoal paga pela empresa.

Para pessoa não sócia:

- remuneração administrativa pendente de regularização;
- adiantamento a colaborador;
- reembolso de despesa comprovada;
- empréstimo de terceiro;
- devolução de empréstimo;
- despesa pessoal paga pela empresa;
- valor a receber da pessoa.

O sistema deve bloquear distribuição de lucros, retirada de capital e pró-labore de
sócio para quem não possua vínculo societário ativo.

## 5. Fluxos de interface

### 5.1 Saída rápida do caixa/banco

Manter o registro diário rápido. Em “Mais opções”, incluir:

1. Despesa da empresa;
2. Pagamento de conta/fornecedor já cadastrado;
3. Retirada para sócio aguardando classificação;
4. Despesa pessoal paga pela empresa;
5. Pagamento/adiantamento para colaborador ou pessoa relacionada;
6. Transferência entre contas;
7. Aplicação ou resgate financeiro;
8. Estorno vinculado a uma operação anterior.

Cada opção deve mostrar somente os campos necessários. O usuário não precisa navegar
para outro módulo para concluir a operação.

### 5.2 Retirada recorrente de Alexandre

Fluxo recomendado:

1. selecionar Alexandre;
2. informar valor e conta de destino;
3. confirmar “retirada aguardando classificação contábil”;
4. registrar o PIX uma única vez;
5. acumular os movimentos na competência mensal;
6. no fechamento, classificar o total com orientação contábil.

Várias transferências semanais continuam permitidas. O relatório deve mostrar tanto o
número de transferências quanto o número de classificações, sem misturá-los.

### 5.3 Situação de Diana

Enquanto não houver definição formal:

- registrar pagamentos administrativos como “remuneração pendente de regularização”;
- registrar valores pessoais como adiantamento/valor a receber de pessoa relacionada;
- registrar dinheiro colocado na empresa como empréstimo ou valor de terceiro
  aguardando documento;
- nunca classificá-la automaticamente como sócia.

O sistema deve exibir alerta permanente até que o tipo de vínculo seja definido pelo
responsável contábil/trabalhista.

## 6. Fechamento mensal de sócios e pessoas relacionadas

Criar assistente mensal com:

- total transferido para cada pessoa;
- despesas pessoais pagas diretamente pela empresa;
- valores devolvidos;
- aportes ou empréstimos recebidos;
- saldo anterior e saldo final da conta-corrente;
- movimentos ainda sem documento;
- proposta de classificação, sempre sujeita à confirmação;
- campo para anexar orientação ou documento contábil;
- aprovação por usuário com permissão específica.

O sistema não calculará automaticamente quanto é pró-labore ou lucro distribuível.
Poderá registrar os valores informados pelo contador e impedir que a soma ultrapasse o
total de retiradas da competência.

## 7. Aplicações financeiras e RDB

### 7.1 Conta de investimento

Permitir cadastrar uma conta financeira do tipo investimento, vinculada ao banco:

- nome do produto/instituição;
- saldo principal aplicado;
- rendimento acumulado;
- liquidez e vencimento opcionais;
- histórico de aplicações, resgates, rendimentos, IR, IOF e tarifas.

### 7.2 Lançamentos

- aplicação: banco -> investimento, natureza transferência;
- resgate do principal: investimento -> banco, natureza transferência;
- rendimento: receita financeira;
- IR/IOF/tarifa: tributo ou despesa financeira;
- resgate parcial não encerra a aplicação;
- conciliação compara o extrato bancário e o extrato do investimento.

O sistema deve reconhecer descrições como “Aplicação RDB” e “Resgate RDB”, sugerindo a
transferência correta sem gravar automaticamente.

## 8. Estorno vinculado

Ao selecionar “Estornar”, o sistema deve:

1. localizar o recebimento original;
2. mostrar cliente, OS/venda, forma, valor, taxa e data;
3. permitir estorno total ou parcial;
4. reabrir o saldo a receber quando aplicável;
5. neutralizar o movimento bancário/caixa;
6. reverter taxas e comissões conforme regras documentadas;
7. registrar motivo, usuário e comprovante;
8. impedir repetição pela mesma chave idempotente.

Se a origem não for encontrada, criar “estorno aguardando identificação”, fora de
Despesas Gerais, para posterior vínculo.

## 9. SumUp e adquirentes

Criar conta de liquidação da adquirente:

- venda bruta gera valor a receber da SumUp;
- taxa reduz o valor a receber e vira despesa de adquirência;
- depósito líquido transfere SumUp -> Nubank;
- chargeback neutraliza a venda ou o recebível original;
- relatório importa identificador, bandeira, modalidade, parcelas, bruto, taxa,
  líquido e depósito;
- linhas “Total de depósitos” e “Total geral” são informativas e nunca geram dinheiro;
- arquivos sobrepostos permanecem idempotentes;
- conciliação permite várias vendas contra um depósito.

## 10. Correção auditável de setembro

Não executar correção automática. Criar um assistente com prévia e confirmação:

1. reclassificar R$ 242,90 da energia residencial para a conta-corrente de Alexandre;
2. confirmar se as saídas em dinheiro de R$ 20,00 e R$ 100,00 foram retiradas;
3. manter R$ 4.092,00 de transferências como retiradas pendentes de classificação;
4. separar os R$ 200,00 administrativos de Diana dos R$ 50,00 pessoais;
5. identificar a finalidade dos R$ 10,00 e da entrada de R$ 300,00 de Diana;
6. reclassificar aplicação RDB de R$ 1.050,00 e resgate de R$ 980,00 como
   transferências patrimoniais;
7. vincular o estorno de R$ 976,60 ao recebimento original;
8. reclassificar o repasse SumUp de R$ 415,94 como transferência;
9. revisar as linhas SumUp ignoradas, descartando apenas resumos duplicados;
10. preservar todos os registros originais e gerar eventos inversos/corretivos.

## 11. Relatórios

Criar relatórios separados:

- retiradas por sócio: quantidade de transferências e total financeiro;
- classificação mensal: pró-labore, lucros, adiantamentos e pendências;
- conta-corrente por pessoa;
- despesas pessoais pagas pela empresa;
- valores colocados na empresa por sócios e terceiros;
- posição de investimentos: principal, rendimento e saldo;
- estornos vinculados e pendentes;
- DRE sem transferências, capital, aplicações ou despesas pessoais;
- fluxo de caixa incluindo todos os movimentos financeiros, com natureza separada.

## 12. Segurança e auditoria

- permissões distintas para registrar, classificar e aprovar;
- usuário não aprova a própria correção sensível, quando a empresa ativar dupla
  aprovação;
- operações atômicas e idempotentes;
- períodos fechados exigem reabertura ou correção retroativa formal;
- nenhuma exclusão física de movimentos financeiros confirmados;
- alteração de vínculo societário não modifica períodos anteriores;
- isolamento obrigatório por empresa.

## 13. Fases de desenvolvimento

### Fase 1 — Base segura

- cadastro de pessoas financeiras;
- conta-corrente por pessoa;
- retirada aguardando classificação;
- despesa pessoal paga pela empresa;
- bloqueio de aporte em saída;
- relatórios básicos e permissões.

### Fase 2 — Fechamento mensal

- consolidação das retiradas semanais;
- classificação mensal;
- documentos e aprovação;
- alertas de pendências e limites.

### Fase 3 — Investimentos

- contas de investimento;
- aplicação/resgate/rendimento/impostos;
- regras de sugestão RDB;
- posição e conciliação de investimentos.

### Fase 4 — Estornos

- vínculo total/parcial ao recebimento;
- reversão de contas a receber, taxas e comissões;
- pendência de identificação;
- trilha completa de auditoria.

### Fase 5 — SumUp e adquirentes

- importador detalhado;
- conta de liquidação;
- taxas e depósitos agrupados;
- chargeback;
- conciliação bruto -> taxa -> líquido -> Nubank.

### Fase 6 — Saneamento histórico

- assistente de correção de setembro;
- prévia dos efeitos;
- correções por interface;
- relatório antes/depois;
- bloqueio contra repetição.

## 14. Testes de aceitação

1. Saída nunca pode ser registrada como aporte.
2. Repetir retirada com mesma chave não duplica o movimento.
3. Três PIX do mês podem formar uma classificação mensal sem perder os três PIX.
4. Despesa residencial não entra na DRE da loja.
5. Pessoa não sócia não recebe distribuição de lucros.
6. Aplicação RDB não reduz o resultado operacional.
7. Resgate do principal não aumenta receita.
8. Apenas rendimento do RDB aparece como receita financeira.
9. Estorno total reabre o valor a receber correto.
10. Estorno parcial reabre somente a parcela estornada.
11. Repetir estorno não duplica os efeitos.
12. Depósito SumUp não reconhece novamente a venda como receita.
13. Linha-resumo SumUp não cria movimento financeiro.
14. Correção retroativa preserva o período e o registro original.
15. Empresa diferente não visualiza pessoas ou movimentos de outra empresa.

## 15. Implantação gradual e reversão

1. criar backup antes de cada fase;
2. usar somente migrações aditivas inicialmente;
3. ativar por feature flag por empresa;
4. executar primeiro em modo de leitura/sombra;
5. comparar relatórios antigos e novos;
6. liberar escrita apenas para administrador;
7. corrigir setembro somente depois da conferência da prévia;
8. em caso de problema, desativar a funcionalidade sem apagar tabelas ou auditoria.

## 16. Decisões externas pendentes

- valor e competência do pró-labore de Alexandre;
- regra para classificar retiradas acima do pró-labore;
- existência e comprovação de lucros distribuíveis;
- natureza das duas saídas em dinheiro de R$ 120,00;
- formalização trabalhista/contratual de Diana;
- natureza da entrada de R$ 300,00 feita por Diana;
- tratamento contábil definitivo de adiantamentos e pessoas relacionadas;
- contas contábeis usadas para investimentos, rendimentos, IR e IOF.

Essas decisões não impedem a construção da base técnica. Enquanto estiverem pendentes,
o sistema deverá manter os fatos financeiros em classificação provisória e destacá-los
no fechamento mensal.

## 17. Estado da implementação em 13/10/2026

A base técnica das fases 1 a 5 foi implementada na migração aditiva
`caixa.0072_patrimonio_pessoas_investimentos_estornos`, incluindo pessoas financeiras,
conta-corrente, classificação mensal, investimentos, estornos vinculados e detalhamento
de adquirentes. A fase 6 foi disponibilizada como correção manual auditável: movimentos
bancários históricos podem ser vinculados sem duplicar o saldo, mas nenhuma
reclassificação é executada automaticamente.

As decisões do item 16 continuam dependentes de validação humana/contábil.
