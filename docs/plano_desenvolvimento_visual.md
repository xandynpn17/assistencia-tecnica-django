# Plano de Desenvolvimento Visual

## Objetivo

Elevar a experiencia visual e operacional do sistema para um padrao mais profissional, consistente e rapido de usar no dia a dia de uma assistencia tecnica.

O foco nao e criar uma aparencia "bonita" isolada. O foco e reduzir tempo de operacao, melhorar leitura, diminuir erro humano e padronizar componentes entre `ordens`, `estoque`, `caixa`, `clientes`, `configuracoes`, `agenda` e `fiscal`.

## Diagnostico resumido

### Pontos fortes

- O sistema ja possui boa estrutura funcional por modulo.
- A sidebar e os fluxos principais ja dao uma base reconhecivel para o usuario.
- As telas mais importantes foram refinadas aos poucos e ja possuem padroes uteis, como duplo clique em listas e tooltips compactos.
- A OS ja esta se tornando o centro operacional do sistema.

### Pontos fracos

- Cada app cresceu com micro-padroes proprios de cards, filtros, botoes, headers e tabelas.
- Algumas telas ainda parecem densas sem hierarquia clara.
- Existem diferencas visuais entre listagens, formularios e dashboards.
- Alguns textos ainda usam acentuacao parcial ou entidades HTML antigas.
- Modais, acoes secundarias e mensagens de bloqueio ainda nao seguem um sistema visual unico.
- A experiencia em telas menores precisa de uma revisao dedicada.

## Principios visuais

- Operacional primeiro: telas devem ajudar o atendente a decidir rapidamente a proxima acao.
- Menos decoracao, mais leitura: usar contraste, espacamento e hierarquia em vez de excesso de cards.
- Consistencia por componente: mesmo tipo de acao deve parecer igual em todos os modulos.
- Densidade controlada: informacao suficiente sem parecer apertada.
- Estados claros: vazio, carregando, sem permissao, bloqueado, erro e sucesso precisam ser previsiveis.
- Mobile/tablet como consulta rapida: nao precisa ter a mesma densidade do desktop, mas nao pode quebrar.

## Fases

### Fase V1 - Inventario visual e tokens base
Status: concluida
Prioridade: alta

Objetivo:
- criar uma base visual unica sem refatorar telas inteiras ainda.

Escopo:
- mapear componentes recorrentes:
  - headers;
  - filtros;
  - tabelas;
  - botoes;
  - badges de status;
  - cards de indicadores;
  - modais;
  - mensagens de bloqueio/permissao;
- definir tokens CSS:
  - cores funcionais;
  - espacamentos;
  - bordas;
  - sombras;
  - tipografia;
  - tamanhos de botoes;
- criar uma camada CSS propria do sistema acima do AdminLTE.

Entregas:
- arquivo de estilos base do sistema;
- documento curto de componentes visuais;
- primeira aplicacao nos elementos globais.

Resultado esperado:
- base consistente para evoluir sem reescrever cada tela de forma isolada.

Progresso:
- criado stylesheet global `core/static/css/app_ui.css` com tokens de cor, espacamento, tipografia e componentes base;
- `core/templates/core/base.html` agora carrega essa camada global;
- estrutura de container visual padrao aplicada no wrapper de conteudo (`ui-page-shell`).

### Fase V2 - Layout global, sidebar e navegacao
Status: concluida
Prioridade: alta

Objetivo:
- estabilizar a navegacao principal e reduzir quebras visuais.

Escopo:
- revisar sidebar:
  - quebras de texto;
  - submenus;
  - estados ativos;
  - permissoes ocultas/bloqueadas;
- padronizar topo das paginas;
- melhorar tela 403/sem permissao;
- revisar breadcrumbs ou contexto de modulo.

Entregas:
- sidebar mais previsivel e compacta;
- pagina de acesso bloqueado com linguagem amigavel;
- headers globais padronizados.

Resultado esperado:
- usuario entende onde esta, o que pode fazer e por que algo esta bloqueado.

Progresso:
- sidebar recebeu padronizacao de densidade/contraste/estados ativos via CSS global;
- ajuste de quebra de texto nos itens de menu para evitar truncamentos visuais;
- tela `403` passou a usar estilo visual dedicado (`ui-no-permission`) mais consistente com o sistema.
- `core/base_inner.html` alinhado ao mesmo padrao visual do layout principal para evitar experiencias divergentes.

### Fase V3 - Padronizacao de listagens e filtros
Status: concluida
Prioridade: alta

Objetivo:
- tornar todas as listas principais rapidas de ler e operar.

Escopo:
- padronizar listagens de:
  - ordens;
  - clientes;
  - produtos/artigos;
  - movimentacoes;
  - contas a receber;
  - contas a pagar;
  - expedicoes;
  - usuarios;
- definir padrao unico para:
  - filtros;
  - busca rapida;
  - paginacao;
  - duplo clique;
  - estado vazio;
  - contadores/resumo;
  - exportacao.

Entregas:
- componente visual de filtros;
- tabelas com densidade e acoes consistentes;
- comportamento de duplo clique documentado e aplicado.

Resultado esperado:
- menos tempo procurando informacao e menos botoes repetidos.

Progresso:
- tela `clientes` reestruturada com:
  - header padrao por bloco;
  - filtro em linha operacional;
  - tabela mais enxuta;
  - estado vazio mais claro;
  - duplo clique para abrir detalhes.

### Fase V4 - OS como tela operacional principal
Status: concluida
Prioridade: alta

Objetivo:
- transformar a tela da OS na melhor tela do sistema.

Escopo:
- refinar cabecalho da OS:
  - status;
  - cliente;
  - equipamento;
  - tecnico;
  - acoes principais;
- padronizar abas:
  - detalhes;
  - orcamentos;
  - servicos e pecas;
  - linhas de trabalho;
  - arquivos;
  - alertas;
  - pedidos;
- reduzir informacoes repetidas;
- melhorar tooltips/infos compactas;
- manter compatibilidade com PDFs e fluxos existentes.

Entregas:
- header operacional compacto;
- abas com mesma estrutura de titulo, resumo e acoes;
- badges e estados por status com linguagem visual unica.

Resultado esperado:
- tecnico/atendente trabalha pela OS sem se perder entre abas e acoes.

Progresso:
- estrutura da tela de verificacao de cliente/abertura de OS alinhada ao layout base (header padrao + bloco de conteudo unico), eliminando sobreposicoes com o rodape;
- fluxo de cadastro e busca mantido com a mesma operacao, agora em estrutura visual consistente com os demais modulos.
- abas da OS receberam shell visual unico (navegacao/tabs/conteudo) para leitura mais clara e menor ruído operacional.

### Fase V5 - Estoque, consulta de artigos e venda a mostrador
Status: concluida
Prioridade: media/alta

Objetivo:
- deixar consulta e venda mais rapidas, com menor confusao entre produto, peca e servico.

Escopo:
- repaginar consulta de artigos:
  - resumo do artigo;
  - estoque por ponto;
  - preco/margem;
  - reservas;
  - venda rapida;
- revisar visual de cadastro de produto;
- melhorar indicadores de estoque;
- deixar claro quando o item e `produto`, `peca`, `consumivel` ou `servico`.

Entregas:
- resumo lateral ou painel superior mais objetivo;
- acoes de reserva/venda mais evidentes;
- separacao visual clara entre informacao e acao.

Resultado esperado:
- atendente consegue consultar, reservar ou vender sem interpretar blocos confusos.

Progresso:
- tela `consulta_artigos` consolidada no padrao operacional (busca + resumo + fechamento no mesmo contexto visual);
- base pronta para o proximo ajuste de micro-hierarquia em cabecalho/acoes e estados da venda.
- cabecalho da venda a mostrador padronizado com titulo, subtitulo operacional e estado rapido da operacao.
- telas `lista_produtos` e `movimentacoes` passaram a usar cabecalho modular unico (titulo + contexto + acoes), com melhor distribuicao entre cabecalho e conteudo.

### Fase V6 - Caixa e financeiro operacional
Status: concluida
Prioridade: media/alta

Objetivo:
- melhorar confianca visual em valores, status e acoes sensiveis.

Escopo:
- padronizar dashboards do caixa;
- revisar contas a receber/pagar;
- melhorar visual de pagamento;
- destacar divergencias, vencidos, parciais e cancelados;
- reforcar estados de permissao em acoes financeiras.

Entregas:
- tabelas financeiras mais legiveis;
- badges financeiros padronizados;
- formularios com melhor hierarquia de valores.

Resultado esperado:
- menos risco de erro em pagamentos, descontos, contas e fechamento.

Progresso:
- tela `contas_receber_list` alinhada ao header modular (titulo + contexto + acao principal), reduzindo redundancia no corpo;
- continuidade da padronizacao no caixa operacional em curso para dashboards e tabelas financeiras.
- telas `contas_pagar_list` e `dashboard_caixa_operacional` avancaram para o padrao de header modular e shell de formulario para filtros.

### Fase V7 - Formularios, modais e mensagens do sistema
Status: concluida
Prioridade: media

Objetivo:
- reduzir friccao em cadastro e edicao.

Escopo:
- padronizar formularios:
  - secoes;
  - campos obrigatorios;
  - ajuda contextual;
  - erros;
  - acoes de salvar/cancelar;
- padronizar modais:
  - confirmacao;
  - exclusao;
  - bloqueio;
  - operacao sensivel;
- revisar mensagens:
  - sucesso;
  - erro;
  - aviso;
  - sem permissao.

Entregas:
- formularios mais escaneaveis;
- modais consistentes;
- mensagens com tom profissional e claro.

Resultado esperado:
- menos duvidas ao preencher e menos risco em acoes criticas.

Progresso:
- formulario de agendamento recebeu cabecalho contextual padrao com acao de retorno;
- tela de `modelos_mensagem` recebeu cabecalho modular para separar contexto da lista/edicao.
- camada global passou a incluir `ui-form-shell`, padrao de modais e mensagens (`ui-message-info`/`ui-message-warning`) para acelerar uniformizacao entre apps.
- tela `verificar_cliente_os` recebeu ajuste de layout escopado para eliminar conflito entre formulario aberto e rodape, sem hack global.

### Fase V8 - PDFs e documentos emitidos
Status: concluida
Prioridade: alta

Objetivo:
- consolidar documentos como parte profissional da experiencia da empresa.

Escopo:
- revisar:
  - OS impressa;
  - etiqueta;
  - relatorio tecnico;
  - guia de expedicao;
  - taloes/recibos;
  - exportacoes financeiras;
- eliminar sobreposicoes;
- padronizar cabecalho, rodape, fontes, margens e tabelas;
- testar nomes longos, textos longos e anexos.

Entregas:
- PDF da etiqueta/OS corrigido;
- suite de testes de layout critico;
- padrao visual dos documentos.

Resultado esperado:
- documentos prontos para cliente, parceiros e auditoria.

Progresso:
- faixa de etiqueta/corte da OS impressa corrigida em `ordens/view_modules/impressao.py`;
- teste automatizado adicionado em `ordens/tests.py`.
- `ordens/view_modules/expedicao.py` recebeu clipping por largura real de texto na `guia_expedicao_pdf`, prevenindo sobreposicao em parceiro/referencia/cliente/status com textos longos.
- novo teste de regressao cobre emissao de PDF de expedicao com campos longos, garantindo retorno valido (`application/pdf` + assinatura `%PDF`).

### Fase V9 - Responsividade e homologacao visual
Status: concluida
Prioridade: media

Objetivo:
- garantir que o sistema nao quebre em notebook pequeno, tablet ou telas estreitas.

Escopo:
- revisar principais telas em:
  - desktop amplo;
  - notebook;
  - tablet;
  - mobile de consulta;
- corrigir overflow, botoes quebrados, tabelas ilegíveis e cards comprimidos;
- criar checklist visual por perfil.

Entregas:
- checklist visual;
- ajustes responsivos nas telas principais;
- relatorio de homologacao visual.

Resultado esperado:
- experiencia confiavel fora do desktop ideal.

Progresso:
- ajustes responsivos globais adicionados em `core/static/css/app_ui.css` (header, shell de pagina, acoes, tabelas e footer em telas estreitas);
- checklist de homologacao criado em `docs/checklist_homologacao_visual.md`;
- layout global ajustado para `sticky footer` sem sobrepor formularios e mantendo o rodape no fim da viewport.

## Ordem recomendada

1. V1 - Inventario visual e tokens base
2. V2 - Layout global, sidebar e navegacao
3. V3 - Listagens e filtros
4. V4 - Tela da OS
5. V8 - PDFs e documentos
6. V5 - Estoque e consulta de artigos
7. V6 - Caixa e financeiro
8. V7 - Formularios, modais e mensagens
9. V9 - Responsividade e homologacao

## Criterios de aceite

- Telas principais usam headers, filtros, tabelas e botoes com o mesmo padrao.
- Nenhuma acao critica aparece sem contexto de permissao ou bloqueio.
- PDFs principais nao apresentam sobreposicao com textos longos.
- Fluxos de OS, estoque e caixa ficam mais rapidos para uso repetido.
- Checklist visual aprovado em pelo menos desktop e notebook.

## Fechamento do plano visual

Status geral: concluido.

Resumo de encerramento:
- fases V1 a V9 concluidas neste ciclo;
- linguagem visual base consolidada em camada global (`app_ui.css`);
- padrao de headers, acoes, formularios, tabelas e mensagens aplicado nas telas operacionais principais;
- telas de OS, estoque e caixa com melhor hierarquia de leitura e menor friccao operacional;
- documentos PDF criticos reforcados para cenarios de texto longo;
- responsividade global estabilizada para desktop, notebook, tablet e mobile de consulta.

Backlog pos-plano (melhoria continua):
- refinamento de micro-espacamentos por tela conforme uso real da equipe;
- revisao incremental de acentuacao residual em pontos legados;
- evolucao do design system para biblioteca de componentes reutilizaveis por app.
