# Pendencias Reais para Go-Live Local

## Objetivo

Consolidar, em um unico lugar, o que realmente falta para colocar o sistema em uso local na empresa com seguranca operacional.

Este documento nao cria um novo roadmap grande. Ele serve para:

- separar o que ja foi concluido do que ainda precisa de fechamento real;
- listar os bloqueios práticos antes de usar com dados reais;
- orientar a homologacao final em PostgreSQL local e rede interna.

## Situacao atual resumida

Os planos principais do projeto estao marcados como concluidos:

- fase inicial de endurecimento tecnico;
- fase visual;
- fase A pre-uso local;
- estoque;
- caixa;
- configuracoes;
- preparacao para PostgreSQL local.

Na pratica, isso significa que o sistema ja tem base funcional e tecnica para uso real.

Atualizacao de validacao automatizada em 2026-07-13:

- suite ampla de `configuracoes`, `estoque` e `core` executada com sucesso;
- 269 testes automatizados concluidos sem falha;
- 57 testes de permissoes/configuracoes concluidos sem falha;
- correcao estrutural aplicada nos templates base para carregar o bloco `styles` das telas de configuracoes;
- smoke local via `manage_local.ps1 check` concluido sem erros.

O que ainda resta nao e um novo ciclo grande de desenvolvimento, e sim:

1. fechar o lote final de correcao operacional;
2. validar os fluxos mais criticos manualmente;
3. confirmar operacao local em PostgreSQL e rede;
4. consolidar rotina de backup e restauracao.

---

## P0 - Bloqueios reais antes de usar com dados reais

Prioridade: critica

### P0.1 - Fechar e validar o lote atual de correcoes operacionais

Status: concluido tecnicamente em 2026-06-22

Itens do bloco atual:

- impedir que URL textual em `clientes/` vire listagem ampla por engano;
- permitir `Outros` em tipo de equipamento com digitacao manual;
- corrigir atribuicao de tecnico responsavel sem erro visual e com linha de historico;
- registrar aprovacao parcial de orcamento na linha de trabalho;
- exibir `Tipo da OS` onde faz falta;
- avisar antes de fechar OS com saldo financeiro em aberto;
- registrar OS fechada com saldo pendente em indicador/financeiro;
- revisar PDF de orcamento com textos mais longos.

Observacao:

- o bloco foi fechado tecnicamente no codigo;
- testes automatizados direcionados passaram em PostgreSQL local;
- ainda vale a validacao manual completa em tela, principalmente em OS e PDF.

### P0.2 - Validar manualmente o fluxo principal fim a fim no PostgreSQL local

Status: pendente de execucao manual final

Fluxo minimo que precisa passar sem erro:

1. cadastrar cliente;
2. abrir OS;
3. registrar diagnostico;
4. criar orcamento;
5. aprovar totalmente e parcialmente;
6. migrar itens aprovados;
7. adicionar servico e peca;
8. registrar relatorio tecnico;
9. abrir caixa;
10. receber pagamento;
11. fechar OS;
12. consultar historico do cliente;
13. emitir PDFs principais.

Referencia operacional:

- `docs/checklist_homologacao_manual.md`

### P0.3 - Validar backup e restore apos as ultimas mudancas

Status: concluido tecnicamente em 2026-06-22

Precisa confirmar novamente:

- backup de banco;
- backup de `media`;
- restore completo em base temporaria;
- visibilidade correta de OS, clientes, produtos e configuracoes apos restore;
- logo, anexos e assinaturas voltando corretamente.

Referencias:

- `docs/backup_restore_local.md`
- `docs/trocar_servidor_local.md`

### P0.4 - Confirmar operacao padrao exclusivamente pelo modo local correto

Status: concluido tecnicamente em 2026-06-22

Regra recomendada para uso real:

- nao subir o sistema com `manage.py runserver` direto;
- usar sempre `powershell -ExecutionPolicy Bypass -File .\run_local.ps1`;
- manter o banco oficial em PostgreSQL local;
- evitar confusao entre SQLite legado e ambiente PostgreSQL.

Isso e importante porque o uso direto de `manage.py` pode carregar ambiente errado e gerar erros enganosos de banco.

---

## P1 - Pendencias importantes antes de colocar 2 ou 3 PCs em uso

Prioridade: alta

### P1.1 - Homologacao em rede local real

Status: pendente de validacao com 2 ou 3 PCs

Validar com 2 ou 3 PCs:

- login simultaneo;
- abertura e leitura da mesma OS por maquinas diferentes;
- alteracao de status/tecnico refletindo corretamente;
- pagamento no caixa sem conflito;
- upload de anexos e geracao de PDF a partir de cliente de rede.

Referencia:

- `docs/homologacao_rede_local.md`

Observacao:

- smoke tecnico local ja validado em `127.0.0.1` e no IP da LAN da maquina em 2026-06-22;
- o `.env.local` foi regenerado para corrigir IP antigo em `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS`;
- ainda falta somente o teste real entre maquinas diferentes.

### P1.2 - Definir o PC servidor oficial

Status: pendente

Definicoes necessarias:

- maquina que hospedara PostgreSQL, Django, `media` e backups;
- IP fixo ou reserva DHCP;
- rotina de inicializacao do PostgreSQL local;
- rotina de inicializacao da aplicacao;
- pasta oficial de backup.

### P1.3 - Validar logo e arquivos de media no ambiente local final

Status: pendente

Como ja houve comportamento inconsistente com logo/upload entre ambientes, vale validar no ambiente local final:

- upload da logo;
- exibicao da logo no login e sidebar;
- uso da logo nos PDFs;
- restore da logo via backup.

---

## P2 - Ajustes recomendados, mas nao bloqueantes para o primeiro uso

Prioridade: media

### P2.1 - Validar PDF de orcamento com cenarios extremos

Status: pendente

Casos para conferir:

- nome longo de cliente;
- descricao longa de item;
- muitos itens;
- observacoes extensas;
- assinatura e bloco final.

### P2.2 - Revisao fina de microcopy e acentuacao residual

Status: pendente continuo

Mesmo com os planos fechados, ainda vale continuar varrendo:

- textos pequenos quebrados;
- labels antigas;
- mensagens de erro muito tecnicas;
- inconsistencias entre `orcamento`, `peca`, `tecnico`, `numero`, `configuracoes`.

### P2.3 - Padronizacao futura do PostgreSQL local

Status: opcional

Pendencia residual ja conhecida:

- se desejado, padronizar a porta local para `5432` em vez de `5433`;
- revisar indices e constraints depois de algum tempo de uso real com dados da loja.

---

## Ordem recomendada de fechamento

### Etapa 1 - Fechar o lote atual de bugs

- concluir ajustes que estao no working tree;
- validar OS, orcamento e fechamento financeiro;
- revisar PDF de orcamento na pratica.

### Etapa 2 - Homologacao manual local

- executar o checklist manual;
- registrar falhas reais encontradas;
- corrigir somente o que bloquear a operacao.

### Etapa 3 - Backup e restore final

- gerar backup limpo;
- restaurar em base temporaria;
- confirmar que dashboard, OS e media voltam corretamente.

### Etapa 4 - Rede local

- subir pelo `run_local.ps1`;
- testar com 2 ou 3 PCs;
- validar uploads, PDFs e sincronismo basico.

### Etapa 5 - Go-live controlado

- iniciar uso real com poucos usuarios;
- acompanhar SLA, caixa, OS fechadas com saldo e logs de integracao;
- manter rotina diaria de backup.

---

## Checklist final de aceite para comecar a usar

Use este bloco como criterio objetivo de liberacao:

- [ ] sistema sobe pelo `run_local.ps1` sem erro;
- [ ] `check_go_live`, `check_postgres_ready --check-connection` e `check_tenant_data --strict` passam;
- [ ] cliente -> OS -> orcamento -> servicos/pecas -> caixa -> fechamento funciona no PostgreSQL local;
- [ ] aprovacao parcial de orcamento funciona sem confusao operacional;
- [ ] fechamento de OS com saldo pendente avisa corretamente e gera acompanhamento;
- [ ] PDFs principais ficam legiveis em cenarios reais;
- [ ] backup completo foi gerado com sucesso;
- [ ] restore completo foi testado em base temporaria;
- [ ] logo, anexos e assinaturas funcionam apos restore;
- [ ] 2 ou 3 PCs acessam o sistema pela rede local sem conflito basico;
- [ ] rotina de backup diario e pasta oficial de backup estao definidas.

---

## Conclusao

Hoje, o projeto nao tem mais grandes fases abertas.

O que falta e um fechamento pratico de go-live:

- pequenos ajustes finais;
- homologacao manual;
- validacao de backup/restore;
- validacao em rede local.

Quando esse documento estiver todo marcado, o sistema entra em uma fase de uso real assistido, e nao mais de desenvolvimento estrutural.
