# Plano de Refino - Setup Inicial, OS, Estoque, Inventario e Backup

## Objetivo

Refinar a fase de configuracao e operacao para deixar o sistema mais intuitivo no primeiro uso, mais coerente na configuracao de documentos da OS e mais claro na separacao entre:

- inventario de estoque;
- inventario de equipamentos de clientes em loja;
- backup e restauracao local.

Este plano foi pensado para uso local real em loja, sem inventar estruturas desnecessarias nem quebrar o que ja funciona.

## Diagnostico atual

### 1. Setup inicial

Hoje o setup inicial cobre apenas:

- nome da empresa;
- CNPJ;
- telefone;
- email;
- endereco livre;
- prefixo da OS;
- tipo de empresa;
- linhas de atuacao.

Pontos fracos atuais:

- CNPJ e telefone sem mascara/formatacao guiada;
- endereco ainda livre, sem estrutura por CEP, cidade e UF;
- faltam campos empresariais importantes como razao social e inscricoes;
- prefixo da OS existe, mas o numero inicial da OS ainda nao entra no setup;
- o setup vira um item de navegacao permanente, quando deveria ser um assistente de primeiro uso e nao uma rotina do dia a dia.

### 2. Configuracao de OS e documentos

Hoje as configuracoes relacionadas a OS estao espalhadas entre:

- `ConfiguracaoOrdemServico`;
- `ConfiguracaoSistema`;
- preview de documentos;
- layouts e termos em blocos separados.

Pontos fracos atuais:

- o atendente/gestor nao enxerga isso como um unico assunto;
- rodape, termos, layout, cor, etiquetas e exibicao de informacoes estao tecnicamente presentes em partes, mas com baixa coerencia operacional;
- a preview depende de OS real e hoje retorna `Sem OS cadastrada para pre-visualizacao`, o que quebra a experiencia logo numa base nova.

### 3. Localizacao/ubicacao padrao

Hoje o estoque usa:

- `ponto_operacional`;
- `ubicacao_padrao`;
- campo legado `localizacao`.

Pontos fracos atuais:

- a estrutura operacional do estoque nao nasce a partir do setup inicial;
- o usuario ainda pode sentir duplicidade entre `localizacao` e `ubicacao_padrao`;
- falta preset por tipo de operacao/empresa para acelerar a base inicial.

### 4. Inventario

Hoje existe inventario de estoque por ponto e ubicacao.

Isso e bom para pecas e produtos, mas nao cobre o problema operacional que voce descreveu:

- conferência dos equipamentos de clientes em loja;
- lista por OS / tipo / modelo / posicao;
- rotina de “picar” o que foi encontrado fisicamente;
- deteccao do que esta faltando ou fora do lugar.

Esse segundo caso nao e inventario de estoque. E um inventario de custodia operacional de equipamentos.

### 5. Backup

O sistema ja possui boa base de backup e restore, inclusive:

- backup por UI;
- restore administrativo;
- restore publico/local sem login;
- scripts locais de preparo e migracao.

Pontos a melhorar:

- a experiencia ainda pode ficar mais simples para gestor nao tecnico;
- backup, inventario ciclico e metodo de custo estao misturados com muitas outras configuracoes;
- falta uma leitura mais executiva do “estado de seguranca operacional”.

## Diretriz arquitetural

### Inventario de estoque

Permanece dentro do app `estoque`.

Motivo:

- compartilha produtos, saldos, pontos operacionais e ubicacoes;
- ja existe estrutura pronta;
- separar agora em outro app aumentaria complexidade sem ganho real.

### Inventario de equipamentos em loja

Nao deve nascer dentro do inventario de estoque.

Motivo:

- a entidade principal nao e o produto, e sim a OS/equipamento do cliente;
- o objetivo e controle fisico de patio, bancada, prateleira, armario, expedicao ou aguardando retirada;
- isso conversa mais com `ordens` do que com `estoque`.

Recomendacao:

- criar primeiro como submodulo operacional de `ordens`;
- so virar app propria no futuro se evoluir para coletor, etiquetas, auditoria recorrente, multiplos fluxos ou mobile dedicado.

## Plano de desenvolvimento

### Fase R1 - Setup inicial profissional

Objetivo:

Transformar o setup inicial em um assistente real de implantacao.

Escopo:

- formatar CNPJ;
- formatar telefone;
- adicionar celular / WhatsApp;
- separar endereco em:
  - CEP;
  - logradouro;
  - numero;
  - complemento;
  - bairro;
  - cidade;
  - estado;
- integrar busca por CEP no setup inicial;
- adicionar:
  - razao social;
  - inscricao estadual;
  - inscricao municipal;
  - nome fantasia;
- incluir no setup:
  - prefixo da OS;
  - numero inicial da OS;
- manter tipo de empresa e linhas de atuacao;
- ao concluir setup:
  - esconder item de “Setup inicial” da sidebar;
  - manter acesso posterior apenas por um botao tipo `Reabrir assistente inicial` dentro de configuracoes.

Resultado esperado:

- base nova fica pronta para uso real sem gambiarras;
- primeira configuracao ja nasce com dados empresariais suficientes.

### Fase R2 - Estrutura operacional padrao por setup

Objetivo:

Fazer o setup inicial gerar defaults operacionais coerentes.

Escopo:

- criar presets de `ponto_operacional` e `ubicacao_padrao` conforme tipo/linha da empresa;
- exemplos:
  - assistencia tecnica:
    - `AT` atendimento;
    - `BC` bancada;
    - `AG` aguardando cliente;
    - `EX` expedicao;
    - `EST` estoque;
  - oficina:
    - recepcao;
    - elevador/bay;
    - aguardando peca;
    - patio;
- vincular `ubicacao_padrao` sugerida para produtos novos por tipo;
- reduzir dependencia do campo legado `localizacao`.

Resultado esperado:

- o estoque e os equipamentos ja nascem com um mapa operacional minimamente padrao.

### Fase R3 - Reorganizacao de configuracoes da OS

Objetivo:

Consolidar tudo que e “documentos e regras da OS” num fluxo mais intuitivo.

Escopo:

- reorganizar as telas em grupos claros:
  - Dados da empresa;
  - Ordem de servico;
  - Documentos e PDFs;
  - Estoque e inventario;
  - Backup e recuperacao;
- na area `Ordem de servico`, concentrar:
  - prefixo;
  - numero inicial;
  - mensagens de rodape;
  - termos e condicoes;
  - layout da OS impressa;
  - layout dos PDFs;
  - cor dos documentos;
  - etiqueta de corte;
  - campos visiveis na OS/PDF;
  - exibicao de assinatura/validacao;
- revisar o texto da tela para linguagem mais operacional.

Resultado esperado:

- o usuario entende rapidamente onde mexer quando quer ajustar a OS e os PDFs.

### Fase R4 - Preview sem dependência de OS real

Objetivo:

Corrigir a experiencia de preview em base vazia.

Escopo:

- substituir `Sem OS cadastrada para pre-visualizacao` por preview com dados mockados;
- criar amostras internas seguras para:
  - OS digital;
  - OS impressao;
  - relatorio tecnico;
  - orcamento;
- permitir trocar presets mesmo sem nenhuma OS cadastrada;
- manter opcao de usar OS real quando houver.

Resultado esperado:

- configuracao de documentos funciona desde o primeiro minuto do sistema.

### Fase R5 - Higiene da estrutura de empresa

Objetivo:

Melhorar coerencia dos dados da empresa entre setup inicial e tela de empresa.

Escopo:

- evitar duplicidade/confusao entre campos do setup e da tela completa de empresa;
- definir claramente:
  - o que e obrigatorio no primeiro uso;
  - o que e complementar e pode ficar para depois;
- aplicar mascaras e validacoes padronizadas;
- deixar os campos fiscais em grupos:
  - cadastro basico;
  - contato;
  - endereco;
  - tributacao;
  - identidade visual.

Resultado esperado:

- menos retrabalho ao configurar empresa pela primeira vez.

### Fase R6 - Estoque: simplificacao operacional

Objetivo:

Melhorar a compreensao de estoque na configuracao e no cadastro de produtos.

Escopo:

- reforcar o campo `metodo de custo` como escolha operacional entre:
  - `PMP`;
  - `PEPS`;
- manter `UEPS` fora do escopo;
- explicar na UI impacto do metodo escolhido;
- destacar melhor:
  - retencao de backup;
  - inventario ciclico;
  - metodo de custo;
  - politica de reserva;
- revisar `localizacao` para descontinuacao visual progressiva, priorizando `ubicacao_padrao`.

Resultado esperado:

- menos ambiguidade no cadastro e no entendimento de saldos/custos.

### Fase R7 - Inventario de estoque mais claro
Status: concluida (base operacional entregue)

Objetivo:

Melhorar o inventario de pecas/produtos sem criar uma estrutura paralela.

Escopo:

- criar tela operacional com:
  - saldo do sistema;
  - quantidade contada;
  - ajuste;
  - impacto financeiro;
  - PMP total;
  - PVP total;
- permitir recorte por:
  - ponto;
  - ubicacao;
  - categoria;
  - fornecedor;
- destacar itens divergentes e impacto total;
- melhorar a tela de indicadores de inventario.

Resultado esperado:

- inventario de estoque fica util para contagem e para decisao gerencial.

Entregue nesta etapa:

- fluxo operacional digital criado em `Estoque > Inventarios`;
- abertura de inventario com numero proprio e recorte por ponto/ubicacao/categoria;
- tela de conferencia com quantidade do sistema, contada, ajuste, situacao, motivo e observacao;
- fechamento com resumo de divergencias, mantendo o inventario tecnico antigo compatibilizado.

### Fase R8 - Inventario de equipamentos em loja
Status: parcialmente concluida

Objetivo:

Criar controle fisico dos equipamentos dos clientes dentro da operacao.

Escopo funcional:

- criar submodulo em `ordens` para `Inventario de equipamentos em loja`;
- gerar lista com:
  - numero da OS;
  - cliente;
  - tipo de equipamento;
  - marca/modelo;
  - tecnico responsavel;
  - status;
  - posicao/local atual;
- permitir abrir uma conferencia por setor/posicao;
- marcar equipamentos encontrados;
- apontar:
  - faltando;
  - encontrado fora da posicao;
  - OS sem posicao definida;
- manter historico de conferencias.

Escopo tecnico:

- usar OS como entidade principal;
- aproveitar `local_armazenamento`/posicao da OS como base inicial;
- permitir evolucao futura para etiqueta/QR code.

Entregue nesta etapa:

- criado o submodulo `Ordens > Conciliacao de Ordens`;
- geracao de conferencia por ordens abertas, com filtro por `local_armazenamento`;
- snapshot por OS com numero, cliente, tipo/modelo, status, dias em aberto, valor parado e local;
- conferencia item a item com motivo de divergencia, observacao e fechamento da conciliacao.

Fica como evolucao futura:

- modo de auditoria recorrente por setores;
- leitura por etiqueta/QR code;
- segunda etapa voltada a “picar” rapidamente em campo com interface ainda mais enxuta.

Resultado esperado:

- controle real do que esta fisicamente na loja, sem misturar isso com pecas de estoque.

### Fase R9 - Backup e recuperacao mais executivos

Objetivo:

Deixar backup e restore mais simples para operacao diaria.

Escopo:

- reorganizar `Backup e recuperacao` como secao propria nas configuracoes;
- destacar:
  - ultimo backup gerado;
  - retencao configurada;
  - tamanho aproximado;
  - status da pasta oficial;
  - alerta se nunca houve restore testado;
- simplificar o texto da UI;
- manter atalhos para:
  - gerar backup;
  - restaurar;
  - abrir recuperacao local;
  - abrir guia do novo computador.

Resultado esperado:

- gestor entende rapidamente se a seguranca operacional esta em dia.

## Ordem recomendada de execucao

1. `R1 - Setup inicial profissional`
2. `R2 - Estrutura operacional padrao por setup`
3. `R3 - Reorganizacao de configuracoes da OS`
4. `R4 - Preview sem dependencia de OS real`
5. `R5 - Higiene da estrutura de empresa`
6. `R6 - Estoque: simplificacao operacional`
7. `R7 - Inventario de estoque mais claro`
8. `R8 - Inventario de equipamentos em loja`
9. `R9 - Backup e recuperacao mais executivos`

## Decisoes recomendadas

### Sobre nova app para inventario

Recomendacao atual:

- **nao criar app nova agora** para inventario de estoque;
- **nao misturar inventario de equipamentos com estoque**;
- criar o inventario de equipamentos primeiro como modulo de `ordens`.

### Sobre localizacao

Recomendacao atual:

- manter compatibilidade tecnica temporaria;
- parar de promover `localizacao` como campo principal;
- concentrar operacao em `ponto_operacional + ubicacao_padrao`.

### Sobre preview de documentos

Recomendacao atual:

- preview deve funcionar mesmo em banco zerado;
- usar fixture/mock interno e nao depender de OS real.

## Criterios de conclusao

Vamos considerar esta etapa concluida quando:

- setup inicial permitir configuracao empresarial real sem gambiarra;
- item de setup desaparecer da sidebar apos conclusao;
- configuracoes de OS/documentos ficarem centralizadas e intuitivas;
- preview de documentos funcionar em base vazia;
- estoque nascer com presets coerentes;
- inventario de estoque ficar gerencialmente legivel;
- inventario de equipamentos em loja existir como rotina separada do estoque;
- backup/restore ficar mais claro para uso diario.
