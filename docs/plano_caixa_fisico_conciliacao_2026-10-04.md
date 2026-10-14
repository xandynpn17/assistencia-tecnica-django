# Plano de evolucao financeira: caixa fisico, conciliacao e correcoes

Data da analise: 04/10/2026

Atualizacao de desenvolvimento: 05/10/2026

## Estado da implementacao em 05/10/2026

Implementado no codigo, ainda nao aplicado ao banco restaurado nem a producao:

- fechamento transacional com snapshots imutaveis e versoes sucessivas;
- eventos auditados de abertura, fechamento e reabertura;
- correcao da sugestao de abertura quando a contagem anterior e R$ 0,00;
- efeitos de correcoes de lancamentos fechados preservando o snapshot original;
- validacao de colisao de chave idempotente em transferencias;
- calculadora central de dinheiro fisico;
- pagina `Caixa > Dinheiro fisico`, com filtro por data e extrato de gaveta;
- separacao da parcela em dinheiro nos pagamentos mistos;
- locais gaveta e cofre, saldo de corte, fundo de troco, sangria e reforco;
- transferencias fisicas atomicas, auditadas e idempotentes;
- divergencia de fechamento como pendencia, sem receita/despesa automatica;
- aprovacao para investigacao pela interface.
- documentacao de movimento retroativo ja existente com previa dos checkpoints;
- absorcao total ou parcial em divergencia posterior, sem novo movimento financeiro;
- preservacao explicita de saldos iniciais e contagens durante a absorcao.

O recebimento de pagamentos nao ganhou campos, confirmacoes nem consultas adicionais.
A composicao continua sendo validada em memoria durante o processamento ja existente.

As migracoes `caixa 0065`, `0066`, `0067` e `0068` sao somente aditivas. Elas criam novas
tabelas e nao fazem conversao, saneamento ou preenchimento automatico dos historicos.

## 1. Escopo e regra de seguranca

Este documento descreve a implementacao proposta a partir do codigo atual e do backup
`backup_20261003_122422.zip`. A restauracao foi feita apenas no ambiente local de
desenvolvimento. Nenhum registro de producao foi alterado.

Regras obrigatorias para todas as fases:

- historicos financeiros permanecem imutaveis;
- uma correcao cria um novo fato auditavel e nunca apaga o fato original;
- contagens fisicas informadas em fechamentos nao sao recalculadas silenciosamente;
- migracoes sao aditivas e inicialmente aceitam os registros legados;
- nenhum saldo e ajustado somente para coincidir com banco ou caixa;
- toda operacao financeira usa `transaction.atomic`, bloqueio das linhas afetadas e
  chave de idempotencia;
- alteracoes de periodo fechado exigem permissao especifica, motivo e aprovacao;
- a implantacao sera gradual, com previa, modo de leitura e possibilidade de desativar
  a nova interface sem desfazer dados.

## 2. Evidencias encontradas no backup

### Caso dos R$ 200

O backup contem a transferencia de R$ 200 do Nubank para o caixa, com data de
movimento em 01/10 e registro efetuado em 03/10. A saida bancaria esta conciliada com
a linha MAFRATEX e a entrada de dinheiro foi vinculada ao caixa de 01/10.

O fechamento de 01/10 preservou a contagem fisica de R$ 405,93. Depois da inclusao
retroativa, o esperado desse fechamento foi acrescido em R$ 200 e passou a apresentar
diferenca de R$ -200. As aberturas posteriores continuaram usando a ultima contagem
fisica, e nao o saldo teorico corrigido.

No backup, o caixa de 03/10 esta aberto. Seus movimentos formam exatamente o esperado
de R$ 223,00:

- saldo inicial: R$ 385,93;
- saida em dinheiro: R$ 200,00;
- outra saida em dinheiro: R$ 13,72;
- entrada registrada como sobra: R$ 50,79;
- esperado: R$ 223,00.

A contagem relatada de R$ 423,00 gera a diferenca positiva de R$ 200,00. Portanto, o
fluxo correto nao deve criar uma segunda entrada de R$ 200 nem somar esse valor
automaticamente a todas as aberturas. Deve vincular a diferenca positiva posterior a
correcao retroativa que gerou a diferenca negativa anterior. As contagens permanecem
como checkpoints fisicos imutaveis.

### Registro de R$ 50,79

Existe uma entrada operacional de R$ 50,79 descrita como sobra de caixa de origem nao
confirmada, com hipotese de devolucao de fornecedor nao comprovada. Ela ja integra o
esperado de R$ 223,00.

Nao se deve duplicar, apagar nem transformar automaticamente esse registro em
devolucao de fornecedor. A solucao sera vincula-lo, mediante revisao humana, a uma
divergencia legada com status `pendente de identificacao`. A natureza contabil futura
somente sera definida quando houver comprovacao.

### Limitacoes atuais confirmadas no codigo

- `Caixa` concentra sessao diaria, saldo, contagem e diferenca no mesmo registro.
- pagamentos mistos ja guardam a parte em dinheiro, mas nao existe extrato fisico
  acumulado por local de custodia;
- o resumo generico soma meios bancarios e cartoes, embora eles nao sejam dinheiro de
  gaveta;
- transferencias possuem transacao e chave idempotente, mas uma transferencia para
  caixa fechado nao possui previa de efeitos nem ligacao explicita com cada efeito de
  caixa;
- a correcao atual de lancamento fechado altera diretamente saldo final e diferenca,
  sem cadeia de impactos ou ponto de absorcao;
- a importacao impede a repeticao do mesmo arquivo e usa identificadores do banco
  quando disponiveis. CSV generico sem identificador usa o numero da linha no hash e
  pode duplicar movimentos quando periodos sobrepostos mudam a ordem das linhas;
- sugestoes de conciliacao pontuam valor, data e texto, mas ainda podem apresentar um
  candidato sustentado quase somente pelo valor;
- `ContaPagar` e `PagamentoContaPagar` ja suportam obrigacao e pagamentos parciais,
  mas uma saida manual pode contornar a obrigacao e reconhecer a despesa no pagamento;
- `MovimentoSocio` exige um `AporteCapital` de origem para todas as retiradas, o que
  obriga um aporte historico mesmo quando a classificacao economica e outra.

## 3. Arquitetura proposta

### 3.0 Correcoes estruturais previas no codigo

Antes de criar as novas telas, o nucleo atual precisa dos seguintes ajustes. Eles nao
alteram dados existentes e devem ser cobertos por testes de caracterizacao.

#### Prioridade critica

1. **Corrigir a abertura quando a ultima contagem for zero.** A sugestao atual usa uma
   cadeia baseada em `or`; portanto, uma contagem valida de R$ 0,00 pode ser ignorada e
   substituida pelo saldo contabil anterior. A escolha deve testar `None`, nao o valor
   booleano do decimal.
2. **Extrair abertura e fechamento para servicos transacionais.** O fechamento atual e
   feito diretamente na view, sem `select_for_update` da sessao. O novo servico deve
   bloquear caixa, movimentos relevantes e estado de fechamento no mesmo commit.
3. **Versionar fechamentos e reaberturas.** Hoje o mesmo registro `Caixa` e reaberto e
   depois sobrescrito, preservando apenas o ultimo conjunto de numeros. Criar
   `FechamentoCaixa` imutavel e `EventoSessaoCaixa` para abertura, fechamento,
   reabertura e novo fechamento.
4. **Parar de alterar snapshots fechados diretamente.** A funcao atual de correcao
   soma um delta em `saldo_final` e `diferenca_fechamento`. Substituir por efeito de
   correcao versionado, mantendo o snapshot original e uma visao calculada atual.
5. **Validar colisao de idempotencia.** Servicos que encontram uma chave existente
   retornam o objeto sem verificar se valor, data, empresa, origem e destino coincidem.
   Repeticao identica deve retornar sucesso; mesma chave com payload diferente deve
   gerar conflito auditavel.

#### Prioridade alta

6. **Centralizar o calculo do caixa.** Abertura, fechamento, dashboards e saneamento
   calculam saldos em funcoes diferentes. Criar `CalculadoraCaixaFisico` pura, com um
   resultado tipado contendo saldo anterior, entradas em dinheiro, saidas, esperado,
   contado, diferenca e totais nao fisicos.
7. **Eliminar a ambiguidade de `saldo_final`.** O campo atual representa um total
   contabil que mistura meios. Mantê-lo como legado e introduzir campos/snapshots
   explicitos para dinheiro esperado, dinheiro contado e totais por meio.
8. **Vincular explicitamente transferencias e suas pernas.** A transferencia guarda os
   endpoints, mas os lancamentos fisicos criados nao possuem FK para ela. Cada perna
   deve apontar para a operacao de tesouraria que a originou.
9. **Aplicar regras de permissao tambem nos servicos.** As views protegem parte das
   operacoes, mas servicos sensiveis podem ser chamados por outros fluxos. Politicas de
   corrigir, aprovar, reabrir e operar cofre devem ser verificadas no dominio.
10. **Separar executor e aprovador.** O fluxo de socio atualmente registra o mesmo
    usuario como executor e aprovador. Correcoes de periodo fechado, diferencas e
    operacoes sensiveis devem permitir regra de quatro olhos configuravel.

#### Prioridade media

11. **Normalizar datas operacionais.** `Caixa.data` usa criacao automatica, enquanto
    movimentos possuem data efetiva e data de registro. A sessao deve possuir data
    operacional explicita, abertura em, fechamento em e fuso da empresa.
12. **Criar tipos de dominio em vez de JSON livre.** A composicao de pagamentos e a
    conferencia por meio usam JSON. Preservar o snapshot, mas validar com schema e,
    para o novo livro fisico, usar registros relacionais.
13. **Padronizar arredondamento monetario.** Todos os servicos devem quantizar na
    fronteira de entrada e rejeitar composicoes cuja soma seja diferente do total, em
    vez de corrigir silenciosamente o componente principal.
14. **Usar consultas agregadas no extrato.** Alguns resumos atuais iteram objetos em
    Python. O extrato novo deve paginar, agregar no banco e possuir indices por empresa,
    local, data efetiva e status.

### 3.0.1 Limite entre melhoria de codigo e correcao de dados

O desenvolvimento nao executara saneamento sobre o backup nem sobre producao. O
software entregara uma interface que:

- detecta o caso e apresenta a previa;
- exige decisao, justificativa e aprovacao do usuario autorizado;
- cria vinculos, efeitos ou estornos auditados;
- nunca atualiza historicos automaticamente durante a migracao.

Assim, o caso dos R$ 200 e o registro de R$ 50,79 somente serao tratados no computador
oficial depois da atualizacao, por acao explicita do usuario na nova interface.

### 3.1 Livro de dinheiro fisico

Criar os modelos:

- `LocalDinheiroFisico`: gaveta, cofre e outros locais internos, por empresa;
- `OperacaoDinheiroFisico`: cabecalho imutavel, tipo, data efetiva, data de registro,
  justificativa, usuario, aprovador e chave idempotente;
- `PartidaDinheiroFisico`: uma ou duas pernas assinadas por local;
- `VinculoOperacaoLegada`: liga operacao nova a pagamento, lancamento, transferencia,
  fechamento ou divergencia anterior sem reescrever esses objetos;
- `ConfiguracaoFundoTroco`: valor-alvo por gaveta e vigencia.

Regras:

- recebimento em dinheiro cria entrada apenas na gaveta;
- a parte em dinheiro de pagamento misto cria entrada pelo valor liquido de troco;
- PIX, debito e credito nao criam partida fisica;
- gaveta para cofre cria duas pernas de igual valor e saldo total da empresa zero;
- cofre para gaveta usa a operacao inversa;
- sangria e transferencia de custodia, nao despesa e nao retirada de socio;
- saida para fornecedor, socio ou despesa reduz um local e referencia seu documento;
- repeticao da mesma chave retorna a operacao ja criada;
- saldos sao calculados pelo livro, nunca armazenados como verdade editavel.

Para os dados antigos, o extrato usa um adaptador de leitura ate uma data de corte.
Na ativacao, um inventario fisico aprovado cria o saldo inicial de cada local. Nao
havera conversao automatica em massa dos lancamentos antigos.

### 3.2 Extrato do caixa fisico

Nova tela `Caixa > Dinheiro fisico`, com filtros por periodo e local:

- saldo anterior e origem do saldo;
- recebimentos em dinheiro e parcela em dinheiro de pagamentos mistos;
- despesas pagas em dinheiro;
- transferencias banco-caixa;
- movimentacoes gaveta-cofre;
- sangrias, fundo de troco e ajustes aprovados;
- saldo acumulado apos cada linha;
- referencia clicavel para OS, venda, conta a pagar, conciliacao ou correcao;
- data efetiva e data/hora do registro exibidas separadamente;
- indicador de registro retroativo ou de periodo fechado.

O fechamento exibira dois blocos independentes:

1. dinheiro fisico: esperado, contado, diferenca e local;
2. meios nao fisicos: PIX, debito, credito, taxas, pendencias e conciliacao.

### 3.3 Correcao de fechamento fechado

Criar:

- `CorrecaoFechamentoCaixa` com status rascunho, aguardando aprovacao, aplicada,
  absorvida ou estornada;
- `EfeitoCorrecaoFechamento` com valores antes/depois por fechamento;
- `AbsorcaoCorrecaoCaixa`, que liga uma diferenca posterior a uma correcao anterior
  sem criar novo movimento de dinheiro;
- snapshot JSON da previa e versao do algoritmo para auditoria.

Fluxo pela interface:

1. usuario escolhe o fato a corrigir e informa a data efetiva;
2. sistema bloqueia os caixas do intervalo e simula o impacto;
3. previa mostra saldo esperado, contagem preservada e diferenca antes/depois em cada
   data;
4. checkpoints com contagem fisica interrompem a propagacao automatica;
5. usuario escolhe, quando comprovado, o fechamento posterior que absorveu o valor;
6. outro usuario autorizado aprova;
7. aplicacao cria somente vinculos e efeitos auditados; nao altera contagens nem cria
   dinheiro duplicado;
8. uma repeticao com a mesma chave devolve a correcao existente.

Aplicacao ao caso de R$ 200:

- manter a transferencia e a entrada retroativa de 01/10;
- manter a contagem original de 01/10;
- exibir a diferenca negativa causada pela inclusao tardia;
- manter as aberturas baseadas nas contagens fisicas ja informadas;
- no fechamento de 03/10, vincular a diferenca positiva de R$ 200 como absorcao da
  mesma correcao;
- nao gerar nova entrada de R$ 200 e nao mudar a contagem de R$ 423;
- manter a diferenca bruta visivel, mas classifica-la como explicada pela correcao.

Como o backup recebido possui o caixa de 03/10 ainda aberto, essa vinculacao devera
ser oferecida durante o fechamento, e nao aplicada automaticamente na migracao.

### 3.4 Sobras e faltas

Criar `DivergenciaCaixa` com:

- esperado, contado, diferenca bruta e direcao;
- status: pendente, aprovada, em investigacao, identificada, resolvida ou estornada;
- justificativa, evidencias e trilha de aprovacao;
- origem identificada opcional: recebimento, despesa, transferencia, fornecedor,
  socio ou erro de classificacao;
- valor ainda nao explicado, permitindo resolucao parcial;
- ligacao com correcao retroativa quando a diferenca for ponto de absorcao.

Confirmar uma contagem cria a divergencia, mas nao cria receita ou despesa operacional.
Quando a origem for identificada, um assistente de resolucao cria o movimento correto
ou um estorno/neutralizacao e vincula tudo a divergencia.

Para os R$ 50,79, a primeira entrega apenas apresentara o registro legado para revisao.
Se o responsavel confirmar que e sobra sem origem, ele permanece pendente. Se surgir
comprovante de fornecedor, a interface cria a devolucao correta e neutraliza a
classificacao operacional anterior sem apagar o lancamento original.

### 3.5 Fornecedores, devolucoes e rateios

Evoluir o fluxo existente de contas a pagar:

- documento de compra gera obrigacao uma unica vez;
- pagamentos parciais somente reduzem a obrigacao e movimentam banco/dinheiro;
- bloquear ou alertar fortemente quando uma saida manual aparentar pagamento de
  fornecedor com obrigacao aberta;
- criar `DevolucaoCompra` e `RecebimentoDevolucaoCompra` separados: a devolucao reduz
  estoque/custo/obrigacao e o recebimento informa banco ou local fisico, mesmo que
  diferente do meio original;
- criar `RateioDocumentoCompra` e linhas destinadas a OS, estoque, centro de custo ou
  ativo;
- exigir que o usuario confirme os destinos e que a soma seja exatamente o total
  rateavel;
- nunca ratear automaticamente: o sistema pode sugerir e explicar, mas a confirmacao
  e humana.

### 3.6 Socios

Separar eventos juridico-contabeis:

- devolucao de AFAC e amortizacao de emprestimo continuam vinculadas ao aporte/passivo;
- juros de emprestimo ficam separados do principal;
- reducao formal de capital exige referencia e aprovacao;
- retirada/distribuicao a definir com o contador nao exige a criacao de aporte
  ficticio, mas exige socio, competencia, documento, aprovador e classificacao;
- adiantamento ao socio e emprestimo da empresa ao socio devem ser categorias proprias,
  se validadas pelo responsavel contabil.

Antes de liberar as novas classificacoes contabilmente, a empresa devera validar com o
contador quais eventos estao permitidos e seus mapeamentos. A interface pode registrar
o fato financeiro sem inventar capital anterior, mantendo o status `aguardando
classificacao contabil` quando necessario.

### 3.7 Conciliacao e importacao

- manter hash do arquivo para repeticao integral;
- criar uma chave canonica por linha usando identificador do banco; na ausencia dele,
  usar conta, data, valor, descricao normalizada e um indice de ocorrencia estavel no
  proprio dia, acompanhado de alerta de baixa confianca;
- registrar importacoes sobrepostas e relacionar cada linha canonica a todos os lotes
  em que apareceu;
- nunca alterar uma linha conciliada ou periodo fechado por nova importacao;
- detectar conflito quando a mesma chave externa vier com valor/data diferentes;
- exibir motivos de cada sugestao: valor, data, documento, contraparte e referencia;
- nao sugerir como forte quando a unica evidencia for valor igual;
- distinguir `saldo atual calculado`, `saldo do extrato na data` e `saldo confirmado no
  fechamento`;
- destacar recebimento avulso e permitir identificar cliente/origem posteriormente;
- conciliacao e desfazimento continuam imutaveis, com evento inverso e motivo.

## 4. Fases de entrega

### Fase 0 - Protecao e observabilidade

- adicionar permissoes especificas de consultar, corrigir, aprovar e operar cofre;
- padronizar chaves idempotentes e eventos de auditoria;
- criar servico unico de calculo fisico em modo somente leitura;
- adicionar testes de caracterizacao do comportamento legado;
- disponibilizar feature flags por empresa.

### Fase 1 - Primeira entrega recomendada

- livro e extrato de dinheiro fisico;
- locais gaveta/cofre;
- sangria, reforco e fundo de troco;
- previa e aplicacao auditada de correcao retroativa;
- novo relatorio de fechamento por meio;
- divergencias basicas e absorcao da correcao de R$ 200.

Esta fase entra primeiro em `modo sombra`: o novo extrato e comparado com o fechamento
atual sem substituir a operacao. A ativacao de escrita ocorre somente apos a
conferencia de um periodo real.

### Fase 2 - Diferencas e conciliacao

- workflow completo de sobra/falta e aprovacao;
- resolucao posterior da origem;
- importacao sobreposta robusta e conflitos;
- explicacao das sugestoes e saldos por data;
- tratamento assistido do registro legado de R$ 50,79.

### Fase 3 - Fornecedores e socios

- obrigacoes, devolucoes por meio diferente e pagamentos parciais;
- rateio confirmado entre OS, estoque e centros de custo;
- classificacoes de socios desacopladas de aporte ficticio;
- mapeamentos contabilmente validados.

#### Estado tecnico em 05/10/2026

- contas a pagar e pagamentos parciais continuam sendo a fonte da obrigacao;
- a saida manual permite apontar uma conta a pagar aberta e, nesse caso, redireciona
  para a baixa correta sem gravar uma segunda despesa;
- creditos/devolucoes de fornecedor podem ser reconhecidos na propria compra e
  recebidos parcialmente no banco ou no caixa fisico, independentemente do meio de
  pagamento original;
- o recebimento da devolucao usa chave idempotente, operacao atomica, permissao
  financeira e estorno auditado;
- devolucao recebida e classificada separadamente e nao vira receita operacional;
- retiradas a classificar, distribuicao de lucros e adiantamentos de socio podem ser
  registrados sem criar aporte ficticio, aguardando o mapeamento contabil validado;
- o rateio entre OS, estoque e centro de custo agora nasce em rascunho, exige escolha
  humana de cada destino, rejeita excedente e so confirma quando a soma fecha
  exatamente o valor da compra; depois de confirmado, fica imutavel para auditoria.

## 5. Testes de aceitacao obrigatorios

1. Registrar a transferencia retroativa de R$ 200 duas vezes resulta em uma unica
   transferencia e uma unica entrada fisica.
2. A previa mostra o efeito em 01/10 e preserva todas as contagens posteriores.
3. Vincular a diferenca de R$ 200 de 03/10 absorve a correcao sem criar movimento.
4. Repetir a aprovacao ou atualizar a pagina nao duplica efeitos.
5. Pagamento misto soma apenas a parcela em dinheiro, descontado o troco.
6. PIX, credito e debito nao alteram o saldo da gaveta.
7. Sangria reduz a gaveta e aumenta o cofre no mesmo commit; uma falha reverte ambas.
8. A mesma sangria repetida pela chave nao duplica valores.
9. Sobra de R$ 50,79 pode ficar pendente sem virar receita operacional.
10. Pagamento parcial de fornecedor reduz a obrigacao sem reconhecer nova despesa.
11. Devolucao de compra via dinheiro apos compra via PIX movimenta o local correto.
12. Rateio sem soma exata ou sem confirmacao e rejeitado.
13. Importar arquivos sobrepostos mantem uma linha por transacao e preserva conciliadas.
14. Sugestao apenas por valor nao pode ser apresentada como correspondencia forte.
15. Usuario sem permissao nao corrige periodo fechado nem aprova a propria correcao.
16. Ultimo fechamento contado em R$ 0,00 sugere abertura de R$ 0,00, sem usar fallback.
17. Duas tentativas simultaneas de fechamento produzem uma unica versao valida.
18. Reabrir e fechar novamente preserva integralmente a primeira versao do fechamento.
19. Mesma chave idempotente com payload diferente e rejeitada como conflito.
20. Servico sensivel chamado fora da view continua exigindo permissao.

Em 05/10/2026, a suite completa do modulo financeiro foi executada em banco de testes
isolado: 317 testes aprovados. Ja possuem cobertura automatizada, entre outros: caixa
contado em zero, versoes de fechamento, dinheiro fisico e sangria idempotente,
divergencia sem receita artificial, absorcao retroativa de R$ 200 sem duplicacao,
importacao sobreposta, sugestao fraca apenas por valor, retirada de socio sem aporte
ficticio, devolucao de fornecedor por meio diferente e protecao contra duplicacao da
despesa manual. Depois dessa bateria, os dois cenarios de rateio confirmado foram
executados isoladamente e aprovados. As aprovacoes segregadas e os demais testes de
aceitacao ainda devem ser concluidos antes da ativacao completa das fases posteriores.

## 6. Implantacao e reversao

1. gerar e validar backup antes da atualizacao;
2. aplicar somente migracoes aditivas;
3. executar verificacao de integridade e testes de idempotencia;
4. ativar leitura do extrato fisico para administradores;
5. conferir saldos legados e realizar inventario de gaveta/cofre;
6. registrar o saldo de corte aprovado;
7. ativar escrita da Fase 1 para uma empresa;
8. monitorar divergencias antes de liberar as fases seguintes.

Reversao funcional: desativar as feature flags e retornar a interface anterior. As
tabelas novas permanecem preservadas para auditoria; nao ha migracao reversa destrutiva
nem exclusao dos eventos criados. Uma operacao incorreta e revertida por estorno
auditado, nunca por exclusao no banco.

## 7. Decisoes que exigem validacao humana

- classificacoes contabeis exatas de retirada/distribuicao de socios;
- mapeamento contabil de sobra/falta ainda nao identificada;
- data de corte e inventario inicial de cada local fisico;
- aprovador responsavel por correcoes de periodo fechado;
- comprovacao da origem dos R$ 50,79.

Essas decisoes nao impedem a construcao tecnica da Fase 1, mas impedem classificacoes
contabeis automaticas sem respaldo.
