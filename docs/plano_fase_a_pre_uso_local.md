# Plano Fase A - Pre-Uso Real Local

## Objetivo

Preparar o sistema para uso real na empresa em modo local/offline em rede, com um PC servidor e 2 ou 3 PCs acessando pelo navegador.

Esta fase tem foco em refinamento, correcao e homologacao operacional. A prioridade nao e criar modulos novos, e sim deixar os fluxos existentes seguros, claros e confiaveis para atendimento, bancada, estoque e caixa.

## Contexto

- O sistema sera usado inicialmente na empresa principal.
- O uso sera local em rede, acessado pelo navegador.
- Um PC ficara como servidor local com PostgreSQL, aplicacao Django, arquivos `media` e backups.
- Os demais PCs acessarao via IP local, por exemplo `http://192.168.1.50:8000`.
- Apos validacao interna, a mesma base podera ser testada na empresa familiar e evoluir para instalador local.

## Principios

- Operacao diaria acima de complexidade tecnica.
- Nao travar atendente e tecnico em tarefas normais.
- Proteger acoes sensiveis: financeiro, configuracoes, estoque critico e rastreabilidade de equipamento.
- Evitar perda de dados com backup/restore validado.
- Garantir documentos profissionais para cliente, parceiro e auditoria.
- Priorizar telas e fluxos realmente usados antes do go-live local.

## Criterio final da Fase A

A fase sera considerada pronta quando o fluxo abaixo puder ser feito sem erro critico:

```text
Cadastrar cliente
Abrir OS
Registrar diagnostico
Criar orcamento
Aprovar orcamento
Reservar/adicionar peca
Executar servico
Gerar relatorio tecnico
Receber pagamento no caixa
Emitir documentos/PDFs
Fechar OS
Consultar historico do cliente
Fazer backup
Restaurar backup em ambiente temporario
Acessar de outro PC na rede
```

---

## A1 - Estabilizacao Inicial

Status: concluida  
Prioridade: critica

### Objetivo

Garantir que ambiente, banco, empresa ativa, backup e restore estao consistentes antes de entrar com dados reais.

### Escopo

- Rodar `check_go_live`.
- Rodar `check_postgres_ready --check-connection`.
- Rodar `check_tenant_data --strict`.
- Confirmar que novos registros ficam vinculados a empresa ativa.
- Validar backup manual.
- Validar restore em banco temporario.
- Validar restore com `media`.
- Garantir que `.env.postgres.local` permanece fora do Git.
- Verificar se o sistema sobe sem depender de PyCharm.

### Criterios de aceite

- Checks sem erro critico.
- Backup gera `database.dump`, `media.zip` e `manifest.json`.
- Restore testado sem perder OS, clientes, produtos e configuracoes.
- Dashboard mostra corretamente os dados apos restore.

---

## A2 - Cliente e Abertura de OS

Status: concluida tecnicamente  
Prioridade: critica

### Objetivo

Deixar o inicio do atendimento rapido, claro e confiavel.

### Escopo

- Revisar tela `verificar-cliente`.
- Validar busca por CPF, CNPJ e telefone.
- Validar cadastro de cliente novo.
- Garantir selecao intuitiva do cliente.
- Validar CEP e preenchimento automatico.
- Revisar campos obrigatorios de cliente.
- Revisar criacao de OS para fora de garantia, garantia, garantia de servico, parceiro externo e equipamento sem numero de serie.
- Exibir campos de garantia de servico apenas quando aplicavel.
- Proteger numero de serie e dados criticos depois de confirmados.

### Criterios de aceite

- Atendente consegue abrir uma OS simples em menos de 1 minuto.
- Tela nao quebra com formulario aberto.
- Rodape nao sobrepoe conteudo.
- Garantia de servico nao polui a tela quando nao esta selecionada.
- OS criada aparece imediatamente na dashboard/listagens.

---

## A3 - Tela Principal da OS

Status: concluida tecnicamente  
Prioridade: critica

### Objetivo

Transformar a OS na tela operacional central, com proxima acao clara para atendente e tecnico.

### Escopo

- Revisar cabecalho da OS: numero, cliente, equipamento, status, tecnico, prioridade, valor/saldo.
- Revisar abas: detalhes, orcamento, servicos e pecas, linha de trabalho, arquivos, relatorio tecnico, alertas, pedidos/expedicao.
- Reduzir informacoes repetidas.
- Garantir destaque para acoes principais:
  - registrar diagnostico;
  - criar orcamento;
  - adicionar servico/peca;
  - finalizar tecnico;
  - ir para caixa;
  - imprimir documentos.
- Revisar mensagens de bloqueio com motivo e proxima acao.

### Criterios de aceite

- Usuario entende rapidamente o status e a proxima acao.
- Acoes bloqueadas explicam o motivo.
- Abas mantem padrao visual consistente.
- OS com muitos dados continua navegavel.

### Execucao tecnica

- Tela de abertura/OS ja usa fluxo visual por etapas e cards de contexto.
- Campos de garantia de servico ficam ocultos quando o tipo de reparo nao exige esse fluxo.
- Local de armazenamento foi tratado como campo operacional auditado, acessivel a usuarios de operacao.
- Blocos de resumo excessivos foram movidos/compactados em interacoes mais leves.
- Corrigido comparativo de "Garantia de serviço" em Servicos & Pecas para respeitar o valor real com acento.

---

## A4 - Orcamentos

Status: concluida tecnicamente  
Prioridade: alta

### Objetivo

Garantir que orcamento, autorizacao e migracao para servicos/pecas estejam claros e seguros.

### Escopo

- Validar diferenca entre `orcamentado`, `autorizado`, `pendente cliente` e `recusado`.
- Revisar criacao de itens: servico, peca, produto do estoque, desconto e tecnico responsavel.
- Validar aprovacao total e parcial.
- Validar migracao de itens aprovados para servicos/pecas.
- Validar orcamento com item recusado.
- Revisar impacto nas comissoes.
- Revisar PDF do orcamento.

### Criterios de aceite

- Algo pode estar orcado sem estar autorizado.
- Aprovacao parcial funciona sem confundir.
- Itens aprovados migram corretamente.
- PDF do orcamento nao sobrepoe textos.
- Orcamento fica compreensivel para cliente.

### Execucao tecnica

- Fluxo separa `orcamentado` de `autorizado`.
- Aprovacao parcial mantem a OS em orcamento quando ainda existem itens pendentes.
- Itens aprovados podem migrar para Servicos & Pecas sem duplicar itens ja migrados.
- Permissoes granulares protegem desconto, aprovacao, recusa e migracao.
- PDF do orcamento recebeu ajustes de layout e textos padrao revisados.

---

## A5 - Servicos, Pecas e Estoque na OS

Status: concluida tecnicamente  
Prioridade: alta

### Objetivo

Garantir integracao clara entre OS, item executado, reserva e baixa de estoque.

### Escopo

- Validar adicao manual de servico.
- Validar adicao manual de peca.
- Validar item vindo do estoque.
- Validar reserva automatica de peca na OS.
- Validar baixa da reserva ao pagar/finalizar.
- Validar devolucao de estoque ao reabrir/cancelar.
- Revisar mensagens de peca sem saldo.
- Revisar campo de ponto/local de estoque.
- Garantir que usuarios comuns operem sem acessar acoes perigosas.
- Bloquear ajuste manual, transferencia critica, exclusao de produto e alteracao de saldo sem permissao.

### Criterios de aceite

- Tecnico/atendente consegue lancar peca sem entender detalhes internos de estoque.
- Saldo nao fica divergente.
- Reservas vencidas sao visiveis.
- Baixa ocorre no momento correto.
- Acoes de risco exigem permissao.

---

## A6 - Caixa, Pagamentos e Venda a Mostrador

Status: concluida tecnicamente  
Prioridade: critica

### Objetivo

Validar o caixa para operacao real, com seguranca contra erro financeiro e fraude simples.

### Escopo

- Validar abertura de caixa.
- Validar pagamento de OS.
- Validar pagamento parcial.
- Validar desconto com permissao.
- Validar exclusao/estorno de pagamento com justificativa.
- Validar fechamento de caixa por forma de pagamento.
- Validar venda a mostrador:
  - consulta de artigo;
  - cesto;
  - guia;
  - ida ao caixa;
  - pagamento;
  - baixa no estoque.
- Revisar se atendente opera sem ver DRE/faturamento sensivel.
- Revisar tela de registrar pagamento para evitar erro de valor, troco e forma de pagamento.

### Criterios de aceite

- Caixa fecha sem divergencia escondida.
- Pagamento duplicado e impedido.
- Venda a mostrador e clara do inicio ao fim.
- Acoes sensiveis deixam auditoria.
- Atendente opera sem acesso a indicadores financeiros sensiveis.

### Execucao tecnica

- Caixa possui validacao de desconto por permissao granular.
- Exclusao/estorno de pagamento exige justificativa e pode exigir dupla confirmacao configuravel.
- Configuracoes antifraude foram adicionadas para desconto critico e exclusao de pagamento.
- Venda a mostrador e consulta de artigos foram revisadas em fases anteriores.
- Indicadores financeiros sensiveis seguem protegidos por perfil/permissao.

---

## A7 - PDFs e Documentos

Status: concluida tecnicamente  
Prioridade: critica/alta

### Objetivo

Garantir documentos profissionais e sem sobreposicao para cliente, parceiro e auditoria.

### Documentos alvo

- OS impressa normal.
- OS fisica com etiqueta/corte.
- Relatorio tecnico.
- Orcamento.
- Guia de expedicao.
- Talao/recibo.
- Comprovantes financeiros, se usados.

### Escopo

- Testar nomes longos de cliente.
- Testar marca/modelo longos.
- Testar numero de serie longo.
- Testar defeito/peritagem longa.
- Testar termos longos.
- Testar com logo e sem logo.
- Testar assinatura de entrada/saida.
- Testar multiplas paginas.
- Testar etiqueta da OS.
- Revisar margens, cabecalho, rodape e assinaturas.
- Padronizar fonte, cor e hierarquia entre documentos.

### Criterios de aceite

- Nenhum PDF pode sobrepor texto.
- Documentos ficam profissionais para entregar ao cliente.
- Etiqueta da OS imprime legivel.
- Orcamento e relatorio tecnico suportam texto longo.
- Guia de expedicao suporta parceiro/cliente com nomes longos.

---

## A8 - Textos, Acentuacao e Microcopy

Status: concluida tecnicamente  
Prioridade: alta

### Objetivo

Eliminar textos quebrados e padronizar linguagem operacional.

### Escopo

- Varrer templates, forms, models e views principais.
- Corrigir textos visiveis com mojibake.
- Padronizar termos como:
  - orcamento;
  - pecas;
  - tecnico;
  - numero;
  - configuracoes.
- Revisar mensagens de erro.
- Revisar mensagens de sucesso.
- Revisar labels de permissoes.
- Revisar textos dos PDFs.

### Criterios de aceite

- Telas principais sem textos quebrados.
- Mensagens claras para atendente.
- Textos prontos para uso com cliente.

---

## A9 - Permissoes por Perfil

Status: concluida tecnicamente  
Prioridade: alta

### Objetivo

Validar que a equipe opera sem travar, mas sem acesso a dados e acoes sensiveis.

### Perfis alvo

- Administrador.
- Gerente.
- Atendente.
- Tecnico.

### Escopo

- Validar menus visiveis por perfil.
- Validar paginas bloqueadas com 403 amigavel.
- Validar acoes permitidas para atendente:
  - criar OS;
  - editar dados operacionais;
  - vender;
  - receber pagamento;
  - cancelar operacao dentro de regra.
- Validar bloqueios para atendente/tecnico:
  - DRE;
  - faturamento geral;
  - comissoes de outros;
  - excluir pagamento;
  - alterar numero de serie sem permissao;
  - configuracoes;
  - ajuste manual de estoque.
- Revisar tela de criacao/edicao de usuario.

### Criterios de aceite

- Atendente e tecnico nao ficam travados.
- Dados financeiros sensiveis ficam ocultos.
- Acoes perigosas exigem permissao.
- Bloqueio aparece como mensagem amigavel, nao erro tecnico.

---

## A10 - Dashboard, Indicadores e Alertas

Status: concluida tecnicamente  
Prioridade: media/alta

### Objetivo

Garantir que dashboard e alertas ajudem a decidir o que fazer hoje.

### Escopo

- Validar se ordens por status batem com listagens.
- Validar ultimas OS abertas.
- Validar duplo clique nas listas.
- Validar alertas de SLA:
  - OS parada;
  - orcamento sem resposta;
  - peca reservada vencendo;
  - equipamento pronto ha muitos dias;
  - parceiro externo atrasado.
- Revisar excesso de cards e ruido visual.

### Criterios de aceite

- Dashboard bate com dados reais.
- Alertas sao acionaveis.
- Usuario entende rapidamente o que precisa fazer hoje.

### Execucao tecnica

- Dashboard principal passou a exibir o bloco "Prioridades de hoje".
- O bloco usa as regras de SLA configuraveis ja existentes.
- Sao exibidos total, resumo por tipo de pendencia e ate 5 acoes acionaveis.
- Cada pendencia possui botao direto para agir no destino correto.
- A dashboard continua sem expor indicadores financeiros para perfis operacionais.

---

## A11 - Backup, Restore e Setup Local

Status: concluida tecnicamente  
Prioridade: critica

### Objetivo

Permitir uso local com seguranca de dados e restauracao simples em outro PC.

### Escopo

- Melhorar tela de backup.
- Melhorar tela de restore.
- Validar restore com sistema parado.
- Criar opcao no setup inicial:
  - comecar do zero;
  - restaurar backup existente.
- Validar backup vindo de outro PC.
- Validar se apos restore a empresa ativa fica correta.
- Validar se media, logos e anexos voltam corretamente.
- Criar checklist "trocar servidor local".

### Execucao tecnica

- Setup inicial passou a exibir uma opcao clara para restaurar backup antes de configurar do zero.
- Middleware passou a liberar a tela de restore mesmo quando o setup inicial ainda nao foi concluido.
- Restore pela UI passou a exigir confirmacao explicita de risco.
- Restore pela UI passou a oferecer reparo local de empresa unica para dados antigos sem empresa ativa.
- Criado comando `repair_single_tenant_data` para corrigir registros legados sem empresa apos restore.
- `restore_db` passou a aceitar `--repair-single-tenant`.
- Criado checklist `docs/trocar_servidor_local.md`.

### Criterios de aceite

- E possivel restaurar backup sem repetir configuracao inicial.
- Restore nao deixa OS invisivel na dashboard.
- Backup pode ser usado para migrar para outro PC.

---

## A12 - Homologacao em Rede Local

Status: concluida tecnicamente  
Prioridade: alta

### Objetivo

Validar o sistema em cenario real com 2 ou 3 PCs acessando o servidor local pelo navegador.

### Escopo

- Rodar sistema em um PC servidor.
- Acessar por outro PC via IP local.
- Validar login simultaneo.
- Validar abertura de OS simultanea.
- Validar caixa e regras de operador.
- Validar upload de arquivos.
- Validar geracao de PDF.
- Validar performance.
- Validar firewall/porta.
- Validar backup em janela segura.

### Criterios de aceite

- 2 ou 3 PCs conseguem operar sem conflito.
- Sistema nao depende de internet para fluxo interno.
- PDFs e anexos funcionam nos PCs clientes.
- Backup fica no servidor.

### Execucao tecnica

- Criado `docs/homologacao_rede_local.md` com roteiro completo de validacao em 2 ou 3 PCs.
- Criado `test_local_network.ps1` para validar IP, porta e resposta HTTP a partir do servidor ou de um PC cliente.
- Checklist local atualizado com restore antigo usando `--repair-single-tenant`.
- Checklist local atualizado com validacao de rede antes da operacao real.
- `check_go_live` reforcado para validar migrations pendentes, scripts locais, static/media, backup vazio e configuracao de rede local.

---

## Ordem recomendada

1. A1 - Estabilizacao inicial.
2. A2 - Cliente e abertura de OS.
3. A3 - Tela principal da OS.
4. A4 - Orcamentos.
5. A5 - Servicos, pecas e estoque na OS.
6. A6 - Caixa, pagamentos e venda a mostrador.
7. A7 - PDFs e documentos.
8. A8 - Textos, acentuacao e microcopy.
9. A9 - Permissoes por perfil.
10. A11 - Backup, restore e setup local.
11. A10 - Dashboard, indicadores e alertas.
12. A12 - Homologacao em rede local.

## Foco inicial recomendado

Para iniciar a fase sem dispersao, atacar primeiro:

1. A1 - estabilidade de ambiente e dados.
2. A2/A3 - abertura e operacao da OS.
3. A7 - PDFs principais.
4. A6 - caixa e pagamentos.
5. A11 - backup/restore e setup local.

## Registro de progresso

Atualizado em 20/05/2026:

- Plano criado e A1 iniciada.
- A1: `check_postgres_ready --check-connection` validado com sucesso no PostgreSQL local.
- A1: `check_tenant_data --strict` validado com sucesso; modelos criticos sem registros fora da empresa ativa.
- A1: `.env.postgres.local` confirmado como ignorado pelo Git.
- A1: backup manual validado em `backups/fase_a/backup_20260520_125028` com `database.dump`, `media.zip` e `manifest.json`.
- A1: restore validado em banco temporario `assistencia_fase_a_restore_test`, com contagens conferidas de empresa, clientes, OS, orcamentos e produtos.
- A1: banco temporario e pasta temporaria de media removidos apos a validacao.
- A1: `manage.py check` validado sem issues no ambiente atual.
- A1: criado `setup_local_env.ps1` para gerar `.env.local` seguro, ignorado pelo Git, com `DEBUG=0`, `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, PostgreSQL e modo local em rede.
- A1: criado `run_local.ps1` para carregar `.env.local`, executar checks e iniciar o sistema acessivel na rede local.
- A1: `.env.local` gerado para este PC com endereco de acesso local em rede.
- A1: `check_go_live` com `.env.local` validado sem falhas criticas; restou apenas aviso esperado do modo local em rede por usar HTTP interno.
- A1: `check_tenant_data --strict` validado novamente com `.env.local`.
- A1: `run_local.ps1 -CheckOnly` validado com sucesso.
- A1 concluida; A2 iniciada.
- A2: corrigida entrega de `config_sistema` para a tela `verificar-cliente`, mantendo o minimo de busca coerente com configuracao.
- A2: `ClienteForm` passou a validar duplicidade de documento dentro da empresa ativa quando a view informa o tenant.
- A2: mensagens visiveis de validacao da busca/cadastro foram corrigidas para acentuacao adequada.
- A2: testes `ordens.tests.VerificarClienteOSViewTests` executados com sucesso: 11 testes OK.
- A2: testes `ordens.tests.FluxoCriticoE2ETests` executados com sucesso: 5 testes OK.
- A3: detalhe da OS passou a usar queryset filtrado pela empresa ativa e `select_related` nos relacionamentos principais.
- A3: itens de servicos/pecas da OS agora carregam produto, ponto operacional e tecnico responsavel com `select_related` na tela de detalhe.
- A3: testes `DetalhesOrdemCabecalhoTests`, `PermissoesGranularesOSTests` e `FluxoCriticoE2ETests` executados com sucesso: 16 testes OK.


- A4: aba de orcamento da OS passou a exibir status por item (Pendente/Aprovado/Recusado), reduzindo confusao em aprovacao parcial.
- A4: tabela de orcamento passou a usar orcamento_itens ja otimizado no contexto, evitando consultas extras por item/tecnico.
- A4: testes orcamentos e DetalhesOrdemCabecalhoTests executados com sucesso: 37 testes OK.


- A5: revisados fluxos existentes de reserva automatica, renovacao/cancelamento de reserva e baixa/devolucao de estoque vinculada a OS.
- A5: testes `OrdemEstoqueIntegracaoTests` e `IntegracaoServicoPecaEstoqueTests` executados com sucesso: 5 testes OK.
- A6: validado teste pontual de acesso operacional ao registro de pagamento do caixa.
- A6: validados testes criticos de desconto em pagamento e bloqueio por permissao: 2 testes OK.
- A6: tentativa de rodar classes completas de caixa em bloco unico excedeu tempo; validacao foi quebrada em testes pontuais para evitar travamento.
- A7: OS fisica com etiqueta/corte revisada; a area de recorte agora reserva faixa integral em cada via para evitar sobreposicao com tabelas e assinaturas.
- A7: adicionado teste de folga minima entre etiqueta e conteudo das vias na impressao da OS.
- A7: testes `ordens.tests.ImpressaoPdfHeadersTests` executados com sucesso: 10 testes OK.
- A7: testes `ordens.tests.GuiasExpedicaoParceiroTests` e `orcamentos.tests.ImpressaoOrcamentoPdfTests` executados com sucesso: 8 testes OK.
- A8: corrigidos defaults de textos de orçamento/termos da OS em `ConfiguracaoSistema` e criada migration de saneamento para registros existentes.
- A8: revisados textos visiveis em permissoes, configuracoes, detalhes da OS, formulario da OS, orcamentos e modais de servicos/pecas.
- A8: `manage.py check` e `makemigrations --check --dry-run` validados com sucesso.
- A8: testes `VerificarClienteOSViewTests`, `ImpressaoPdfHeadersTests` e `ImpressaoOrcamentoPdfTests` executados com sucesso: 26 testes OK.
- A9: local de armazenamento da OS liberado para perfil operacional de OS, mantendo registro em linha de trabalho/log para rastreabilidade.
- A9: mensagens e labels de permissoes sensiveis revisados para linguagem clara e acentuada.
- A9: testes `PermissoesGranularesOSTests` executados com sucesso: 5 testes OK.
- A9: testes de permissoes em configuracoes/estoque executados com sucesso: 49 testes OK.
- Validacao final 2026-05-21: `manage.py migrate` aplicado com sucesso, incluindo `configuracoes.0059_corrigir_textos_padrao_os_orcamento`.
- Validacao final 2026-05-21: `manage.py check` executado sem issues.
- Validacao final 2026-05-21: `manage.py check_tenant_data --strict` executado sem pendencias; clientes, OS, orcamentos, produtos e contas estao associados a empresa.
- Validacao final 2026-05-21: `run_local.ps1 -CheckOnly` validado com `.env.local`; apenas aviso esperado de modo local em rede via HTTP interno.
- Validacao final 2026-05-21: suite principal `configuracoes core ordens orcamentos caixa estoque --keepdb` executada com 509 testes OK.
- Smoke operacional 2026-05-21: 32 rotas principais verificadas via Django Client autenticado como administrador, incluindo dashboard, OS, estoque, caixa, configuracoes, SLA e PDFs.
- Smoke operacional 2026-05-21: PDFs de OS normal, OS fisica/etiqueta e relatorio tecnico responderam `application/pdf` com status 200.
- Smoke operacional 2026-05-21: `caixa:registrar_pagamento` redirecionou para `/caixa/abrir/` quando nao havia caixa aberto; comportamento esperado confirmado com tela de abertura respondendo status 200.
