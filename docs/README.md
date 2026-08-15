# Documentacao Interna

## Fontes ativas

- `plano_desenvolvimento_sistema.md`: roadmap tecnico e status das fases.
- `plano_desenvolvimento_estoque.md`: roadmap tecnico especifico do modulo de estoque.
- `plano_desenvolvimento_caixa.md`: diagnostico e roadmap tecnico especifico do modulo de caixa.
- `plano_fiscal_tributario_financeiro_2026.md`: plano consolidado de correcao fiscal/tributaria, caixa, bancos, conciliacao, estoque e preparacao para IBS/CBS.
- `plano_desenvolvimento_comissoes.md`: politica operacional, roadmap e homologacao da apuracao de comissoes.
- `plano_desenvolvimento_venda_mostrador.md`: roadmap operacional e tecnico especifico do fluxo de venda a mostrador/PDV.
- `plano_desenvolvimento_configuracoes.md`: diagnostico e roadmap tecnico da app configuracoes com foco em integracoes e preparacao SaaS.
- `plano_desenvolvimento_visual.md`: roadmap de padronizacao visual, UX operacional e documentos/PDFs.
- `plano_fechamento_fase_inicial_v1.md`: plano final de hardening, tenant, observabilidade, refino tecnico, fila tecnica, metricas e antifraude.
- `plano_fase_a_pre_uso_local.md`: plano de refinamento e homologacao antes do uso real local em rede.
- `plano_fechamento_go_live_local.md`: plano final e curto para fechar bugs, homologar, validar backup/restore e liberar o uso local.
- `pendencias_reais_go_live_local.md`: consolidacao do que ainda falta de verdade antes do uso real local.
- `relatorio_fechamento_go_live_local_2026-06-22.md`: evidencia tecnica da execucao automatizada do fechamento de go-live local.
- `entrega_1_fluxo_permissoes.md`: diagnostico inicial de fluxo e permissoes.
- `permissoes_por_perfil.md`: visao funcional de acessos por perfil.
- `revisao_arquitetura.md`: fotografia arquitetural atual do sistema.
- `ownership_modulos.md`: ownership tecnico atual por app e ponto oficial de manutencao.
- `checklist_homologacao_manual.md`: validacoes manuais de operacao.
- `checklist_homologacao_estoque.md`: roteiro de homologacao manual por perfil do estoque (Fase E7).
- `manual_financeiro_compras_bancos_v1_1.md`: compras da OS, contas a pagar, cartões corporativos, bancos, sócios, saneamento retroativo e contabilidade gerencial da versão 1.1.1.
- `notas_versao_1_1_2_conciliacao.md`: correções de duplicidade, conciliação, edição/cancelamento auditado e datas retroativas.
- `notas_versao_1_1_3_saneamento_financeiro.md`: saneamento auditado da base, relatorios sem duplicidade, conciliacao guiada e tratamento correto de PIX e saidas bancarias.
- `manual_estoque_fiscal_caixa.md`: manual operacional após as melhorias de estoque, XML, tributação, preço, caixa e conciliação.
- `manual_caixa_fiscal_dfe.md`: configuração segura do certificado A1, consulta oficial de NF-e destinadas por NSU e importação para conferência no estoque.
- `manual_rateio_precificacao_canais_custos_os.md`: operação do rateio automático por despesas reais, maquininhas, preços por canal e custos previstos/realizados da OS.
- `checklist_homologacao_configuracoes.md`: roteiro de homologacao manual por perfil da app configuracoes.
- `checklist_migracao_postgresql.md`: guia de validacao da futura migracao de banco.
- `backup_restore_local.md`: procedimento operacional de backup/restore local com PostgreSQL e media.
- `trocar_servidor_local.md`: checklist para migrar a instalacao local para outro PC usando backup.
- `homologacao_rede_local.md`: roteiro de validacao com 2 ou 3 PCs acessando o servidor local.
- `relatorio_homologacao_estoque.md`: template operacional para registrar execucao manual da E7.
- `relatorio_homologacao_estoque_2026-05-13.md`: consolidacao da evidencia automatizada e pendencias manuais da E7.
- `relatorio_homologacao_postgresql_2026-05-12.md`: homologacao da migracao para PostgreSQL no ambiente de desenvolvimento.
- `relatorio_homologacao_configuracoes_2026-05-14.md`: consolidacao da evidencia automatizada da homologacao da configuracoes.
- `analise_profissional_sistema_2026-05-14.md`: revisao senior do produto, UX, riscos tecnicos e oportunidades de funcionalidades.

## Fontes historicas

- `legacy_code/`: codigo legado arquivado para consulta.
- `legacy_code/lista_funcoes_programa.txt`: inventario historico de funcoes (inclui legado).
- `legacy_code/resumo_funcoes_programa.txt`: resumo historico de contagem por modulo.

## Regra de uso

- Para manutencao e desenvolvimento, priorizar sempre as fontes ativas.
- Arquivos historicos devem ser tratados como referencia de auditoria, nao como fonte de implementacao.
- Quando houver duvida sobre "onde mexer", consultar primeiro `ownership_modulos.md`.
