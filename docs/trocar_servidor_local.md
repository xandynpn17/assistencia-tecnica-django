# Trocar Servidor Local

Checklist para mover a instalação local para outro PC sem perder dados.

## 1. No PC antigo

1. Pare o uso do sistema nos outros computadores.
2. Gere um backup completo pelo menu de configurações ou pelo comando:

```powershell
py -3.12 manage.py backup_db --include-media
```

3. Copie a pasta gerada em `backups\backup_AAAAMMDD_HHMMSS\` para um pendrive, NAS ou nuvem.
4. Confirme que a pasta possui:
   - `database.dump`
   - `manifest.json`
   - `media.zip`, quando houver logos, anexos, assinaturas ou arquivos enviados.

## 2. No PC novo

1. Instale PostgreSQL, Python e dependências do projeto.
2. Configure o arquivo local de ambiente com as credenciais do banco.
3. Rode as migrations em uma base vazia:

```powershell
py -3.12 manage.py migrate
```

4. Copie a pasta do backup para `backups\`.
5. Acesse o sistema pelo navegador.
6. Na tela de setup inicial, clique em **Restaurar backup** antes de concluir a configuração manual.
7. Marque:
   - restaurar `media.zip`, se existir;
   - reparar dados antigos sem empresa ativa, recomendado para backups de versões anteriores.

## 3. Validação Depois Do Restore

1. Entrar com um usuário administrador.
2. Verificar Dashboard, clientes, ordens, estoque e caixa.
3. Abrir uma OS antiga e confirmar que cliente, equipamento, orçamento e histórico aparecem.
4. Abrir Configurações > Empresa e conferir dados da empresa.
5. Rodar o diagnóstico:

```powershell
py -3.12 manage.py check_tenant_data --strict
```

Se houver registros sem empresa em uma instalação local de empresa única:

```powershell
py -3.12 manage.py repair_single_tenant_data --force
```

## 4. Rede Local

1. Deixe o servidor rodando apenas no PC principal.
2. Os outros PCs acessam pelo navegador usando o IP do servidor.
3. Garanta IP fixo ou reserva DHCP para o PC servidor.
4. Mantenha backup diário no servidor e cópia externa semanal.
