# Manual operacional — Estoque, tributação e caixa

## 1. Antes de começar

Confirme a empresa ativa no sistema. Produtos, fornecedores, regras tributárias, caixas, bancos e movimentos ficam separados por empresa. Nunca use uma empresa apenas como “filial” de outro CNPJ sem orientação fiscal: transferências entre CNPJs podem exigir documento próprio.

## 2. Cadastro de produto

No menu **Estoque > Novo produto**:

1. Informe nome, tipo do item, SKU/EAN e categoria. Use **Produto fabricado / industrializado** quando a própria empresa produzir o item; essa opção permite regra e anexo distintos da simples revenda.
2. Selecione marca/fabricante. Quando não existir, use **Outra marca / fabricante**; o sistema cria e reaproveita a marca sem duplicar.
3. Selecione fornecedor, ponto operacional e localização física.
4. Preencha NCM e CEST para mercadorias, ou código do serviço para serviços, conforme informação validada.
5. Escolha uma regra tributária específica somente quando o item tiver tratamento próprio. Em branco, o motor procura a regra vigente pela operação e classificação.
6. Cadastre lote/série quando o produto exigir rastreabilidade.

O saldo inicial deve ser usado apenas na implantação. Depois disso, toda quantidade deve entrar por recebimento, transferência, devolução ou ajuste auditável.

## 3. Custos

Os campos têm funções diferentes:

- **Último custo de compra:** custo unitário completo da entrada mais recente; serve de referência para a próxima formação de preço.
- **Frete de compra:** parcela unitária do frete incorporada ao custo.
- **Impostos no custo:** somente tributos não recuperáveis que efetivamente aumentam o custo.
- **Custos operacionais:** comissão, marketplace, CAC e demais despesas usadas na formação gerencial do preço.
- **Custo médio:** média ponderada do saldo anterior com as entradas confirmadas; permanece separado e é usado nas baixas pelo método PMP.

Na importação de XML, desconto permanece ligado ao item; frete, seguro e outras despesas são rateados proporcionalmente. Tributos recuperáveis ficam separados e não entram automaticamente no custo.

## 4. Impostos e regime tributário

O regime pertence à empresa, mas a regra pertence à operação. Uma mesma empresa pode usar uma regra de comércio para revenda e regras distintas para serviços.

Em **Fiscal > Motor tributário**:

1. Crie um perfil com regime e vigência.
2. Informe RBT12 e folha dos 12 meses quando necessários ao Simples/Fator R.
3. Crie regras para revenda, prestação de serviço e tratamentos especiais.
4. Cadastre as faixas do Simples com anexo, limites, alíquota nominal e parcela a deduzir.
5. Para CBS, IBS, Imposto Seletivo ou convivência com tributos atuais, cadastre componentes por vigência, base, crédito e impacto.
6. Mantenha como **Rascunho** até o contador confirmar CNAE, anexo, faixa e tratamentos; depois marque como **Homologado**.

No início da tela, use o painel **Prontidão da precificação automática**. Ele aponta perfil sem homologação, RBT12 ausente, naturezas sem regra, produtos sem NCM/código de serviço, taxas de recebimento zeradas, custos fixos ausentes e falta de conta bancária. Um alerta não impede simulações, mas identifica onde o resultado ainda depende de fallback ou confirmação.

A fórmula do Simples usa RBT12, alíquota nominal e parcela a deduzir da faixa cadastrada. Regra sem faixa pode usar uma alíquota estimada configurada, sempre com alerta quando não homologada. O cálculo é gerencial e não substitui PGDAS-D ou escrituração.

## 5. Formação do preço

O sistema calcula:

1. custo de compra e adicionais;
2. custos variáveis e taxa de recebimento;
3. alíquota tributária estimada da regra vigente;
4. margem desejada;
5. preço sugerido e preço mínimo.

O **preço final** é a decisão comercial. Quando o custo ou a regra muda, o sistema recalcula sugerido/mínimo, mas preserva o preço final já praticado. Revise alertas de preço abaixo do mínimo ou margem negativa antes de salvar.

Cada cálculo guarda uma memória com perfil, regra, anexo, faixa, fórmula e vigência. Pagamentos concluídos mantêm o snapshot original mesmo que a regra seja alterada depois.

## 6. Importação de XML de compra

Quando a empresa possui certificado A1, também é possível abrir **Fiscal > Caixa fiscal NF-e**, sincronizar os documentos destinados ao CNPJ e preparar a importação sem procurar manualmente o arquivo XML. A consulta usa NSU; depois de sincronizar, pesquise pelo número da NF-e. Somente documentos com XML completo podem ser enviados ao Estoque, sempre como rascunho para conferência. Consulte o manual `manual_caixa_fiscal_dfe.md`.

Em **Estoque > Entradas > Importar XML**:

1. Selecione o XML autorizado da NF-e ou um ZIP com até 50 XMLs, além do ponto e da localização de destino.
2. Se desejar conta a pagar, marque a opção. As duplicatas do XML geram parcelas separadas; o vencimento manual é usado apenas quando o XML não informa cobrança parcelada.
3. O sistema valida chave, protocolo, modelo 55 e CNPJ destinatário; duplicatas não são importadas novamente.
4. Confirme o fornecedor novo ou divergente.
5. Para poucos itens, associe um produto existente ou cadastre um novo individualmente. Em notas maiores, use **Revisão coletiva e criação de produtos**: selecione as linhas, aplique categoria, marca, natureza e margem; informe apenas preços/exceções necessários.
6. Revise tributos que compõem custo e tributos recuperáveis.
7. Compare totais e confira custo anterior, custo da entrada e custo médio projetado.
8. Clique **Receber no estoque** somente após a conferência.

Antes do recebimento, vencimentos e valores das parcelas podem ser revisados no detalhe da entrada. A soma precisa coincidir exatamente com o total financeiro da nota. Ao receber, cada parcela gera sua própria conta a pagar vinculada ao XML.

O upload cria apenas um rascunho. Saldo, custo, histórico e conta a pagar são gerados juntos somente no recebimento. Cancelar o rascunho não movimenta estoque nem financeiro.

Na revisão coletiva, produtos já encontrados são apenas confirmados: o cadastro, custo e preço final atuais são preservados. Produtos desconhecidos recebem dados estruturados da NF-e, custo completo rateado e preço sugerido automático. Preço final `0` aceita a sugestão; qualquer valor informado passa a ser a decisão comercial. A confirmação é atômica e repetir a operação não duplica produtos.

Produtos desconhecidos agora ficam em **pré-cadastro** antes da criação. O sistema sugere categoria e marca com confiança e justificativa baseadas em descrição, NCM e histórico local. Use **Salvar pré-cadastro** para guardar a revisão sem criar produto, estoque ou financeiro. Somente **Aprovar** promove o rascunho a produto. Se faltar categoria ou marca, selecione **Outros / criar** para cadastrar e selecionar sem sair da NF-e.

O sistema classifica a identificação como **exata**, **provável**, **nova** ou **conflitante**. Apenas exatos e novos entram na ação coletiva. Sugestões prováveis e conflitos mostram os candidatos e devem ser resolvidos individualmente; isso evita ligar a compra ao produto errado ou criar duplicidade silenciosa.

Quando um ZIP tiver várias notas, abra **Estoque > Entradas > Central do lote**. A tela reúne os itens das NF-e, mantém o trabalho confirmado, permite buscar e filtrar pendentes, exatos, prováveis, novos, conflitos, itens sem NCM e preços abaixo do mínimo. O resumo pode ser exportado em CSV.

Para produto já cadastrado, a central mostra **atual x importado/proposto**. Marque somente os campos que realmente devem mudar. Nome, NCM, CEST, CFOP, unidade, margem e preço permanecem inalterados quando suas caixas não forem selecionadas; alterações confirmadas ficam no histórico.

### Cadastro em massa por CSV/XLSX

Em **Estoque > Produtos > Importar**, use CSV ou XLSX quando não houver XML fiscal. Baixe o **modelo CSV completo**, preencha e valide o arquivo antes de importar. Além de nome, SKU/EAN, categoria, marca e fornecedor, o lote aceita custos de compra/frete/impostos/comissão/marketplace/CAC, margens, NCM, CEST, CFOP, CST/CSOSN, origem da mercadoria, unidade, preço e saldo inicial. Preço final zero aciona a sugestão automática.

CSV/XLSX é útil para catálogo e implantação, mas não substitui uma NF-e: não cria conta a pagar nem comprova quantidades compradas. Use saldo inicial apenas na implantação; compras normais devem entrar pela NF-e/entrada de mercadoria para manter custo e rastreabilidade.

Para planilhas recorrentes, abra **Salvar novo mapeamento de colunas**, escolha o fornecedor, informe um nome e relacione `campo_sistema=coluna_arquivo`. Nas próximas importações, selecione o mapeamento salvo; o sistema reaplica cabeçalhos e fornecedor padrão.

### CT-e, NFS-e e SPED/EFD

Em **Estoque > Entradas > CT-e / NFS-e / SPED**, envie somente o XML/TXT estruturado. O CT-e precisa ser modelo 57 autorizado e incluir o CNPJ da empresa entre os participantes; NFS-e/RPS e SPED também precisam corresponder ao CNPJ ativo. Esses documentos são armazenados para conferência e deduplicados por hash. Marcar como conferido não movimenta estoque, não altera custos e não gera financeiro. PDF, imagem ou DANFE não são aceitos como substitutos do arquivo estruturado.

## 7. Oferta, cedência e perdas

Use a movimentação correta em vez de registrar venda fictícia:

- **Oferta/brinde:** saída definitiva pelo custo; informe beneficiário, finalidade/campanha e autorização quando exceder o limite.
- **Cedência:** use cessão definitiva ou temporária. Na temporária, registre a devolução e a condição do item.
- **Uso interno, avaria, perda ou vencimento:** escolha o motivo correspondente e descreva a causa.

Essas saídas baixam estoque pelo custo, não pelo preço final de venda. O documento e o tratamento fiscal aplicável devem seguir a regra homologada pelo contador.

## 8. Caixa, bancos e datas

- Registre a forma real de pagamento; pagamentos mistos são separados por meio no fechamento.
- A contagem física compara apenas dinheiro, não PIX/cartão.
- Cadastre contas bancárias e importe/registre o extrato para conciliação.
- Vincule cada forma bancária à sua conta de liquidação. Ao pagar uma conta a pagar com essa forma, o sistema cria uma saída bancária conciliável e não reduz o dinheiro físico; para pagamento em espécie, o caixa deve estar aberto.
- Na conciliação simples, o sistema destaca correspondência exata de valor e informa a distância entre as datas.
- A tela apresenta sugestões de correspondência considerando valor, data e semelhança do documento/contraparte; a confirmação continua sendo humana.
- Use **Conciliação agrupada** quando um lançamento do banco corresponder a vários movimentos do sistema, ou o inverso. Todos os itens devem ser da mesma empresa e conta.
- Quando a diferença for uma tarifa, juros, rendimento ou ajuste real do banco, marque **Registrar a diferença**. O sistema cria o movimento bancário e financeiro correspondente e conclui a conciliação com rastreabilidade.
- Divergências exigem justificativa. Para corrigir uma associação, use **Desfazer**, informe o motivo e refaça; o histórico anterior permanece auditável.
- Transferência entre caixa e banco não é receita nem despesa.
- Use data de competência, data de movimentação e data de registro conforme o fato; lançamentos retroativos exigem permissão e ficam auditados.
- Correções de movimentos confirmados devem ser feitas por estorno e novo lançamento.
- Ordem gratuita de R$ 0,00 é concluída sem recebimento artificial e sem alerta pendente.

### Capital inicial e injeção de dinheiro

Em **Caixa > Tesouraria**, use **Capital inicial ou injeção de recursos**. Escolha entre capital social/aumento de capital, AFAC, empréstimo de sócio ou outro aporte; informe aportante, documento, valor, competência, data efetiva e um único destino (conta bancária ou caixa).

O aporte aumenta o saldo, mas recebe natureza **Capital e aportes** e não compõe receita operacional/DRE. Datas retroativas exigem a permissão financeira específica. Registros confirmados são imutáveis; uma correção deve ser documentada por movimento inverso.

### Transferência entre empresas/CNPJs

Em **Estoque > Movimentações > Entre empresas/CNPJs**, selecione a empresa e o produto de destino equivalentes. Somente empresas formalmente vinculadas ao mesmo usuário ficam disponíveis. O sistema exige documento fiscal e natureza da operação, gera uma saída na origem e uma entrada autônoma no destino e transfere o custo da baixa para a entrada. Não use essa rotina para pontos do mesmo CNPJ; nesse caso, utilize a transferência interna comum.

### Nova versão tributária

Uma regra homologada não pode mais ser editada diretamente. Em **Fiscal > Motor tributário**, use **Nova versão de regra homologada**: informe a próxima vigência, alíquota, fonte normativa e observação. O sistema encerra a versão anterior no dia precedente, copia faixas/tributos e cria um rascunho que deve ser revisado e homologado.

## 9. Rotina recomendada

Diariamente: conferir entradas, movimentos pendentes, vendas, caixa e extrato. No fechamento: contar dinheiro, comparar todos os meios, justificar diferenças e conciliar contas bancárias. Mensalmente: revisar RBT12, folha/Fator R, vigências tributárias, margens, custos, inventário e pendências com o contador.

Não homologue regra tributária sem evidência. Registre a fonte normativa e mantenha o parecer do contador junto ao período correspondente.
