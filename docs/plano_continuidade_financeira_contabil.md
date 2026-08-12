# Plano de continuidade — financeiro, custos, bancos e contabilidade gerencial

Data: 11/08/2026  
Estado: planejado, ainda não implementado  
Dependência: entrega `e9e7d0f` aplicada e validada

## 1. Objetivo

Concluir as evoluções financeiras que ficaram deliberadamente fora da entrega anterior, mantendo três princípios:

1. custo interno nunca aparece para o cliente;
2. competência, vencimento, movimento financeiro e data de registro são fatos diferentes;
3. nenhum evento pode ser contado duas vezes em estoque, margem da OS, contas a pagar, banco ou DRE.

O sistema continuará sendo uma plataforma de gestão e contabilidade gerencial. A classificação contábil oficial, o plano de contas e a escrituração fiscal deverão ser validados pelo contador antes de uma integração formal.

## 2. Diagnóstico das pendências reais

### 2.1. Contas a pagar

Existe cadastro, edição, pagamento parcial e integração bancária, porém a baixa ainda possui limitações:

- usa a data atual como competência e movimento;
- escolhe a conta bancária indiretamente pela configuração da forma de pagamento;
- pagamentos sem conta bancária dependem do caixa atualmente aberto;
- o comprovante não possui uma estrutura própria;
- o custo da OS pode ser ligado a uma saída manual, mas ainda não diretamente à obrigação e às suas parcelas.

### 2.2. Compra específica de uma OS

O custo estimado e o custo real já existem, mas falta um fluxo único:

`item a comprar → compra/obrigação → recebimento da peça → custo real da OS → pagamento → conciliação`

Sem essa ligação, o usuário precisa registrar parte dos fatos separadamente e confirmar manualmente que não houve duplicidade.

### 2.3. Cartão corporativo

O sistema já trata cartão recebido de clientes e sua liquidação futura. Não existe, porém, um módulo próprio para cartão usado pela empresa em despesas, com:

- cartões e responsáveis;
- ciclo de fechamento e vencimento;
- compras parceladas;
- faturas;
- pagamento da fatura por uma conta bancária;
- conciliação sem reconhecer novamente cada compra como saída bancária.

### 2.4. Conciliação e fechamento bancário

OFX/CSV e conciliações 1:1, 1:N e N:1 já existem. Ainda faltam:

- criação orientada de lançamentos a partir de uma linha desconhecida;
- lotes de importação com arquivo, período e hash;
- mapeamentos CSV reutilizáveis por banco;
- saldo informado no extrato e fechamento formal do período;
- painel de diferença e itens não conciliados por conta;
- bloqueio/reabertura auditada de período bancário.

### 2.5. Capital e sócios

Entradas de capital social, AFAC e empréstimo de sócio já podem ser registradas. Faltam os movimentos inversos e o controle do saldo por origem:

- devolução de AFAC;
- amortização de empréstimo;
- retirada/redução de capital;
- juros, quando aplicáveis;
- extrato gerencial por sócio/aportante;
- anexos e aprovação para operações relevantes.

### 2.6. Permissões

Os custos estão protegidos por perfil gerencial, mas o modelo profissional requer permissões distintas para visualizar margem, cadastrar custo, confirmar custo real, estornar, operar retroativamente, pagar contas, fechar banco e administrar capital.

### 2.7. Relatórios

A DRE já incorpora custos diretos da OS e evita duplicidade quando há saída vinculada. Ainda faltam:

- rentabilidade consolidada por OS, técnico e tipo de serviço;
- previsto versus realizado;
- despesas fixas versus variáveis de forma uniforme;
- fluxo por conta e meio de pagamento;
- relatórios de custos pendentes e vínculos incompletos;
- exportações gerenciais consistentes com a tela.

### 2.8. Contabilidade formal

O livro financeiro atual não é um razão contábil por partidas dobradas. Para chegar a esse nível serão necessários plano de contas, eventos contábeis, lançamentos balanceados, fechamento, estorno e exportação ao contador.

## 3. Ordem de desenvolvimento

## Fase 0 — Homologação da entrega atual

Objetivo: confirmar em ambiente de uso que a base para a continuação está estável.

Entregas:

- roteiro assistido para OS sem cobrança;
- custo estimado de peça manual;
- custo de insumo invisível ao cliente;
- baixa e devolução de estoque;
- saída bancária retroativa;
- aporte bancário retroativo;
- importação OFX e conciliação;
- conferência de PDF/orçamento sem custos internos;
- registro de evidência, usuário, resultado e eventual divergência.

Critério de aceite: todos os cenários aprovados em uma empresa de teste e pelo menos um fluxo real controlado, sem divergência de saldo.

## Fase 1 — Contas a pagar e custos da OS — prioridade crítica

Objetivo: criar a cadeia auditável entre custo, obrigação, pagamento e banco.

### Modelo de dados

Evoluir `ContaPagar` e `PagamentoContaPagar` com:

- competência da despesa;
- emissão/documento e vencimento;
- data real do pagamento;
- forma de pagamento;
- conta bancária ou caixa de origem explícitos;
- fornecedor cadastrado opcional, mantendo nome livre para compatibilidade;
- documento, observação e comprovante;
- chave de idempotência;
- usuário e auditoria de estorno;
- vínculo de `CustoOrdemServico` com a conta a pagar e, quando aplicável, com a parcela.

### Regras

- criar a obrigação reconhece a despesa/custo na competência, sem reduzir banco ou caixa;
- pagar reduz somente a conta financeira escolhida, na data informada;
- dinheiro exige caixa da mesma data e aberto;
- PIX, transferência e débito exigem conta bancária;
- pagamento parcial preserva saldo da obrigação;
- custo de OS ligado à conta a pagar não pode ultrapassar o valor da obrigação;
- uma conta pode distribuir custos entre várias OS, com soma controlada;
- estorno de pagamento não apaga o registro original;
- cancelar obrigação com custo real ou pagamento exige fluxo de reversão documentado;
- pagamento não duplica o custo na DRE.

### Interface

- assistente “Registrar compra/custo da OS”;
- opção de gerar conta a pagar agora ou registrar material já disponível;
- distribuição do valor entre uma ou várias OS;
- alerta de valor não alocado ou alocado em excesso;
- extrato cronológico da obrigação, pagamentos e estornos.

Critério de aceite: uma compra específica pode sair do orçamento, gerar obrigação, virar custo real, ser paga total ou parcialmente por banco e ser conciliada sem dupla contagem.

## Fase 2 — Compras e recebimento da peça — prioridade alta

Objetivo: profissionalizar itens “a comprar” sem exigir cadastro prévio completo no estoque.

Entregas:

- fila de itens aprovados com situação `a comprar`;
- pedido/cotação simples por fornecedor;
- recebimento parcial ou total;
- opção “usar diretamente na OS” ou “dar entrada no estoque”;
- atualização do custo real a partir do recebimento;
- vínculo com XML/NF-e importada quando existir;
- divergência entre quantidade/custo estimado e recebido;
- cancelamento da compra com motivo;
- alerta ao fechar OS com peça manual sem custo real confirmado.

Critério de aceite: nenhuma peça comprada para uma OS concluída permanece silenciosamente com custo zero.

## Fase 3 — Cartão corporativo e faturas — prioridade alta

Objetivo: separar compra no cartão da saída bancária que paga a fatura.

### Modelos propostos

- `CartaoCorporativo`: empresa, emissor, final, responsável, limite, dia de fechamento, vencimento e conta de pagamento padrão;
- `CompraCartaoCorporativo`: data, competência, fornecedor, valor, parcelas, categoria, centro, OS/custo opcional e comprovante;
- `ParcelaCartaoCorporativo`: competência, valor, fatura e status;
- `FaturaCartaoCorporativo`: período, fechamento, vencimento, total calculado, total informado, diferença e status;
- `PagamentoFaturaCartao`: conta bancária, data, valor, referência e movimento conciliável.

### Regras

- compra no cartão reconhece despesa/obrigação, não saída bancária imediata;
- parcelamento distribui vencimentos sem alterar a competência configurada para a despesa;
- pagamento da fatura gera uma única saída bancária;
- compras da fatura não geram saídas bancárias individuais;
- diferença entre fatura calculada e informada exige tarifa, juros, estorno ou justificativa;
- devolução de compra gera crédito auditável na fatura.

Critério de aceite: compras, parcelas e pagamento de uma fatura fecham sem duplicar a despesa ou a saída bancária.

## Fase 4 — Conciliação e fechamento bancário — prioridade alta

Objetivo: transformar a tesouraria em processo mensal verificável.

Entregas:

- `ImportacaoExtrato` com nome, hash, período, saldo inicial/final e usuário;
- linhas de extrato vinculadas ao respectivo lote;
- perfis de mapeamento CSV por banco;
- ação “Criar lançamento desta linha” com opções despesa, receita não operacional, transferência, aporte, tarifa, juros ou rendimento;
- sugestões de categoria, centro e contraparte com confirmação humana;
- visão de pendências e diferença por conta/período;
- fechamento bancário com saldo do sistema, saldo do extrato e diferença zero;
- reabertura somente com permissão, motivo e auditoria;
- relatório de itens não conciliados.

Automação segura:

- correspondências exatas podem ser sugeridas em lote;
- nenhuma linha desconhecida deve virar despesa/receita automaticamente sem confirmação;
- importações repetidas devem continuar idempotentes.

Critério de aceite: o mês de uma conta pode ser fechado com todas as linhas tratadas e saldo final igual ao extrato.

## Fase 5 — Capital, empréstimos e movimentos de sócios — prioridade média

Objetivo: controlar entradas e saídas de recursos dos sócios fora do resultado operacional.

Entregas:

- saldo por tipo e aportante;
- devolução de AFAC;
- amortização de empréstimo e juros separados;
- retirada/redução de capital;
- anexos e documento de referência;
- aprovação para saídas de capital;
- integração com banco e conciliação;
- relatório cronológico por sócio/aportante.

Critério de aceite: principal de capital/empréstimo não altera receita ou despesa operacional; somente juros e encargos seguem a classificação gerencial configurada.

## Fase 6 — Permissões e segregação de funções — prioridade alta

Objetivo: permitir equipes maiores e futuras empresas sem expor informações sensíveis.

Permissões propostas:

- visualizar custo estimado;
- editar custo estimado;
- visualizar custo real e margem;
- registrar consumo sem visualizar valor do custo;
- confirmar custo real;
- estornar custo;
- criar/editar conta a pagar;
- pagar conta;
- lançar retroativamente;
- importar extrato;
- conciliar e desfazer conciliação;
- fechar/reabrir período bancário;
- registrar e devolver capital;
- visualizar DRE e relatórios de rentabilidade;
- administrar plano de contas.

Regras:

- negar no backend, não apenas ocultar botões;
- filtrar sempre por empresa;
- registrar tentativas negadas nas operações críticas;
- manter custos fora de PDFs, portal, mensagens e respostas destinadas ao cliente.

Critério de aceite: matriz automatizada confirma acesso e negação por perfil, empresa e operação.

## Fase 7 — Relatórios de rentabilidade e qualidade dos dados — prioridade média

Objetivo: oferecer visão gerencial confiável sem se apresentar como contabilidade oficial.

Entregas:

- rentabilidade por OS: receita, custo estimado, custo real, impostos, taxas, comissão e margem;
- previsto versus realizado por período;
- rentabilidade por técnico, tipo de equipamento, tipo de serviço e empresa;
- despesas fixas e variáveis por categoria/centro;
- fluxo realizado por conta e meio de pagamento;
- posição de contas a pagar e receber;
- painel de dados incompletos: peça sem custo, custo sem vínculo, pagamento sem conciliação e período aberto;
- CSV/PDF com os mesmos filtros e totais da tela;
- fechamento gerencial mensal com snapshot imutável e reabertura auditada.

Critério de aceite: o mesmo período/filtro produz os mesmos totais no card, tabela, CSV, PDF e fechamento.

## Fase 8 — Plano de contas e partidas dobradas — prioridade posterior

Objetivo: preparar integração contábil, sem substituir a validação profissional.

### Estrutura proposta

- plano de contas versionado por empresa;
- contas patrimoniais e de resultado;
- eventos contábeis parametrizados;
- lote contábil e lançamentos com débito e crédito balanceados;
- competência, histórico, documento e centro de custo;
- fechamento por competência;
- estorno por contrapartida, sem exclusão;
- exportação em formato definido com o contador.

### Eventos iniciais

- venda/serviço;
- recebimento;
- compra e obrigação;
- pagamento de fornecedor;
- consumo de estoque/CMV;
- despesa no cartão e pagamento da fatura;
- aporte, empréstimo e amortização;
- transferência entre contas;
- impostos e taxas;
- estornos.

Critério de aceite: todo lote possui débitos iguais aos créditos, mantém rastreabilidade até o documento original e é aprovado em uma competência piloto pelo contador.

## 4. Dependências e decisões externas

O sistema pode oferecer padrões profissionais, mas algumas decisões devem ser confirmadas pelo usuário e/ou contador antes das respectivas fases:

- categorias e centros de custo adotados pela empresa;
- regime de competência usado em compras parceladas;
- tratamento de AFAC, empréstimos, juros e retiradas;
- plano de contas e códigos contábeis;
- formato de exportação aceito pelo escritório contábil;
- regras de aprovação e limites por usuário;
- cartões, datas de corte e contas bancárias reais;
- data de corte e saldos iniciais para implantação.

Essas decisões serão configurações por empresa. Não devem ficar fixas no código.

## 5. Estratégia de migração

- migrações aditivas e reversíveis sempre que possível;
- novos campos inicialmente opcionais para preservar registros antigos;
- relatório de saneamento antes de tornar campos obrigatórios;
- nenhum custo histórico presumido como zero confirmado;
- nenhuma despesa antiga movida automaticamente entre caixas ou bancos;
- pagamentos antigos recebem marcador de “data/origem não confirmada” quando não houver evidência;
- backfills idempotentes e com contagem antes/depois;
- backup obrigatório antes de cada implantação relevante;
- ativação das novas regras por empresa após homologação.

## 6. Testes obrigatórios por fase

Cada fase deve conter:

- testes de modelo e serviço;
- idempotência;
- estorno e reprocessamento;
- isolamento por empresa;
- permissões no backend;
- datas retroativas e virada de mês;
- valores parciais e arredondamento;
- ausência de dupla contagem na DRE;
- ausência de custos nos documentos do cliente;
- regressão dos módulos `ordens`, `orcamentos`, `estoque`, `caixa`, `configuracoes` e `fiscal` quando afetados.

## 7. Portões de qualidade

Uma fase só pode seguir para produção quando:

1. migrações e rollback lógico estiverem revisados;
2. `manage.py check` e `makemigrations --check` estiverem limpos;
3. testes direcionados e suíte ampla passarem;
4. auditoria multiempresa não apontar pendências;
5. roteiro manual de homologação estiver aprovado;
6. documentação de usuário estiver atualizada;
7. dados internos não aparecerem em saídas para o cliente;
8. saldos antes/depois forem reconciliados.

## 8. Marcos de entrega

### Marco A — Integridade de compras e pagamentos

Fases 0, 1 e 2 concluídas. O sistema controla peça a comprar, custo real, obrigação, pagamento e conciliação.

### Marco B — Tesouraria completa

Fases 3, 4 e 5 concluídas. Cartões corporativos, bancos e recursos dos sócios possuem fluxos auditáveis.

### Marco C — Gestão profissional multiempresa

Fases 6 e 7 concluídas. Permissões granulares e relatórios consistentes suportam crescimento da operação.

### Marco D — Integração contábil

Fase 8 concluída e validada com o contador em competência piloto.

## 9. Próxima execução recomendada

Iniciar pela Fase 0 e imediatamente pela Fase 1. A primeira implementação técnica deve corrigir datas e origem financeira de `PagamentoContaPagar` e criar o vínculo controlado entre `CustoOrdemServico` e `ContaPagar`. Somente depois deve ser construído o cartão corporativo ou o razão contábil.
