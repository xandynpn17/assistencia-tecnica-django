# Checklist de Homologacao Visual

## Escopo

- Modulos cobertos: `ordens`, `estoque`, `caixa`, `configuracoes`, `agenda`.
- Ambientes: desktop amplo, notebook, tablet e mobile de consulta.

## Itens de validacao

- Header e contexto da pagina:
  - titulo visivel e sem quebra;
  - acoes principais acessiveis sem overflow.
- Tabelas:
  - sem sobreposicao de colunas;
  - rolagem horizontal funcional em telas pequenas;
  - leitura minima preservada.
- Formularios:
  - labels e campos sem colisao;
  - botoes de acao sem quebra em mobile;
  - mensagens de erro/sucesso legiveis.
- Rodape e navegacao:
  - rodape fora da area de formulario;
  - sidebar e submenus sem truncamento critico.
- Documentos/PDF:
  - sem sobreposicao de textos longos;
  - dados operacionais legiveis;
  - cabecalho/rodape consistentes.

## Status atual

- Desktop amplo: validado.
- Notebook: validado.
- Tablet: validacao estrutural concluida por CSS global responsivo.
- Mobile de consulta: validacao estrutural concluida por CSS global responsivo.

## Observacoes

- A tela `verificar_cliente_os` recebeu ajuste dedicado de layout para evitar conflito entre rodape e formulario aberto.
- O PDF de guia de expedicao passou a truncar campos longos por largura real, evitando sobreposicao de texto.
