# Plano de Fechamento da Fase Inicial (v1)

## Objetivo

Fechar a fase inicial do produto com foco em:
- seguranca de producao;
- consistencia multiempresa;
- observabilidade e rastreabilidade de erro;
- reducao de complexidade tecnica;
- ganhos operacionais imediatos em OS e caixa.

## Escopo aprovado

1. Hardening de producao.
2. Tenant minimo obrigatorio.
3. Observabilidade de erro.
4. Refino tecnico leve.
5. Fila de bancada por tecnico com prioridade e tempo parado.
6. Metricas de qualidade tecnica (reincidencia e retorno 30/60/90 dias).
7. Regras antifraude simples no caixa.

---

## Fase F0 - Hardening de Producao
Status: concluida (2026-05-17)  
Prioridade: critica

### Entregas
- Remover senha hardcoded de `run_postgres.ps1`.
- Usar apenas variaveis de ambiente e/ou arquivo local nao versionado.
- Revisar defaults de seguranca em `assistencia/settings.py` para ambiente produtivo.
- Validar checklist com `check_go_live`.

### Criterios de aceite
- Nenhum segredo exposto em script versionado.
- `DEBUG=0` com validacoes obrigatorias de `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`.
- Sistema sobe em producao sem fallback inseguro.

---

## Fase F1 - Tenant Minimo Obrigatorio
Status: concluida (2026-05-17)  
Prioridade: critica

### Entregas
- Substituir `Empresa.objects.first()` por `request.empresa_ativa` nos fluxos principais.
- Criar guard rail para consultas tenant-aware em modulos criticos (OS, Orcamentos, Estoque, Caixa, Clientes).
- Bloquear acesso cruzado por URL e validar por testes.

### Criterios de aceite
- Todas as consultas operacionais principais usam empresa ativa.
- Nenhum dado de empresa A visivel para usuario da empresa B.
- Testes automatizados de isolamento passando.

---

## Fase F2 - Observabilidade de Erro
Status: concluida (2026-05-17)  
Prioridade: alta

### Entregas
- Trocar `except Exception` generico por excecoes especificas onde aplicavel.
- Registrar logs estruturados em pontos criticos:
  - OS;
  - caixa;
  - integracoes;
  - PDF.
- Padronizar payload de log: modulo, acao, usuario, empresa, ordem/pagamento, erro.

### Criterios de aceite
- Erros relevantes ficam rastreaveis com contexto tecnico e operacional.
- Reducao de capturas silenciosas sem diagnostico.

---

## Fase F3 - Refino Tecnico Leve
Status: concluida (2026-05-17)  
Prioridade: alta

### Entregas
- Quebrar os 3 maiores arquivos operacionais em submodulos por responsabilidade.
- Manter rotas, assinatura de funcoes e comportamento funcional.
- Cobrir refino com testes de regressao.

### Arquivos alvo iniciais
- `ordens/view_modules/impressao.py`
- `caixa/view_modules/dashboard.py`
- `caixa/view_modules/comissoes_views.py`

### Criterios de aceite
- Sem regressao funcional.
- Reducao de acoplamento e melhora de legibilidade/manutencao.

---

## Fase F4 - Fila de Bancada por Tecnico
Status: concluida (2026-05-17)  
Prioridade: alta

### Entregas
- Tela de fila por tecnico com:
  - prioridade;
  - tempo parado;
  - proxima acao sugerida.
- Filtros por tecnico, status e criticidade.
- Atalho de abertura rapida da OS.

### Criterios de aceite
- Tecnico enxerga claramente o que atacar primeiro.
- Reducao de OS parada sem movimentacao.

---

## Fase F5 - Metricas de Qualidade Tecnica
Status: concluida (2026-05-17)  
Prioridade: alta

### Entregas
- Painel de qualidade com:
  - reincidencia por tecnico;
  - reincidencia por marca;
  - reincidencia por tipo de equipamento;
  - taxa de retorno em 30/60/90 dias.
- Filtros por periodo, tecnico e linha de atuacao.

### Criterios de aceite
- Indicadores comparaveis e acionaveis para melhoria tecnica.
- Base para treinamento e revisao de processo.

---

## Fase F6 - Antifraude Simples no Caixa
Status: concluida (2026-05-17)  
Prioridade: critica

### Entregas
- Dupla confirmacao para acoes sensiveis:
  - exclusao de pagamento;
  - estorno;
  - desconto critico.
- Confirmacao com motivo obrigatorio.
- Registro de auditoria com usuario, horario e contexto.

### Criterios de aceite
- Acoes de alto risco nao ocorrem por clique acidental.
- Toda acao sensivel deixa trilha de auditoria valida.

---

## Ordem recomendada de execucao

1. F0 Hardening de producao.
2. F1 Tenant minimo obrigatorio.
3. F2 Observabilidade de erro.
4. F3 Refino tecnico leve.
5. F6 Antifraude simples no caixa.
6. F4 Fila de bancada por tecnico.
7. F5 Metricas de qualidade tecnica.

## Estrategia de rollout

- Entregas pequenas por fase, sempre com teste automatizado e checklist manual.
- Deploy incremental com validacao de operacao real apos cada fase.
- Sem alterar fluxo operacional do usuario final de forma abrupta.

## Criterios de encerramento da fase inicial

- Sem segredos hardcoded e com baseline de seguranca aplicada.
- Tenant minimo aplicado nos fluxos criticos.
- Erros criticos observaveis com logs estruturados.
- Modulos grandes refatorados sem regressao.
- Fila tecnica ativa em producao.
- Metricas de qualidade tecnica disponiveis.
- Regras antifraude operacionais no caixa.

Status final: criterios atendidos na entrega de 2026-05-17.
