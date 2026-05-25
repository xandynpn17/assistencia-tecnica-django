# Homologação em Rede Local

Objetivo: validar o uso inicial com 2 ou 3 PCs acessando o sistema pelo navegador, com um PC principal como servidor local.

## 1. Preparar o PC Servidor

1. Configure PostgreSQL e `.env.local`.
2. Valide o ambiente:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\run_local.ps1 -CheckOnly
```

3. Inicie o sistema na rede:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\run_local.ps1
```

4. Anote o endereço exibido, por exemplo:

```text
http://192.168.1.50:8000/
```

## 2. Testar Acesso Dos PCs Clientes

Em cada PC cliente, abra o PowerShell e execute:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\test_local_network.ps1 -ServerIp 192.168.1.50 -OpenBrowser
```

Se a porta falhar:

- confirme se o servidor está rodando;
- confirme se os PCs estão na mesma rede;
- libere a porta 8000 no firewall do Windows do PC servidor;
- prefira IP fixo ou reserva DHCP para o servidor.

## 3. Fluxos Operacionais Para Validar

### Login e Sessões

- Entrar em 2 PCs ao mesmo tempo com usuários diferentes.
- Confirmar que atendente/técnico não acessa telas sensíveis.
- Confirmar que gerente/admin acessa configurações, backup e indicadores.

### Ordem de Serviço

- PC 1 abre uma OS nova.
- PC 2 pesquisa a OS criada e abre os detalhes.
- PC 1 altera status ou técnico responsável.
- PC 2 recarrega a OS e confirma que a alteração apareceu.
- Gerar PDF/etiqueta da OS.

### Orçamento e Serviços/Peças

- Adicionar serviço manual.
- Adicionar peça do estoque.
- Validar reserva automática quando aplicável.
- Aprovar/recusar orçamento.
- Confirmar que a OS evolui corretamente.

### Caixa

- Registrar pagamento de OS.
- Efetuar venda a mostrador.
- Testar cancelamento/estorno apenas com perfil autorizado.
- Conferir se atendente/técnico não enxerga relatórios financeiros sensíveis.

### Estoque

- Criar produto com estoque inicial.
- Movimentar entrada/saída.
- Reservar peça para OS.
- Confirmar baixa após pagamento quando o fluxo exigir.

### Arquivos e PDFs

- Upload de logo, anexos e assinaturas.
- Abrir PDFs em PC cliente.
- Conferir se textos não sobrepõem em etiquetas e guias.

## 4. Backup Durante Homologação

1. Faça um backup antes de começar o teste com dados reais.
2. Faça outro backup no fim do expediente.
3. Copie semanalmente para fora do PC servidor.
4. Valide restore em uma base separada antes de confiar no backup.

## 5. Critérios De Aceite

- 2 ou 3 PCs conseguem operar ao mesmo tempo.
- Abertura e atualização de OS aparecem entre máquinas.
- Caixa e estoque não geram conflito operacional.
- Uploads e PDFs funcionam nos PCs clientes.
- Backup fica centralizado no servidor.
- Usuários sem permissão veem bloqueio amigável ou não veem menus sensíveis.
