# Relatorio de Fechamento Go-Live Local - 2026-06-22

## Objetivo

Registrar a execucao tecnica das fases iniciais do fechamento de go-live local, com foco em:

- bugs finais de operacao;
- validacao em PostgreSQL local;
- backup e restore;
- consolidacao do modo local oficial.

## Escopo executado

### G1 - Lote final de bugs operacionais

Validacoes realizadas:

- `manage.py check`
- regressao direcionada dos fluxos corrigidos
- regressao complementar das areas de criacao de OS, atualizacao AJAX e PDF de orcamento

Resultado:

- `manage.py check` sem issues;
- regressao direcionada: OK;
- bateria complementar: `26 testes OK`.

Principais pontos consolidados:

- rota textual indevida de clientes protegida;
- `Outros` em tipo de equipamento persistindo valor manual;
- troca de tecnico por AJAX com retorno de linha de historico;
- aprovacao parcial refletindo na linha de trabalho;
- alerta e acompanhamento de fechamento com saldo pendente;
- exibicao de `Tipo da OS` reforcada em pontos operacionais.

### G3 - Backup e restore

Comando executado:

- `manage.py backup_db --output-dir backups/go_live_validation --include-media`

Fluxo executado:

1. geracao de backup real;
2. criacao de banco temporario;
3. restore completo no banco temporario;
4. restore de `media`;
5. reparo local de empresa unica;
6. `check_tenant_data --strict`;
7. conferencia de contagens;
8. remocao do banco temporario.

Resultado:

- backup gerado com sucesso;
- restore executado com sucesso;
- `media` restaurada com sucesso;
- tenant check aprovado;
- contagens validadas:
  - empresa: 1
  - clientes: 7
  - ordens: 7
  - orcamentos: 7
  - produtos: 1

Backup validado:

- `backups/go_live_validation/backup_20260622_133424`

### G4 - Modo local oficial

Validacoes executadas:

- `powershell -ExecutionPolicy Bypass -File .\\run_local.ps1 -CheckOnly`
- `manage.py check_postgres_ready --check-connection`
- `manage.py check_tenant_data --strict`

Resultado:

- ambiente oficial local validado;
- PostgreSQL local pronto para uso;
- configuracao tenant sem pendencias;
- fluxo oficial de subida consolidado em `run_local.ps1`.

### G5 - Preparacao tecnica de rede local

Validacoes executadas:

- subida do sistema pelo fluxo oficial local;
- `test_local_network.ps1` em `127.0.0.1`;
- `test_local_network.ps1` no IP local da LAN.

Achado importante:

- havia processos `runserver` orfaos na porta `8000`, o que mascarava os testes;
- havia tambem um IP antigo em `.env.local`, causando `400` no acesso pela LAN;
- o ambiente local foi regenerado com `setup_local_env.ps1 -Overwrite` para refletir o IP atual.

Resultado:

- loopback: `200 OK`;
- IP da rede local: `200 OK`;
- trilha tecnica de acesso local validada com sucesso.

## O que ainda depende de homologacao manual

### G2 - Fluxo principal fim a fim

Ainda precisa de execucao manual em tela:

- cadastro de cliente;
- abertura de OS;
- aprovacao total e parcial;
- migracao de itens;
- servicos e pecas;
- pagamento no caixa;
- fechamento da OS;
- historico do cliente;
- PDFs principais.

### G5 - Rede local real

Ainda precisa de ambiente com 2 ou 3 PCs:

- login simultaneo;
- leitura/atualizacao da mesma OS por maquinas diferentes;
- upload/anexos/PDFs via cliente de rede;
- validacao do PC servidor oficial.

### G6 - Uso real assistido

Depende de decisao operacional:

- inicio do uso na empresa;
- rotina diaria de backup;
- acompanhamento de SLA, caixa e OS com saldo pendente.

## Conclusao

As etapas tecnicas mais criticas deste fechamento ja foram executadas com sucesso:

- G1 concluida tecnicamente;
- G3 concluida tecnicamente;
- G4 concluida tecnicamente.

Restam principalmente:

- homologacao manual de operacao;
- homologacao em rede local real;
- inicio controlado do uso real.
