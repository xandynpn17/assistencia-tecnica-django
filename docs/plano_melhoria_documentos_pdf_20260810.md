# Plano de melhoria dos documentos PDF

Data de início: 10/08/2026

## Objetivo

Padronizar os documentos entregues ao cliente e os documentos internos, com leitura simples, aparência profissional e preservação integral das informações relevantes. O fluxo continuará preparado para operação local, sem QR Code nesta fase.

## Regras confirmadas

- A Ordem de Serviço impressa terá os dados completos no ORIGINAL e no DUPLICADO.
- O cliente leva o ORIGINAL.
- A empresa guarda o DUPLICADO assinado.
- A assinatura não será repetida na frente nem na via do cliente.
- O verso do ORIGINAL apresentará os termos completos para consulta do cliente.
- O verso do DUPLICADO apresentará os mesmos termos e uma declaração única de concordância, com os campos de assinatura de abertura e de entrega.
- Nenhum termo contratual poderá ser cortado silenciosamente.
- O QR Code ficará fora do escopo enquanto o sistema operar somente na rede local.

## Etapas de desenvolvimento

### 1. Ordem de Serviço impressa

- Remover assinaturas da frente das duas vias.
- Manter os dados da OS nas duas vias, identificando claramente ORIGINAL e DUPLICADO.
- Imprimir termos completos no verso das duas vias.
- Concentrar a declaração de concordância e as assinaturas somente no verso do DUPLICADO.
- Permitir continuação paginada quando um texto personalizado não couber, sem truncamento.
- Rever espaçamentos, tamanhos mínimos de fonte e indicação de corte.

### 2. Etiquetas de identificação

- Substituir a grade de etiquetas estreitas por etiquetas maiores e mais legíveis.
- Melhorar margens internas, espaçamento entre etiquetas e contraste.
- Exibir OS, cliente e identificação essencial do equipamento sem poluição visual.

### 3. Relatório Técnico

- Simplificar a versão entregue ao cliente.
- Priorizar dados básicos do cliente; tipo, marca/modelo e série do equipamento; peritagem; defeito reclamado; relatório técnico; peças utilizadas; e serviços realizados.
- Omitir informações internas e financeiras por padrão, mantendo opções configuráveis quando forem úteis.
- Eliminar assinaturas redundantes.

### 4. Orçamento

- Exibir no PDF as observações gerais já cadastradas no orçamento.
- Exibir os detalhes de cada item quando preenchidos.
- Separar conteúdo público de informações internas, sem mostrar status operacional de item ao cliente.
- Melhorar clareza dos valores, condições e aprovação.

### 5. Padronização brasileira

- Centralizar formatação de moeda, telefone, documentos e datas.
- Usar moeda no padrão `R$ 1.234,56` em todos os documentos.
- Evitar funções de formatação duplicadas entre módulos.

### 6. Qualidade e homologação

- Atualizar testes automáticos para verificar integridade do texto e regras de assinatura.
- Criar amostras representativas com conteúdo curto e longo.
- Renderizar e inspecionar visualmente todas as páginas alteradas.
- Validar ausência de cortes, sobreposições, páginas quase vazias e caracteres quebrados.
- Documentar um checklist breve para teste no computador definitivo.

## Critérios de aceite

- ORIGINAL e DUPLICADO contêm os mesmos dados essenciais da OS.
- Só o DUPLICADO contém campos de assinatura.
- Os termos completos podem ser recuperados do PDF, mesmo quando extensos.
- Etiquetas permanecem legíveis após impressão e recorte.
- O RT não expõe informações internas ou excesso de dados por padrão.
- Observações e detalhes preenchidos no orçamento aparecem no documento do cliente.
- Valores monetários usam o padrão brasileiro.
- Testes automáticos passam e os PDFs foram conferidos visualmente.

## Fora do escopo desta fase

- QR Code e validação pública pela internet.
- Assinatura eletrônica com validade jurídica externa.
- Emissão fiscal automática.

## Situação da implementação em 10/08/2026

- Etapas 1 a 6 concluídas no código.
- Migration `configuracoes.0089` criada para ativar o RT resumido por padrão.
- Testes de OS, RT, orçamento, configuração e formatadores executados com sucesso.
- Amostras finais renderizadas em A4 e inspecionadas visualmente.
- A implantação no computador definitivo requer aplicar as migrations e reiniciar o servidor.
