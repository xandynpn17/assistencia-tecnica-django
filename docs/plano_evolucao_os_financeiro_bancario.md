# Plano de evolução — OS, custos internos, financeiro e bancos

Data: 11/08/2026

## Status da entrega técnica — 11/08/2026

Implementado e validado:

- resultado financeiro da OS e conclusão sem cobrança, sem pagamento fictício de R$ 0,01;
- cancelamento técnico dos recebíveis automáticos antigos de valor zero;
- custo estimado, fornecedor/cotação e situação de aquisição nos itens do orçamento;
- custos reais internos da OS, insumos manuais, estorno e margem gerencial restrita à gestão;
- baixa de estoque gerando custo histórico da OS e devolução estornando o mesmo custo;
- recuperação conservadora de custos para consumos históricos de estoque identificáveis;
- vínculo opcional do custo da OS à saída financeira, com limite de alocação e proteção contra dupla contagem na DRE;
- saída por dinheiro/caixa ou meio eletrônico/conta bancária, inclusive bancária retroativa sem exigir caixa aberto;
- proteção para não lançar dinheiro retroativo em um caixa físico de outra data ou já fechado;
- cadastro de contas, movimentos, transferências, importação OFX/CSV idempotente e conciliação existente;
- capital social, AFAC e empréstimo de sócio fora da receita operacional, com aporte bancário retroativo;
- relatórios por data informada sem restrição silenciosa ao caixa atual;
- DRE separando peças baixadas do estoque e custos diretos internos das OS;
- isolamento por empresa auditado sem pendências;
- 538 testes automatizados aprovados no conjunto `ordens`, `orcamentos`, `caixa` e `configuracoes`.

Evoluções posteriores, fora desta entrega:

- cartão corporativo com ciclo completo de fatura;
- integração direta do custo da OS com conta a pagar e compras parceladas;
- fechamento bancário mensal formal e criação orientada de lançamentos a partir de linhas do extrato;
- mapeamentos CSV reutilizáveis específicos por banco;
- permissões financeiras mais granulares que os perfis gerenciais atuais;
- partidas dobradas, plano de contas contábil e exportação para o contador.

Esses itens posteriores não impedem os fluxos entregues, mas são necessários antes de tratar o sistema como escrituração contábil formal.

O roteiro detalhado dessas evoluções está documentado em `docs/plano_continuidade_financeira_contabil.md`.

## 1. Objetivo

Corrigir a apuração de margem das Ordens de Serviço, permitir custos internos e peças avulsas sem distorcer o valor apresentado ao cliente, vincular corretamente despesas ao meio de pagamento e à conta financeira e profissionalizar o acompanhamento bancário e a conciliação.

O sistema continuará sendo uma ferramenta de gestão financeira e contabilidade gerencial. Escrituração contábil e classificação fiscal definitiva continuam sujeitas à validação do contador.

## 2. Regra inviolável de privacidade comercial

Custos internos nunca serão apresentados ao cliente.

Isso inclui:

- custo estimado de peças;
- custo real de compra;
- custo médio ou histórico do estoque;
- custo de componentes e insumos;
- fornecedor e cotação interna;
- margem, markup e rentabilidade;
- impostos estimados internamente;
- taxas de cartão e comissões;
- observações internas de compra e custo.

Esses dados não podem aparecer em:

- orçamento impresso ou PDF;
- OS original ou duplicado;
- relatório técnico;
- recibo ou comprovante entregue ao cliente;
- etiquetas;
- mensagens, e-mails ou WhatsApp gerados para o cliente;
- portal/consulta pública;
- exportações destinadas ao cliente;
- respostas de API ou telas sem permissão financeira.

Não haverá opção `mostrar custo ao cliente`. A separação será estrutural: documentos comerciais consultarão apenas preço, descrição e quantidade de venda. Custos ficarão em estruturas e permissões internas.

## 3. Diagnóstico atual

### 3.1. Peça manual no orçamento

Um item manual classificado como peça possui preço de venda, mas não guarda adequadamente o custo estimado ou real. Sem vínculo com estoque, a margem pode ser calculada como se a peça não tivesse custo.

### 3.2. Insumos embutidos no serviço

Materiais como teclas, solda, fluxo, fios, conectores, parafusos e produtos de limpeza podem ser usados no reparo sem constituírem uma cobrança separada ao cliente. Hoje não há um fluxo completo para atribuir esses custos diretamente à OS.

### 3.3. Despesas e pagamentos

A saída manual possui datas e classificação financeira, mas não exige simultaneamente meio de pagamento e conta de origem. Como consequência, despesas bancárias podem afetar indevidamente o caixa físico atual.

### 3.4. Bancos

Já existem cadastro de contas, movimentos bancários, importação CSV, proteção contra duplicidade e conciliação. Faltam centralização visual, formatos adicionais, integração uniforme com despesas/recebimentos e fechamento bancário por período.

### 3.5. OS sem cobrança

OS zeradas e recebíveis antigos de valor zero precisam de tratamento comercial próprio, sem simular pagamento de R$ 0,00 ou exigir R$ 0,01.

## 4. Modelo funcional proposto

### 4.1. Item comercial

Representa o que o cliente contratou e pode enxergar:

- tipo: serviço ou peça;
- nome e descrição comercial;
- quantidade;
- preço unitário;
- desconto;
- garantia;
- total cobrado.

### 4.2. Estimativa interna de custo

Usada durante a criação do orçamento para avaliar viabilidade e formar preço:

- custo estimado unitário;
- fornecedor/cotação opcional;
- referência e validade da cotação;
- prazo estimado de compra;
- situação: disponível, a comprar, solicitado, recebido ou cancelado;
- observação interna.

A estimativa não gera estoque, despesa, conta a pagar, movimento bancário ou lançamento na DRE.

### 4.3. Custo real da OS

Criar `CustoOrdemServico`, acessível somente internamente, com:

- empresa e OS;
- vínculo opcional com item do orçamento;
- tipo: peça, componente, insumo, consumível, terceiro, frete ou outro;
- origem: estoque, compra específica, conta a pagar, despesa paga ou lançamento manual autorizado;
- produto de estoque opcional;
- descrição, unidade e quantidade;
- custo unitário histórico e total;
- fornecedor e documento opcionais;
- competência;
- centro de custo e categoria;
- vínculos com estoque, conta a pagar e movimento financeiro, quando existentes;
- usuário, data de registro, justificativa e estorno.

O custo real é um retrato histórico: alterações futuras no custo do produto não modificam a margem de uma OS concluída.

### 4.4. Regras contra dupla contagem

- Material em estoque: gera consumo e custo da OS, sem nova saída de dinheiro.
- Compra a prazo específica: gera custo da OS e conta a pagar, sem saída até o pagamento.
- Compra paga no momento: gera custo e movimento na conta escolhida.
- Insumo manual já disponível: gera custo da OS, sem criar pagamento fictício.
- Um custo vinculado a estoque, compra ou despesa não pode ser reconhecido novamente por outro caminho.
- Estorno preserva o registro original e cria contramovimento auditável.

### 4.5. Margem da OS

Apresentar apenas a usuários autorizados:

`Receita líquida − peças − insumos − terceiros − impostos − taxas − comissões = resultado da OS`

Durante o orçamento, mostrar margem prevista usando custos estimados. Após compra/consumo, mostrar margem realizada e a diferença entre estimado e real.

## 5. Fluxos de uso

### 5.1. Peça avulsa cobrada do cliente

1. Usuário inclui uma peça manual no orçamento.
2. Informa preço de venda e custo estimado interno.
3. Sistema calcula margem prevista.
4. Após aprovação, a peça fica marcada como “a comprar”.
5. Ao receber/comprar, usuário informa ou importa o custo real.
6. O custo real é vinculado à OS e substitui a estimativa na margem realizada.
7. Se a OS for concluída sem custo real, o sistema alerta e exige correção ou justificativa autorizada.

### 5.2. Insumo incluído no serviço

1. Cliente vê somente “Recuperação da placa”.
2. Técnico ou responsável abre a área interna “Custos e materiais”.
3. Registra teclas, solda e demais materiais utilizados.
4. Pode escolher produto de estoque ou “Insumo manual”.
5. O sistema calcula o custo da OS sem acrescentar itens ao orçamento do cliente.

### 5.3. Despesa

Toda saída exige:

- descrição, categoria e centro de custo;
- competência e data real do movimento;
- meio: dinheiro, PIX, transferência, débito, crédito, boleto, débito automático ou outro;
- origem: caixa físico, conta bancária, cartão corporativo ou conta transitória;
- beneficiário e documento opcionais;
- comprovante opcional;
- OS vinculada, quando a despesa for específica de um reparo.

Regras:

- dinheiro exige caixa aberto e afeta somente o numerário físico;
- PIX, débito e transferência exigem conta bancária;
- cartão corporativo cria obrigação da fatura e não reduz o banco imediatamente;
- movimento retroativo afeta a conta e a data informadas, sem alterar silenciosamente caixa fechado;
- data de cadastro permanece imutável para auditoria.

### 5.4. Conta bancária e extrato

1. Cadastrar banco, agência, conta, tipo, saldo inicial e data de corte.
2. Associar PIX, cartão, boleto e demais formas às respectivas contas de liquidação.
3. Registrar automaticamente movimentos gerados por recebimentos, despesas, transferências e aportes.
4. Importar extrato OFX ou CSV.
5. Conciliar correspondências exatas automaticamente e apresentar sugestões prováveis.
6. Tratar linhas sem correspondência como despesa, transferência, aporte, tarifa, juros ou rendimento.
7. Confirmar fechamento por período comparando saldo do sistema e saldo do extrato.

## 6. Plano de implementação

### Fase 0 — Proteção e diagnóstico de dados — prioridade crítica

- inventariar OS manuais sem custo e recebíveis zerados;
- identificar lançamentos retroativos ligados ao caixa atual;
- criar relatório de inconsistências sem alterar dados automaticamente;
- preparar migrações reversíveis e rotinas idempotentes;
- registrar métricas antes da correção.

### Fase 1 — OS sem cobrança — prioridade crítica

- criar resultado financeiro: cobrável, cortesia, garantia, sem reparo, cancelada ou uso interno;
- implementar “Concluir sem cobrança” com justificativa;
- impedir criação de conta a receber de valor zero;
- retirar recebíveis zero antigos das pendências, preservando histórico;
- manter OS gratuitas nos relatórios operacionais.

### Fase 2 — Custos estimados no orçamento — prioridade alta

- adicionar custo estimado e dados de cotação ao item manual;
- permitir custo somente a perfis autorizados;
- calcular margem prevista e preço mínimo interno;
- alertar margem negativa ou abaixo da meta;
- assegurar que formulários e documentos do cliente não recebam esses campos.

### Fase 3 — Custos reais e insumos da OS — prioridade alta

- criar `CustoOrdemServico` e permissões;
- criar aba interna “Custos e materiais” na OS;
- aceitar produto do estoque e insumo manual;
- integrar compra específica, estoque e contas a pagar;
- congelar custo histórico no consumo;
- implementar alertas de custo pendente e variação estimado/real;
- criar estorno e trilha de auditoria;
- impedir dupla contabilização.

### Fase 4 — Saídas por meio e conta financeira — prioridade crítica

- tornar meio de pagamento e origem financeira obrigatórios;
- separar caixa físico, bancos, cartões e contas transitórias;
- corrigir movimentações retroativas;
- permitir saídas bancárias sem caixa aberto;
- tratar cartão corporativo por fatura/conta a pagar;
- unificar o serviço de pagamento, movimento, livro e auditoria.

### Fase 5 — Contas bancárias e conciliação — prioridade alta

- reorganizar a tela “Contas e extratos”;
- mostrar saldo do sistema, saldo do extrato, diferença e pendências;
- adicionar importação OFX;
- criar mapeamentos CSV reutilizáveis por banco;
- anexar e identificar arquivo, período e hash da importação;
- melhorar regras de sugestão e conciliação 1:1, 1:N e N:1;
- permitir criação orientada de lançamentos a partir do extrato;
- criar fechamento mensal e relatório de itens não conciliados;
- manter conexão automática via Open Finance/API como fase posterior.

### Fase 6 — Capital, saldos iniciais e sócios — prioridade alta

- separar saldo de implantação, capital, AFAC e empréstimo de sócio;
- permitir conta/data corretas sem tratar como receita operacional;
- criar devolução, amortização e retirada com classificação própria;
- integrar aportes bancários à conciliação;
- exigir validação contábil das classificações configuradas.

### Fase 7 — Relatórios e rentabilidade — prioridade alta

- padronizar movimento, competência, vencimento e registro;
- corrigir filtros de período em cards, tabelas, gráficos, CSV e PDF;
- criar rentabilidade por OS, técnico, tipo de serviço e período;
- separar margem prevista da realizada;
- apresentar fluxo de caixa por conta e meio;
- manter capital fora da receita operacional;
- disponibilizar relatório de divergências e dados incompletos.

### Fase 8 — Integração contábil futura — prioridade posterior

- estruturar plano de contas gerencial;
- mapear eventos a débito e crédito;
- exportar lançamentos para o contador;
- avaliar integração com sistema contábil;
- não apresentar a gestão financeira atual como escrituração oficial.

## 7. Segurança e permissões

Criar permissões distintas:

- visualizar custos da OS;
- cadastrar/alterar custos estimados;
- confirmar custos reais;
- visualizar margem;
- estornar custos;
- lançar movimento retroativo;
- conciliar extratos;
- registrar diferença bancária;
- gerenciar capital e saldos iniciais.

Técnicos podem registrar consumo conforme a política da empresa, mas preço de custo, margem e dados financeiros podem ficar restritos à administração.

Templates, serializers, exportadores e geradores de PDF voltados ao cliente devem possuir testes que confirmem a ausência dos campos internos.

## 8. Migração e tratamento do histórico

- não presumir custo zero como custo real confirmado;
- marcar peças manuais históricas sem custo como “custo não informado”;
- permitir saneamento por lote com usuário e justificativa;
- não recalcular automaticamente OS fechadas sem autorização;
- preservar valores originais e registrar ajustes;
- gerar lista de recebíveis zero para correção segura;
- identificar despesas retroativas que afetaram caixa incorreto;
- reconciliar saldos iniciais com uma data de corte aprovada.

## 9. Testes obrigatórios

### Privacidade

- custo não aparece em orçamento, OS, recibo, RT, etiqueta ou PDF;
- usuário sem permissão não recebe custo pela tela, exportação ou API;
- busca, mensagens e impressão não vazam fornecedor ou margem.

### Custos

- peça manual com custo estimado calcula margem prevista;
- custo estimado não altera estoque nem financeiro;
- custo real altera margem realizada;
- insumo manual entra no custo sem aparecer para cliente;
- consumo de estoque usa custo histórico;
- custo não é duplicado ao pagar a compra;
- conclusão com custo pendente alerta corretamente;
- estorno recompõe os efeitos aplicáveis.

### Financeiro

- PIX afeta somente a conta bancária escolhida;
- dinheiro afeta somente o caixa correto;
- cartão corporativo gera fatura, sem saída bancária imediata;
- lançamento retroativo respeita data e conta;
- caixa fechado não é alterado silenciosamente;
- OS zero não gera recebível nem exige pagamento.

### Bancos

- reimportar o mesmo extrato não duplica linhas;
- OFX e CSV normalizam sinais e datas corretamente;
- conciliações 1:1, 1:N e N:1 fecham os totais;
- desfazimento preserva auditoria;
- linha desconhecida pode gerar lançamento categorizado;
- saldo final do sistema confere com o extrato.

### Relatórios

- mesmo filtro gera os mesmos totais em card, tabela, gráfico e exportação;
- fluxo usa data de movimento;
- DRE gerencial usa competência;
- previsto usa vencimento;
- auditoria usa data de registro.

## 10. Critérios de conclusão

O plano será considerado concluído quando:

1. Nenhum custo interno puder aparecer para o cliente.
2. Peças manuais não forem tratadas silenciosamente como custo zero.
3. Insumos não faturados reduzirem corretamente a margem da OS.
4. Uma saída identificar meio, conta e data real.
5. Despesas bancárias não alterarem o dinheiro físico.
6. OS zeradas forem concluídas sem pagamento e sem pendência.
7. Contas bancárias puderem ser fechadas contra extratos importados.
8. Capital e empréstimos de sócio não forem classificados como receita operacional.
9. Relatórios respeitarem integralmente os filtros escolhidos.
10. Toda correção relevante possuir usuário, data, justificativa e possibilidade de auditoria.

## 11. Ordem recomendada de entrega

Executar primeiro as fases 0, 1 e 4, pois corrigem valores potencialmente incorretos no caixa e contas a receber. Em seguida, executar as fases 2 e 3 para formar preço e margem corretamente. Depois, concluir bancos, capital e relatórios. A integração contábil formal permanece como evolução posterior.
