# Evolução E6/E7 — operação e gestão

Estado: implementada no ambiente local de desenvolvimento, em homologação. Não equivale a publicação no Git nem instalação no PC definitivo. Base de desenvolvimento `assistencia_dev`; backup pré-migration: `backups/evolucao_e6_e7_local/backup_20260921_213241.zip`. Migrations novas: `ordens.0052` a `ordens.0054`.

Verificação automática: 118 testes de operação/caixa/estoque passaram na regressão ampliada; 11 testes próprios da evolução e o cenário de pedido aberto passaram após os ajustes finais. `manage.py check` e `makemigrations --check --dry-run` sem pendências.

## Operação (E6)

- Central de pendências em **Ordens de Serviço → Central de Pendências**, por empresa: OS sem atividade, orçamento com itens sem resposta, equipamento pronto, pedido com quantidade pendente e fabricante vencido. Valores/cobranças de fabricante só aparecem para gestão financeira. Os prazos são configuráveis por gestor. Não há fechamento automático.
- Histórico em **OS → Histórico do equipamento**. Série/marca/modelo sugerem candidatos da mesma empresa; somente OS do mesmo cliente mostram detalhes. Registros potencialmente relacionados a outro cliente só aparecem como contagem. Gestor pode confirmar ou desfazer o vínculo por identificador interno; há log da alteração. Não há fusão automática.
- Checklist em **OS → Checklist de entrega**. Itens gerais e adicionais por tipo de equipamento configuráveis por empresa, acessórios, testes e observação. Cada OS guarda fotografia dos itens quando o checklist é iniciado, preservando a conferência antiga após mudanças na configuração. Se a obrigatoriedade estiver ligada, a marcação de conclusão exige todos os itens, acessórios e testes; caso contrário, pode concluir com pendências visíveis. Ainda não bloqueia o fluxo legado de entrega/fechamento da OS nem altera PDFs; essa integração requer homologação do balcão para evitar travar ordens antigas.

## Gestão (E7)

- **Caixa → Rentabilidade OS**: receita comercial registrada, custo realizado, custo previsto, comissão, taxas estimadas de pagamentos diretos e margem de referência; os totais por tipo/marca/modelo resumem as últimas 50 OS. Peça sem custo e checkout agrupado sem rateio são sinalizados como provisórios. Não é saldo, DRE oficial ou lucro líquido definitivo. Ainda falta atribuir taxas agrupadas e retrabalho por OS e ampliar filtros/agrupamentos.
- **Caixa → Fluxo**: separa contas a receber de fabricantes, demais recebíveis, contas a pagar e recorrentes de referência. Contas vencidas aparecem à parte. Recorrentes não são somadas às obrigações para evitar duplicidade; por isso a diferença projetada mostra apenas contas lançadas. Repasses futuros de cartão com prazo registrado aparecem separadamente como bruto/taxa/líquido estimados, sem integrar entradas ou saldo; a confirmação pelo extrato segue manual.
- **Estoque → Reposição**: pedidos de compra de reposição da OS, ainda abertos, reduzem somente a compra adicional sugerida; transferência imediata do armazém continua possível. Saldo negativo gera aviso. O sistema continua exigindo confirmação humana para gerar entrada em rascunho. Substitutos/compatibilidade validada não são sugeridos automaticamente.

## Homologação antes do PC definitivo

1. Configurar prazos e dois itens de checklist; conferir que OS antiga continua abrindo e que checklist iniciado mantém seus itens após mudar a configuração.
2. Confirmar e desfazer um vínculo de histórico; conferir que outro cliente não revela dados.
3. Conferir uma OS com peça sem custo, uma com custo previsto e uma com checkout agrupado no relatório de rentabilidade.
4. Conferir em Fluxo uma conta de fabricante, uma conta a pagar e uma recorrente já lançada para não somar duas vezes.
5. Conferir reposição com pedido em aberto, depois cancelado; a compra sugerida deve aumentar ao cancelar.
6. Atualizar o PC definitivo só depois de commit/push, backup próprio do PC definitivo, migrations e ensaio dos fluxos de balcão. O backup de desenvolvimento não substitui o da loja.
