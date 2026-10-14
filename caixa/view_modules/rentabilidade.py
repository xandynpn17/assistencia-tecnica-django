from django.shortcuts import render

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa
from ordens.models import OrdemServico
from ordens.services.rentabilidade import resumo_rentabilidade_os
from decimal import Decimal


@role_required(CAIXA_FINANCIAL_ROLES)
def rentabilidade_os(request):
    require_sensitive_permission(request.user, "perm_os_ver_custos")
    empresa = obter_empresa_ativa(request)
    ordens = OrdemServico.objects.filter(empresa=empresa).prefetch_related("servicos_pecas", "custos_internos").order_by("-data_abertura")[:50]
    linhas = [resumo_rentabilidade_os(ordem) for ordem in ordens]
    grupos = {}
    for linha in linhas:
        ordem = linha["ordem"]
        chave = (ordem.tipo_equipamento or "Não informado", ordem.marca_equipamento or "Não informada", ordem.modelo_equipamento or "Não informado")
        grupo = grupos.setdefault(chave, {"tipo": chave[0], "marca": chave[1], "modelo": chave[2], "quantidade": 0, "provisorias": 0, "receita": Decimal("0.00"), "margem": Decimal("0.00")})
        grupo["quantidade"] += 1
        grupo["provisorias"] += not linha["margem_confirmada"]
        grupo["receita"] += linha["receita_registrada"]
        grupo["margem"] += linha["margem_referencia"]
    return render(request, "caixa/rentabilidade_os.html", {"linhas": linhas, "grupos": sorted(grupos.values(), key=lambda item: -item["quantidade"]), "menu_app": "caixa", "menu_sub": "rentabilidade_os"})
