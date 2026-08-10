# Plano Fiscal, Tributário, Caixa e Estoque — 2026

## 1. Objetivo

Este documento consolida o diagnóstico e o plano de desenvolvimento para:

- separar corretamente venda de mercadorias e prestação de serviços;
- calcular custos, impostos estimados, margem e preço final sem confundir gestão com apuração fiscal;
- preparar o sistema para Simples Nacional, Lucro Presumido, Lucro Real e transição para IBS/CBS;
- profissionalizar caixa, contas bancárias, conciliação e fechamento por meio de pagamento;
- importar XML de compras e transformar a nota em fornecedor, produtos, custos e entrada de estoque conferível;
- corrigir ordens de serviço de valor zero;
- completar as movimentações de estoque, incluindo ofertas, cessões e perdas;
- manter todos os registros separados por empresa, mesmo que inicialmente exista apenas uma empresa usuária.

O plano é técnico e operacional. Classificações fiscais, anexos, alíquotas e tratamentos especiais devem ser homologados pelo contador antes do uso em produção.

## 2. Decisões de arquitetura

### 2.1 Separação por empresa

Todo novo registro fiscal, financeiro, bancário ou de estoque deve possuir vínculo obrigatório com a empresa. Usuários somente poderão consultar ou alterar dados das empresas às quais tenham acesso.

Essa regra deve abranger, no mínimo:

- configurações e perfis tributários;
- produtos, serviços, marcas e fornecedores;
- caixas, contas bancárias e conciliações;
- vendas, ordens de serviço, recebimentos e despesas;
- documentos fiscais e certificados;
- movimentos, saldos e inventários de estoque;
- auditoria, anexos e relatórios.

Não devem existir configurações fiscais globais compartilhadas acidentalmente entre empresas.

### 2.2 Gestão não é apuração fiscal

O sistema pode calcular uma estimativa de imposto para formar preço e projetar margem. Essa estimativa não substitui o cálculo oficial do contador, PGDAS-D, escrituração ou documento fiscal.

Devem existir campos separados para:

- custo de aquisição;
- custos adicionais de aquisição;
- custo médio/contábil;
- imposto estimado para precificação;
- imposto efetivamente apurado;
- preço de venda;
- margem estimada e margem realizada.

### 2.3 Registros financeiros imutáveis

Movimentos confirmados não devem ser apagados ou sobrescritos silenciosamente. Correções devem ocorrer por estorno e novo lançamento, preservando usuário, data, motivo e vínculo com o registro original.

### 2.4 Três datas distintas

Sempre que aplicável, guardar separadamente:

- data de competência: quando a receita ou despesa pertence economicamente;
- data de movimentação: quando o dinheiro entrou ou saiu;
- data/hora de registro: quando o usuário lançou no sistema.

O sistema deve permitir lançamentos retroativos com permissão e trilha de auditoria, sem alterar a data real de criação.

## 3. Diagnóstico consolidado — linha de base

Esta seção preserva o diagnóstico que originou o plano. As expressões “ainda não existe” e “precisa” abaixo descrevem a linha de base anterior às entregas; o estado atual e as evidências estão registrados, fase a fase, na seção 5.

### 3.1 Fiscal e tributário

O sistema atual possui uma base inicial de configuração tributária, porém ainda não representa com segurança todos os cenários necessários.

Principais lacunas identificadas:

- uma única seleção de anexo não atende à empresa que vende mercadorias e presta serviços;
- a configuração existente não governa integralmente o cálculo usado no estoque;
- o cálculo simplificado usa alíquotas configuradas, mas não contempla de forma completa RBT12, faixa, parcela a deduzir e alíquota efetiva;
- o modo avançado soma tributos informados, mas não constitui um motor fiscal confiável;
- não há tratamento completo de Fator R, segregação de receitas, ICMS-ST, monofásico, substituição tributária, DIFAL, antecipação, benefícios ou retenções;
- Lucro Presumido e Lucro Real ainda não possuem fluxo completo de estimativa e apuração;
- não há uma camada preparada para a transição de PIS/Cofins/ICMS/ISS/IPI para CBS, IBS e Imposto Seletivo;
- classificação por NCM, CEST, CFOP, CST/CSOSN, origem e natureza da operação precisa de validação e maior cobertura;
- a emissão fiscal encontrada deve ser tratada como simulação até existir integração real, retorno verificável, armazenamento de XML e tratamento de rejeições;
- certificado e senha não podem ser armazenados de forma insegura nem compartilhados entre empresas.

### 3.2 Venda de produtos e prestação de serviços

Uma empresa do Simples Nacional pode ter receitas submetidas a tratamentos diferentes. Portanto, o regime tributário pertence à empresa, mas a regra de tributação deve ser definida por operação e por item.

O sistema deve permitir, por exemplo:

- mercadoria para revenda associada a uma regra de comércio;
- serviço associado ao anexo aplicável e, quando necessário, ao Fator R;
- produto monofásico ou sujeito a ICMS-ST com tratamento próprio;
- venda mista com itens de produto e serviço segregados no mesmo atendimento;
- alteração de regra com vigência, sem recalcular documentos históricos.

A informação recebida de que a empresa está no “Anexo II” deve permanecer como pendência de validação. Em regra, o Anexo II está ligado a atividades industriais; mercadoria adquirida para revenda normalmente exige outra análise. O sistema não deve decidir isso apenas pelo texto “produto”. CNAE, atividade efetiva, origem da mercadoria e tratamento do item precisam ser confirmados pelo contador.

### 3.3 Caixa e financeiro

Já existe estrutura de fechamento por meio de pagamento, mas o fluxo precisa ser consolidado.

Lacunas prioritárias:

- pagamentos mistos precisam participar corretamente da conferência por meio;
- a contagem de dinheiro físico deve comparar somente o saldo esperado em espécie;
- contas bancárias ainda precisam de cadastro e vínculo com recebimentos, pagamentos e transferências;
- ainda falta conciliação bancária com situação pendente, conciliada, divergente e ignorada justificadamente;
- receitas e despesas precisam aceitar competência e movimentação retroativas;
- fechamento deve gerar fotografia imutável dos valores esperados e informados;
- diferença de caixa precisa de justificativa, permissão e auditoria;
- transferências entre caixa e banco não podem ser tratadas como receita ou despesa;
- ordem de serviço com total zero não pode gerar alerta de pendência nem exigir recebimento mínimo de R$ 0,01.

### 3.4 Estoque

Melhorias já previstas ou implementadas devem permanecer no escopo funcional:

- marca/fabricante com opção “Outros” e preenchimento manual;
- movimentações de oferta e cessão interna;
- perdas, avarias, vencimento, uso interno e ajustes com motivos próprios;
- cálculo assistido de impostos estimados e preço no Simples Nacional.

O cálculo automático do estoque ainda deve evoluir para usar perfis tributários por item/operação. Oferta e cessão devem retirar estoque pelo custo, sem criar uma venda fictícia pelo preço de varejo. O impacto fiscal e documental da saída deverá ser definido pela regra configurada e validada pelo contador.

O recebimento manual de mercadorias já possui uma base funcional: permite fornecedor, documento, itens, quantidades, custos, rateios, lote/série e confirmação posterior do estoque. Entretanto, ainda não existe importação de XML de NF-e de compra. O campo XML da aplicação fiscal não lê uma nota recebida nem cria fornecedor, produtos ou entrada de mercadoria.

Também devem ser corrigidas as seguintes limitações do fluxo atual:

- o cadastro tecnicamente chamado `FornecedorGarantia` é reutilizado como fornecedor comercial e deve ser generalizado sem perder os vínculos existentes;
- o CNPJ do fornecedor deve ser validado e ter unicidade adequada por empresa;
- produto desconhecido não pode ser criado dentro da conferência de uma entrada;
- a importação de produtos existente aceita CSV/XLSX, mas não XML fiscal;
- não há chave de acesso da NF-e armazenada na entrada para impedir importação duplicada;
- a entrada de mercadoria ainda não gera conta a pagar vinculada à compra;
- `custo_unitario` e `custo_medio` precisam ter semântica inequívoca: último custo de compra e custo médio não devem ser confundidos ou sobrescritos sem histórico;
- alteração do custo deve recalcular preço sugerido e preço mínimo, preservando o preço final até decisão autorizada do usuário.

## 4. Modelo funcional proposto

### 4.1 Perfil tributário da empresa

Campos mínimos:

- empresa;
- regime tributário;
- início e fim de vigência;
- CNAE principal e CNAEs secundários;
- inscrição estadual e municipal;
- indicador de contribuinte de ICMS;
- parâmetros do Simples, Presumido ou Real;
- responsável pela validação;
- situação: rascunho, homologado ou inativo.

### 4.2 Regra tributária por operação

Uma empresa poderá ter várias regras simultâneas. A regra deve considerar:

- tipo do item: mercadoria, produto fabricado, serviço ou outro;
- finalidade: revenda, uso/consumo, ativo, oferta, cessão, perda ou devolução;
- origem e destino da operação;
- cliente contribuinte ou não contribuinte;
- NCM/CEST para produtos e código de serviço para serviços;
- anexo/segregação do Simples quando aplicável;
- tratamento monofásico, ST, retenção, benefício ou isenção;
- tributos, bases, percentuais e vigência;
- prioridade e motivo da regra aplicada.

O resultado do cálculo deve explicar qual regra foi usada. Nenhuma alteração futura deve modificar transações já concluídas.

### 4.3 Formação de preço

O assistente de preço deve apresentar separadamente:

1. custo líquido de aquisição;
2. frete, seguro, embalagem e outras despesas;
3. impostos não recuperáveis incorporados ao custo;
4. comissões e taxas variáveis;
5. imposto estimado sobre a venda;
6. margem desejada;
7. preço sugerido;
8. preço final escolhido;
9. margem estimada em reais e percentual.

O usuário deve enxergar alertas para margem negativa, preço abaixo do custo e regra fiscal não homologada.

### 4.4 Movimentações de estoque

Tipos mínimos:

- entrada por compra;
- saída por venda;
- devolução de compra e de venda;
- oferta/brinde;
- cessão interna;
- uso/consumo interno;
- perda, avaria e vencimento;
- ajuste de inventário;
- transferência entre locais/empresas, quando autorizada.

Cada movimento deve possuir quantidade, custo unitário registrado, documento/origem, motivo, usuário, empresa, local de estoque e data. Transferência entre empresas deve ser tratada como operação entre pessoas jurídicas distintas, não como simples troca de endereço.

### 4.5 Contas bancárias e conciliação

Cadastro mínimo:

- empresa e instituição financeira;
- agência, conta e tipo;
- moeda;
- saldo inicial e data do saldo;
- conta contábil/gerencial opcional;
- situação ativa/inativa;
- usuários autorizados.

Conciliação:

- importação ou entrada manual do extrato;
- sugestão de correspondência por valor, data, documento e contraparte;
- conciliação um para um, um para vários e vários para um;
- registro de tarifas, juros e diferenças;
- prevenção de duplicidade;
- auditoria de quem conciliou e desfez a conciliação.

### 4.6 Importação de XML de compras

O fluxo deve ser dividido em importação, conferência e recebimento. Fazer upload do XML não deve movimentar estoque imediatamente.

#### Validação do documento

- aceitar XML autorizado de NF-e de entrada em formato suportado;
- validar estrutura, versão, chave de acesso, emitente, destinatário, número, série e datas;
- conferir se o CNPJ destinatário corresponde à empresa ativa;
- armazenar o arquivo original e um resumo normalizado;
- impedir duplicidade pela combinação empresa + chave de acesso;
- rejeitar arquivos inválidos com mensagem compreensível, sem criar dados parciais;
- tratar XML de cancelamento, evento ou documento diferente sem confundi-lo com nota de compra.

#### Fornecedor

- localizar fornecedor prioritariamente pelo CNPJ normalizado;
- apresentar diferenças de razão social, IE e endereço para revisão;
- permitir criar o fornecedor a partir do XML mediante confirmação;
- nunca alterar automaticamente dados cadastrais relevantes sem mostrar a comparação;
- manter o fornecedor isolado por empresa.

O cadastro deve evoluir de fornecedor de garantia para fornecedor comercial geral, preservando recursos específicos de garantia como dados opcionais.

#### Correspondência e criação de produtos

Para cada item do XML, tentar localizar o produto nesta ordem:

1. GTIN/EAN válido;
2. código do produto no fornecedor associado ao mesmo fornecedor;
3. SKU interno previamente mapeado;
4. correspondência manual escolhida pelo usuário.

Itens sem correspondência devem permanecer pendentes. A tela deve permitir cadastrar o produto sem abandonar a conferência, trazendo do XML apenas dados confiáveis, como descrição, GTIN, código do fornecedor, NCM, CEST e unidade comercial. Categoria, marca, regra fiscal, localização, margem e preço devem ser revisados antes da criação.

Cada associação confirmada deve criar ou atualizar o relacionamento produto-fornecedor para reutilização em importações futuras. Não realizar correspondência automática apenas pela descrição.

#### Custos e valores

- importar quantidade, valor unitário, desconto, frete, seguro, outras despesas e tributos disponíveis;
- distinguir impostos recuperáveis de valores que compõem o custo;
- permitir rateio documentado de valores globais entre os itens;
- mostrar custo anterior, último custo de compra, custo da entrada e custo médio projetado;
- registrar a fórmula e os componentes do custo da entrada;
- recalcular preço sugerido e preço mínimo após o recebimento;
- não alterar automaticamente o preço final praticado, salvo política explícita e autorizada;
- preservar histórico de custo por fornecedor, documento e data.

#### Confirmação e integrações

- gerar uma entrada de mercadoria em rascunho após a importação;
- exigir resolução de produtos pendentes, divergências e lote/série antes do recebimento;
- movimentar o estoque apenas na confirmação “Receber entrada”;
- garantir idempotência para que a mesma entrada não seja recebida duas vezes;
- permitir gerar conta a pagar vinculada à nota, com vencimentos e condições revisáveis;
- vincular XML, entrada, movimentos de estoque e conta a pagar na auditoria;
- permitir cancelar o rascunho sem alterar estoque ou financeiro.

## 5. Plano de execução

### Fase 0 — Contenção e correções críticas

Prioridade: P0.

Status: **concluída em 05/08/2026**.

Entregas realizadas:

- removida a geração local de chave, protocolo e autorização fiscal fictícios;
- fila fiscal sem integração real passa a bloquear os documentos com mensagem explícita de não transmissão;
- documentos anteriormente marcados como autorizados pela simulação são invalidados pela migração, preservando o registro histórico;
- configurações e documentos fiscais passaram a ser isolados por empresa;
- certificado não é solicitado enquanto a integração estiver desabilitada e a senha não é persistida;
- OS com total zero é considerada quitada, não cria recebível, não gera alerta e não redireciona ao caixa;
- pagamentos mistos são decompostos por forma no fechamento;
- saldo contábil permanece separado do dinheiro físico esperado;
- contagem física considera saldo inicial em espécie, parcela recebida em dinheiro, entradas manuais e saídas do caixa, sem somar PIX/cartão;
- migração de realinhamento de sequências passou a executar SQL específico somente no PostgreSQL, permitindo a criação do banco SQLite de testes;
- formulário de itens da OS recebeu o contexto de empresa necessário, eliminando acesso indefinido e filtrando produtos/pontos por empresa.

Evidências automatizadas:

- `manage.py check`: sem problemas identificados;
- `makemigrations --check --dry-run`: nenhuma migração pendente;
- suíte fiscal/OS/fechamento: 26 testes aprovados;
- suíte de isolamento multiempresa: 9 testes aprovados;
- `git diff --check` nos arquivos da fase: sem erros de whitespace.

- impedir que emissão fiscal simulada seja apresentada como autorização real em produção;
- corrigir OS de valor zero para concluir sem recebimento e sem alerta de pendência;
- incluir pagamentos mistos no fechamento por meio de pagamento;
- comparar dinheiro físico somente com movimentos em espécie;
- revisar isolamento por empresa nos cadastros fiscais e financeiros;
- proteger credenciais e senhas de certificado;
- criar testes de regressão para esses casos.

Critérios de aceite:

- OS de R$ 0,00 é finalizada sem lançamento financeiro artificial;
- nenhum alerta de valor pendente é criado para total zero;
- fechamento discrimina corretamente dinheiro, PIX, cartão, boleto e pagamentos mistos;
- divergência de dinheiro não usa valores de meios eletrônicos;
- ambiente de produção não gera chave, protocolo ou status fiscal fictício.

Observação técnica resolvida: `configuracoes/migrations/0086_realinhar_sequencias_configuracoes.py` agora verifica o fornecedor do banco e executa `pg_get_serial_sequence` somente em PostgreSQL. A regressão automatizada voltou a criar e destruir normalmente o banco SQLite de testes.

### Fase 1 — Livro financeiro e datas retroativas

Prioridade: P0/P1.

Status: **concluída em 05/08/2026**.

Entregas realizadas:

- criado livro financeiro imutável, isolado por empresa e vinculado ao caixa e à origem operacional;
- pagamentos, recebimentos e lançamentos manuais geram movimentos idempotentes automaticamente;
- competência, movimentação e data/hora real de registro foram separadas;
- lançamentos com datas diferentes do dia atual exigem permissão específica;
- data de movimentação futura é bloqueada no fluxo operacional;
- exclusão autorizada de pagamento cria contramovimento de estorno e preserva o movimento original, usuário, motivo e vínculo;
- registros do livro não podem ser alterados ou excluídos pelo modelo nem pelo painel administrativo;
- relatório financeiro permite alternar entre regime de caixa/movimentação e competência;
- DRE passou a consultar receitas e despesas pela competência;
- livro financeiro está visível no relatório e pode ser exportado em CSV ou PDF;
- migração faz backfill das datas e dos movimentos históricos sem duplicar entradas vinculadas a pagamentos.

Evidências automatizadas:

- `manage.py check`: sem problemas identificados;
- `makemigrations --check --dry-run`: nenhuma migração pendente;
- suíte específica da Fase 1: 5 testes aprovados;
- regressão conjunta posterior, incluindo descontos, isolamento multiempresa e permissões: 21 testes aprovados integralmente.

- unificar eventos financeiros em um livro de movimentos rastreável;
- separar competência, movimentação e registro;
- permitir lançamentos retroativos conforme permissão;
- implementar estorno em vez de exclusão destrutiva;
- vincular movimentos à venda, OS, despesa, recebimento ou transferência;
- criar histórico completo de alterações;
- revisar relatórios por regime de caixa e competência.

Critérios de aceite:

- o usuário autorizado escolhe datas passadas sem alterar a data de auditoria;
- relatórios podem filtrar por competência ou movimentação;
- estorno preserva o lançamento original;
- somatórios do caixa, contas a receber/pagar e livro financeiro são conciliáveis.

### Fase 2 — Contas bancárias, tesouraria e conciliação

Prioridade: P1.

Status: **concluída em 05/08/2026**.

Entregas realizadas:

- cadastro de contas bancárias isolado por empresa, com saldo inicial, saldo realizado e saldo projetado;
- vínculo opcional da forma de pagamento com a conta bancária de liquidação;
- recebimentos vinculados geram movimento bancário idempotente;
- pagamentos de contas a pagar feitos por forma vinculada a banco geram saída bancária e movimento financeiro idempotentes, sem reduzir o dinheiro físico do caixa e sem exigir caixa aberto;
- taxas de adquirente reduzem o valor líquido previsto e o prazo configura a data futura de liquidação;
- transferências banco–banco, caixa–banco e banco–caixa movimentam tesouraria sem gerar receita ou despesa;
- movimentos bancários são imutáveis e pagamentos excluídos geram movimento bancário inverso;
- importação de extrato CSV por conta com identificador externo e proteção contra duplicidade;
- conciliação manual classifica itens como conciliados ou divergentes, exigindo justificativa para divergência;
- conciliação agrupada aceita um para um, um para vários e vários para um, bloqueando o reaproveitamento de linhas ou movimentos ativos;
- cada conciliação possui totais, diferença, usuário e data próprios; o desfazimento exige motivo, devolve as linhas ao estado pendente e preserva o histórico original;
- a conciliação simples destaca correspondências exatas por valor e a diferença de data para auxiliar a conferência;
- linhas sem correspondência podem ser ignoradas somente com justificativa e usuário responsável;
- painel de tesouraria mostra contas, posições, movimentos, extratos e acesso à conciliação;
- formas de pagamento exibem a conta de liquidação configurada;
- DRE e totais operacionais desconsideram lançamentos de natureza transferência.

Evidências automatizadas:

- suíte específica da Fase 2: 10 testes aprovados, incluindo pagamentos bancários de fornecedores, agrupamento, divergência, desfazimento e isolamento;
- regressão conjunta das Fases 0/1/2, descontos, permissões e multiempresa: 21 testes aprovados;
- `manage.py check`: sem problemas identificados;
- `makemigrations --check --dry-run`: nenhuma migração pendente;
- `git diff --check`: sem erros de whitespace (somente avisos de normalização LF/CRLF do Git no Windows).

- cadastrar contas bancárias por empresa;
- associar meios de pagamento às contas de liquidação;
- implementar transferências caixa-banco e banco-banco;
- criar conciliação manual e por importação de extrato;
- controlar taxas de adquirentes e recebíveis de cartão;
- gerar posição financeira por caixa e conta.

Critérios de aceite:

- não há transferência registrada como receita/despesa;
- o mesmo item de extrato não é conciliado duas vezes;
- toda diferença pode ser explicada e auditada;
- saldo por conta é reproduzível a partir dos movimentos.

### Fase 2A — XML de compras e recebimento assistido

Prioridade: P1.

Status: **concluída tecnicamente em 05/08/2026**.

Entregas realizadas:

- cadastro de fornecedor comercial compatível com o cadastro anterior, CNPJ normalizado, validado e único por empresa;
- importação idempotente de XML autorizado de NF-e modelo 55, com validação da chave, protocolo, CNPJ destinatário, tamanho e conteúdo seguro;
- armazenamento do XML original, resumo normalizado, chave de acesso e divergências cadastrais;
- criação de entrada em rascunho sem movimentação imediata de estoque ou financeiro;
- confirmação obrigatória de fornecedor novo ou divergente antes do recebimento;
- correspondência de itens por GTIN e código do fornecedor, sempre limitada à empresa ativa;
- cadastro assistido de produto novo e reaproveitamento do vínculo produto-fornecedor;
- conferência explícita de tributos incorporados ao custo e tributos recuperáveis;
- rateio proporcional e auditável de frete, seguro e despesas, mantendo descontos por item;
- prévia de custo anterior, custo da entrada e custo médio projetado;
- recebimento atômico com saldo, camada de custo, custo médio, histórico do produto e custo de referência do fornecedor;
- conta a pagar opcional criada somente no recebimento e pelo valor financeiro total da NF-e;
- recálculo de preço sugerido e mínimo sem alteração silenciosa do preço final vigente;
- isolamento de chave, fornecedor, GTIN, produtos e entradas por empresa.
- validação adicional do CNPJ emitente, modelo, série e número contra a chave de acesso e da chave registrada no protocolo;

Evidências automatizadas:

- suíte específica de XML: 9 testes aprovados;
- regressão conjunta de entrada manual, XML, tesouraria e conciliação: 23 testes aprovados;
- `manage.py check`: sem problemas identificados;
- `makemigrations --check --dry-run`: nenhuma migração pendente.

- generalizar o cadastro de fornecedor comercial preservando compatibilidade com os fornecedores existentes;
- adicionar chave de acesso e arquivo XML à entrada de mercadoria, com unicidade por empresa;
- criar serviço seguro de leitura e normalização de XML de NF-e recebida;
- implementar identificação e criação assistida do fornecedor;
- implementar correspondência de produtos e cadastro de item novo durante a conferência;
- importar e ratear valores da nota, distinguindo tributos recuperáveis e custo incorporado;
- mostrar prévia da alteração de custo e da precificação;
- gerar entrada em rascunho e reutilizar o recebimento transacional existente;
- criar vínculo opcional com contas a pagar;
- registrar auditoria e histórico de custo por documento e fornecedor;
- corrigir a migração `configuracoes/migrations/0086_realinhar_sequencias_configuracoes.py` para que os testes possam executar em SQLite e PostgreSQL.

Critérios de aceite:

- XML válido da empresa ativa cria somente um rascunho, sem movimentar estoque;
- nova tentativa com a mesma chave de acesso não duplica fornecedor, entrada, estoque ou conta a pagar;
- fornecedor existente é encontrado pelo CNPJ e diferenças cadastrais exigem confirmação;
- item conhecido é relacionado corretamente por GTIN ou código no fornecedor;
- item desconhecido pode ser cadastrado dentro da conferência e permanece vinculado ao item da nota;
- todos os valores importados podem ser comparados com os totais do XML;
- usuário visualiza custo anterior, custo da entrada e custo médio projetado;
- confirmação atualiza saldo, camadas de custo, custo médio e histórico exatamente uma vez;
- preço sugerido/mínimo é recalculado, mas preço final vigente não muda silenciosamente;
- cancelamento do rascunho não altera estoque nem financeiro;
- testes do fluxo passam nos bancos suportados pelo projeto.

### Fase 2B — Cadastro em massa assistido por documentos fiscais

Prioridade: P1.

Status: **concluída tecnicamente em 06/08/2026; parâmetros fiscais continuam sujeitos à homologação externa**.

Entregas já realizadas nesta fase:

- importação de um XML ou lote ZIP com até 50 XMLs, validado integralmente e deduplicado por empresa, chave e hash;
- lote persistente por arquivo, com usuário, origem, hash, documentos, contadores, pendências, situação e reabertura pela carteira de entradas;
- grade de revisão coletiva dos itens pendentes de uma NF-e;
- confirmação em massa de correspondências exatas sem alterar custo, preço ou classificação do produto existente;
- classificação da correspondência como exata, provável, nova ou conflitante, com candidatos e pontuação explicáveis;
- bloqueio de confirmação coletiva para sugestões prováveis e conflitos até escolha humana individual;
- criação coletiva de produtos desconhecidos com categoria, marca, natureza, margem e preço final individual;
- preço final zero interpretado como aceite do preço sugerido pelo motor de custos e tributos;
- rateio do custo pela nota completa mesmo quando a revisão é feita em partes;
- operação transacional, repetível sem duplicação e com confirmação explícita do usuário;
- histórico do produto e evento operacional com documento, item, usuário, custo e preço;
- importação CSV/XLSX enriquecida com custos, margens, NCM, CEST, CFOP, CST/CSOSN, origem e unidade comercial;
- diagnóstico de prontidão por empresa para perfil/regra fiscal, RBT12, classificação, taxas, custos fixos e contas bancárias.
- central única do lote atravessando várias NF-e, com retomada, busca, filtros de situação/classificação/preço e exportação CSV;
- comparação `atual x importado/proposto` e atualização campo a campo somente mediante seleção explícita;
- resolução humana de sugestões prováveis e conflitos dentro da própria central do lote;
- mapeamentos CSV/XLSX nomeados, salvos e reaplicáveis por fornecedor, com valores padrão;
- relatório consolidado de total, pendentes, resolvidos, novos, prováveis e conflitos;
- adaptadores conservadores para CT-e autorizado, NFS-e/RPS estruturada e SPED/EFD, armazenados como conferência auditável sem movimentação automática;
- validações de lote multi-NF-e, atualização seletiva, idempotência e carga com 200 itens.

Complementos técnicos concluídos nesta fase:

- decisões confirmadas permanecem no item e o lote pode ser reaberto sem perder o trabalho anterior;
- produtos existentes preservam todos os campos por padrão e guardam histórico dos campos efetivamente alterados;
- mapeamentos de fornecedor podem ser criados, sobrescritos pelo mesmo nome e reutilizados;
- locks transacionais, hashes e restrições únicas protegem contra duplicidade e reprocessamento concorrente;
- documentos complementares ficam separados da NF-e de compra e não geram saldo, custo ou financeiro silenciosamente.

Evidências do marco implementado em 06/08/2026:

- 74 testes integrados de fiscal, XML/ZIP, lote, cadastro, custos, precificação e documentos complementares: aprovados;
- `manage.py check`: sem problemas identificados;
- `makemigrations --check --dry-run`: nenhuma alteração pendente;
- migrações `estoque.0052` a `estoque.0055` aplicadas no banco local;
- cópias de segurança anteriores aos dois marcos: `db.pre_lote_importacao_20260806.sqlite3` e `db.pre_pendencias_tecnicas_20260806.sqlite3`.

Objetivo:

- transformar documentos de compra e arquivos de catálogo numa central de preparação de produtos em lote;
- identificar automaticamente produtos já cadastrados com critérios seguros;
- preparar produtos novos como rascunhos revisáveis;
- permitir que o usuário concentre o trabalho em preço final, exceções e informações realmente ausentes;
- impedir que uma importação altere silenciosamente cadastro, estoque, preço praticado ou financeiro.

#### Fontes e níveis de confiança

- NF-e de compra modelo 55 em XML autorizado permanece como fonte fiscal principal para fornecedor, itens, quantidades, custos, classificação e parcelas;
- lotes ZIP com vários XML de NF-e devem ser aceitos com deduplicação por empresa, chave de acesso e hash;
- CSV e XLSX devem ser aceitos para catálogo de fornecedor, lista de produtos e atualização comercial, com mapeamento de colunas salvo por fornecedor;
- CT-e poderá complementar o frete de aquisição e seu rateio, mediante vínculo confirmado com as notas relacionadas;
- NFS-e e documentos de serviço não devem criar saldo físico de estoque; poderão gerar serviço, custo ou conta a pagar conforme fluxo próprio;
- SPED/EFD e outros arquivos fiscais estruturados devem ser tratados prioritariamente como fontes de conferência e reconciliação, não como autorização automática para criar ou movimentar produtos;
- PDF, imagem ou DANFE sem o XML poderão ser usados futuramente apenas como leitura assistida/OCR, sempre sujeitos a revisão, e nunca como substitutos silenciosos do documento fiscal estruturado.

#### Correspondência dos produtos

O motor de identificação deve classificar cada resultado como `exato`, `provável`, `novo` ou `conflitante`:

1. correspondência exata por GTIN/EAN válido dentro da empresa;
2. correspondência exata por código do produto no mesmo fornecedor;
3. correspondência por SKU interno previamente mapeado;
4. sugestão provável por código de fabricante, NCM, marca, unidade e descrição normalizada;
5. produto novo quando não existir candidato aceitável;
6. conflito quando mais de um cadastro puder representar o mesmo item ou quando GTIN, fornecedor e classificação discordarem.

Sugestões prováveis nunca devem ser confirmadas automaticamente. Toda decisão confirmada alimentará o relacionamento produto-fornecedor para melhorar as próximas importações.

#### Grade de revisão em massa

A conferência deve oferecer uma única grade com:

- situação e confiança da correspondência;
- fornecedor, código do fornecedor, GTIN, descrição, NCM, CEST, CFOP e unidade;
- produto existente ou indicação de novo cadastro;
- quantidade, custo anterior, custo da entrada e custo médio projetado;
- regra tributária sugerida, anexo/tratamento e alertas de classificação;
- margem padrão da categoria, custos variáveis, rateio, preço mínimo, preço sugerido e preço final;
- ações em lote para categoria, marca, natureza do item, localização, margem, regra tributária e política de arredondamento;
- filtros de "somente pendentes", "novos", "conflitantes", "sem classificação" e "preço abaixo do mínimo".

O sistema poderá preencher automaticamente preço sugerido e mínimo. O preço final poderá ser aceito em lote, informado individualmente ou preservado para produtos existentes. Alterações em produtos existentes deverão apresentar comparação `atual x importado x proposto` por campo.

#### Rascunho, validação e confirmação

- cada arquivo ou conjunto de arquivos deve gerar um lote de importação com estado, progresso, usuário, empresa, origem e hash;
- novos produtos devem permanecer em rascunho e indisponíveis para venda até cumprir os campos mínimos e serem confirmados;
- o lote deve permitir salvar e continuar depois, sem perder decisões já tomadas;
- falha em um item não pode apagar as revisões dos demais nem movimentar parcialmente o estoque;
- a confirmação final deve ser transacional e idempotente, criando ou atualizando produtos, vínculos com fornecedor, entrada de mercadoria, camadas de custo e conta a pagar exatamente uma vez;
- nome, marca, NCM, regra tributária e preço final de produto existente não podem ser sobrescritos sem seleção explícita do usuário;
- toda informação importada deve guardar proveniência: arquivo, chave/documento, fornecedor, item, data e usuário que confirmou;
- o resultado deve produzir um relatório de criados, relacionados, atualizados, ignorados, conflitantes e rejeitados.

Critérios de aceite:

- uma NF-e com vários produtos novos pode ser revisada e confirmada numa única operação;
- itens já conhecidos são associados sem exigir recadastro e sem duplicação;
- o usuário consegue aplicar categoria, margem e política de preço a vários itens simultaneamente;
- produtos existentes preservam o preço final por padrão e mostram qualquer mudança proposta;
- nenhum item com conflito, classificação obrigatória ausente ou regra fiscal inválida é ativado silenciosamente;
- importar novamente o mesmo documento ou lote não duplica produtos, vínculos, custos, estoque ou contas a pagar;
- o lote pode ser interrompido e retomado com todas as decisões preservadas;
- XML, CSV/XLSX e futuros adaptadores passam pelo mesmo processo de normalização, revisão, auditoria e confirmação;
- testes cobrem alto volume, concorrência, duplicidade, isolamento entre empresas e falha parcial.

### Fase 3 — Motor tributário e precificação

Prioridade: P1.

Status: **concluída tecnicamente em 05/08/2026; parametrização fiscal aguarda homologação do contador**.

Entregas realizadas:

- perfis tributários isolados por empresa, regime, vigência e situação de homologação;
- regras por tipo de item, finalidade, tratamento especial, NCM/CEST, código de serviço, UF e prioridade;
- distinção efetiva entre mercadoria de revenda, serviço e produto fabricado/industrializado;
- finalidades próprias para oferta, cessão, uso/consumo, perda, avaria, vencimento e devolução, sem reaproveitar regra vinculada incompatível com a operação;
- faixas configuráveis do Simples com RBT12, alíquota nominal, parcela a deduzir e cálculo da alíquota efetiva;
- seleção de Anexo III/V por Fator R quando a regra exigir;
- estimativas configuráveis para Lucro Presumido e Lucro Real, sem apresentação como apuração oficial;
- classificação fiscal e vínculo opcional de regra no produto;
- seleção automática de regra por operação e classificação, com fallback legado claramente não homologado;
- memória de cálculo com perfil, regra, faixa, fórmula, vigência, anexo, tratamento e fonte normativa;
- integração da alíquota ao preço sugerido/mínimo e aos encargos gerenciais congelados no pagamento;
- preservação do preço final e dos snapshots históricos após mudanças de regra.

Evidências automatizadas:

- suíte fiscal completa: 22 testes aprovados, cobrindo também industrialização, operações não comerciais e tratamentos normal, monofásico, ST e isento;
- regressão conjunta fiscal, cadastro/precificação de produto e caixa multiempresa: 45 testes aprovados;
- `manage.py check` e verificação de migrações: aprovados.

- substituir o anexo único por perfis e regras tributárias com vigência;
- separar produto, serviço, industrialização e tratamentos especiais;
- implementar cálculo do Simples com RBT12, faixa, parcela a deduzir, alíquota efetiva e segregação de receita;
- suportar Fator R onde aplicável;
- modelar estimativas para Lucro Presumido e Lucro Real sem prometer apuração contábil completa;
- incluir NCM, CEST, origem, CFOP, CST/CSOSN e códigos de serviço necessários;
- versionar regras e registrar explicação do cálculo;
- integrar o resultado ao assistente de preço do estoque.

Critérios de aceite:

- produto e serviço da mesma empresa podem usar regras diferentes;
- a memória do cálculo mostra dados de entrada, regra, vigência e resultado;
- regra não homologada produz alerta e não é silenciosamente assumida;
- alterações de configuração não mudam vendas históricas;
- preço sugerido evidencia custo, imposto estimado, despesas e margem.

### Fase 4 — Reforma tributária e convivência de regimes

Prioridade: P1, com cronograma de vigência.

Status: **estrutura técnica concluída em 05/08/2026; alíquotas e cronograma operacional aguardam atualização normativa e homologação**.

Entregas realizadas:

- tributos parametrizados por regra e vigência, aceitando códigos atuais, CBS, IBS, Imposto Seletivo e futuros;
- configuração de alíquota, percentual de base, crédito, natureza, destino e fonte normativa;
- modos de convivência para adicionar, substituir ou apenas informar um tributo;
- seleção automática por data sem reescrever períodos anteriores;
- memória de débito, crédito e valor líquido de cada componente;
- simulador comparativo de alíquota, preço sugerido, lucro e margem entre datas;
- tela gerencial para cadastrar perfis, regras, faixas, tributos e comparar cenários.

Não foram carregadas alíquotas legais fixas no código. Os parâmetros de produção devem ser cadastrados por vigência com fonte normativa e confirmação do contador.

- criar tributos parametrizados por período, evitando fórmulas rígidas no código;
- preparar CBS, IBS e Imposto Seletivo;
- suportar convivência e transição com tributos atuais conforme calendário legal;
- manter classificação, base, crédito, débito, destino e memória de cálculo;
- implementar simulador de impacto no preço e na margem;
- criar rotina de atualização e homologação das tabelas tributárias.

Critérios de aceite:

- regras futuras podem ser cadastradas sem alterar períodos anteriores;
- o cálculo seleciona a regra pela data e natureza da operação;
- relatórios distinguem estimativa gerencial de valor fiscal efetivo;
- cenários de transição são testados com casos homologados pelo contador.

### Fase 5 — Integração fiscal real

Prioridade: P1/P2, antes de emissão em produção.

Status: **dependência externa real — provedor/autorizador ainda não contratado ou definido**.

Contenção já concluída:

- nenhuma chave, protocolo ou autorização é gerada localmente;
- fila sem integração real é bloqueada e registrada como rejeitada, com mensagem explícita;
- status autorizado permanece reservado a retorno verificável de uma integração futura;
- configuração, documentos, numeração e arquivos fiscais permanecem isolados por empresa;
- senha de certificado não é persistida pelo fluxo desabilitado.

Não é tecnicamente responsável implementar transmissão real sem definir documentos necessários, provedor, credenciais, certificado, ambientes e contrato de API. Esses itens permanecem como dependência externa, não como funcionalidade simulada.

- integrar provedor ou serviço fiscal real para os documentos necessários;
- validar certificado, ambiente, numeração e série por empresa;
- armazenar XML, protocolo, eventos, cancelamentos e rejeições;
- implementar idempotência, contingência e consulta de status;
- remover qualquer autorização simulada do fluxo produtivo;
- controlar acesso a segredos e registrar auditoria.

Critérios de aceite:

- status “autorizado” somente existe após retorno verificável do autorizador/provedor;
- reenvio não duplica documento;
- XML e protocolo são recuperáveis;
- falhas e rejeições ficam visíveis ao usuário e não viram sucesso aparente.

### Fase 6 — Migração, homologação e implantação

Prioridade: P1.

Status: **preparação técnica concluída em 05/08/2026; homologação humana e implantação permanecem externas**.

Entregas realizadas:

- migração das configurações tributárias antigas para perfil e regras versionadas em rascunho, sem falsa homologação;
- fila por empresa de produtos e serviços sem NCM ou código de serviço;
- testes automatizados de regimes, segregação, vigência, Fator R, reforma, preço, pagamentos e isolamento;
- manual operacional de estoque, XML, custos, preço, tributação, caixa e conciliação;
- manutenção dos checklists existentes de homologação, backup, restauração e implantação local.

Dependências para implantação:

- contador preencher e homologar CNAEs, anexos, faixas, tratamentos e parâmetros por vigência;
- responsável da empresa aprovar cenários de preço/margem e permissões;
- executar checklist no banco/ambiente de produção, com backup e teste de restauração;
- contratar/configurar provedor antes de qualquer emissão fiscal real.

- migrar configurações existentes para perfis versionados;
- classificar produtos e serviços em lote, com fila de pendências;
- criar massa de testes aprovada pelo contador;
- executar testes unitários, integração, permissões, regressão e desempenho;
- homologar por empresa em ambiente separado;
- documentar operação, fechamento, conciliação e correção de erros;
- implantar por etapas com backup e plano de reversão.

Critérios de aceite:

- não existem registros órfãos ou compartilhados entre empresas;
- saldos anteriores e posteriores à migração são conciliados;
- usuários recebem apenas as permissões necessárias;
- contador e responsável da empresa aprovam os casos fiscais críticos;
- equipe conclui checklist operacional antes do uso real.

## 6. Matriz mínima de testes

### Fiscal

- venda somente de mercadoria;
- venda somente de serviço;
- atendimento misto;
- Simples com faixas e vigências diferentes;
- serviço sujeito e não sujeito ao Fator R;
- item monofásico, ST, isento e tributado normalmente;
- devolução, cancelamento, oferta, cessão e perda;
- alteração de regra após venda concluída;
- duas empresas com regimes e certificados diferentes.

### Caixa e bancos

- pagamento integral e misto;
- pagamento zero em OS gratuita;
- recebimento parcial, desconto e acréscimo;
- fechamento com e sem divergência;
- transferência entre caixa e banco;
- despesa e entrada retroativas;
- conciliação simples, agrupada e com tarifa;
- tentativa de conciliar o mesmo extrato duas vezes.

### Estoque e preço

- marca cadastrada e marca manual “Outros”;
- entrada com frete, desconto e imposto não recuperável;
- preço abaixo do custo e margem negativa;
- oferta e cessão sem receita fictícia;
- perda e ajuste com autorização;
- transferência entre locais e entre empresas;
- mudança de custo sem alterar a memória histórica da venda.

### XML de compras

- XML válido com fornecedor e todos os produtos já cadastrados;
- XML válido com fornecedor novo;
- XML com produto novo e cadastro durante a conferência;
- correspondência por GTIN e por código do fornecedor;
- descrição semelhante que não deve provocar associação automática;
- XML destinado a outro CNPJ;
- chave de acesso já importada;
- arquivo inválido, evento ou XML cancelado;
- nota com desconto, frete, seguro, despesas e tributos;
- imposto recuperável que não deve compor custo;
- divergência entre soma dos itens e total do documento;
- produto controlado por lote e número de série;
- recebimento repetido da mesma entrada;
- geração, cancelamento e conciliação da conta a pagar vinculada;
- duas empresas importando documentos e fornecedores completamente isolados.

### Cadastro em massa por documentos e catálogos

- NF-e com dezenas ou centenas de itens novos e existentes;
- lote ZIP com documentos repetidos, válidos e inválidos;
- CSV/XLSX com mapeamento de colunas salvo por fornecedor;
- correspondência exata, provável, nova e conflitante;
- aplicação em lote de categoria, natureza, margem e política de preço;
- preservação do preço final e dos campos protegidos de produtos existentes;
- interrupção e retomada do lote sem perda das decisões;
- confirmação atômica sem produto ou estoque parcialmente processado;
- importação concorrente do mesmo documento;
- relatório final e proveniência de cada campo importado.

## 7. Pendências para validação do contador

Antes da homologação fiscal, obter resposta documentada para:

- quais CNAEs e atividades são efetivamente exercidos;
- qual anexo/segregação se aplica à revenda de mercadorias;
- por que foi indicado o Anexo II e em quais operações ele seria usado;
- qual anexo se aplica a cada tipo de serviço;
- se há incidência e cálculo de Fator R;
- RBT12, faixas e alíquotas efetivas usadas nos cenários de teste;
- quais produtos são monofásicos, sujeitos a ST, isentos ou beneficiados;
- regras de ICMS, DIFAL, antecipação, IPI, ISS e retenções aplicáveis;
- tratamento fiscal e documental de ofertas, brindes, cessões e uso interno;
- cronograma e parâmetros de CBS/IBS a adotar durante a transição;
- documentos fiscais que o sistema deverá emitir e provedor a integrar.

Essas respostas devem gerar configurações versionadas e casos de teste, não condições fixas espalhadas pelo código.

## 8. Ordem recomendada

1. Fase 0: riscos e erros críticos.
2. Fase 1: base financeira auditável e datas.
3. Fase 2: bancos e conciliação.
4. Fase 2A: importação de XML e recebimento assistido.
5. Fase 2B: cadastro em massa assistido por documentos fiscais e catálogos.
6. Fase 3: motor tributário e precificação.
7. Fase 4: reforma tributária.
8. Fase 5: emissão fiscal real.
9. Fase 6: migração e homologação.

As correções da Fase 0 podem ser entregues separadamente. As demais fases devem preservar compatibilidade de dados e isolamento por empresa desde a primeira migração.

## 9. Definição de concluído

### Auditoria técnica final — 05/08/2026

No escopo encerrado em 05/08/2026, todas as entregas então previstas e tecnicamente executáveis sem definição fiscal externa foram implementadas. A Fase 2B, acrescentada em 06/08/2026, entrou em execução com o núcleo de importação e revisão em massa já operacional. A revisão final daquele escopo acrescentou:

- conciliação bancária 1:1, 1:N e N:1, com prevenção de reuso, divergência justificada, desfazimento e histórico preservado;
- saída bancária conciliável ao pagar conta a pagar por forma vinculada a banco, sem afetar dinheiro físico e sem exigir caixa aberto;
- proteção multiempresa adicional nos detalhes e relatórios de contas a pagar/receber, aging, garantias e auditoria operacional;
- produto fabricado/industrializado separado da mercadoria de revenda no cadastro, na regra e no motor;
- finalidades tributárias próprias para perda, avaria e vencimento, sem aplicação indevida da regra de revenda vinculada ao produto;
- movimentações próprias de perda, vencimento e uso interno, todas baixadas pelo custo e com motivo obrigatório;
- migração das conciliações simples preexistentes para o novo histórico agrupado.

Evidência consolidada desta auditoria:

- 180 testes da regressão ampla do caixa e permissões: aprovados;
- 45 testes conjuntos de fiscal, XML, estoque e tesouraria em banco de teste criado do zero: aprovados;
- `manage.py check`: aprovado;
- `makemigrations --check --dry-run`: nenhuma alteração pendente;
- `git diff --check`: sem erro de whitespace; apenas avisos LF/CRLF do Git no Windows.
- banco SQLite local copiado para `db.pre_melhorias_20260805.sqlite3` e todas as migrações aplicadas com sucesso; nenhuma migração local permaneceu pendente.

Permanecem somente dependências externas ou humanas: homologação dos parâmetros pelo contador, definição/contratação do provedor fiscal real, credenciais/certificado, massa fiscal homologada e execução do checklist de implantação/backup/restauração no ambiente de produção.

### Complementares concluídos em 06/08/2026

- duplicatas da NF-e importadas como parcelas revisáveis e convertidas em contas a pagar individuais no recebimento;
- conciliação assistida por pontuação de valor, data e descrição/documento, com lançamento controlado de tarifa, juros, rendimento ou ajuste;
- fluxo de estoque entre empresas/CNPJs com documento fiscal obrigatório, acesso restrito a empresas vinculadas ao usuário, produtos e pontos isolados e movimentos distintos de saída/entrada;
- regra tributária homologada imutável, com criação de nova versão, encerramento automático da vigência anterior e cópia de faixas/tributos;
- registro de capital social, AFAC, empréstimo de sócio e outras injeções, em banco ou caixa, com data retroativa autorizada e natureza não operacional;
- migrações `caixa.0049` e `estoque.0051` aplicadas após backup `db.pre_complementares_20260806.sqlite3`;
- 49 testes focados aprovados; regressão ampla de 431 testes executada, com uma incompatibilidade no fallback de vendedores identificada, corrigida e revalidada no teste específico.

O plano somente estará concluído quando:

- todas as fases aplicáveis tiverem implementação, testes e evidências;
- não houver autorização fiscal simulada em produção;
- cálculos gerenciais e valores fiscais estiverem claramente separados;
- caixa, bancos e estoque puderem ser conciliados por origem;
- XML, fornecedor, produtos, custos, entrada e conta a pagar estiverem rastreáveis entre si;
- regras fiscais estiverem versionadas por empresa, operação e vigência;
- cenários tributários críticos tiverem homologação do contador;
- usuários possuírem manual operacional e permissões testadas;
- backup, restauração, auditoria e reversão tiverem sido validados.

## 10. Referências oficiais para acompanhamento

- Manual do PGDAS-D e DEFIS, Portal do Simples Nacional.
- Resolução CGSN nº 140/2018 e alterações posteriores.
- Lei Complementar nº 123/2006 e alterações posteriores.
- Emenda Constitucional nº 132/2023.
- Lei Complementar nº 214/2025 e regulamentações posteriores.
- Documentação técnica vigente de NF-e, NFC-e, NFS-e, CBS e IBS.

As fontes devem ser revisitadas em cada implantação, pois regras e cronogramas podem mudar.
