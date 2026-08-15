# Manual — rateio automático, canais de venda e custos internos

Atualizado em 15/08/2026.

## 1. Objetivo

O preço do produto deixa de depender de um valor fixo de despesas configurado manualmente. O sistema utiliza:

- custo final da compra;
- custos adicionais monetários do produto;
- tributos estimados pela regra fiscal da empresa e natureza do item;
- despesas efetivas classificadas no Caixa;
- custo real dos meios de recebimento;
- margem mínima e margem desejada.

O resultado é apresentado como **preço mínimo** e **preço recomendado**. O usuário continua responsável por escolher o preço final.

## 2. Classificar despesas no Caixa

Acesse **Caixa > Categorias financeiras**. Toda categoria de saída possui dois controles:

1. **Comportamento da despesa**: fixa, variável ou semivariável.
2. **Tratamento no preço**: define se e onde a despesa entra no rateio.

Tratamentos disponíveis:

| Tratamento | Uso recomendado | Efeito no preço |
|---|---|---|
| Estrutura geral | aluguel, energia, sistemas, pessoal, marketing institucional | rateado entre produtos e serviços conforme a participação real de receita |
| Somente produtos | logística ou estrutura exclusiva da revenda | entra somente na precificação dos produtos |
| Somente serviços | estrutura exclusiva da assistência técnica | entra somente nos serviços |
| Canal/maquininha | taxas já capturadas no recebimento | não entra novamente no rateio estrutural |
| Estoque/CMV | compra de mercadoria para revenda | não entra no rateio, pois já compõe o custo do produto |
| Tributo | impostos sobre a venda | não entra novamente, pois é tratado pela regra tributária |
| Investimento | máquinas, móveis e imobilizado | não é despesa estrutural corrente |
| Não ratear | aportes, transferências e casos sem efeito no preço | não altera a sugestão |

Categorias existentes podem ser editadas. Antes de confiar integralmente no cálculo, revise especialmente categorias antigas com nomes genéricos, como “Compras e Insumos” e “Despesas Gerais”.

## 3. Como o rateio é calculado

O motor utiliza os três últimos meses encerrados e considera a data de competência:

`taxa estrutural = despesas alocadas ao escopo ÷ receita do escopo`

Para despesas de estrutura geral, a parcela destinada a produtos segue a participação real das vendas de produtos na receita total. Pagamentos de contas, saídas avulsas e compras em cartão são tratados de forma a evitar duplicar a mesma despesa.

Compras de estoque, tributos, investimentos e taxas de canal não entram novamente no rateio estrutural.

Se não existir receita histórica suficiente, o sistema apresenta alerta. Para bases que já possuíam planejamento mensal legado, ele é mantido temporariamente como transição; sem esse histórico legado, a taxa estrutural fica zero. Não existe cálculo matematicamente confiável sem uma base de vendas, portanto o preço deve ser revisado até formar histórico.

Por segurança, uma taxa estrutural acima de 70% é limitada e sinalizada para revisão. O limite não corrige os dados: ele evita que uma classificação incorreta gere preços absurdos.

## 4. Cadastrar maquininhas e taxas

Acesse **Caixa > Canais e maquininhas**.

Cadastre nesta ordem:

1. adquirente, por exemplo Stone, Rede, Cielo ou Mercado Pago;
2. maquininha/canal, por exemplo “Stone Balcão” ou “Mercado Pago Link”;
3. condições por modalidade, parcelas e vigência.

Cada condição aceita:

- PIX, débito ou crédito;
- faixa de parcelas;
- taxa percentual;
- tarifa fixa por transação;
- prazo de recebimento;
- início e fim da vigência.

O sistema bloqueia condições ativas com parcelas e datas sobrepostas. Para trocar uma taxa, edite a condição anterior, informe o fim da vigência e depois cadastre a nova. O histórico antigo é preservado.

Em **Caixa > Formas de pagamento**, vincule a forma utilizada na venda à maquininha, modalidade e número padrão de parcelas. Formas sem maquininha continuam utilizando a taxa fixa legada cadastrada na própria forma.

## 5. Taxa automática dos canais

Quando existem recebimentos, a taxa de referência é calculada pelo custo efetivo ponderado dos últimos 90 dias:

`taxa média = total de taxas estimadas ÷ total recebido`

Sem histórico, o sistema usa a média das condições ativas cadastradas. Se também não houver condições cadastradas, preserva a taxa manual anterior em vez de zerá-la. No cadastro do produto, marque **Usar taxa média automática dos canais**. O campo percentual fica somente leitura e é atualizado pela simulação.

Na edição de um produto, o sistema também mostra preços mínimo e recomendado para cada maquininha/modalidade. A tarifa fixa é incorporada antes das alíquotas percentuais, evitando subestimar o preço.

## 6. Preencher os custos do produto

Use os campos da seguinte forma:

- **Custo final da última compra**: custo final unitário de aquisição, preferencialmente vindo da entrada/XML com o rateio da nota.
- **Frete de compra**: use somente se ainda não estiver incluído no custo final importado.
- **Custo adicional manual**: valor que não cabe em nenhum campo detalhado.
- **Impostos variáveis da venda (R$)**: somente custo monetário que não esteja incluído na alíquota fiscal automática.
- **Comissão, marketplace e CAC (R$)**: valores por unidade quando forem efetivamente monetários e não percentuais já capturados por outro motor.
- **Custo operacional calculado**: campo somente leitura; soma os valores monetários anteriores.

O adicional manual e os custos detalhados são somados. Não informe a mesma despesa em mais de um campo.

## 7. Formação do preço

No modo simples, a margem é aplicada sobre o custo e o sistema acrescenta tributos, canal e estrutura:

`preço recomendado = custo com margem ÷ (1 - tributos - canal - estrutura)`

No modo avançado, a margem é preservada sobre a receita líquida:

`preço recomendado = custo ÷ (1 - tributos - canal - estrutura - margem desejada)`

O preço mínimo usa a margem mínima no mesmo raciocínio. Se o preço final ficar abaixo do mínimo, o sistema exige confirmação e justificativa. O preço final nunca é trocado silenciosamente: a decisão comercial permanece com o usuário.

## 8. Custos internos de peças da OS

Ao adicionar uma peça avulsa que ainda não existe no estoque, informe a situação do custo:

- custo final previsto;
- fornecida pelo cliente;
- sem custo para a empresa.

O **custo final previsto** é o total que a empresa espera pagar por aquele item da OS. Ele entra na margem gerencial, mas não é mostrado no orçamento, recibo ou documento do cliente.

Quando a compra for realizada, registre um custo interno como **Realizado** e vincule-o ao mesmo item. O custo realizado substitui o previsto na apuração, sem somar os dois. Custos como teclas, componentes, insumos ou material já disponível também podem ser lançados diretamente como custo interno realizado, mesmo quando não são cobrados separadamente do cliente.

## 9. Auditoria de estoque

A quantidade do cadastro do produto é somente leitura. Entradas, saídas, ofertas, cedências, transferências e ajustes devem ocorrer por movimentações de estoque.

Ao trocar a localização padrão, o sistema não copia o saldo anterior para a nova localização. Isso evita duplicidade física. A auditoria dispõe de planejamento e correção por camadas de custo para bases antigas com saldo por localização divergente.

## 10. Checklist de homologação

1. Revise a classificação das categorias financeiras antigas.
2. Cadastre ao menos uma maquininha com débito e crédito.
3. Encerre uma taxa antiga e cadastre uma nova vigência para verificar o histórico.
4. Vincule uma forma de pagamento à maquininha.
5. Cadastre um produto com custo de compra, adicional manual e frete; confirme que todos são somados uma única vez.
6. Compare preço mínimo e recomendado em dinheiro, PIX, débito e crédito parcelado.
7. Confirme que uma compra de mercadoria não aumenta o rateio estrutural.
8. Crie uma peça avulsa em uma OS com custo previsto; confirme que o custo não aparece ao cliente.
9. Registre o custo realizado da mesma peça e confirme que ele substitui o previsto.
10. Troque a localização padrão de um produto com saldo e confirme que nenhuma quantidade nova é criada.

## 11. Limites e responsabilidade fiscal

Os valores tributários do estoque são estimativas gerenciais para formação de preço. NCM, CEST, CFOP, CSOSN/CST, anexos do Simples e regras da reforma tributária devem ser homologados pelo contador. O sistema auxilia e mantém memória de cálculo, mas não substitui validação fiscal nem emissão de documento fiscal.
