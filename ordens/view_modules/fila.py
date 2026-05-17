from django.contrib.auth import get_user_model
from django.shortcuts import render

from configuracoes.permissions import ORDER_ROLES, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa
from ordens.models import OrdemServico
from ordens.services.fila_bancada import STATUS_ATIVOS_FILA, montar_fila_bancada


@role_required(ORDER_ROLES)
def fila_bancada_tecnicos(request):
    empresa = obter_empresa_ativa(request, strict=False)
    tecnico_id = (request.GET.get("tecnico_id") or "").strip()
    status = (request.GET.get("status") or "").strip()
    prioridade = (request.GET.get("prioridade") or "").strip()

    itens = montar_fila_bancada(
        empresa=empresa,
        tecnico_id=tecnico_id,
        status=status,
        prioridade=prioridade,
    )
    tecnicos = (
        get_user_model()
        .objects.filter(is_active=True, tipo_usuario="tecnico")
        .order_by("username")
    )

    return render(
        request,
        "ordens/fila_bancada.html",
        {
            "menu_app": "ordens",
            "menu_sub": "fila_bancada",
            "itens": itens,
            "tecnicos": tecnicos,
            "status_disponiveis": [
                (codigo, label)
                for codigo, label in OrdemServico.STATUS_CHOICES
                if codigo in STATUS_ATIVOS_FILA
            ],
            "filtro_tecnico_id": tecnico_id,
            "filtro_status": status,
            "filtro_prioridade": prioridade,
        },
    )
