from django.db import transaction

from caixa.view_modules.helpers import (
    _garantir_categorias_financeiras_padrao,
    _garantir_centros_custo_padrao,
    _garantir_formas_pagamento_padrao,
)
from configuracoes.models import (
    ConfiguracaoOrdemServico,
    ConfiguracaoSistema,
    SetupInicialSistema,
    UsuarioEmpresa,
)
from configuracoes.services.setup_inicial import sincronizar_tipos_ativos_por_linhas
from estoque.services_estrutura import garantir_estrutura_estoque_padrao


@transaction.atomic
def provisionar_empresa(*, empresa, usuario_admin, setup_origem=None):
    """Cria um tenant operacional completo, sem compartilhar cadastros transacionais."""
    empresa.save()
    UsuarioEmpresa.objects.update_or_create(
        usuario=usuario_admin,
        empresa=empresa,
        defaults={"ativo": True, "padrao": False, "tipo_usuario": "adm"},
    )

    ConfiguracaoSistema.get_configuracao(empresa=empresa)
    ConfiguracaoOrdemServico.get_configuracao(empresa=empresa)
    garantir_estrutura_estoque_padrao(empresa=empresa)
    _garantir_formas_pagamento_padrao(empresa)
    _garantir_centros_custo_padrao(empresa)
    _garantir_categorias_financeiras_padrao(empresa)

    setup, _ = SetupInicialSistema.objects.get_or_create(empresa=empresa)
    if setup_origem:
        setup.tipo_empresa = setup_origem.tipo_empresa
    setup.concluido = True
    setup.save(update_fields=["tipo_empresa", "concluido", "atualizado_em"])
    if setup_origem:
        linhas = setup_origem.linhas_atuacao.all()
        setup.linhas_atuacao.set(linhas)
        if linhas.exists():
            sincronizar_tipos_ativos_por_linhas(linhas, empresa=empresa)
    return empresa
