# Plano de evolução — Caixa, custos de OS e garantias

Data de conclusão técnica: 30/08/2026

## Objetivo

Reduzir o trabalho duplicado entre orçamento, serviços/peças e custos; permitir cobrança mista de cliente e fabricante na mesma OS; e tornar a movimentação da Caixa compatível com taxas reais de cartão, PIX, dinheiro, troco e liquidação bancária.

## Etapas concluídas

### 1. Pagamentos e taxas de maquininha

- Taxas configuráveis por maquininha, modalidade, bandeira, faixa de parcelas e vigência.
- Taxa percentual, tarifa fixa, prazo D+ e conta bancária de liquidação.
- Registro contábil do valor bruto da venda, despesa da taxa e entrada líquida no banco.
- Composição de pagamento simples ou mista com bandeira e parcelas preservadas no histórico.
- Dinheiro registra valor entregue pelo cliente e troco devolvido.
- A tela mostra antes da confirmação: bruto bancário, taxa estimada, líquido e prazo de crédito.
- Falhas inesperadas retornam mensagem operacional e ficam registradas no log, evitando página 500 sem orientação.

### 2. Custos de OS e integração com orçamento/estoque

- Item aprovado no orçamento é sincronizado automaticamente com Serviços e Peças.
- Seleção de produto do estoque mantém o vínculo real com o cadastro e usa o custo médio/unitário na baixa.
- Peça comprada depois do orçamento pode manter custo previsto e receber custo real quando adquirida.
- Insumos não cobrados do cliente continuam como custo interno da OS.
- Custos reais substituem a previsão do mesmo item sem duplicar margem ou CMV.
- Listas exibem o nome real do item em vez de descrições genéricas.
- Custos internos permanecem fora dos documentos entregues ao cliente.

### 3. Garantia com cobrança mista

- Cada serviço ou peça possui o campo “Quem paga”: cliente, fabricante/garantia ou sem cobrança.
- A mesma OS pode gerar, por exemplo, R$ 100,00 a receber do cliente e R$ 18,00 do fabricante.
- O recebimento do cliente não é mais bloqueado só porque a OS é de garantia.
- A marca pode ter valor padrão de mão de obra do fabricante e repasse padrão ao técnico.
- Regras específicas por tipo de equipamento continuam tendo prioridade sobre o padrão da marca.
- O repasse ao técnico é independente do valor recebido do fabricante.

### 4. Usabilidade da Caixa

- A navegação mantém as ações diárias visíveis e agrupa relatórios/cadastros em uma área expansível.
- A tela de pagamento reúne valor, forma, condição da maquininha, troco e conclusão no bloco principal.
- Desconto, pagamento misto, datas retroativas e observações ficam em blocos opcionais.
- A tela de saída explica a origem financeira e seleciona automaticamente caixa ou banco quando existir somente uma opção.
- Datas contábeis e retroativas foram movidas para opções avançadas.

## Regras operacionais recomendadas

1. Cadastre cada maquininha com sua conta bancária de liquidação.
2. Cadastre as taxas vigentes por modalidade, bandeira e parcelas. Use uma regra sem bandeira como fallback geral.
3. Ao cobrar cartão, confira bandeira, parcelas, taxa prevista e líquido antes de finalizar.
4. Em OS de garantia, classifique cada item conforme o verdadeiro pagador.
5. Use “sem cobrança” para insumos incorporados ao serviço e registre o valor como custo interno.
6. Para peça ainda não comprada, informe o custo final previsto; depois vincule o custo real da aquisição.
7. Em saída, escolha o meio efetivamente usado. Dinheiro reduz caixa físico; PIX/transferência/cartão corporativo reduzem a conta bancária escolhida.

## Atualização de outro computador

Após obter o código atualizado, o processo de atualização deve executar as migrações. As novas migrações são:

- `caixa.0060_taxa_maquininha_bandeira`
- `configuracoes.0097_marca_repasse_tecnico_garantia`
- `orcamentos.0010_item_responsavel_cobranca`
- `ordens.0050_servicopeca_responsavel_cobranca`

Não é necessário levar o banco de desenvolvimento para o computador definitivo. O banco definitivo deve ser preservado e apenas migrado pelo atualizador oficial.

## Validação executada

- Verificação estrutural do Django sem erros.
- Verificação de migrações sem alterações pendentes.
- Testes de taxa por bandeira/parcelas e liquidação de R$ 460,00 bruto para R$ 442,00 líquido.
- Teste de dinheiro com troco.
- Testes de pagamento misto, idempotência e cobrança de cliente em OS de garantia.
- Testes integrados de orçamento, custo previsto, custo real, estoque, compras e fechamento de garantia.

## Evoluções futuras não bloqueantes

- Importação automática de agenda de recebíveis das adquirentes para comparar previsão e depósito real.
- Sugestão de bandeira a partir do arquivo de extrato/recebíveis quando o provedor disponibilizar essa informação.
- Painel executivo configurável por perfil, permitindo ocultar indicadores gerenciais que não sejam usados no balcão.
- Integração fiscal/emissão automática permanece separada e pode ser ativada futuramente sem alterar este fluxo financeiro.
