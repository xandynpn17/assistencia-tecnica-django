# Manual — Caixa fiscal de entrada NF-e com certificado A1

## Finalidade

A **Caixa fiscal NF-e** consulta o serviço oficial de Distribuição DF-e do Ambiente Nacional para localizar documentos destinados ao CNPJ da empresa ativa. Ela não é um emissor fiscal e não envia manifestação do destinatário automaticamente.

Cada empresa possui certificado, NSU, documentos e histórico próprios. Em uma futura operação multiempresa, nunca reutilize o A1 de um CNPJ em outro cadastro.

## Configuração inicial no computador principal

1. Confirme em **Configurações** se CNPJ e UF da empresa ativa estão corretos.
2. Em **Fiscal > Configuração fiscal**, escolha **Produção** para documentos reais. Homologação serve apenas para testes.
3. Abra **Fiscal > Caixa fiscal NF-e**.
4. Selecione o arquivo A1 `.pfx` ou `.p12`, informe a senha e clique em **Validar e salvar A1**.
5. Confira titular, CNPJ e validade apresentados pelo sistema.

O arquivo e a senha ficam cifrados no banco; a senha não volta a ser exibida. O XML recebido também é armazenado cifrado. O servidor usa arquivos PEM temporários somente durante a conexão mTLS e os remove ao terminar a consulta.

Para que backups continuem legíveis após trocar o computador, preserve de forma segura a variável `FISCAL_CREDENTIAL_KEY`. Quando ela não for definida, a proteção deriva de `SECRET_KEY`, que também precisa acompanhar a restauração. Não envie essas chaves, o A1 ou sua senha por chat ou e-mail.

## Consulta diária

1. Clique em **Buscar novas NF-e**.
2. Aguarde o retorno da SEFAZ.
3. Pesquise pelo número da nota, chave, fornecedor ou CNPJ.
4. Quando houver **XML completo**, clique em **Preparar importação**.
5. Escolha ponto operacional e localização. Marque conta a pagar apenas se desejar preparar o financeiro da compra.
6. Confira a entrada criada no Estoque, resolva fornecedor e produtos, revise custos, preços e parcelas.
7. Somente depois clique em **Receber**. É nesse momento que o saldo e o custo médio são atualizados.

O número da NF-e sozinho não identifica um documento de forma segura em todo o Brasil. A consulta oficial ocorre em sequência por **NSU**; depois da sincronização, o sistema permite localizar rapidamente a nota pelo número.

## Resumo e XML completo

A SEFAZ pode retornar apenas um resumo, um evento ou o XML completo. Somente o XML completo pode virar entrada de mercadoria. Um resumo permanece na caixa como **Aguardando XML completo**.

O sistema não envia automaticamente Ciência da Operação, Confirmação da Operação, Desconhecimento ou Operação não Realizada. Essa separação é proposital: manifestações têm efeitos fiscais e devem depender de uma decisão explícita e de orientação contábil.

## Segurança e controles

- consultas respeitam o último NSU por empresa e por ambiente;
- documentos repetidos não criam outra entrada;
- existe intervalo mínimo entre consultas para reduzir risco de rejeição 656;
- toda execução registra usuário, horário, ambiente, NSUs, retorno e contagem;
- telas e documentos são filtrados pela empresa ativa;
- o XML não é exibido em texto na interface;
- remover o A1 preserva documentos e histórico, mas interrompe novas consultas.

## Limites atuais

- emissão de NF-e/NFC-e/NFS-e continua em standby;
- não há manifestação automática do destinatário;
- indisponibilidade, regras de retenção e retorno do Ambiente Nacional dependem da SEFAZ;
- o sistema auxilia a operação, mas não substitui validação de NCM, CFOP, CST/CSOSN, créditos ou escrituração pelo responsável fiscal.

## Teste recomendado

Primeiro use **Homologação** somente para validar conectividade, se houver dados de teste adequados. Para receber documentos reais destinados à empresa, selecione **Produção**, cadastre o A1 verdadeiro e faça uma consulta. Confirme que o documento pertence ao CNPJ ativo e que a entrada permanece em rascunho até o recebimento.
