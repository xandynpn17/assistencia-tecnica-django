# Sistema de Gestao para Assistencia Tecnica

Projeto Django para operacao de assistencia tecnica de eletronicos, com foco em fluxo rapido para:

- clientes
- ordens de servico
- estoque
- servicos e pecas
- tecnicos
- financeiro

## Estrutura atual

O projeto ja possui estes apps:

- `core`
- `clientes`
- `ordens`
- `estoque`
- `orcamentos`
- `caixa`
- `configuracoes`

Resumo do papel de cada um:

- `clientes`: cadastro e historico do cliente
- `ordens`: abertura, acompanhamento e conclusao da OS
- `estoque`: pecas, produtos, servicos e movimentacoes
- `orcamentos`: itens e aprovacao de orcamentos
- `caixa`: pagamentos, contas e comissoes
- `configuracoes`: usuarios, empresa e parametros do sistema

## Prioridade atual

Consolidar o fluxo principal:

1. cadastrar cliente
2. criar OS
3. informar equipamento e defeito
4. adicionar servicos e pecas
5. calcular totais
6. aprovar e concluir

## Observacao importante sobre servicos e tecnicos

Na base atual:

- servicos ficam em `estoque.Produto` com `tipo_item="servico"`
- tecnicos usam o modelo `configuracoes.User` com perfil tecnico

Isso evita duplicacao agora e permite continuar o desenvolvimento sem abrir apps novos neste momento.

## Ambiente de desenvolvimento

Abra o workspace do VS Code na pasta do projeto Django:

- `C:\Users\Xandy\Documents\projetodjango\assistencia`

Nao abra a pasta pai `projetodjango` para desenvolver este app, porque `manage.py`, `requirements.txt` e o `.venv` correto ficam dentro de `assistencia`.

Passos sugeridos no VS Code para recriar o ambiente:

1. instalar Python 3.13
2. abrir a pasta `assistencia`
3. recriar a `.venv` na raiz do projeto
4. instalar dependencias de `requirements.txt`
5. executar `check`, migracoes e servidor

Comandos esperados:

```powershell
cd C:\Users\Xandy\Documents\projetodjango\assistencia
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

## Documentacao complementar

Analise da arquitetura atual: `docs/revisao_arquitetura.md`
