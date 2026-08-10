# Monitoramento de Integridade do Estoque

## Objetivo

Executar diariamente a reconciliacao do estoque e manter evidencia pesquisavel por empresa. O monitoramento compara:

- total do produto x saldos por ponto;
- saldos negativos;
- ponto x ubicacoes;
- ubicacoes x camadas de custo;
- reservas ativas x saldo fisico;
- saldo fisico x lotes;
- saldo fisico x numeros de serie.

## Comando oficial

No ambiente local Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 monitorar_estoque --empresa 1 --origem agendada --falhar-se-divergir
```

No servidor, use o mesmo ambiente configurado para o Django:

```text
python manage.py monitorar_estoque --empresa <ID> --origem agendada --falhar-se-divergir

## Execução automática no Windows

A rotina oficial local foi instalada como tarefa `Assistencia-MonitoramentoEstoque`, com repetição a cada 15 minutos. Ela executa todas as empresas separadamente e grava o histórico no sistema.

Arquivos operacionais:

- `scripts/monitorar_estoque_agendado.ps1`: executor silencioso e log persistente;
- `scripts/instalar_monitoramento_estoque.ps1`: instalação/atualização idempotente da tarefa;
- `logs/monitoramento_estoque_agendado.log`: saída das execuções automáticas.

O comando usado pela tarefa é `monitorar_estoque --todas-empresas --origem agendada --falhar-se-divergir`.
```

Execute uma vez para cada empresa ativa. Sem `--empresa`, o comando audita a base inteira e grava uma execucao global.

## Comportamento para automacao

- sem divergencias: encerra com sucesso e grava status `ok`;
- com divergencias: grava status `divergencia` e, com `--falhar-se-divergir`, retorna codigo de erro ao agendador;
- falha inesperada: grava status `erro` com a mensagem tecnica e propaga o erro;
- cada execucao preserva resumo, contagens e ate 100 exemplos de cada categoria.

O historico aparece em **Estoque > Divergencias**, com alerta quando nao existe execucao persistida nas ultimas 25 horas.

## Frequencia recomendada

- diariamente, fora do horario de maior movimento;
- adicionalmente apos importacao, migracao relevante ou correcao de saldo;
- manter o agendador configurado para alertar a gestao quando o processo retornar codigo diferente de zero.

## Seguranca

O comando e somente diagnostico: nao altera saldos, movimentos, lotes, series ou reservas. Correcoes devem continuar sendo feitas por inventario, estorno ou movimentacao auditada.
