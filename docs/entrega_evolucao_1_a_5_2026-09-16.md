# Evolução 1 a 5 — ABGest 1.2.0

Estado: implementação e homologação locais. Não publicada nem instalada no PC definitivo por esta execução.

## O que muda na utilização

### Bancos e conciliação

Em Caixa → Bancos/Tesouraria, escolher conta e datas e clicar em Aplicar filtros. Há períodos rápidos e filtros avançados para natureza, lote, origem e importação. As listas têm páginas; os totais abrangem todos os resultados filtrados, não só a página visível. Natureza distingue operacional, transferência e capital pelas fontes conhecidas; “Não classificado” inclui movimentos antigos e linhas ainda sem vínculo seguro, sem presumir receita ou despesa.

Movimentos disponíveis são os que ainda podem ser conciliados. Para rever o histórico, selecionar a consulta correspondente. O histórico de conciliações seleciona grupos com pelo menos uma linha no filtro: os valores apresentados são os do grupo inteiro, que pode abranger datas fora do período. Não comparar esse total de grupo com saldo bancário.

Os saldos atuais das contas permanecem identificados como atuais. A posição até uma data considera o saldo inicial e os movimentos até essa data, não apenas descrições encontradas na pesquisa. Voltar da conciliação ou edição de conta preserva os filtros.

### OS e cliente

Os dados do equipamento mostram Data da compra e Nº da nota fiscal, sem exigir preenchimento em OS antigas.

O botão do cliente na OS abre Dados, Histórico e Financeiro. A ficha completa continua numa página ampla, com OS e recebimentos paginados. Configurações → Utilizadores permite controlar separadamente a consulta de dados completos, histórico, financeiro e edição. Esconder uma aba não é a única proteção: a autorização também ocorre no servidor e por empresa.

### Financeiro e gastos do cliente

O dashboard tem Entradas e saídas — financeiro geral por data efetiva. Movimentos sem sessão de caixa entram no período correto. O caixa físico continua separado. Aportes e transferências não são receita operacional, conciliação não é venda adicional, e fluxo líquido não é lucro nem saldo bancário.

Vendas avulsas/guias e checkout agrupado podem identificar um cliente cadastrado. O gasto dele considera o valor pago, sem deduzir a taxa de cartão; fabricante não é dívida do cliente. Em aberto é a dívida oficial atual, mesmo quando o filtro de pagamentos é de outro mês.

Uma devolução parcial entra na data da devolução e não apaga o recebimento do mês anterior. Um mês só com devolução pode, corretamente, ter gasto líquido negativo. O ticket médio indicado é por recebimento antes das devoluções.

Para identificar vendas antigas, Caixa → Relatórios, correções e cadastros → Identificar clientes antigos. Escolher recibo, cliente e justificativa. O vínculo é auditado, sem alterar valores, datas ou dados impressos no recibo original. Não associar só porque o nome parece igual. Cancelamentos completos antigos que apagaram o pagamento não são reconstruídos nesta ficha.

## Backup automático e nuvem

### Preparação no servidor

1. Manter backup manual completo e confirmar espaço livre. Escolher horário sem utilização e retenções local/remota. A retenção local permanece nas configurações gerais de backup; a rotina tem retenção própria para os pacotes cifrados copiados à pasta da nuvem.
2. Instalar e configurar o aplicativo da nuvem escolhida no PC servidor. A pasta de sincronização deve ser independente do destino de backup local. Nunca sincronizar a pasta ativa do PostgreSQL.
3. Para cópia criptografada, gerar uma chave aleatória de 32 bytes codificada em base64 URL-safe e definir `ABGEST_BACKUP_KEY` no ambiente protegido carregado pelo servidor (`.env.local`). Não colocar no Git, enviar no chat ou perder a única cópia. Guardar também num local seguro fora do PC. Se mudar a chave, conservar a anterior para recuperar os pacotes antigos.
4. Em Configurações → Backup → Backup automático e nuvem, configurar horário, pasta sincronizada e retenção. A rotina começa desativada. Apenas o administrador autorizado da instalação pode gerir um pacote que inclui todas as empresas.
5. Instalar a tarefa no Windows servidor, como administrador, a partir da pasta do projeto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\instalar_backup_agendado.ps1
```

6. Habilitar a rotina. A tarefa verifica a cada 30 minutos e faz uma cópia diária após o horário definido, com recuperação da execução pendente se o PC esteve desligado. Execuções simultâneas são bloqueadas. O programa não precisa estar aberto.
7. Executar um backup pela tela, conferir integridade e histórico. A cópia local é ZIP completo; apenas o pacote `.abenc` criptografado é copiado para a pasta de nuvem.
8. Confirmar no site/aplicativo da nuvem que o pacote chegou. O estado “Copiado; upload não confirmado” não comprova upload. O aplicativo de sincronização pode precisar de sessão Windows aberta, mesmo que o backup local rode como SYSTEM.
9. Reiniciar o servidor e testar agendamento e upload. Guardar evidência de recuperação isolada antes de depender desta proteção.

Falha de upload/cópia não apaga o backup local válido. A próxima verificação tenta novamente a cópia do backup diário existente. Falta de internet, permissões, quota e espaço livre precisam de acompanhamento. A retenção remota da pasta sincronizada pode propagar exclusões à nuvem: manter retenções distintas e confirmar a política do fornecedor.

### Testar recuperação sem restaurar o banco ativo

Num ambiente separado, com acesso ao PostgreSQL de homologação e permissão de criar banco temporário:

```powershell
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 validar_recuperacao_backup "C:\CopiaSegura\backup_exemplo.zip"
```

O comando verifica o pacote, recupera o banco e os anexos em destinos temporários e remove apenas esses destinos gerados. Não recebe nome de banco de destino nem restaura o banco ativo. Não certifica, sozinho, a validade de todas as referências a ficheiros: abrir anexos representativos numa homologação completa também é necessário.

Para um pacote baixado exclusivamente da nuvem, configurar a chave correspondente no ambiente de recuperação e primeiro obter um ZIP novo:

```powershell
powershell -ExecutionPolicy Bypass -File .\manage_local.ps1 decifrar_backup_nuvem "C:\CopiaSegura\backup_exemplo.zip.abenc" "C:\CopiaSegura\recuperado.zip"
```

Esse comando não restaura o banco e não sobrescreve um destino existente. Depois validar o ZIP pelo procedimento anterior. Só registar a declaração de teste na tela após realizar e conferir o teste; a declaração não executa uma recuperação.

## Atualização gradual no outro PC

Esta versão ainda precisa de publicação. Depois de existir referência publicada e homologada:

1. Pausar o uso da equipa antes de trocar o código. Confirmar a pasta do projeto, o servidor alvo e a versão.
2. Fazer backup completo pelo fluxo atual e guardar configurações/chaves fora do Git. Não levar o banco de desenvolvimento à loja.
3. Atualizar para a referência publicada. O script abaixo não faz a obtenção do código; ele executa as etapas posteriores à atualização do repositório.
4. Executar como administrador `ATUALIZAR-APOS-GIT-PULL-COMO-ADMIN.cmd`. Ele chama `atualizar_gradual.ps1`: pausa a tarefa de backup e o serviço ABGestWaitress quando estavam ativos, gera backup completo, verifica plano, instala dependências, aplica migrations, atualiza estáticos e verifica o projeto. Reinicia apenas o serviço que estava ativo e reativa a tarefa anteriormente habilitada.
5. Se houver falha, manter manutenção. O script não restaura automaticamente um banco antigo. Em especial, se houver backup em execução, aguardar e verificar a tarefa que ficou desabilitada pela manutenção antes de nova tentativa.
6. Conferir versão, migrations, login, OS antiga, anexos, PDFs e valores conhecidos; verificar saúde HTTP após reinício. O serviço Windows e essa verificação final ainda precisam de ensaio no ambiente definitivo.
7. Habilitar o backup automático somente após a configuração e os testes acima.

Quatro migrations novas: caixa 0064; configurações 0098, 0099 e 0100. Foram aplicadas apenas localmente nesta execução. São estruturas adicionais; não corrigem saldos antigos nem restauram ficheiros ausentes. Não presumir que voltar só o código é seguro: essa compatibilidade ainda não foi certificada.

## Validação de desenvolvimento

`testar_evolucao_gradual.ps1` executa a regressão crítica em banco Django de testes separado, incluindo dinheiro/desconto, checkout agrupado, custos/garantia, XML, cliente, filtros, permissões e backup. Não executar testes de escrita manualmente no banco real.

Regressão específica final: 108 testes aprovados. Regressão ampla de autorização/tesouraria/multiempresa: 291 testes aprovados, com sobreposição entre baterias. Recuperação real de um pacote completo testada num banco temporário: 157 tabelas, 324 migrations e 78 anexos. Acesso manual a backup/download/restore também restringe administradores de empresa quando o pacote abrange outras empresas.

Revisão final de 17/09: 22 testes adicionais aprovados, incluindo natureza bancária e linhas pendentes sem classificação. As evidências locais e os limites de ativação estão no plano de evolução. WhatsApp/PDF, central de pendências e IA continuam nas fases seguintes.
