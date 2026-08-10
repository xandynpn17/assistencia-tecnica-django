# Manual do utilizador — criação de produtos e configuração fiscal

## 1. Objetivo deste manual

Este manual explica como cadastrar produtos e serviços, informar custos, utilizar a assistência tributária e definir o preço final. Ele também esclarece o que o sistema calcula automaticamente e quais dados precisam ser confirmados pelo responsável fiscal ou contador.

O sistema oferece uma **estimativa gerencial** para formação de preço e margem. Ele não substitui o enquadramento fiscal oficial, o PGDAS-D, a escrituração ou a emissão de documentos fiscais.

## 2. Preparação inicial

Antes de cadastrar produtos, confirme:

1. se a empresa correta está ativa;
2. se o regime tributário da empresa está configurado;
3. se existe um perfil tributário vigente;
4. se as regras de revenda, serviços e, quando aplicável, industrialização estão cadastradas;
5. se as faixas e alíquotas foram validadas;
6. se categorias, marcas, fornecedores, pontos operacionais e localizações já estão organizados.

Produtos, fornecedores, regras fiscais e movimentos ficam separados por empresa. Essa separação evita que o cadastro ou a tributação de um CNPJ seja utilizado indevidamente por outro.

## 3. Formas de criar produtos

O sistema oferece três formas principais.

### 3.1. Cadastro individual

Use **Estoque > Novo produto** quando precisar cadastrar um item isolado ou fazer uma configuração detalhada.

### 3.2. Importação de NF-e em XML

Use **Estoque > Entradas > Importar XML** para compras reais. É o fluxo recomendado porque o sistema pode:

- cadastrar ou identificar o fornecedor;
- localizar produtos existentes por EAN ou código do fornecedor;
- sugerir correspondências prováveis;
- indicar conflitos para decisão humana;
- cadastrar produtos novos;
- ratear desconto, frete, seguro e outras despesas da nota;
- atualizar o custo após a conferência;
- criar a entrada e lançar o estoque somente no recebimento;
- criar as contas a pagar, se essa opção for selecionada.

Também é possível importar um ZIP com várias NF-e e revisar os itens na **Central do lote**.

### 3.3. Importação por CSV ou XLSX

Use **Estoque > Produtos > Importar** para implantação de catálogo ou cadastro em massa quando não existir XML fiscal. O sistema aceita dados comerciais, custos e classificações fiscais e permite salvar mapeamentos de colunas por fornecedor.

Uma planilha não substitui a NF-e e, por si só, não comprova uma compra nem cria contas a pagar.

## 4. Cadastro individual passo a passo

### 4.1. Identificação do item

Preencha:

- **Nome:** descrição clara e padronizada;
- **SKU:** código interno; se ficar vazio, o sistema pode gerar um código;
- **EAN:** código de barras; evite inventar um EAN comercial;
- **Tipo do item:** determina o tratamento operacional e ajuda a selecionar a regra fiscal;
- **Categoria:** organiza o catálogo e pode fornecer uma margem padrão;
- **Marca/fabricante:** não precisa ser igual ao fornecedor;
- **Fornecedor:** empresa da qual o item é normalmente comprado;
- **Unidade comercial:** por exemplo, UN, CX ou KG;
- **Ponto operacional e localização:** indicam onde o item fica armazenado.

Se a marca não existir, use a opção de **outra marca/fabricante** e informe o nome. Antes de criar, confira se já não existe uma variação com grafia diferente.

### 4.2. Escolha correta do tipo

- **Produto:** mercadoria comum para revenda;
- **Peça:** item utilizado ou vendido em ordens de serviço;
- **Consumível:** material de consumo ou utilização recorrente;
- **Produto fabricado/industrializado:** item produzido ou transformado pela própria empresa;
- **Serviço:** atividade prestada; não representa quantidade física de mercadoria.

A escolha do tipo não define sozinha o imposto oficial, mas direciona a procura da regra tributária correta. Uma revenda não deve ser cadastrada como serviço apenas porque é vendida junto com uma ordem de serviço.

### 4.3. Classificação fiscal

Para mercadorias, confira os campos:

- **NCM**;
- **CEST**, quando aplicável;
- **origem da mercadoria**;
- **CFOP padrão**;
- **CST/CSOSN**;
- **código de benefício fiscal**, quando aplicável.

Para serviços, confira principalmente:

- **código do serviço**;
- regra de prestação de serviço;
- município e demais informações exigidas no processo fiscal adotado pela empresa.

Use os dados da nota do fornecedor como apoio, mas não trate a informação recebida como validação definitiva para todas as suas operações de saída. NCM, CEST, CFOP, CST/CSOSN e códigos de serviço devem ser homologados por quem responde pela área fiscal.

### 4.4. Regra tributária do produto

O campo **Regra tributária** é opcional.

- Deixe-o vazio quando o produto puder utilizar a seleção automática por empresa, vigência, tipo, finalidade e classificação.
- Escolha uma regra específica quando o item tiver tratamento próprio, como substituição tributária, tributação monofásica, isenção ou outra exceção validada.

Não selecione manualmente uma regra apenas para obter um preço menor. A regra deve representar a operação fiscal real.

## 5. Como preencher os custos

Todos os custos monetários do cadastro são valores **por unidade**.

| Campo | Como utilizar |
| --- | --- |
| Último custo de compra | Valor unitário da compra mais recente. É uma referência de precificação, não o custo médio das baixas. |
| Frete de compra | Parcela unitária do frete de aquisição atribuída ao produto. |
| Custo adicional manual | Reserva para um custo em reais que não esteja detalhado nos demais campos. Evite duplicar valores. |
| Impostos variáveis da venda | Valor estimado em reais por unidade quando existir um custo fiscal monetário não representado pela alíquota percentual. Não repita aqui o imposto já calculado pela regra fiscal. |
| Comissão de venda | Comissão fixa estimada em reais por unidade. |
| Marketplace | Custo fixo/monetário do canal por unidade. Percentuais do canal devem ser tratados pela política correspondente. |
| CAC comercial | Custo de aquisição do cliente atribuído à unidade. |
| Custo médio | Média ponderada das entradas confirmadas. É usado para avaliação e baixa de estoque pelo método adotado. |

Regra prática: **custo da compra** mostra quanto a mercadoria custou para entrar; **custos de venda** mostram quanto custa vendê-la. Ambos podem influenciar o preço, mas devem permanecer identificados para que a margem seja legível.

Na importação de XML, o sistema calcula o custo da entrada com base nos valores da nota e no rateio. Revise sempre antes de receber. Tributos recuperáveis não devem aumentar automaticamente o custo; a recuperabilidade precisa seguir o regime e a orientação fiscal da empresa.

### 5.1. Rateio de custos fixos

Se a empresa quiser considerar aluguel, energia, pessoal administrativo e outros custos fixos na precificação:

1. cadastre os custos fixos na competência correta;
2. defina o critério de rateio;
3. informe a previsão mensal de venda do produto;
4. marque **Incluir rateio de custo fixo**;
5. revise o valor unitário calculado.

O rateio é gerencial. Ele ajuda a evitar preços que pagam apenas a mercadoria e ignoram a estrutura da empresa. Uma previsão de venda irreal pode distorcer o resultado, por isso deve ser revisada mensalmente.

## 6. Como funciona a configuração fiscal

### 6.1. Regime da empresa e regra da operação

O **regime tributário** pertence à empresa. O sistema admite:

- Simples Nacional;
- Lucro Presumido;
- Lucro Real.

A **regra tributária** pertence à operação. Por isso, a mesma empresa pode ter simultaneamente:

- regra de revenda de mercadorias;
- regra de produto fabricado;
- regra de prestação de serviço;
- regras diferentes para serviços sujeitos a anexos distintos;
- regras específicas para oferta, cedência, perda, devolução ou tratamento especial.

No Simples Nacional, não é correto aplicar automaticamente o anexo de serviço a todas as vendas de produtos. O sistema permite separar as regras por natureza e finalidade. O anexo e a taxa efetiva devem ser configurados e confirmados conforme a atividade e a operação reais.

### 6.2. Perfil tributário

Em **Fiscal > Motor tributário**:

1. crie o perfil da empresa;
2. informe o regime e a vigência;
3. para o Simples, informe o RBT12 e, quando necessário, a folha dos últimos 12 meses;
4. crie as regras necessárias;
5. cadastre as faixas do Simples com anexo, limites, alíquota nominal e parcela a deduzir;
6. mantenha o perfil e as regras como **Rascunho** durante a validação;
7. depois da conferência, marque-os como **Homologados**.

O painel **Prontidão da precificação automática** mostra dados ausentes ou inconsistentes, como perfil sem homologação, falta de RBT12, natureza sem regra, produto sem NCM, serviço sem código, custos fixos ausentes ou taxas de recebimento não configuradas.

### 6.3. Mais de um anexo do Simples

O sistema aceita mais de uma regra e mais de um anexo na mesma empresa. Exemplo:

- revenda de mercadorias: regra própria de comércio;
- serviço A: regra de serviço em determinado anexo;
- serviço B: regra sujeita ao Fator R, podendo alternar entre anexos conforme os parâmetros cadastrados;
- produto fabricado: regra própria de industrialização.

O sistema seleciona a regra compatível com a data, o tipo do item, a finalidade e a classificação. Quando o produto possui uma regra específica, ela tem preferência desde que seja compatível.

### 6.4. Cálculo estimado no Simples

Quando as faixas estão cadastradas, a estimativa utiliza o RBT12, a alíquota nominal e a parcela a deduzir da faixa. Em termos gerenciais, a taxa efetiva segue a estrutura:

`(RBT12 × alíquota nominal − parcela a deduzir) ÷ RBT12`

Se não houver uma faixa válida, o sistema pode usar a alíquota estimada configurada na regra ou o parâmetro básico da empresa, apresentando alerta. Um fallback é útil para simulação, mas não deve ser confundido com regra fiscal homologada.

### 6.5. Reforma tributária

As regras possuem vigência e podem receber componentes tributários por período, permitindo simulações e transição entre tributos atuais, CBS, IBS e Imposto Seletivo. Alterações futuras devem ser incluídas como **nova versão da regra**, sem apagar a memória do cálculo antigo.

## 7. Formação do preço

O cadastro apresenta três valores diferentes:

- **Preço sugerido:** resultado calculado com custos, tributos, taxas e margem-alvo;
- **Preço mínimo:** piso gerencial calculado com a margem mínima;
- **Preço final:** valor comercial que será efetivamente utilizado.

### 7.1. Modo Simples

Indicado para cadastro inicial e venda de balcão. Aplica a margem sobre o custo e protege o resultado contra tributos e taxa de recebimento:

`preço sugerido = custo × (1 + margem) ÷ (1 − tributos − taxa)`

### 7.2. Modo Avançado

Indicado quando a margem precisa ser preservada como percentual da receita depois de tributos e taxas:

`preço sugerido = custo ÷ (1 − tributos − taxa − margem)`

O modo avançado normalmente resulta em preço maior que a simples aplicação de um percentual sobre o custo, porque trata a margem como parte da receita final.

### 7.3. Definição do preço final

1. confira o custo unitário completo;
2. confira a regra, o anexo e a alíquota indicados;
3. confira a taxa do canal de recebimento;
4. informe margem-alvo e margem mínima;
5. compare preço sugerido e preço mínimo;
6. simule dinheiro, PIX, cartão e marketplace;
7. informe o preço final decidido pela empresa;
8. justifique e obtenha autorização se o preço ficar abaixo do mínimo.

Quando custo ou tributação mudam, o sistema recalcula o sugerido e o mínimo, mas preserva o preço final já praticado para evitar uma alteração comercial silenciosa.

### 7.4. Exemplo simplificado

Considere:

- custo total considerado: R$ 50,00;
- tributos estimados: 6%;
- taxa de recebimento: 2%;
- margem-alvo: 30%.

No modo avançado:

`50 ÷ (1 − 0,06 − 0,02 − 0,30) = R$ 80,65`

O valor é uma referência gerencial. O preço final ainda deve considerar mercado, arredondamento comercial, descontos e validação dos parâmetros.

## 8. Criação de produtos pela NF-e

### 8.1. Importação

1. abra **Estoque > Entradas > Importar XML**;
2. envie o XML autorizado ou ZIP;
3. selecione ponto e localização de destino;
4. confirme o fornecedor;
5. revise os produtos encontrados;
6. resolva sugestões prováveis e conflitos;
7. preencha categoria, marca, tipo e margens para os produtos novos;
8. informe o preço final ou use zero para aceitar o sugerido;
9. confira custo, rateio e totais;
10. receba a entrada no estoque.

O upload deixa a nota em rascunho. Ele não altera estoque ou financeiro antes da confirmação do recebimento.

### 8.2. Níveis de correspondência

- **Exata:** EAN ou código do fornecedor aponta de forma segura para um cadastro;
- **Provável:** descrição e NCM sugerem uma correspondência, mas o utilizador precisa confirmar;
- **Nova:** não foi encontrado produto correspondente;
- **Conflitante:** os identificadores apontam para produtos diferentes e a decisão deve ser manual.

Produtos existentes não são alterados silenciosamente. Na Central do lote, marque somente os campos que deseja atualizar, como nome, NCM, CEST, CFOP, CST/CSOSN, origem, unidade, margem ou preço final.

### 8.3. Pré-cadastro profissional de produtos novos

Um item desconhecido da NF-e permanece como **pré-cadastro**, sem criar imediatamente um produto ativo. O sistema preenche nome e NCM do XML e pode sugerir categoria e marca usando dados auditáveis do catálogo:

- marca reconhecida na descrição;
- categoria ou marca predominante em produtos do mesmo NCM;
- palavras da categoria encontradas na descrição;
- histórico já confirmado pela empresa.

Cada sugestão mostra confiança e motivo. Ela não é aceita silenciosamente: o utilizador precisa selecionar a opção no formulário ou salvar o rascunho antes da aprovação.

O estado pode ser:

- **Rascunho incompleto:** ainda falta nome, categoria ou NCM;
- **Pronto para aprovação:** campos mínimos preenchidos;
- **Aprovado:** produto criado e vinculado ao item da NF-e;
- **Produto existente:** não exige novo cadastro.

Use **Salvar pré-cadastro** para continuar depois. Essa ação não cria produto, não movimenta estoque e não gera financeiro. Use **Aprovar selecionados e criar produtos** somente após revisar categoria, marca, NCM, natureza, margens e preço.

Se a categoria ou marca não existir, selecione **Outros / criar categoria** ou **Outros / criar marca**. Informe o nome — e a margem padrão, no caso da categoria — e clique **Criar e selecionar**. O novo cadastro pertence somente à empresa ativa e aparece imediatamente em todos os itens da revisão.

### 8.4. Reimportação

O sistema controla chave e conteúdo para evitar duplicidade. Reimportar a mesma NF-e não deve criar outra entrada, outro produto ou outro saldo.

## 9. Oferta, cedência, uso interno e perdas

Não registre uma oferta como venda fictícia.

- **Oferta/brinde:** saída definitiva, justificada por cliente, campanha ou finalidade;
- **Cedência definitiva:** item entregue sem previsão de retorno;
- **Cedência temporária:** item entregue com controlo de devolução e condição;
- **Uso interno:** consumo pela própria empresa;
- **Avaria, perda ou vencimento:** baixa com motivo e evidência.

Essas movimentações baixam o estoque pelo custo, não pelo preço de venda. O eventual documento fiscal e o tratamento tributário devem seguir uma regra validada para a finalidade correspondente.

## 10. Erros mais comuns

- usar o anexo de serviço para mercadorias de revenda;
- somar o mesmo imposto na regra percentual e no custo monetário;
- confundir marca com fornecedor;
- atualizar o preço final automaticamente sem decisão comercial;
- cadastrar saldo inicial para uma compra normal;
- confirmar uma correspondência provável apenas pela descrição;
- incluir tributo recuperável como custo sem validação;
- cadastrar NCM, CFOP ou CST/CSOSN por suposição;
- editar uma regra homologada em vez de criar nova versão;
- considerar a estimativa do sistema como apuração fiscal oficial.

## 11. Checklist antes de salvar um produto

- [ ] empresa ativa correta;
- [ ] tipo do item correto;
- [ ] nome, SKU/EAN, categoria e marca conferidos;
- [ ] fornecedor e unidade informados;
- [ ] NCM ou código do serviço preenchido;
- [ ] regra automática adequada ou exceção específica selecionada;
- [ ] custos informados por unidade e sem duplicidade;
- [ ] margem-alvo e margem mínima revisadas;
- [ ] taxa do canal de recebimento conferida;
- [ ] preço sugerido e mínimo analisados;
- [ ] preço final definido conscientemente;
- [ ] quantidade inicial utilizada somente quando apropriado.

## 12. Checklist fiscal periódico

Mensalmente ou sempre que houver mudança relevante:

- atualizar RBT12 e folha de 12 meses;
- revisar o Fator R, quando aplicável;
- conferir vigência do perfil e das regras;
- revisar produtos sem NCM e serviços sem código;
- verificar regras sem faixa ou ainda em rascunho;
- revisar tratamentos monofásicos, ST, isenções e retenções;
- atualizar taxas de cartão e marketplace;
- revisar custos fixos, previsão de vendas e rateios;
- conferir produtos vendidos abaixo do preço mínimo;
- guardar a evidência e a fonte normativa das decisões fiscais.

## 13. Responsabilidades

O **utilizador operacional** cadastra, importa, confere custos, resolve correspondências e define o preço comercial dentro de sua autorização.

O **responsável financeiro/gestor** valida margens, custos fixos, taxas, preços abaixo do mínimo e políticas comerciais.

O **contador ou responsável fiscal** confirma regime, CNAE, anexos, Fator R, NCM, CEST, CFOP, CST/CSOSN, códigos de serviço, recuperabilidade de tributos, benefícios e tratamentos especiais.

O sistema registra a memória do cálculo e ajuda a aplicar a configuração homologada de maneira consistente, mas a responsabilidade pela classificação fiscal continua sendo humana e documental.
