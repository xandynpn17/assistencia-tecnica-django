# Checklist Manual de Homologacao

Este roteiro valida o fluxo principal fim a fim (ordens, estoque, caixa e comissoes).

## 1) Preparacao rapida

```powershell
python manage.py check
python manage.py migrate
python manage.py gerar_base_teste --prefixo HMLMAR2026 --clientes 30 --produtos 24 --marcas 10 --tecnicos 8 --ordens 20 --limpar
```

Resultado esperado:
- sem erros no `check` e `migrate`
- base criada com clientes, produtos, tecnicos e ordens

## 2) Login e permissoes

1. Entrar com superuser.
2. Entrar com tecnico comum.
3. Confirmar que ambos conseguem abrir OS e usar CEP.

Resultado esperado:
- sem erro de permissao no formulario de OS
- busca de CEP funcionando para perfis operacionais

## 3) Fluxo de Ordem de Servico

1. Criar nova OS.
2. Em orcamento, incluir 1 item de servico e 1 item de peca.
3. Aprovar os itens.
4. Migrar itens aprovados para "Servicos e Pecas".
5. Preencher relatorio tecnico.
6. Evoluir status para finalizada.

Resultado esperado:
- migracao so ocorre para itens aprovados
- item aparece uma unica vez em servicos/pecas
- sem duplicidade de valores

## 4) Fluxo de Caixa

1. Abrir caixa do dia.
2. Registrar pagamento da OS.
3. Fechar caixa.
4. Conferir dashboard diario e filtro por periodo.

Resultado esperado:
- abertura/fechamento sem erro
- valores consolidados em entradas/saidas

## 5) Fluxo de Comissoes

1. Abrir `/caixa/meu-desempenho/`.
2. Informar intervalo de datas (obrigatorio, maximo 12 meses).
3. Selecionar tecnico individual ou todos.
4. Marcar/desmarcar caixas de calculo para servicos e pecas.
5. Informar percentual (%) para cada tipo.
6. Gerar resultado.

Resultado esperado:
- tabelas separadas por tecnico
- separacao por tipo: servico, peca, vendas e bonus
- totais e comissao coerentes com percentual informado
- ordens ja pagas nao reaparecem para pagamento duplicado

## 6) Fluxo administrativo de comissoes

1. Abrir tela administrativa de comissoes.
2. Filtrar por tecnico/periodo/status.
3. Selecionar em lote e aplicar: liberar, marcar como paga, cancelar.

Resultado esperado:
- mudanca de status em lote funcionando
- historico de status consistente

## 7) Estoque (venda a mostrador)

1. Abrir "Consulta de artigos".
2. Confirmar que nao lista tudo antes da busca.
3. Buscar por nome/EAN.
4. Confirmar listagem resumida (nome, EAN, marca, preco, ponto, estoque).
5. Abrir detalhes do item.

Resultado esperado:
- consulta apenas apos busca
- detalhes completos somente ao abrir o produto

## 8) Agenda (opcional)

1. Criar agendamento vinculado a uma OS.
2. Ajustar inicio/fim no mesmo dia.
3. Conferir visualizacao no calendario mensal.

Resultado esperado:
- sem sobreposicao incorreta de evento entre dias
- formulario preenche fim no mesmo dia por padrao

