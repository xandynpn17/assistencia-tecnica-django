# Versao 1.1.3 - saneamento e reconstrucao financeira

## Base saneada

- As oito saidas operacionais existentes, no total de R$ 1.002,15, foram canceladas de forma auditada.
- Os registros originais permanecem no historico com usuario, data e justificativa; nenhuma entrada foi removida.
- Duas conciliacoes incorretas foram desfeitas e suas linhas voltaram a ficar pendentes.
- O pagamento de R$ 54,83 foi estornado e a conta a pagar correspondente voltou a ficar em aberto/vencida.
- O backup anterior ao saneamento foi preservado para recuperacao.

## Relatorios e manutencao

- Pagamentos e lancamentos vinculados deixaram de aparecer em duplicidade na tela de relatorios.
- Os totais respeitam os filtros de data, forma de pagamento, categoria e centro de custo.
- Pagamentos de contas realizados diretamente pelo banco passam a compor as saidas totais e os agrupamentos gerenciais.
- Estornos e itens cancelados ficam ocultos na visao operacional, mas podem ser exibidos pelo filtro de historico completo.
- Pagamentos possuem atalho para cancelamento auditado; lancamentos manuais possuem atalho para editar/cancelar.
- Catalogos globais duplicados por cadastros da empresa deixaram de aparecer repetidos nos seletores.

## Conciliacao guiada

A criacao pela linha do extrato exige a natureza economica correta:

- nova receita ou nova despesa operacional;
- recebimento ja registrado, sem reconhecer receita novamente;
- liquidacao agrupada de cartao;
- pagamento de conta a pagar existente;
- transferencia entre contas;
- capital, AFAC ou emprestimo de socio;
- tarifa, juros ou rendimento;
- movimento nao empresarial, com justificativa.

O PIX foi vinculado a conta Nubank para os recebimentos futuros. Seis PIX historicos com correspondencia exata de data e valor foram preparados como movimentos bancarios disponiveis, sem conciliacao automatica e sem duplicar receita. O usuario continua responsavel pela confirmacao de cada correspondencia.

## Datas e estornos

- O estorno bancario usa a mesma data do movimento original.
- O registro original e sua contrapartida ficam neutralizados e fora das sugestoes futuras.
- Uma operacao retroativa nao altera o caixa fisico aberto na data atual.

## Rotina de emergencia

O comando `reset_saidas_reconciliacao` permite repetir um saneamento somente quando quantidade e total conferem exatamente com o conjunto previamente validado. Exige backup, confirmacao explicita, motivo, empresa e usuario, e executa tudo em uma unica transacao.

Nao ha migracoes novas nesta versao.
