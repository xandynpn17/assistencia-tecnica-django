from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema
from configuracoes.permissions import (
    ORDER_ROLES,
    STOCK_MANAGE_ROLES,
    STOCK_VIEW_ROLES,
    has_role,
    require_sensitive_permission,
    role_required,
)
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa

from ..models import PontoOperacional, Produto, ReservaEstoque, UbicacaoEstoque
from ..services import criar_reserva_estoque
from .helpers import (
    _registrar_evento_estoque,
    cancelar_reserva,
    consumir_reservas_ordem,
    converter_reserva,
    datetime,
    devolver_reservas_ordem,
    expirar_reservas_vencidas,
)


@role_required(ORDER_ROLES)
def api_criar_reserva(request):
    empresa = obter_empresa_ativa(request, strict=True)
    config = ConfiguracaoSistema.get_configuracao()
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    produto = get_object_or_404(
        filtrar_queryset_empresa(Produto.objects.ativos().nao_servicos().filter(permite_os=True), empresa),
        id=request.POST.get("produto_id"),
    )
    ponto = get_object_or_404(PontoOperacional, id=request.POST.get("ponto_id"), ativo=True)
    nome = (request.POST.get("nome") or "").strip()
    telefone = (request.POST.get("telefone") or "").strip()
    ubicacao_id = (request.POST.get("ubicacao_id") or "").strip()
    try:
        quantidade = int(request.POST.get("quantidade") or "1")
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)
    if not nome:
        return JsonResponse({"ok": False, "erro": "Informe nome para reserva."}, status=400)
    valido_ate_raw = (request.POST.get("valido_ate") or "").strip()
    if not valido_ate_raw:
        valido_ate = timezone.localdate() + timedelta(days=int(getattr(config, "estoque_reserva_os_validade_dias", 3) or 3))
    else:
        try:
            valido_ate = datetime.strptime(valido_ate_raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "erro": "Data de validade invalida. Use YYYY-MM-DD."}, status=400)
    if quantidade <= 0:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)
    if valido_ate < timezone.localdate():
        return JsonResponse({"ok": False, "erro": "Data de validade da reserva nao pode ser passada."}, status=400)

    ubicacao = None
    if ubicacao_id.isdigit():
        ubicacao = (
            UbicacaoEstoque.objects.filter(id=int(ubicacao_id), ativo=True)
            .select_related("ponto_operacional")
            .first()
        )
        if not ubicacao:
            return JsonResponse({"ok": False, "erro": "Ubicacao informada nao foi encontrada."}, status=400)
        if ubicacao.ponto_operacional_id != ponto.id:
            return JsonResponse({"ok": False, "erro": "A ubicacao nao pertence ao ponto informado."}, status=400)
    elif getattr(produto, "ubicacao_padrao_id", None):
        ubicacao = produto.ubicacao_padrao

    try:
        reserva = criar_reserva_estoque(
            produto=produto,
            ponto_operacional=ponto,
            ubicacao=ubicacao,
            quantidade=quantidade,
            nome_contato=nome,
            telefone_contato=telefone,
            valido_ate=valido_ate,
            usuario=request.user,
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)
    _registrar_evento_estoque(
        "reserva_criada",
        usuario=request.user,
        reserva_id=reserva.id,
        produto_id=produto.id,
        ponto_id=ponto.id,
        quantidade=quantidade,
    )
    return JsonResponse({"ok": True, "codigo_reserva": reserva.codigo_reserva})


@role_required(STOCK_MANAGE_ROLES)
def api_expirar_reservas(request):
    empresa = obter_empresa_ativa(request, strict=True)
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    total = expirar_reservas_vencidas(usuario=request.user, empresa=empresa)
    _registrar_evento_estoque("reservas_expiradas_execucao", usuario=request.user, quantidade=total)
    return JsonResponse({"ok": True, "reservas_expiradas": total})


@role_required(STOCK_MANAGE_ROLES)
def api_converter_reserva(request, codigo_reserva):
    empresa = obter_empresa_ativa(request, strict=True)
    require_sensitive_permission(request.user, "perm_estoque_converter_reserva")
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    reserva = get_object_or_404(ReservaEstoque.objects.filter(produto__empresa=empresa), codigo_reserva=codigo_reserva)
    try:
        converter_reserva(reserva, usuario=request.user, motivo="Conversao manual")
        _registrar_evento_estoque("reserva_convertida", usuario=request.user, reserva_id=reserva.id)
        return JsonResponse({"ok": True})
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)


@role_required(STOCK_MANAGE_ROLES)
def api_cancelar_reserva(request, codigo_reserva):
    empresa = obter_empresa_ativa(request, strict=True)
    require_sensitive_permission(request.user, "perm_estoque_cancelar_reserva")
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    motivo = (request.POST.get("motivo") or "").strip() or "Cancelada manualmente"
    reserva = get_object_or_404(ReservaEstoque.objects.filter(produto__empresa=empresa), codigo_reserva=codigo_reserva)
    try:
        cancelar_reserva(reserva, usuario=request.user, motivo=motivo)
        _registrar_evento_estoque("reserva_cancelada", usuario=request.user, reserva_id=reserva.id)
        return JsonResponse({"ok": True})
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)


@role_required(STOCK_VIEW_ROLES)
def reservas_clientes(request):
    from ordens.models import LinhaTrabalho

    empresa = obter_empresa_ativa(request, strict=True)
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    quick = (request.GET.get("quick") or "").strip()
    ponto_id = (request.GET.get("ponto") or "").strip()
    page_number = request.GET.get("page")
    reservas = (
        ReservaEstoque.objects.select_related(
            "produto",
            "ponto_operacional",
            "ubicacao",
            "ordem_servico",
            "ordem_servico__tecnico_responsavel",
        )
        .filter(produto__empresa=empresa)
        .prefetch_related(
            Prefetch(
                "ordem_servico__linhas_trabalho",
                queryset=LinhaTrabalho.objects.select_related("usuario").order_by("id"),
            )
        )
    )
    if q:
        reservas = reservas.filter(Q(codigo_reserva__icontains=q) | Q(nome_contato__icontains=q) | Q(telefone_contato__icontains=q) | Q(produto__nome__icontains=q))
    if status:
        reservas = reservas.filter(status=status)
    if ponto_id.isdigit():
        reservas = reservas.filter(ponto_operacional_id=int(ponto_id))
    hoje = timezone.localdate()
    resumo_qs = reservas
    resumo = {
        "total": resumo_qs.count(),
        "ativas": resumo_qs.filter(status="ativa").count(),
        "vencidas": resumo_qs.filter(status="ativa", valido_ate__lt=hoje).count(),
        "sem_os": resumo_qs.filter(ordem_servico__isnull=True).count(),
        "com_os": resumo_qs.filter(ordem_servico__isnull=False).count(),
        "expiram_curto": resumo_qs.filter(status="ativa", valido_ate__lte=hoje + timedelta(days=2), valido_ate__gte=hoje).count(),
        "sem_estrutura": resumo_qs.filter(Q(ponto_operacional__isnull=True) | Q(ubicacao__isnull=True)).count(),
    }
    if quick == "ativas":
        reservas = reservas.filter(status="ativa")
    elif quick == "vencidas":
        reservas = reservas.filter(status="ativa", valido_ate__lt=hoje)
    elif quick == "expiram":
        reservas = reservas.filter(status="ativa", valido_ate__lte=hoje + timedelta(days=2), valido_ate__gte=hoje)
    elif quick == "sem_os":
        reservas = reservas.filter(ordem_servico__isnull=True)
    elif quick == "com_os":
        reservas = reservas.filter(ordem_servico__isnull=False)
    elif quick == "sem_estrutura":
        reservas = reservas.filter(Q(ponto_operacional__isnull=True) | Q(ubicacao__isnull=True))
    reservas_por_ponto = list(
        resumo_qs.filter(status="ativa")
        .values("ponto_operacional__codigo")
        .annotate(total=Count("id"))
        .order_by("-total", "ponto_operacional__codigo")[:8]
    )
    reservas = reservas.order_by("-criado_em", "-id")
    reservas_page = Paginator(reservas, 40).get_page(page_number)
    pontos_operacionais = list(PontoOperacional.objects.filter(ativo=True).order_by("codigo"))
    return render(
        request,
        "estoque/reservas_clientes.html",
        {
            "reservas": reservas_page,
            "reservas_page": reservas_page,
            "q": q,
            "status_filtro": status,
            "quick": quick,
            "ponto_filtro": ponto_id,
            "resumo": resumo,
            "reservas_por_ponto": reservas_por_ponto,
            "pontos_operacionais": pontos_operacionais,
            "status_choices": ReservaEstoque.STATUS_CHOICES,
            "can_manage": has_role(request.user, STOCK_MANAGE_ROLES),
            "hoje": hoje,
            "limite_proximo": hoje + timedelta(days=2),
            "menu_app": "estoque",
            "menu_sub": "reservas_clientes",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def associar_reserva_ordem(request, codigo_reserva):
    empresa = obter_empresa_ativa(request, strict=True)
    if request.method != "POST":
        return redirect("estoque:reservas_clientes")
    reserva = get_object_or_404(ReservaEstoque.objects.filter(produto__empresa=empresa), codigo_reserva=codigo_reserva)
    ordem_ref = (request.POST.get("ordem_id") or "").strip()
    if not ordem_ref:
        messages.error(request, "Informe o ID ou numero da ordem.")
        return redirect("estoque:reservas_clientes")
    from ordens.models import OrdemServico
    ordem = OrdemServico.objects.filter(empresa=empresa).filter(Q(numero_os__iexact=ordem_ref) | Q(id=ordem_ref if ordem_ref.isdigit() else None)).first()
    if not ordem:
        messages.error(request, "Ordem nao encontrada.")
        return redirect("estoque:reservas_clientes")
    reserva.ordem_servico = ordem
    reserva.save(update_fields=["ordem_servico"])
    messages.success(request, f"Reserva {reserva.codigo_reserva} associada a OS {ordem.numero_os}.")
    return redirect("estoque:reservas_clientes")


@role_required(STOCK_MANAGE_ROLES)
def expirar_reservas_web(request):
    empresa = obter_empresa_ativa(request, strict=True)
    if request.method == "POST":
        total = expirar_reservas_vencidas(usuario=request.user, empresa=empresa)
        messages.success(request, f"Reservas expiradas: {total}.")
    return redirect("estoque:reservas_clientes")


@role_required(STOCK_MANAGE_ROLES)
def converter_reserva_web(request, codigo_reserva):
    empresa = obter_empresa_ativa(request, strict=True)
    require_sensitive_permission(request.user, "perm_estoque_converter_reserva")
    if request.method == "POST":
        reserva = get_object_or_404(ReservaEstoque.objects.filter(produto__empresa=empresa), codigo_reserva=codigo_reserva)
        try:
            converter_reserva(reserva, usuario=request.user, motivo="Conversao manual")
            messages.success(request, f"Reserva {reserva.codigo_reserva} convertida.")
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("estoque:reservas_clientes")


@role_required(STOCK_MANAGE_ROLES)
def cancelar_reserva_web(request, codigo_reserva):
    empresa = obter_empresa_ativa(request, strict=True)
    require_sensitive_permission(request.user, "perm_estoque_cancelar_reserva")
    if request.method == "POST":
        reserva = get_object_or_404(ReservaEstoque.objects.filter(produto__empresa=empresa), codigo_reserva=codigo_reserva)
        try:
            cancelar_reserva(reserva, usuario=request.user, motivo="Cancelamento manual")
            messages.success(request, f"Reserva {reserva.codigo_reserva} cancelada.")
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("estoque:reservas_clientes")


def integrar_reservas_no_fechamento(ordem, usuario=None):
    return consumir_reservas_ordem(ordem, usuario=usuario)


def integrar_reservas_na_reabertura(ordem, usuario=None):
    return devolver_reservas_ordem(ordem, usuario=usuario)


__all__ = [
    "api_criar_reserva",
    "api_expirar_reservas",
    "api_converter_reserva",
    "api_cancelar_reserva",
    "reservas_clientes",
    "associar_reserva_ordem",
    "expirar_reservas_web",
    "converter_reserva_web",
    "cancelar_reserva_web",
    "integrar_reservas_no_fechamento",
    "integrar_reservas_na_reabertura",
]




