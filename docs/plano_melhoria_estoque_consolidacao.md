# Plano de Melhoria - Consolidacao da App Estoque

## Objetivo

Fechar a app `estoque` como modulo operacional de uso real em loja, reduzindo ambiguidade nas telas, simplificando o treinamento da equipe e consolidando as regras que ja existem no dominio.

## Diagnostico Resumido

O modulo ja esta forte em escopo e regra de negocio, mas ainda existe distancia entre:

- o que o sistema e capaz de fazer;
- o que o usuario entende na tela;
- o fluxo realmente pratico no balcao, estoque e recebimento.

O foco desta etapa nao e criar features soltas. O foco e consolidar o que ja existe e transformar a app em operacao clara, previsivel e treinavel.

## Blocos de Consolidacao

### Bloco 1 - Cadastro de produto e estrutura fisica
Status: concluido tecnicamente
Prioridade: alta

Objetivo:
- transformar a ficha de produto em um fluxo guiado e menos denso;
- fechar a linguagem operacional de `ponto operacional + ubicacao`;
- reduzir confusao entre categoria, marca, fornecedor e compatibilidade;
- tornar o modo simples vs avancado realmente compreensivel.

Escopo:
- reorganizar visual e microcopy da ficha de produto;
- reforcar regras operacionais antes do salvamento;
- esclarecer como o sistema trata ubicacao digitada, ponto operacional e estrutura fisica;
- explicar melhor categorias, fornecedores e modelos compativeis;
- revisar mensagens de erro e de confirmacao no cadastro.

Entregas deste ciclo:
- ficha de produto com orientacoes operacionais mais claras;
- botao `Salvar e estruturar` levando direto para a estrutura do item;
- separacao mais clara entre marca/fabricante e fornecedor principal;
- explicacao visual da diferenca entre custos em `R$` e politicas em `%`;
- leitura de saldo disponivel e reservado na listagem de produtos.

Criterio de aceite:
- usuario entende a diferenca entre item fisico e servico sem treinamento tecnico;
- usuario consegue cadastrar um produto comum com seguranca em poucos passos;
- a estrutura fisica fica clara antes de salvar;
- o significado de `simples` e `avancado` fica evidente na tela.

### Bloco 2 - Consolidacao comercial e de precificacao
Status: concluido tecnicamente
Prioridade: alta

Objetivo:
- fechar uma politica operacional de preco para cada cenario da loja.

Escopo:
- separar com clareza custo de compra, custo variavel de venda e preco final;
- definir linguagem padrao para impostos, frete, comissao, CAC e rateio;
- simplificar o entendimento do uso de PMP/PEPS na ponta operacional;
- revisar presets e orientacoes da precificacao.

Entregas desta etapa:
- refino da leitura de margem, lucro e custo total para decisao rapida;
- revisao dos presets de precificacao por contexto operacional;
- reforco da ligacao entre compras recentes, custo e politica de venda;
- consolidacao visual da diferenca entre custo que entra no estoque e custo que protege a venda.

Criterio de aceite:
- atendente ou gerente consegue entender onde cada custo entra;
- o preco final deixa de depender de interpretacao individual;
- o modulo passa a refletir uma politica de preco mais padronizada.

### Bloco 3 - Consolidacao fisica do estoque
Status: concluido tecnicamente
Prioridade: alta

Objetivo:
- alinhar cadastro, entrada, movimentacao, reserva e inventario na mesma linguagem operacional.

Escopo:
- revisar o recebimento de mercadoria para ficar mais natural;
- reforcar leitura de saldo disponivel, reservado e fisico;
- padronizar a visao de ponto operacional e ubicacao nas telas;
- consolidar o ciclo entre produto, entrada, reserva, venda e baixa.

Entregas desta etapa:
- carteira de entradas repaginada com resumo operacional, filtros rapidos e paginacao;
- detalhe da entrada reforcado com leitura operacional, resumo do destino fisico e alerta claro apos recebimento;
- tela de movimentacoes repaginada com resumo por tipo, filtros rapidos para ajustes/avarias/transferencias e leitura mais clara da rota fisica;
- tela de reservas consolidada com filtro por ponto operacional, leitura de vencimento e orientacao clara para tratamento diario;
- listagem e detalhe de inventarios reforcados com orientacao de conferencia, filtros por ponto/categoria/status e navegacao mais consistente;
- validacao automatizada cobrindo listagem de entradas, paginacao e bloqueio pos-recebimento.

Criterio de aceite:
- o usuario entende com clareza o que esta em estoque, reservado e disponivel;
- as movimentacoes deixam menos margem para duvida;
- a posicao fisica passa a ser lida do mesmo jeito em todas as telas.

### Bloco 4 - Consolidacao gerencial e fechamento
Status: concluido tecnicamente
Prioridade: media

Objetivo:
- fechar a app `estoque` para homologacao final de uso real.

Escopo:
- revisar indicadores realmente uteis na operacao;
- revisar auditoria, divergencias e relatorios;
- limpar documentacao para refletir o estado real do modulo;
- montar checklist final de homologacao da app.

Criterio de aceite:
- o plano e a documentacao batem com o comportamento real do sistema;
- a loja consegue testar a operacao do estoque de ponta a ponta;
- o modulo fica pronto para fase final de uso local real.

## Status Atual

Situacao do modulo: `fechado tecnicamente` e pronto para `homologacao manual em loja`.

Validacao executada nesta fase:
- `manage.py check` sem erros;
- suite ampla da app `estoque` com `142 testes OK`;
- validacoes focadas em cadastro, precificacao, entradas, movimentacoes, reservas, inventario e divergencias.
- rodada final de fechamento em 2026-07-17 com `156 testes OK` na suite `estoque.tests`;
- paineis gerenciais e auditoria revisados para o mesmo padrao operacional usado em OS, caixa e configuracoes.

## Checklist Final de Homologacao Manual

1. Cadastro e estrutura
- cadastrar produto simples e avancado;
- confirmar leitura de `ponto operacional + ubicacao`;
- validar saldo disponivel, reservado e fisico na listagem.

2. Precificacao
- testar custo de compra, custos de protecao da venda e preco final;
- validar leitura de margem, lucro e impacto por percentual/valor;
- revisar presets e historico de compra na decisao de preco.

3. Entradas e recebimento
- gerar entrada de mercadoria;
- receber entrada confirmando destino fisico;
- conferir bloqueio de edicao depois do recebimento.

4. Movimentacoes e reservas
- registrar ajuste, transferencia e avaria;
- validar rota fisica completa entre origem e destino;
- criar reserva, filtrar por ponto e tratar reserva vencida.

5. Inventario e divergencias
- gerar inventario por ponto, por ubicacao e por categoria;
- validar contagem cega, recontagem e aprovacao de divergencia;
- revisar relatorio de divergencias e auditoria operacional.

6. Fechamento operacional
- confirmar que o time entende os textos das telas sem treinamento tecnico;
- validar uso real em 1 ponto e depois em 2 pontos operacionais;
- registrar apenas ajustes finos de homologacao, nao mudancas estruturais.

## Ordem Recomendada

1. Bloco 1 - Cadastro de produto e estrutura fisica
2. Bloco 2 - Consolidacao comercial e de precificacao
3. Bloco 3 - Consolidacao fisica do estoque
4. Bloco 4 - Consolidacao gerencial e fechamento

## Observacao Importante

Este plano substitui a logica de pequenas correcoes isoladas na app `estoque`.
Daqui em diante, os ajustes devem ser feitos por bloco fechado, com validacao funcional ao final de cada ciclo.


