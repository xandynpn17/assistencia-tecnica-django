# Analise Profissional do Sistema - 2026-05-14

## Resumo executivo

O sistema ja tem uma base operacional forte: OS, cliente, orcamento, estoque, caixa, expedicao, permissoes, auditoria, PostgreSQL e preparacao para Render. A arquitetura evoluiu bem para um ERP operacional de assistencia tecnica.

O maior risco atual nao e falta de funcionalidades basicas. O risco esta em padronizacao visual, consistencia textual, maturidade SaaS, automacao de comunicacao e fechamento das pontas de documentacao/PDF.

## Pontos fortes

- Fluxo principal bem coberto: cliente -> OS -> orcamento -> servicos/pecas -> caixa.
- Status de OS relativamente rico, permitindo operacao real sem fluxo linear engessado.
- Estoque ja diferencia produto, peca, consumivel e servico, o que ajuda muito nos orcamentos.
- Caixa ja tem recebiveis, pagaveis, comissoes, custos fixos, DRE e auditoria.
- App configuracoes virou um nucleo administrativo com setup inicial, permissoes, auditoria e base SaaS.
- PostgreSQL e Render ja estao encaminhados.
- Testes automatizados cobrem boa parte dos fluxos criticos.

## Pontos ruins ou fragilidades

- Visual ainda tem marcas de crescimento organico: muitas telas usam AdminLTE de forma diferente, com densidade e hierarquia visual variando entre apps.
- Ainda existem textos sem acentuacao completa ou com risco de mojibake em arquivos antigos.
- Alguns PDFs ainda usam desenho manual em coordenadas absolutas, o que aumenta risco de sobreposicao quando nomes, textos ou layouts mudam.
- O modelo multiempresa existe como foundation, mas ainda precisa de filtragem obrigatoria por tenant nas queries antes de virar SaaS real.
- Comunicacao com cliente ainda parece mais operacional/manual do que automatizada por eventos.
- O portal do cliente existe, mas pode virar uma peca central de reducao de chamadas e aumento de confianca.
- Permissoes granulares estao bem melhores, mas o modelo com muitas flags no usuario tende a ficar pesado no longo prazo.
- Arquivos `staticfiles` versionados deixam o repositorio grande e podem criar ruido; idealmente devem ser gerados no deploy.

## Melhorias visuais prioritarias

1. Criar um design system simples para telas internas:
   - cabecalho padrao por modulo;
   - barra de acoes consistente;
   - filtros sempre no mesmo formato;
   - tabela com duplo clique padronizado;
   - estados vazios, loading e erro padronizados.

2. Padronizar dashboards:
   - indicadores com mesma linguagem visual;
   - cores por significado, nao por modulo;
   - cards menos chamativos e mais densos para operacao diaria.

3. Melhorar OS como tela principal:
   - cabecalho compacto fixo com status, cliente, equipamento e acoes principais;
   - timeline tecnica mais legivel;
   - abas com mesma estrutura de titulo, acoes e conteudo.

4. Refinar consulta de artigos/PDV:
   - separar claramente "artigo", "estoque", "preco", "margem", "reserva" e "venda";
   - usar uma coluna lateral de resumo operacional em vez de blocos longos.

5. Revisar responsividade:
   - algumas telas parecem desenhadas para desktop amplo;
   - atendente pode precisar consultar rapidamente em notebook pequeno ou tablet.

## Funcionalidades com alto valor

As referencias de mercado e relatos de clientes apontam para os mesmos problemas: falta de status, demora, orcamento pouco claro, garantia disputada, falta de prova tecnica e baixa previsibilidade. Prioridades recomendadas:

1. Portal do cliente mais forte:
   - status em tempo real;
   - historico de mensagens;
   - fotos/laudo;
   - aprovacao ou recusa de orcamento;
   - aceite de termos;
   - comprovante de retirada.

2. Comunicacao automatica por eventos:
   - OS criada;
   - diagnostico concluido;
   - orcamento enviado;
   - orcamento sem resposta ha X dias;
   - aguardando peca;
   - pronto para retirada;
   - garantia perto de expirar.

3. Aprovacao digital de orcamento:
   - link unico;
   - registro de IP/data;
   - aceite item a item;
   - opcao de aprovar parcial.

4. Checklist tecnico por tipo de equipamento:
   - entrada;
   - diagnostico;
   - teste final;
   - entrega.

5. Laudo tecnico com fotos obrigatorias:
   - antes/depois;
   - evidencia de mau uso;
   - peca substituida;
   - assinatura tecnica.

6. SLA e alertas:
   - OS parada sem movimentacao;
   - orcamento sem resposta;
   - peca reservada vencendo;
   - equipamento pronto ha muitos dias;
   - parceiro externo atrasado.

7. Garantia pos-servico:
   - controle por item/servico;
   - reincidencia por cliente/equipamento;
   - abertura de OS de garantia vinculada a OS original.

8. Captura de etiqueta/numero de serie por camera:
   - reduzir erro de digitacao;
   - agilizar entrada;
   - apoiar garantia e rastreio.

9. Fila de bancada:
   - tecnico ve somente OS atribuida;
   - prioridade;
   - tempo parado;
   - proxima acao.

10. Pos-atendimento:
    - pesquisa NPS simples;
    - alerta para cliente insatisfeito;
    - cupom/retorno preventivo.

## Correcoes tecnicas recomendadas

1. Tenant real:
   - aplicar filtros por `empresa` em managers/querysets;
   - impedir acesso cruzado por URL;
   - criar testes de isolamento.

2. Static files:
   - remover `staticfiles` do versionamento se estiver sendo gerado por `collectstatic`;
   - manter somente `static`/`core/static` como fonte.

3. PDF engine:
   - reduzir desenho manual em canvas;
   - preferir Platypus/tabelas/flowables;
   - criar testes contra layout critico.

4. Observabilidade:
   - logging estruturado para erros de PDF, envio de mensagem, backup, restore, pagamentos e webhooks.

5. Tarefas assicronas:
   - futuras filas para email/WhatsApp, lembretes, expirar reservas e gerar relatorios.

## Correcao aplicada nesta rodada

- A etiqueta de corte da OS impressa deixava conteudo muito proximo da linha central do papel.
- Foi criada uma faixa reservada para etiqueta/corte, reduzindo os frames superior e inferior.
- Foi adicionado teste automatizado garantindo que os frames nao encostam entre si na regiao da etiqueta.

Arquivos alterados:

- `ordens/view_modules/impressao.py`
- `ordens/tests.py`

## Fontes externas usadas como referencia

- Fixmo (`https://fixmo.app/`): plataforma de reparo com tracking, POS, inventario, notificacoes e multi-filial.
- GarageArc (`https://garagearc.com/en`): destaca estimativas, ordens, inspecoes digitais, pagamentos e atualizacoes por WhatsApp/SMS/email.
- BayOS (`https://bayos.io/`): reforca ordens de reparo, inspecoes digitais, pagamentos, agenda, inventario e cliente em uma plataforma unica.
- Procon-SP (`https://www.procon.sp.gov.br/atendimento/`): reforca prazo, ordem de servico, orcamento previo e clareza de informacao ao consumidor.

## Prioridade sugerida

1. Corrigir PDFs e documentos criticos.
2. Consolidar portal/aprovacao digital do cliente.
3. Automatizar notificacoes por status.
4. Criar SLA/alertas de OS parada.
5. Aplicar isolamento tenant real.
6. Padronizar design system interno.
7. Remover staticfiles versionado e limpar artefatos gerados.
