# Análise e plano de correção financeira — OS, Caixa e Contabilidade Gerencial

Data da análise: 11/08/2026

## 1. Objetivo

Corrigir as divergências entre Ordem de Serviço, contas a receber, caixa físico, contas bancárias, custos, aportes e relatórios, mantendo a operação simples para o usuário e tecnicamente auditável.

Esta análise diferencia quatro fatos que hoje aparecem misturados em algumas telas:

1. **Fato comercial:** venda, serviço, cortesia, garantia ou cancelamento.
2. **Fato econômico:** receita, custo ou despesa na competência correta.
3. **Fato financeiro:** entrada ou saída real de dinheiro em uma conta e data determinadas.
4. **Registro do sistema:** data e usuário que cadastraram o fato, que não devem substituir a data real da operação.

## 2. Conclusão executiva

O sistema já possui uma base importante: empresas separadas, caixa diário, contas bancárias, formas de pagamento, contas a receber/pagar, livro financeiro imutável, conciliação, datas de competência/movimento e cadastro de capital/aportes.

Entretanto, a integração entre essas estruturas ainda não é uniforme. Os principais problemas confirmados são:

- uma OS gratuita pode deixar um recebível antigo de valor zero visível no histórico, embora não deva exigir pagamento;
- lançamentos retroativos informam datas anteriores, mas continuam presos ao caixa que está aberto hoje;
- a saída manual não permite escolher se o recurso saiu de dinheiro, banco ou outra conta;
- alguns relatórios filtram pela data informada, mas continuam limitados ao caixa aberto atual;
- pagamentos de contas a pagar e baixas manuais de recebíveis não possuem o mesmo tratamento de datas do pagamento comum;
- capital e aportes já existem, mas a função está pouco evidente e o aporte retroativo em dinheiro pode afetar o caixa atual;
- não existe um modelo próprio para pequenos custos internos da OS que não sejam cobrados do cliente;
- a margem por OS está incompleta: existe um método preparado para custo, mas o item da OS não possui o campo de custo que ele tenta consultar;
- a DRE atual é predominantemente gerencial e baseada em recebimentos, não uma contabilidade formal por partidas dobradas.

Recomendação: executar primeiro as correções de integridade P0. Somente depois ampliar custos de OS e contabilidade gerencial. Não é seguro construir novos relatórios em cima das regras atuais sem corrigir a origem e a data dos movimentos.

## 3. Diagnóstico detalhado

### 3.1. OS de valor zero

#### Comportamento esperado

- OS com total igual a zero não gera conta a receber.
- Não deve existir “pagamento de R$ 0,00”, pois pagamento representa movimentação monetária.
- A conclusão deve registrar um motivo financeiro não monetário, por exemplo:
  - cortesia;
  - garantia de serviço;
  - devolução sem reparo;
  - diagnóstico sem cobrança;
  - outro motivo autorizado.
- A OS deve ficar encerrada e sem alerta de saldo pendente.

#### Situação encontrada

- O fluxo atual já evita criar uma nova conta para total zero.
- Há teste automatizado cobrindo a finalização de OS zero sem novo recebível.
- Se já existir uma conta automática para a OS e o total passar a zero, o sistema a mantém com valor zero e status `paga`.
- A tela geral de contas a receber inicia mostrando todos os status. Por isso, o registro zero pode continuar aparecendo no histórico.
- Ao abrir esse registro, a baixa é corretamente recusada e o formulário exige pelo menos R$ 0,01. O erro está na presença/visibilidade do recebível, não na proibição de pagamento zero.

#### Correção proposta

- Criar um resultado financeiro explícito da OS: `cobravel`, `cortesia`, `garantia_servico`, `sem_reparo`, `cancelada` ou `outro_sem_cobranca`.
- Para OS zero, nunca criar `ContaReceber`.
- Para recebível automático antigo sem recebimentos:
  - cancelar tecnicamente o registro com motivo “OS encerrada sem cobrança”;
  - preservar auditoria;
  - não exibi-lo na visão padrão de pendências.
- Se houver recebimentos vinculados, bloquear a conversão silenciosa para zero e exigir estorno/revisão autorizada.
- A listagem de contas a receber deve abrir, por padrão, em `Pendentes`; `Pagas/Canceladas` ficam em histórico.

### 3.2. Pequenos custos internos da OS

#### Necessidade

Registrar componentes, insumos, consumíveis, materiais auxiliares, terceirização e outros custos usados no reparo sem acrescentá-los ao orçamento ou documento entregue ao cliente.

#### Situação encontrada

- `ServicoPeca` representa itens cobrados e exibidos na operação comercial.
- `ItemOrcamento` e `ServicoPeca` guardam o preço de venda, mas não possuem custo estimado/real próprio para uma peça manual. Assim, uma peça avulsa sem vínculo com estoque pode aparecer como margem bruta de 100%, mesmo tendo custo de compra.
- Peças associadas ao estoque podem gerar consumo e custo histórico por movimentação de estoque.
- Não há estrutura própria para custo manual/não faturável da OS.
- `OrdemServico.custo_pecas_financeiro()` procura um atributo `custo_unitario` que não existe em `ServicoPeca`; portanto, o cálculo de margem por OS não captura esse custo por essa via.
- Custos de estoque são apurados de forma agregada na DRE, mas não há uma visão completa de rentabilidade individual da OS.

#### Modelo recomendado

Criar `CustoOrdemServico`, separado dos itens cobrados ao cliente, com:

- empresa e OS;
- tipo: componente, insumo, consumível, terceirização, frete ou outro;
- origem: estoque, compra específica, despesa manual ou ajuste autorizado;
- produto de estoque opcional;
- descrição, quantidade e unidade;
- custo unitário histórico e custo total imutável;
- data de competência;
- categoria financeira e centro de custo;
- fornecedor/documento opcional;
- vínculo opcional com movimentação de estoque;
- vínculo opcional com conta a pagar ou movimento financeiro;
- usuário, data de registro e motivo de estorno;
- classificação estritamente interna. Custos estimados, custos reais e insumos não possuem opção de exibição ao cliente e não podem ser enviados aos documentos comerciais.

Para peças avulsas incluídas no orçamento, adicionar também ao item comercial:

- `custo_estimado_unitario`, informado ao preparar o orçamento e visível somente internamente;
- fornecedor/cotação e prazo estimado opcionais;
- estado de aquisição: não necessário, a comprar, solicitado, recebido ou cancelado;
- `custo_real_unitario`, preenchido pela entrada da compra ou confirmação manual auditada;
- diferença entre custo estimado e real, para alertar perda de margem antes de concluir a OS.

O custo estimado serve para formar preço e prever margem, mas não movimenta estoque, caixa, banco, conta a pagar nem DRE. O custo real é reconhecido quando a peça é adquirida/consumida, conforme o fluxo configurado. Se o custo real não tiver sido informado, a conclusão da OS deve alertar o usuário e exigir correção ou justificativa autorizada, sem assumir custo zero silenciosamente.

#### Dois fluxos diferentes na mesma OS

1. **Peça avulsa cobrada do cliente:** aparece no orçamento pelo preço de venda, guarda custo estimado durante a proposta e custo real após compra/consumo.
2. **Insumo embutido no serviço:** não aparece como cobrança separada; é lançado apenas em `CustoOrdemServico`, podendo ser um produto de estoque ou um material manual não cadastrado.

Exemplo do climatizador: o cliente vê apenas “Recuperação da placa” pelo valor contratado. Internamente, teclas, solda, fluxo, fios e outros materiais entram como custos da OS. A receita permanece pelo valor integral do serviço e a margem passa a descontar esses consumos.

#### Regra essencial contra dupla contagem

- **Material que já estava no estoque:** o consumo reduz estoque e reconhece custo da OS, mas não gera nova saída de dinheiro.
- **Compra feita para a OS e ainda não paga:** reconhece custo/obrigação e cria conta a pagar, sem baixar caixa.
- **Compra paga no momento:** reconhece custo e registra a saída na conta financeira escolhida.
- Nunca deduzir o custo diretamente do valor recebido do cliente. O caixa registra R$ 300 recebidos; a margem da OS mostra R$ 300 de receita menos, por exemplo, R$ 40 de custos.

#### Indicadores por OS

- receita bruta;
- descontos;
- receita líquida gerencial;
- peças cobradas;
- custos de estoque;
- custos internos não faturáveis;
- terceirizações;
- impostos/taxas estimados;
- comissões;
- margem de contribuição e percentual;
- status do custo: previsto, realizado, pago ou estornado.

### 3.3. Saídas e lançamentos retroativos

#### Situação encontrada

- A saída manual permite `data_competencia` e `data_movimento`.
- Mesmo retroativa, ela é sempre vinculada ao caixa aberto atual.
- A tela não permite escolher a origem financeira; consequentemente, toda saída manual é tratada como dinheiro físico.
- O fechamento do caixa subtrai todos os lançamentos de saída associados ao caixa, independentemente da data de movimento.
- O resumo “saídas de hoje” usa a data de cadastro (`data`) em alguns pontos, não `data_movimento`.

Isso confirma a causa relatada: uma despesa cadastrada hoje com data antiga pode reduzir o dinheiro esperado do caixa de hoje.

#### Correção proposta

Todo pagamento/saída deve exigir uma **conta financeira de origem**:

- caixa físico aberto;
- conta bancária;
- carteira/conta digital;
- cartão/conta de liquidação, quando aplicável;
- conta transitória autorizada.

Além da conta, deve ser obrigatório informar o **meio de pagamento da saída**, mantendo conceitos separados:

- meio: dinheiro, PIX, transferência, débito, crédito, boleto, débito automático ou outro;
- origem: caixa físico, conta bancária, cartão corporativo ou conta transitória;
- destino/beneficiário: fornecedor, funcionário, sócio ou terceiro, quando aplicável.

Exemplos: “PIX pela conta Itaú”, “dinheiro pelo caixa da loja” e “cartão corporativo”. Uma compra no cartão corporativo cria obrigação a pagar para a fatura, e não uma saída bancária imediata. O sistema pode sugerir a conta com base no meio escolhido, mas o usuário deve confirmar o destino financeiro antes de salvar.

Regras para retroatividade:

- banco: permitir data real anterior com permissão e referência/comprovante;
- caixa físico ainda aberto na própria data: lançar normalmente;
- caixa físico já fechado: não alterar silenciosamente o fechamento;
- correção de caixa fechado: criar ajuste auditável na data atual, mantendo a competência original e referência ao fechamento afetado;
- implantação inicial: usar saldo inicial da conta na data de corte, não cadastrar despesas e aportes fictícios no caixa atual.

### 3.4. Pagamentos e contas financeiras

Hoje “forma de pagamento” e “local onde o dinheiro está” ainda se confundem em alguns fluxos.

Exemplos:

- PIX é uma forma, mas precisa apontar para uma conta bancária específica;
- cartão pode gerar recebível hoje e liquidação bancária futura, líquida da taxa;
- dinheiro afeta exclusivamente o caixa físico;
- pagamento misto deve gerar uma parcela por destino financeiro;
- boleto pode ficar em compensação antes do crédito bancário.

O sistema já permite associar uma forma a uma conta bancária e criar movimentos futuros de cartão. Essa base deve virar regra obrigatória e uniforme.

Correções:

- criar uma abstração `ContaFinanceira` ou uma camada de serviço que trate caixa e banco de forma uniforme;
- manter o vínculo do pagamento com o turno/operador para conferência, mas separar o total comercial do saldo físico;
- o `saldo_final` do caixa deve significar apenas dinheiro físico;
- totais de PIX, cartão e boleto devem ser conferidos por forma/destino, sem integrar o numerário físico;
- saídas bancárias devem funcionar sem caixa aberto;
- pagamentos em dinheiro exigem caixa aberto;
- pagamentos mistos geram movimentos individualizados e conciliáveis.

### 3.4.1. Contas bancárias, extratos e conciliação

#### O que já existe

O sistema já possui uma base funcional de tesouraria:

- cadastro de conta corrente, poupança ou conta de pagamento por empresa;
- saldo inicial com data de corte;
- movimentos bancários imutáveis;
- associação de formas de pagamento a uma conta de liquidação;
- transferências entre caixa e banco;
- importação de extrato CSV com proteção contra duplicidade;
- conciliação de uma ou várias linhas do extrato com um ou vários movimentos;
- registro justificado de tarifa, juros, rendimento ou diferença;
- sugestão de correspondências por data, valor e descrição.

#### Melhorias recomendadas

1. Criar uma tela “Contas e extratos” com saldo do sistema, saldo do último extrato, diferença, pendências e data da última conciliação.
2. Aceitar OFX como formato preferencial e manter CSV com assistente de mapeamento de colunas salvo por banco. PDF pode ser anexado como comprovante, mas não deve ser o formato principal para conciliação automática.
3. Permitir informar saldo inicial e data de corte sem tratar esse valor como receita.
4. Associar cada PIX, cartão, boleto e débito automático à conta ou conta transitória adequada.
5. Usar uma “caixa de entrada da conciliação” com estados: sugerido, conciliado, pendente, divergente e ignorado com justificativa.
6. Ao encontrar uma linha sem lançamento correspondente, permitir criar despesa, receita não operacional, transferência, tarifa, rendimento ou aporte, já preenchendo data, valor e descrição do extrato.
7. Suportar conciliações 1:1, 1:N e N:1, necessárias para pagamentos agrupados, tarifas descontadas e depósitos compostos.
8. Exibir fechamento mensal por conta: saldo inicial + entradas − saídas = saldo final, comparado ao extrato.
9. Guardar arquivo de origem, hash, período, usuário da importação e histórico de desfazimento para auditoria.
10. Deixar conexão bancária automática por Open Finance/API como fase posterior, usando provedor autorizado e consentimento renovável; nunca armazenar senha do internet banking.

#### Fluxo diário recomendado

1. O usuário cadastra a conta e informa o saldo inicial na data de implantação.
2. Entradas e saídas do sistema já apontam para essa conta.
3. Periodicamente importa OFX/CSV do banco.
4. O sistema concilia automaticamente correspondências exatas e sugere as prováveis.
5. O usuário trata somente diferenças e lançamentos desconhecidos.
6. Ao finalizar o período, confirma que saldo contábil-gerencial e saldo do extrato coincidem.

### 3.5. Contas a pagar e receber

Lacunas confirmadas:

- `PagamentoContaPagar` registra apenas a data de criação e o serviço força a data do movimento para hoje;
- `RecebimentoConta` também depende da data de criação para o histórico próprio;
- a baixa manual de conta a receber cria pagamento sem repassar datas de competência e movimento;
- os fluxos não compartilham integralmente a mesma política de conta financeira, datas, estorno e conciliação.

Correção:

- adicionar competência, movimento e registro aos pagamentos de contas a pagar e recebimentos;
- usar um único serviço transacional para gerar livro, caixa/banco, liquidação e auditoria;
- pagamento não deve alterar o vencimento/competência original da obrigação;
- estorno deve preservar original e gerar contramovimento;
- toda baixa deve guardar conta financeira, forma, usuário, referência e documento.

### 3.6. Capital inicial e investimentos dos sócios

#### O que já existe

Na tela **Caixa > Bancos e conciliação** já existe “Capital inicial ou injeção de recursos”, com:

- capital social inicial/aumento de capital;
- adiantamento para futuro aumento de capital;
- empréstimo de sócio;
- outra injeção de recursos;
- destino em conta bancária ou caixa;
- competência e movimento retroativos mediante permissão;
- natureza `capital`, fora da receita operacional.

#### Problemas restantes

- função pouco evidente no menu;
- não há teste automatizado específico para o fluxo de aporte;
- aporte retroativo destinado a dinheiro só permite selecionar caixa aberto e pode afetar o caixa atual;
- `empréstimo de sócio` e `capital social` aparecem sob a mesma natureza gerencial, embora representem passivo e patrimônio líquido diferentes;
- não há devolução/amortização de empréstimo de sócio como fluxo próprio;
- saldo inicial de implantação e novo aporte estão misturados conceitualmente.

#### Fluxo recomendado

- **Saldo já existente na implantação:** informar como saldo inicial da conta na data de corte.
- **Capital efetivamente integralizado depois da implantação:** registrar como aporte de capital e fluxo de financiamento.
- **Empréstimo do sócio à empresa:** registrar como obrigação com o sócio, com data, documento, vencimento e possibilidade de amortização.
- **AFAC/adiantamento:** manter classe própria e exigir confirmação do responsável contábil sobre a classificação final.
- **Retirada/distribuição/reembolso:** criar operações próprias, sem tratar como despesa operacional comum.

As classificações finais devem ser confirmadas pelo contador responsável. O sistema deve ajudar a registrar e separar, não decidir sozinho a natureza jurídica de um aporte.

### 3.7. Relatórios e filtros por data

#### Defeitos confirmados

- O dashboard principal seleciona caixas pela data do caixa, e não movimentos pela data escolhida.
- A série mensal também agrega por `Caixa.data` e pelos vínculos do caixa.
- Em Relatórios, se existe um caixa aberto e “todos os caixas” não é marcado, pagamentos e lançamentos ficam limitados ao caixa atual mesmo quando o usuário informa outro período.
- Isso torna o filtro por data aparentemente ineficaz para períodos anteriores.
- O filtro por forma de pagamento filtra pagamentos, mas não necessariamente os lançamentos de entrada vinculados usados em todos os totais.
- Algumas auditorias ainda usam `data__date` (registro) em vez de competência ou movimento.
- O estoque só tem `criado_em` para muitas movimentações; assim, custos retroativos entram na data do cadastro.

#### Correção proposta

Cada relatório deve declarar e aplicar um único eixo:

- **Fluxo realizado:** `data_movimento`.
- **DRE/competência:** `data_competencia` ou data econômica da OS/custo.
- **Contas previstas:** vencimento.
- **Auditoria:** `registrado_em`.

O filtro de período deve prevalecer sobre “caixa aberto”. Caixa/conta passa a ser um filtro adicional explícito, nunca uma restrição oculta.

Todos os cards, gráficos, tabelas e exportações devem receber o mesmo conjunto de filtros por uma função centralizada. O cabeçalho deve mostrar: empresa, período, regime de data e contas consideradas.

### 3.8. DRE e contabilidade

#### Estado atual

- A DRE usa pagamentos como receita, portanto se aproxima mais do regime de caixa do que de uma DRE contábil por competência.
- Despesas manuais usam competência, o que mistura bases se o usuário não preencher tudo com disciplina.
- CMV e perdas usam a data de criação da movimentação de estoque.
- Capital é corretamente excluído das receitas/despesas operacionais.
- O `MovimentoFinanceiro` é imutável e admite estorno, o que é uma boa base de auditoria.
- Não existem plano de contas contábil, lançamentos balanceados, débitos/créditos e demonstração patrimonial; logo, o sistema não deve se apresentar como substituto da escrituração contábil oficial.

#### Evolução recomendada

Curto prazo:

- chamar o módulo de **Financeiro gerencial**;
- produzir DRE gerencial coerente por competência;
- produzir fluxo de caixa realizado por movimento;
- separar fluxo operacional, investimento, financiamento e transferências;
- deixar capital fora do resultado e dentro do fluxo de financiamento.

Médio prazo, se houver necessidade de integração contábil:

- plano de contas hierárquico;
- conta contábil para caixa, bancos, clientes, fornecedores, estoque, tributos, capital e empréstimos;
- cabeçalho de lançamento e partidas de débito/crédito;
- validação de soma dos débitos igual à soma dos créditos;
- períodos abertos/fechados e lançamentos de ajuste;
- exportação para o contador, sem tentar substituir o sistema contábil dele.

## 4. Plano de desenvolvimento priorizado

### Fase F0 — Auditoria e saneamento seguro (P0)

- relatório somente leitura de recebíveis automáticos com valor zero;
- relatório de movimentos cuja `data_movimento` difere da data do caixa vinculado;
- relatório de lançamentos sem categoria, centro ou empresa;
- relatório de formas sem conta de liquidação;
- relatório de divergências entre `Pagamento`, `LancamentoCaixa`, `MovimentoFinanceiro` e `MovimentoBancario`;
- script de correção idempotente, com modo simulação e backup obrigatório;
- nenhuma exclusão silenciosa de histórico financeiro.

### Fase F1 — OS sem cobrança (P0)

- motivo de encerramento financeiro;
- fluxo “Concluir sem cobrança” separado de “Receber”; 
- zero não cria recebível, pagamento, talão financeiro ou alerta;
- cancelamento auditado de recebíveis automáticos zero antigos;
- visão padrão de contas a receber somente com pendências;
- relatório de cortesias/garantias de serviço sem tratá-las como receita.

### Fase F2 — Origem do dinheiro e datas corretas (P0)

- conta financeira obrigatória em entradas e saídas;
- saída manual com dinheiro ou banco;
- política para movimentos retroativos e caixas fechados;
- datas em baixa de recebíveis e pagamentos de contas a pagar;
- fechamento do caixa considerando exclusivamente numerário físico;
- banco/PIX/cartão conciliáveis sem afetar o dinheiro contado.

### Fase F3 — Relatórios coerentes (P0)

- remover limitação oculta ao caixa aberto;
- centralizar filtros de empresa, período, regime, conta, categoria e centro;
- corrigir cards, tabelas, gráficos, comparativos e exportações em conjunto;
- separar DRE por competência, fluxo por movimento, previsão por vencimento e auditoria por registro;
- adicionar testes de períodos passados, futuro, pagamento misto e múltiplos caixas.

### Fase F4 — Custos internos da OS (P1)

- criar `CustoOrdemServico` e migrations;
- consumo de estoque com snapshot de custo;
- custo manual/terceirizado sem exposição ao cliente;
- criação opcional de conta a pagar;
- estorno e permissões;
- painel de rentabilidade da OS;
- integração com DRE sem dupla contagem.

### Fase F5 — Capital, saldos iniciais e sócios (P1)

- destacar “Capital e recursos dos sócios” no menu;
- assistente que diferencie saldo inicial, capital, AFAC e empréstimo;
- impedir aporte retroativo em caixa atual;
- operação de amortização/devolução de empréstimo;
- relatórios de financiamento separados da receita;
- testes de banco, caixa, retroatividade, empresa e estorno.

### Fase F6 — DRE gerencial profissional (P1)

- reconhecer receita econômica no evento configurado da OS, não apenas no recebimento;
- separar receita faturada, recebida e a receber;
- custos diretos por OS, CMV, perdas, taxas, impostos e comissões;
- fechar competência com trilha de ajustes;
- reabrir somente com permissão e justificativa;
- comparativo DRE x fluxo de caixa.

### Fase F7 — Integração contábil por débitos e créditos (P2)

- implementar apenas após F0–F6;
- plano de contas e partidas balanceadas;
- mapeamentos automáticos por tipo de operação;
- exportação validável pelo contador;
- não automatizar classificação jurídica/fiscal sem parametrização homologada.

## 5. Critérios de aceite essenciais

### OS zero

- concluir OS zero em qualquer fluxo não cria conta a receber;
- não solicita R$ 0,01;
- não gera alerta pendente;
- registra motivo de não cobrança;
- recebível zero antigo não aparece entre pendências.

### Custos da OS

- custo interno nunca aparece no orçamento, OS impressa, recibo, relatório técnico, portal ou PDF do cliente;
- peça manual cobrada guarda custo estimado e depois custo real, sem presumir margem de 100%;
- custo estimado não movimenta financeiro ou estoque;
- OS com peça manual sem custo real apresenta alerta antes da conclusão;
- insumo embutido no serviço pode ser registrado sem cadastro prévio no estoque;
- consumo de estoque usa custo histórico;
- mesmo custo não entra duas vezes na DRE;
- margem por OS confere com receita, custo, taxas, imposto e comissão;
- estorno recompõe estoque/financeiro quando aplicável.

### Retroatividade e caixa

- despesa bancária de 01/08 lançada em 11/08 aparece em 01/08 no fluxo realizado e não altera o dinheiro do caixa de 11/08;
- competência de julho paga em agosto aparece em julho na DRE e agosto no fluxo;
- caixa fechado não é alterado silenciosamente;
- data de registro continua mostrando 11/08 para auditoria.
- toda saída identifica meio de pagamento e conta financeira de origem;
- saída em PIX/banco não reduz o dinheiro físico esperado do caixa;

### Bancos e conciliação

- conta bancária possui saldo inicial e data de corte sem gerar receita;
- reimportar o mesmo extrato não duplica linhas;
- conciliações 1:1, 1:N e N:1 preservam a trilha de auditoria;
- linha sem correspondência pode originar lançamento categorizado e conciliado;
- saldo final do sistema confere com o saldo do extrato no período;
- nenhuma credencial de internet banking é armazenada.

### Capital

- saldo inicial não aparece como receita;
- capital/aporte aparece como financiamento;
- empréstimo de sócio gera obrigação separada;
- aporte bancário concilia com extrato;
- aporte em dinheiro afeta somente o caixa correto.

### Relatórios

- o mesmo filtro produz totais consistentes no card, tabela, gráfico, CSV e PDF;
- selecionar período passado funciona mesmo com caixa atual aberto;
- filtros deixam explícito se usam movimento, competência, vencimento ou registro;
- totais por forma de pagamento conferem com as parcelas de pagamentos mistos.

## 6. Estratégia de implantação

1. Fazer backup e auditoria somente leitura.
2. Implementar F1 e F2 com feature flags.
3. Rodar saneamento em modo simulação e apresentar quantidades/valores.
4. Corrigir dados somente após validação do relatório de impacto.
5. Implementar F3 e comparar relatórios antigos x novos por pelo menos um mês real.
6. Liberar F4 para um grupo pequeno de OS antes de torná-lo obrigatório.
7. Configurar saldos iniciais e capital com data de corte documentada.
8. Homologar com responsável financeiro e contador os mapeamentos gerenciais.

## 7. Decisões que exigem parametrização do usuário/contador

- momento de reconhecimento da receita da OS;
- classificação de AFAC e empréstimos de sócios;
- plano de contas e grupos da DRE;
- tratamento de impostos por competência;
- política para reabertura de períodos;
- centros de custo e categorias obrigatórias;
- conta bancária de liquidação de cada forma de pagamento.

O sistema pode fornecer padrões seguros e validações, mas essas escolhas dependem da realidade documental e contábil da empresa.

## 8. Referências técnicas contábeis

- CPC 03 (R2) — Demonstração dos Fluxos de Caixa: https://www.cpc.org.br/CPC/Documentos-emitidos/Pronunciamentos/Pronunciamento?Id=34
- CPC 16 (R1) — Estoques: https://www.cpc.org.br/CPC/Documentos-emitidos/Pronunciamentos/Pronunciamento?Id=47
- CPC 26 (R1) — Apresentação das Demonstrações Contábeis: https://www.cpc.org.br/CPC/Documentos-Emitidos/Pronunciamentos/Pronunciamento?Id=57
- CPC 47 — Receita de Contrato com Cliente: https://www.cpc.org.br/Arquivos/Documentos/527_CPC_47_Rev%2021.pdf
- Normas completas do Conselho Federal de Contabilidade: https://cfc.org.br/tecnica/normas-brasileiras-de-contabilidade/normas-completas/

## 9. Resultado esperado ao final

O sistema deverá contar a mesma história em todas as áreas:

- a OS informa o que foi cobrado e o que foi consumido;
- o estoque informa o custo real utilizado;
- contas a receber/pagar mostram direitos e obrigações;
- caixa e bancos mostram onde e quando o dinheiro realmente entrou ou saiu;
- aportes aparecem como financiamento, não receita;
- DRE mostra competência e margem;
- fluxo de caixa mostra realização financeira;
- auditoria mostra quando e por quem cada registro foi feito.
