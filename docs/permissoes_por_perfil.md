# Matriz de Permissoes por Perfil

## Perfis
- `adm`: acesso total operacional.
- `gerente`: acesso operacional + configuracoes (sem administrar admins existentes).
- `atendente`: operacao de atendimento.
- `portal`: sem acesso ao backoffice.

## Rotas principais
| Modulo | Rota | Atendente | Gerente | Admin |
|---|---|---:|---:|---:|
| Clientes | `clientes:lista_clientes` | Sim | Sim | Sim |
| Clientes | `clientes:detalhes_cliente` | Sim | Sim | Sim |
| Clientes | `clientes:editar_cliente` | Sim | Sim | Sim |
| Clientes | `clientes:excluir_cliente` | Nao | Sim | Sim |
| Ordens | `ordens:verificar_cliente_os` | Sim | Sim | Sim |
| Ordens | `ordens:nova_ordem_cliente` | Sim | Sim | Sim |
| Ordens | `ordens:detalhes_ordem` | Sim | Sim | Sim |
| Ordens | `ordens:toggle_fechamento_os` | Sim | Sim | Sim |
| Configuracoes | `configuracoes:painel` | Nao | Sim | Sim |
| Configuracoes | `configuracoes:adicionar_usuario` | Nao | Sim | Sim |
| Configuracoes | `configuracoes:lista_usuarios` | Nao | Nao | Sim |
| Configuracoes | `configuracoes:backup_banco` | Nao | Sim | Sim |

## Observacoes
- Criacao de usuario por `gerente`: permitida, exceto tipo `adm`.
- Exclusao/edicao de usuarios: apenas `adm`.
- Rota de CEP (`configuracoes:buscar_cep`): liberada para equipe operacional.
