# Plano de evolução gradual do ABGest

Data: 16/09/2026
Estado: entregas 1 a 5 implementadas localmente e em homologação; publicação e instalação na loja ainda não realizadas. A nuvem tem adaptador de pasta sincronizada, sem upload remoto confirmado.
Referência de código analisada: `c43b76c`. Esta referência não confirma a versão instalada no PC da loja.

## 1. Objetivo e decisões acordadas

Evoluir o sistema estável em versões pequenas, testáveis e instaláveis separadamente, preservando o banco real da loja e permitindo interromper a evolução entre entregas sem prejudicar a operação existente.

Decisões:

- WhatsApp continua manual. Facilitar o PDF e a mensagem; API paga fica para futuro próximo.
- Data da compra e número da nota entram no bloco existente de dados do equipamento da OS.
- O balão do cliente apresenta dados completos de forma organizada; a ficha ampla continua disponível.
- O histórico de gastos do cliente é mantido e ampliado, não removido.
- Backup automático inclui banco e anexos, com cópia em nuvem e acompanhamento.
- As ideias de pendências, histórico do equipamento, checklist de entrega, rentabilidade, previsão financeira, reposição e padronização visual entram na evolução.
- IA é uma fase posterior, inicialmente apenas consulta e rascunhos.
- Não reescrever o programa nem substituir todos os fluxos de uma só vez.

## 2. Diagnóstico inicial e limites da análise

Constatações do código:

- A tesouraria limita listas recentes, incluindo movimentos e linhas de extrato a 100 registos, sem filtros GET por período nessa tela.
- O dashboard operacional ainda contém entradas e saídas. O resumo considera caixas do período e pode não representar movimentos financeiros sem vínculo a esses caixas.
- Os campos `data_compra` e `numero_nota_fiscal` existem na OS, mas não constam do painel de detalhes do equipamento analisado.
- O balão do cliente contém um resumo e ligação à ficha ampla, com restrição visual por perfil. A autorização da ficha usa uma regra de acesso mais ampla.
- O histórico financeiro do cliente procura pagamentos diretamente vinculados às OS. É necessário integrar checkout agrupado e vendas identificadas, sem duplicidade.
- A geração do link do WhatsApp marca a notificação como enviada, embora não confirme o envio efetivo.
- O backup existente pode incluir banco, anexos e manifesto, com retenção. Há procedimento externo de agendamento, mas falta gestão integrada de execução e nuvem.
- Existem sugestões de peças por compatibilidade cadastrada e histórico; não foi identificada integração de IA generativa nas áreas inspecionadas.

Verificações iniciais executadas: `check` sem problemas; `makemigrations --check --dry-run` sem alterações detetadas. Não equivalem a teste completo, confirmação de migrations aplicadas, auditoria de segurança ou homologação no PC definitivo.

## 3. Regras obrigatórias para atualizações graduais

### Banco e instalação da loja

1. Atualizar código e aplicar migrations no banco existente da loja. Nunca restaurar o banco de desenvolvimento sobre o banco definitivo como passo normal de atualização.
2. Fazer backup completo antes de cada atualização, mesmo antes de existir backup automático.
3. Preservar anexos, configurações locais, chaves, certificados, utilizadores, saldos e históricos.
4. Não alterar valores históricos ou completar vínculos antigos por suposição.
5. Correções de dados, quando necessárias, têm prévia, justificativa, auditoria e execução explícita; não acontecem silenciosamente ao abrir uma tela ou instalar uma versão.
6. Identificar ambiente, banco e versão antes de qualquer operação administrativa. Testes de pagamentos e estoque com criação de movimentos acontecem em homologação, não no banco real.

### Compatibilidade e lançamento

- Uma entrega por vez, com commit identificado e notas próprias. Publicar apenas versões homologadas.
- Cada entrega pode ficar instalada sem exigir a entrega seguinte. Funcionalidades posteriores não devem aparecer quebradas ou sem configuração.
- Preferir campos novos opcionais e estruturas adicionais. Separar adição, preenchimento de dados e remoção de estruturas em versões diferentes.
- Testar compatibilidade da versão anterior com o esquema novo antes de declarar possível voltar apenas o código. Migration aditiva, por si só, não garante rollback seguro.
- Evitar renomear/remover campos ou alterar contratos em uso nas primeiras entregas.
- Backfills volumosos usam comando específico, execução em lotes, simulação, repetição segura e relatório; não bloqueiam toda a instalação.
- Funcionalidades com risco de escrita ou integração externa começam desativadas e são habilitadas por empresa/instalação após configuração e testes.
- Desativar uma funcionalidade deve preservar os registos já criados; o comportamento do fluxo antigo com esses registos precisa ser testado.
- Agendamentos, envios e importações devem ser idempotentes: repetição não gera operações duplicadas.
- Permissões novas precisam de política explícita de adoção, sem conceder acessos sensíveis indiscriminadamente nem bloquear inesperadamente a equipa.
- Usar janela de manutenção para atualização no servidor Windows. Não prometer atualização sem interrupção nesta fase.

## 4. Entregas e dependências

| Entrega | Conteúdo | Dependência | Risco relativo | Estado |
|---|---|---|---|---|
| E0 | Base de homologação e atualização controlada | Nenhuma | Baixo, sem correção financeira | Implementada; homologação local, Windows de produção pendente |
| E1 | Filtros de bancos/conciliação | E0 | Baixo; leitura | Implementada e testada localmente |
| E2 | Compra/nota no equipamento e ficha no balão | E0 | Médio; dados pessoais/permissões | Implementada e testada localmente |
| E3 | Dashboard e histórico financeiro consistente | E0; E1/E2 recomendadas | Médio/alto; interpretação financeira | Implementada e testada localmente; limites históricos documentados |
| E4A | Backup automático local e recuperação | E0 | Médio; proteção de dados | Implementada; recuperação isolada testada, tarefa Windows não instalada |
| E4B | Cópia criptografada em nuvem | E4A | Médio; integração externa | Adaptador de pasta implementado; destino, chave e recuperação remota pendentes |
| E5 | WhatsApp manual com PDF facilitado | E0 | Baixo/médio; privacidade e mensagens | Planeada |
| E6A–E6C | Pendências, equipamento e entrega | E0; E2/E3 quando aplicável | Médio; fluxo operacional | Em homologação local; bloqueio legado/PDF ainda pendentes |
| E7A–E7C | Rentabilidade, previsão e reposição | E3; E6 quando aplicável | Médio; cálculos e sugestões | Em homologação local; rateio agrupado/cartão futuro/compatibilidade ainda pendentes |
| E8 | Base técnica e piloto de IA | E2/E3; E4B recomendada; segurança validada | Alto; dados e sugestões técnicas | Planeada |

Ordem sugerida: E0 → E1 → E2 → E3 → E4A → E4B → E5 → E6 → E7 → E8. A proteção de backup pode avançar antes de E3 se o diagnóstico mostrar urgência. E4B, E6, E7 e E8 não impedem a instalação das entregas anteriores.

### E0 — Base para libertar versões com segurança

Escopo:

- Consolidar este plano como referência das próximas entregas, sem apagar os planos e evidências anteriores.
- Criar uma bateria de regressão do percurso cliente → OS → orçamento → execução → recebimento → banco, usando PostgreSQL isolado.
- Cobrir dinheiro com troco/desconto, cartão, pagamentos mistos, checkout agrupado, estornos parciais, garantia mista cliente/fabricante, XML e estoque.
- Acrescentar identificação discreta da versão e do ambiente para suporte.
- Validar o procedimento de atualização existente e propor um único fluxo que confira backup, versão anterior, migrations, dependências, estáticos, serviços e saúde após reinício.
- Na referência inicial, `ATUALIZAR-APOS-GIT-PULL-COMO-ADMIN.cmd` não produzia backup prévio. A implementação local agora chama o atualizador com backup antes das migrations; manter uma cópia manual anterior à troca do código e ensaiar o fluxo no Windows definitivo.
- Registar versão, banco, esquema e chaves necessários à recuperação, sem guardar segredos no Git ou nos relatórios.
- Priorizar, antes de integrações externas, a revisão de acesso aos anexos, autorização nas rotas e isolamento entre empresas. Corrigir achados confirmados em entregas próprias, sem afirmar que o servidor real foi auditado apenas pelo código local.

Aceitação:

- [ ] Ambiente de teste separado do banco real e claramente identificado.
- [ ] Regressões críticas executadas e resultados registados.
- [ ] Recuperação testada num banco separado, incluindo anexos.
- [ ] Procedimento de atualização e retorno documentado e verificável.
- [ ] Nenhuma ferramenta de teste restaura ou altera produção inadvertidamente.

### E1 — Bancos e conciliação com filtros

Escopo:

- Barra de filtros por conta, data inicial/final do movimento, situação, entrada/saída, natureza e texto.
- Atalhos de período: hoje, últimos 7 dias, mês atual e mês anterior.
- Identificar separadamente a data da importação e permitir filtrar por lote.
- Paginar os resultados; filtrar antes de paginar e calcular totais sobre todo o conjunto filtrado.
- Distinguir saldo atual da conta, saldo no fim do período e totais de movimentos filtrados.
- Preservar filtros e página ao abrir/conciliar/cancelar e regressar à lista.
- Confirmar exclusão de movimentos já conciliados das opções de vínculo, mantendo consulta ao histórico.

Aceitação:

- [ ] Movimento antigo pode ser localizado mesmo fora dos primeiros 100 registos.
- [ ] Datas inválidas e intervalo invertido produzem mensagem, não erro 500.
- [ ] Totais não mudam ao trocar de página.
- [ ] Data retroativa considera a data económica do movimento, não a data do upload.
- [ ] Empresa, conta e permissões são respeitadas em listas e ações.
- [ ] Não há alteração automática de saldos ou conciliações existentes.

### E2 — Equipamento e ficha do cliente

Escopo:

- Exibir data da compra e número da nota dentro do bloco existente do equipamento; usar “Não informado” quando vazios.
- Ampliar o balão com abas compactas de Dados, Histórico e Financeiro. Não carregar o histórico inteiro de uma só vez.
- Dados disponíveis incluem contactos e cadastro; conteúdo sensível depende da permissão.
- Manter botão para a página ampla e permitir abrir OS/vendas do histórico sem perder o contexto original.
- Implementar permissões separadas para dados pessoais completos, histórico operacional, histórico financeiro e edição.
- Aplicar regras no servidor, no balão, na página ampla e nas consultas associadas. Ocultar o botão não basta.
- Mostrar apenas indicadores financeiros já validados; ligar os novos indicadores após E3.

Aceitação:

- [ ] Informação de compra aparece em OS antigas e novas, sem exigir preenchimento retroativo.
- [ ] Balão e página ampla mostram o mesmo cadastro autorizado.
- [ ] Acesso direto à página/API não contorna permissões.
- [ ] Utilizador sem acesso financeiro mantém o acesso operacional autorizado.
- [ ] Nenhum dado de outra empresa é exibido.

### E3 — Consistência financeira e histórico de gastos

Escopo:

- Centralizar serviços de apuramento para reutilização em dashboard, cliente, OS e relatórios, evitando fórmulas paralelas.
- Separar no dashboard caixa de balcão, financeiro geral e resultados; identificar período e âmbito de cada indicador.
- Criar lista cronológica de entradas e saídas com origem, descrição, forma, conta, data e estado.
- Manter o histórico do cliente e incluir OS, guias, acessórios e checkout agrupado com identificação segura do cliente.
- Acrescentar, se necessário, vínculo estruturado do cliente nas vendas, preservando snapshots de recibos já emitidos.
- Representar pagamentos agrupados por distribuição entre origens; exibir o pagamento uma vez e detalhar sua composição.
- Separar total pago, saldo pendente, descontos, devoluções e cobrança à fabricante. Não tratar o valor integral da OS como dívida do cliente numa garantia mista.
- Usar as regras atuais de estorno e alocação, incluindo estornos parciais, em vez de somar pagamentos brutos isoladamente.
- Disponibilizar filtro por período e lista auditável que explique os totais.
- Mostrar registos antigos sem vínculo seguro numa revisão assistida; não associar automaticamente apenas por nome.

Casos obrigatórios:

| Caso | Resultado esperado |
|---|---|
| Cliente paga R$ 460; taxa R$ 18; banco recebe R$ 442 | Histórico do cliente: R$ 460; taxa da empresa: R$ 18; líquido bancário: R$ 442 |
| Cliente deve R$ 100 e fabricante R$ 18 na mesma OS | R$ 100 são atribuídos ao cliente; R$ 18 à fabricante |
| Duas OS e um acessório pagos juntos | Um recebimento, alocado às três origens, sem repetir o total |
| Desconto de R$ 40 num valor de R$ 500, pagamento R$ 460 | Pago: R$ 460; desconto: R$ 40; pendente: zero |
| Devolução parcial de R$ 20 num pagamento de R$ 100 | Total líquido pago pelo cliente: R$ 80; histórico mantém os eventos |
| Transferência SumUp → Nubank | Movimentação entre contas; não aumenta vendas nem gasto do cliente |
| Lançamento retroativo sem caixa do dia | Aparece no período financeiro correto, sem alterar o caixa atual indevidamente |

Aceitação:

- [ ] Os casos acima passam em testes automatizados.
- [ ] Totais da ficha e dos relatórios coincidem para o mesmo âmbito e período.
- [ ] Receita por competência e recebimentos por data não são apresentados como a mesma medida.
- [ ] Valores de cliente/fabricante e pagamentos agrupados não se duplicam.
- [ ] Mudança de cálculo é explicada nas notas: não significa reescrita dos movimentos históricos.
- [ ] Não há saneamento monetário automático em migrations ou acessos GET.

### E4A — Backup automático local

Escopo:

- Reutilizar o mecanismo existente de dump do PostgreSQL e inclusão dos anexos.
- Configurar horário e retenção; executar no servidor mesmo sem navegador aberto, com mecanismo adequado ao Windows.
- Evitar duas execuções simultâneas e executar uma tarefa pendente após indisponibilidade quando aplicável.
- Gerar em área temporária; publicar o pacote apenas depois de concluído e validado.
- Acrescentar manifesto com versão de código/esquema, data, conteúdo e verificações de integridade.
- Definir tratamento de anexos criados durante a cópia, para não declarar completo um pacote inconsistente.
- Mostrar última execução, tamanho, duração, falha e data do último teste de recuperação.
- Alertar sobre falha, falta de espaço e ausência prolongada de backup.

Aceitação:

- [ ] Banco e anexos são recuperados em ambiente separado.
- [ ] Falha no dump/cópia não aparece como sucesso nem apaga a última cópia válida.
- [ ] Retenção remove apenas backups identificados no destino configurado.
- [ ] Agendamento funciona sem sessão aberta no programa e após reinício do servidor.
- [ ] Configuração e chaves necessárias à recuperação têm procedimento de guarda separado.

### E4B — Backup criptografado em nuvem

Decisão antes da ativação externa: escolher a nuvem, conta responsável, capacidade, autenticação e política de retenção. O adaptador inicial de pasta sincronizada já foi implementado localmente; não houve envio externo. Não exige API de WhatsApp nem contratação de IA.

Escopo:

- Criar adaptador para envio de pacotes a um primeiro fornecedor; não implementar várias nuvens simultaneamente.
- Preferir upload direto com confirmação verificável de objeto, tamanho/integridade e execução registada.
- Pasta sincronizada é alternativa inicial, mas só pode indicar “Copiado para sincronização” até existir prova de upload. Não declarar “Backup na nuvem concluído” por cópia local.
- Criptografar antes do envio; chave de recuperação protegida e guardada também fora do PC. Não usar segredos em logs ou Git.
- Manter backup local fora da pasta sincronizada e aplicar retenções local/remota independentes.
- Prever repetição segura, falha de internet, credenciais expiradas, falta de espaço/quota e upload incompleto.
- Cópias diárias/semanais/mensais conforme espaço e necessidade; aprovar a política antes da ativação.
- Não sincronizar diretórios ativos do PostgreSQL nem criar dois bancos graváveis independentes.

Aceitação:

- [ ] Recuperar um pacote exclusivamente da nuvem e abrir anexos após restauração isolada.
- [ ] Recuperação funciona com a chave guardada fora do servidor.
- [ ] Upload incompleto ou indisponível não é marcado como sucesso.
- [ ] Apagar uma cópia local não elimina silenciosamente todas as cópias remotas.
- [ ] Credenciais, conteúdo e destino são acessíveis apenas a administradores autorizados.

### E5 — Orçamento por WhatsApp sem API

Escopo:

- Ação clara “Preparar orçamento para WhatsApp”: gerar/baixar PDF e abrir mensagem preenchida.
- Exibir instrução breve para anexar manualmente o PDF no WhatsApp.
- Preservar versão do orçamento preparado e identificar o ficheiro; confirmar permissões e conteúdo externo, sem custos internos.
- Separar estados preparado/aberto para envio e confirmação manual. Não afirmar entrega ao destinatário.
- Não usar automação de cliques, sessão não oficial ou promessa de anexo automático pelo link `wa.me`.
- Não enviar ligações locais inacessíveis ao cliente como se fossem públicas.

Aceitação:

- [ ] PDF preparado corresponde ao orçamento selecionado, com descontos e totais corretos.
- [ ] Abrir WhatsApp ou cancelar a ação não marca entrega confirmada.
- [ ] Fluxo antigo de impressão/download continua disponível.

### E6 — Operação diária, em três versões independentes

E6A — Central de pendências:

- OS paradas, orçamento sem resposta, equipamento pronto, compra aberta e cobrança de fabricante vencida.
- Cada alerta tem origem, motivo, responsável e acesso à ação relevante.
- Regras de prazo configuráveis por empresa; nenhuma OS/pedido é fechado automaticamente apenas pelo alerta.
- Aceitação: pendências reais rastreáveis, sem valores duplicados ou alertas que persistem após resolução.

E6B — Histórico por equipamento:

- Identificar equipamento por atributos normalizados e identificador interno; série ausente/repetida não permite fusão automática.
- Associar histórico anterior com revisão assistida quando necessário; suportar mudança de proprietário sem expor dados pessoais indevidos.
- Aceitação: localizar reparos anteriores e retornos sem alterar OS antigas nem revelar dados de outro cliente sem autorização.

E6C — Checklist de entrega:

- Checklist por empresa/tipo de equipamento, acessórios, testes finais e fotos.
- Separar obrigatoriedade configurável de sugestões. Não bloquear entregas anteriores por novos campos vazios.
- Aceitação: balcão executa conferência rápida; entrega e PDF respeitam a configuração e o fluxo atual continua utilizável.

### E7 — Gestão, em três versões independentes

E7A — Rentabilidade:

- Apurar OS/modelo/tipo de serviço com custos, insumos, comissões, taxas e retrabalho.
- Distinguir custo previsto, efetivo e desconhecido; custo em falta não pode aparecer como margem de 100% confirmada.
- Aceitação: cálculo explicável por origem e coerente com E3; custos internos continuam privados.

E7B — Previsão financeira:

- Calendário de recebimentos de cartão/fabricantes e obrigações, distinguindo previsto, confirmado e vencido.
- Comparar taxa prevista/real e valor bruto/líquido sem gerar recebimento adicional ao importar extrato.
- Aceitação: projeção nunca é somada como saldo bancário disponível ou venda nova.

E7C — Reposição assistida:

- Considerar estoque físico, reservas, pedidos pendentes, consumo e prazo de reposição.
- Sugerir compras e substituições apenas com compatibilidade cadastrada e confirmação humana.
- Aceitação: pedido existente reduz necessidade sugerida; estoque negativo/inconsistente gera aviso, não compras automáticas.

### E8 — Conhecimento técnico e IA

Primeiro, sem IA:

- Estruturar sintoma, testes/medições, causa confirmada, solução, peça, resultado e retorno.
- Criar catálogo validado de compatibilidades e documentos técnicos autorizados.
- Pesquisar casos anteriores e marcar conhecimento como validado, pendente ou rejeitado.

Depois, piloto opcional:

- Assistente na OS com leitura de dados permitidos, casos semelhantes, referências e rascunho de relatório.
- Consultar estoque real e motor determinístico de preço/custos/impostos; não inventar disponibilidade, tributação ou compatibilidade.
- Hipóteses técnicas claramente identificadas e confirmação pelo técnico, sobretudo em testes com risco elétrico.
- Segregação por empresa e perfil; dados pessoais mínimos; chaves apenas no servidor; limites de custo/utilização.
- Tratar instruções em anexos como conteúdo não confiável, não como autorização para agir.
- Sem alteração autónoma de estoque, orçamento, pagamentos, fechamento de OS ou envio de mensagens.
- Medir utilidade e erros num conjunto de reparos representativos aprovado; acesso gradual e opção de desativar.

Aceitação:

- [ ] Respostas apresentam fontes e distinguem hipótese de causa confirmada.
- [ ] Compatibilidade e valores são verificáveis no sistema.
- [ ] Não existe acesso a dados de outra empresa/utilizador sem permissão.
- [ ] Indisponibilidade da IA não bloqueia operação normal.
- [ ] Piloto tem critérios de qualidade, orçamento e revisão humana antes da expansão.

## 5. Padrão visual transversal

Aplicar progressivamente nas telas modificadas, sem remodelar todo o programa de uma só vez:

- Cabeçalho e ações consistentes; filtros compactos e sempre no mesmo local.
- Valores, datas, origem e estado legíveis; cores com significado estável.
- Estados vazios, carregamento, validação e falha com mensagem útil e referência de suporte.
- Atalhos testados, com alternativa por botão e sem depender exclusivamente de teclas capturadas pelo navegador.
- Preservar contexto ao sair de uma lista; reduzir rolagem em operações de balcão.
- Testar teclado, contraste, zoom, telas menores e tamanho de janela usado na loja.

## 6. Portão de aprovação de cada versão

Antes de publicar:

- [ ] Escopo pequeno, dependências e funcionalidades fora do escopo identificados.
- [ ] Revisão do diff sem segredos, backups, dados pessoais ou alterações locais indevidas.
- [ ] Testes da entrega, regressão financeira/estoque e autorização por empresa/perfil executados.
- [ ] Verificação do projeto, ausência de migrations esquecidas e plano de migrations revistos.
- [ ] Instalação ensaiada sobre cópia representativa da base antiga; não apenas sobre banco vazio.
- [ ] Validação visual das telas e PDFs afetados; nenhum teste destrutivo no banco da loja.
- [ ] Retorno/recuperação ensaiados e limitação após novos registos documentada.
- [ ] Notas de versão com alterações práticas, configuração necessária, riscos e roteiro de teste.
- [ ] Commit/tag identificado e publicação confirmada no repositório remoto.

Antes de instalar na loja:

- [ ] Confirmar origem da versão, instalação alvo, versão anterior e espaço disponível.
- [ ] Pausar o uso da equipa e tarefas agendadas que possam escrever durante a manutenção.
- [ ] Fazer backup completo e preservar configurações/chaves em local protegido.
- [ ] Aplicar apenas o pacote homologado e as suas migrations pelo fluxo oficial.
- [ ] Verificar migrations aplicadas, serviços, versão exibida, login, empresa, OS antiga, anexos, PDFs e indicadores.
- [ ] Conferir valores conhecidos sem criar movimentos fictícios em produção.
- [ ] Habilitar funcionalidades opcionais apenas após configuração e teste adequado.
- [ ] Registar horário, resultado e responsável pela atualização; só então libertar o uso.

“Pode atualizar” significa que este portão foi cumprido para uma versão específica. A existência de commit ou push não é, por si só, garantia de segurança.

## 7. Retorno e recuperação sem perder trabalho novo

1. Se houver falha, suspender a funcionalidade afetada e avaliar se a operação restante pode continuar com segurança.
2. Guardar evidências e uma cópia atual do banco/anexos antes de qualquer recuperação.
3. Priorizar correção compatível para a frente ou retorno apenas do código quando essa compatibilidade tiver sido comprovada.
4. Não reverter migrations com dados reais por tentativa e erro.
5. Restaurar backup anterior apenas como recuperação coordenada. Se houve novas OS, vendas ou pagamentos depois do backup, a restauração perde esses registos; exige avaliação, autorização e plano para preservar/reconciliar o trabalho novo.
6. Nunca usar backup do desenvolvimento para resolver atualização do PC definitivo.

## 8. Decisões externas e itens adiados

Necessário decidir antes da entrega correspondente:

- E2: acesso padrão de cada perfil a dados pessoais e financeiros.
- E4A/E4B: horário, retenção, fornecedor de nuvem, conta, capacidade e responsável pela chave de recuperação.
- E6: prazos de pendência e itens obrigatórios do checklist por empresa.
- E8: autorização para uso de IA, documentos permitidos, orçamento e conjunto de avaliação.

Estas decisões não bloqueiam E0/E1 nem precisam ser tomadas todas de uma vez.

Fora das primeiras entregas: WhatsApp por API, emissão fiscal automática, sincronização bidirecional de bancos, migração integral para nuvem, comercialização SaaS sem auditoria de isolamento e ações autónomas de IA. Emissão fiscal permanece no fluxo manual acordado.

## 9. Acompanhamento

Para cada entrega, registar: estado (planeada/em desenvolvimento/em homologação/publicada/instalada), commit/tag, migrations, testes, configuração, pendências e evidência da instalação. Não marcar concluída apenas porque o código foi escrito.

Referências operacionais existentes: `backup_restore_local.md`, `ownership_modulos.md`, `permissoes_por_perfil.md`, `manual_financeiro_compras_bancos_v1_1.md` e os planos específicos de caixa/estoque/configurações. Documentos antigos que descrevem instalação inicial ou restauração não substituem as regras de atualização incremental deste plano.

## 10. Execução das entregas 1 a 5 — versão local 1.2.0

A numeração solicitada pelo utilizador corresponde a E0, E1, E2, E3 e E4A/E4B. WhatsApp/PDF é a entrega seguinte e não foi incluído nesta implementação.

Implementado:

- Identificação do ambiente no rodapé; script de regressão e atualização com backup anterior às migrations, pausa do serviço e verificações do projeto. Não equivale a deploy Windows homologado ou rollback certificado.
- Filtros bancários por conta, datas, período, estado, entrada/saída, descrição, origem, natureza, lote e data de importação; paginação e totais sobre o conjunto filtrado. Natureza usa fontes conhecidas; movimentos antigos e linhas sem vínculo seguro ficam não classificados. Contrapartidas herdam a natureza da fonte. Histórico de conciliações com pelo menos uma linha do período, mantendo os totais da conciliação inteira explicitamente identificados.
- Data de compra e nota fiscal na OS; balão com Dados/Histórico/Financeiro e ligação à ficha ampla. Permissões independentes no servidor para dados, histórico, financeiro e edição. A migration preserva acessos dos perfis anteriores; novos utilizadores restritos precisam de configuração explícita.
- Entradas/saídas por data do movimento, separadas do caixa físico; histórico do cliente com checkout agrupado, vendas identificadas, dívida oficial e devoluções parciais na data do evento. Revisão auditada de cliente em recebimentos antigos sem alterar valores ou snapshots dos recibos.
- Backup completo atómico, manifesto e hashes, exclusão mútua, política desativada por padrão, acompanhamento, agendamento Windows fornecido e cópia AES-GCM para pasta sincronizada. Falha de nuvem preserva a cópia local e permite repetição sem novo backup diário.

Migrations adicionadas: caixa `0064`, configuracoes `0098`, `0099`, `0100`. Aplicadas apenas ao banco local de desenvolvimento nesta execução. Nenhuma migration de saneamento monetário ou associação de vendas por nome.

Evidências locais:

- Backup anterior à alteração do esquema: `backups/pre_evolucao_20260916/backup_20260916_204635.zip`.
- Backup posterior: `backups/validacao_evolucao_20260916/backup_20260916_210952.zip`.
- Recuperação efetiva desse pacote num PostgreSQL temporário: 157 tabelas, 324 migrations registadas e 78 ficheiros de anexos. Banco temporário e pasta de validação removidos; banco ativo não restaurado. Isto não verifica todas as referências a anexos nem certifica recuperação do servidor definitivo.
- Regressão de autorização/tesouraria/multiempresa: 291 testes aprovados. Bateria específica: 108 testes aprovados. Revisão adicional de 17/09, incluindo natureza bancária: 22 testes aprovados. As baterias têm sobreposição; não somar como casos distintos.
- Telas de filtros, ficha/balão do cliente, dashboard e configuração de backup verificadas no navegador local. Em 17/09, o filtro “Não classificado” foi aplicado pela tela, com 41 linhas de extrato e sem erro. Não há alteração dos PDFs nesta entrega.
- `check` sem problemas; `makemigrations --check --dry-run` sem alterações; quatro migrations adicionais confirmadas aplicadas localmente; quatro scripts PowerShell com sintaxe validada. Atualização do serviço Windows e recuperação remota ainda não executadas.

Pendências reais para ativação/publicação:

1. Commit e publicação com referência identificada; revisão final e aprovação do pacote.
2. Ensaio da atualização e saúde do serviço no Windows da loja; confirmar login, anexos, PDFs e valores conhecidos após reinício. Voltar apenas o código não foi certificado.
3. Escolher nuvem, pasta, retenções, horário, responsável e chave guardada fora do servidor. Instalar a tarefa no servidor; testar após reinício e verificar upload e recuperação exclusiva da nuvem.
4. A sincronização pode depender de sessão Windows aberta no cliente de nuvem. “Copiado; upload não confirmado” não significa proteção remota comprovada.
5. Histórico do cliente usa pagamentos remanescentes e devoluções parciais. Cancelamentos completos antigos que removeram o pagamento não são reconstruídos na ficha. O livro financeiro preserva as contrapartidas disponíveis, mas este plano não recupera dados que já tenham sido apagados.
6. Backups devem correr numa janela sem escrita. A verificação de alterações nos anexos reduz risco, mas não torna banco e ficheiros uma transação única.
7. A auditoria completa de segurança, desempenho e isolamento para comercialização multiempresa continua necessária. A lista financeira já apresenta natureza, forma, conta e estado quando disponíveis. A ausência de classificação em fontes antigas é explicitamente preservada, não preenchida por suposição.

Guia de utilização, configuração e atualização: `entrega_evolucao_1_a_5_2026-09-16.md`. Não restaurar estes backups de desenvolvimento no PC definitivo.
