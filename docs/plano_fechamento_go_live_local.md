# Plano de Fechamento para Go-Live Local

## Objetivo

Fechar a etapa final antes do uso real do sistema em ambiente local, com PostgreSQL, backup confiavel, operacao em rede interna e fluxos principais validados.

Este plano e mais curto e pratico do que os roadmaps anteriores.
O foco agora nao e criar novos modulos.
O foco e:

- eliminar os ultimos bloqueios operacionais;
- validar o fluxo real da loja;
- consolidar o modo correto de uso local;
- reduzir risco de perda de dados ou uso no banco errado.

## Escopo desta etapa

Esta etapa cobre:

1. fechamento do lote final de bugs operacionais;
2. validacao manual do fluxo principal;
3. backup e restore finais;
4. consolidacao do modo local oficial;
5. homologacao em rede local;
6. criterios objetivos de liberacao para comecar a usar.

Nao faz parte desta etapa:

- novas funcionalidades grandes;
- expansao SaaS;
- redesenho de arquitetura;
- integracoes novas complexas.

---

## Fase G1 - Fechamento do lote final de bugs

Status: concluida tecnicamente em 2026-06-22  
Prioridade: critica

### Objetivo

Encerrar os ajustes operacionais que ainda podem atrapalhar o uso real.

### Escopo

- impedir buscas indevidas ou rotas ambiguas em clientes;
- concluir o fluxo de `tipo de equipamento = Outros`;
- estabilizar tecnico responsavel com feedback visual e historico;
- garantir aprovacao parcial de orcamento com reflexo operacional correto;
- revisar exibicao de `Tipo da OS`;
- revisar fechamento de OS com saldo pendente;
- revisar indicadores/alertas derivados desse fechamento;
- revisar PDF de orcamento com textos longos.

### Entregas

- codigo consolidado e sem ajustes “meio prontos” no working tree;
- testes automatizados direcionados cobrindo os pontos criticos;
- checklist de validacao manual desse bloco.

### Criterios de aceite

- nenhum desses fluxos apresenta erro funcional;
- mensagens ficam coerentes para atendente/tecnico;
- os testes direcionados passam no PostgreSQL local.

### Progresso executado

- rota textual invalida de clientes protegida contra listagem ampla;
- `tipo de equipamento = Outros` com digitacao manual validado em teste;
- atribuicao de tecnico por AJAX consolidada com retorno de historico e feedback;
- aprovacao parcial de orcamento passou a registrar linha operacional;
- `Tipo da OS` passou a aparecer onde faltava;
- fechamento de OS com saldo pendente passou a exigir confirmacao e gerar acompanhamento;
- indicadores de OS fechada com saldo pendente adicionados;
- `manage.py check` validado em PostgreSQL local;
- regressao direcionada do bloco executada com sucesso;
- bateria complementar de 26 testes passou com sucesso em PostgreSQL local.

---

## Fase G2 - Homologacao manual do fluxo principal

Status: pendente  
Prioridade: critica

### Objetivo

Validar o sistema no uso real da operacao, fim a fim.

### Escopo

Executar manualmente:

1. cadastro de cliente;
2. abertura de OS;
3. diagnostico;
4. orcamento;
5. aprovacao total;
6. aprovacao parcial;
7. migracao de itens;
8. servicos e pecas;
9. relatorio tecnico;
10. pagamento no caixa;
11. fechamento da OS;
12. consulta do historico do cliente;
13. emissao de PDFs principais.

### Entregas

- rodada de homologacao registrada;
- lista curta de falhas reais encontradas;
- correcao apenas do que bloquear a operacao.

### Criterios de aceite

- o fluxo principal roda sem erro critico;
- nenhuma etapa exige gambiarra operacional;
- os dados ficam consistentes entre OS, caixa e historico.

### Referencia

- `docs/checklist_homologacao_manual.md`

---

## Fase G3 - Backup, restore e seguranca de dados

Status: concluida tecnicamente em 2026-06-22  
Prioridade: critica

### Objetivo

Confirmar que os dados podem ser protegidos e recuperados com seguranca antes do uso real.

### Escopo

- gerar backup completo do banco;
- gerar backup de `media`;
- validar restore em base temporaria;
- validar restore com logos, anexos e assinaturas;
- confirmar visibilidade correta de clientes, OS, produtos e configuracoes apos restore;
- revisar documentacao de troca de servidor local.

### Entregas

- evidencia de backup valido;
- evidencia de restore valido;
- instrucoes finais ajustadas se necessario.

### Criterios de aceite

- backup gera artefatos corretos;
- restore nao deixa OS “sumidas” nem midias quebradas;
- ambiente restaurado abre normalmente em PostgreSQL.

### Progresso executado

- backup real gerado com `manage.py backup_db --include-media` em `backups/go_live_validation/`;
- restore executado com sucesso em banco temporario separado;
- `media.zip` restaurado com sucesso durante a validacao;
- `check_tenant_data --strict` passou no banco restaurado;
- contagens validadas no restore temporario:
  - empresa: 1
  - clientes: 7
  - ordens: 7
  - orcamentos: 7
  - produtos: 1
- banco temporario de validacao removido ao final do teste.

### Referencias

- `docs/backup_restore_local.md`
- `docs/trocar_servidor_local.md`

---

## Fase G4 - Consolidacao do modo local oficial

Status: concluida tecnicamente em 2026-06-22  
Prioridade: alta

### Objetivo

Padronizar a forma correta de operar o sistema localmente e evitar confusao entre SQLite e PostgreSQL.

### Escopo

- reforcar `run_local.ps1` como forma oficial de subida;
- evitar uso operacional de `manage.py runserver` direto;
- revisar mensagens de diagnostico e checklist local;
- padronizar a rotina de subida do ambiente local;
- revisar porta, host e variaveis do banco oficial.

### Entregas

- documentacao operacional simples;
- fluxo padrao de subida e verificacao local;
- menor risco de erro humano ao iniciar o sistema.

### Criterios de aceite

- equipe sabe exatamente como subir o sistema;
- o ambiente certo abre no banco certo;
- check local passa sem ambiguidade.

### Progresso executado

- `run_local.ps1 -CheckOnly` validado com sucesso;
- `check_postgres_ready --check-connection` validado com sucesso;
- `check_tenant_data --strict` validado novamente no ambiente oficial;
- documentacao desta etapa consolidada em:
  - `docs/pendencias_reais_go_live_local.md`
  - `docs/plano_fechamento_go_live_local.md`
- forma oficial de uso local reforcada: subir por `run_local.ps1`, evitando confusao com `manage.py runserver` direto.

---

## Fase G5 - Homologacao em rede local

Status: parcialmente validada tecnicamente em 2026-06-22  
Prioridade: alta

### Objetivo

Validar o uso com 2 ou 3 PCs acessando o servidor local via navegador.

### Escopo

- testar login simultaneo;
- abrir a mesma OS em maquinas diferentes;
- validar atualizacao de tecnico/status entre PCs;
- validar caixa em uso normal;
- validar anexos e PDFs nos clientes;
- validar conectividade e porta do servidor local.

### Entregas

- homologacao em rede registrada;
- lista de ajustes de infraestrutura, se houver;
- confirmacao do PC servidor oficial.

### Criterios de aceite

- 2 ou 3 PCs operam sem conflito basico;
- PDFs e anexos funcionam via rede;
- o sistema se comporta de forma previsivel na LAN.

### Progresso executado

- `test_local_network.ps1` validado com sucesso em `127.0.0.1`;
- `test_local_network.ps1` validado com sucesso no IP local da LAN apos regenerar `.env.local`;
- detectados e removidos processos `runserver` orfaos que estavam interferindo na validacao;
- ambiente local passou a responder HTTP `200` tanto no loopback quanto no IP de rede da maquina.

### Ainda pendente

- execucao com 2 ou 3 PCs reais;
- validacao de sincronismo de OS entre maquinas diferentes;
- validacao pratica de anexos e PDFs em clientes de rede.

### Referencia

- `docs/homologacao_rede_local.md`

---

## Fase G6 - Liberacao controlada para uso real

Status: pendente  
Prioridade: alta

### Objetivo

Entrar em uso real com risco controlado e observacao proxima.

### Escopo

- iniciar operacao com poucos usuarios;
- acompanhar OS com saldo pendente;
- acompanhar caixa e SLA;
- acompanhar logs de integracao;
- confirmar rotina de backup diario;
- ajustar rapidamente apenas o que travar a operacao real.

### Entregas

- inicio de uso assistido;
- rotina minima de suporte e observacao;
- lista de refinamentos pos-go-live.

### Criterios de aceite

- sistema usado no dia a dia sem bloqueio estrutural;
- backups diarios definidos;
- operacao real nao depende de ambiente de teste.

---

## Ordem recomendada

1. G1 - Fechamento do lote final de bugs
2. G2 - Homologacao manual do fluxo principal
3. G3 - Backup, restore e seguranca de dados
4. G4 - Consolidacao do modo local oficial
5. G5 - Homologacao em rede local
6. G6 - Liberacao controlada para uso real

---

## O que eu consigo adiantar sozinho

### Posso executar diretamente

- quase toda a G1;
- grande parte da G3;
- boa parte da G4;
- ajustes documentais e tecnicos preparatorios da G5.

### Vai depender de validacao sua ou do ambiente real

- execucao completa da G2;
- teste real com 2 ou 3 PCs da G5;
- confirmacao final do PC servidor oficial;
- decisao de go-live da G6.

---

## Checklist final de liberacao

- [ ] lote final de bugs concluido
- [ ] testes direcionados passando em PostgreSQL
- [ ] fluxo principal homologado manualmente
- [ ] backup completo validado
- [ ] restore completo validado
- [ ] logo, anexos e assinaturas restauram corretamente
- [ ] sistema sobe via `run_local.ps1` sem erro
- [ ] checks locais passam no ambiente oficial
- [ ] rede local validada com 2 ou 3 PCs
- [ ] rotina diaria de backup definida
- [ ] PC servidor oficial definido

---

## Conclusao

Depois deste plano, o sistema sai da fase de desenvolvimento estrutural e entra em fase de uso real assistido.

O objetivo desta etapa nao e “perfeicao infinita”.
O objetivo e chegar a um ponto seguro, confiavel e operacional para comecar a usar na empresa.
