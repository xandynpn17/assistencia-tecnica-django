from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import ORDER_ROLES, STOCK_MANAGE_ROLES, STOCK_VIEW_ROLES, has_role, role_required

from ..models import PontoOperacional, Produto, ReservaEstoque, SaldoEstoquePonto
from .helpers import _codigo_reserva, _normalizar_saldos_produto, cancelar_reserva, consumir_reservas_ordem, converter_reserva, devolver_reservas_ordem, datetime, expirar_reservas_vencidas, logger


@role_required(ORDER_ROLES)
def api_criar_reserva(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    produto = get_object_or_404(Produto, id=request.POST.get("produto_id"), ativo=True, is_servico=False, permite_os=True)
    ponto = get_object_or_404(PontoOperacional, id=request.POST.get("ponto_id"), ativo=True)
    nome = (request.POST.get("nome") or "").strip()
    telefone = (request.POST.get("telefone") or "").strip()
    try:
        quantidade = int(request.POST.get("quantidade") or "1")
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)
    if not nome:
        return JsonResponse({"ok": False, "erro": "Informe nome para reserva."}, status=400)
    valido_ate_raw = (request.POST.get("valido_ate") or "").strip()
    try:
        valido_ate = datetime.strptime(valido_ate_raw, "%Y-%m-%d").date()
    except Exception:
        return JsonResponse({"ok": False, "erro": "Data de validade invalida. Use YYYY-MM-DD."}, status=400)
    if quantidade <= 0:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)
    if valido_ate < timezone.localdate():
        return JsonResponse({"ok": False, "erro": "Data de validade da reserva nao pode ser passada."}, status=400)

    expirar_reservas_vencidas()
    _normalizar_saldos_produto(produto)
    with transaction.atomic():
        saldo = SaldoEstoquePonto.objects.select_for_update().filter(produto=produto, ponto_operacional=ponto).first()
        if not saldo:
            saldo = SaldoEstoquePonto.objects.create(produto=produto, ponto_operacional=ponto, quantidade=0)
        reservado = ReservaEstoque.objects.select_for_update().filter(produto=produto, ponto_operacional=ponto, status="ativa", valido_ate__gte=timezone.localdate()).aggregate(total=Sum("quantidade"))["total"] or 0
        disponivel = int(saldo.quantidade) - int(reservado)
        if disponivel < quantidade:
            return JsonResponse({"ok": False, "erro": "Sem saldo disponivel para reservar neste ponto."}, status=400)
        reserva = ReservaEstoque.objects.create(codigo_reserva=_codigo_reserva(), produto=produto, ponto_operacional=ponto, quantidade=quantidade, nome_contato=nome, telefone_contato=telefone, valido_ate=valido_ate, status="ativa", usuario=request.user)
    logger.info("reserva_criada", extra={"reserva_id": reserva.id, "produto_id": produto.id, "ponto_id": ponto.id, "quantidade": quantidade, "usuario_id": request.user.id})
    return JsonResponse({"ok": True, "codigo_reserva": reserva.codigo_reserva})


@role_required(STOCK_MANAGE_ROLES)
def api_expirar_reservas(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    total = expirar_reservas_vencidas(usuario=request.user)
    logger.info("reservas_expiradas_execucao", extra={"quantidade": total, "usuario_id": request.user.id})
    return JsonResponse({"ok": True, "reservas_expiradas": total})


@role_required(STOCK_MANAGE_ROLES)
def api_converter_reserva(request, codigo_reserva):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    reserva = get_object_or_404(ReservaEstoque, codigo_reserva=codigo_reserva)
    try:
        converter_reserva(reserva, usuario=request.user, motivo="Conversao manual")
        logger.info("reserva_convertida", extra={"reserva_id": reserva.id, "usuario_id": request.user.id})
        return JsonResponse({"ok": True})
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)


@role_required(STOCK_MANAGE_ROLES)
def api_cancelar_reserva(request, codigo_reserva):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    motivo = (request.POST.get("motivo") or "").strip() or "Cancelada manualmente"
    reserva = get_object_or_404(ReservaEstoque, codigo_reserva=codigo_reserva)
    try:
        cancelar_reserva(reserva, usuario=request.user, motivo=motivo)
        logger.info("reserva_cancelada", extra={"reserva_id": reserva.id, "usuario_id": request.user.id})
        return JsonResponse({"ok": True})
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)


@role_required(STOCK_VIEW_ROLES)
def reservas_clientes(request):
    from ordens.models import LinhaTrabalho

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    page_number = request.GET.get("page")
    reservas = (
        ReservaEstoque.objects.select_related("produto", "ponto_operacional", "ordem_servico", "ordem_servico__tecnico_responsavel")
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
    reservas = reservas.order_by("-criado_em", "-id")
    reservas_page = Paginator(reservas, 40).get_page(page_number)
    return render(
        request,
        "estoque/reservas_clientes.html",
        {
            "reservas": reservas_page,
            "reservas_page": reservas_page,
            "q": q,
            "status_filtro": status,
            "status_choices": ReservaEstoque.STATUS_CHOICES,
            "can_manage": has_role(request.user, STOCK_MANAGE_ROLES),
            "menu_app": "estoque",
            "menu_sub": "reservas_clientes",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def associar_reserva_ordem(request, codigo_reserva):
    if request.method != "POST":
        return redirect("estoque:reservas_clientes")
    reserva = get_object_or_404(ReservaEstoque, codigo_reserva=codigo_reserva)
    ordem_id = request.POST.get("ordem_id")
    if not ordem_id:
        messages.error(request, "Informe o numero da ordem (ID).")
        return redirect("estoque:reservas_clientes")
    from ordens.models import OrdemServico
    ordem = OrdemServico.objects.filter(id=ordem_id).first()
    if not ordem:
        messages.error(request, "Ordem nao encontrada.")
        return redirect("estoque:reservas_clientes")
    reserva.ordem_servico = ordem
    reserva.save(update_fields=["ordem_servico"])
    messages.success(request, f"Reserva {reserva.codigo_reserva} associada a OS {ordem.numero_os}.")
    return redirect("estoque:reservas_clientes")


@role_required(STOCK_MANAGE_ROLES)
def expirar_reservas_web(request):
    if request.method == "POST":
        total = expirar_reservas_vencidas(usuario=request.user)
        messages.success(request, f"Reservas expiradas: {total}.")
    return redirect("estoque:reservas_clientes")


@role_required(STOCK_MANAGE_ROLES)
def converter_reserva_web(request, codigo_reserva):
    if request.method == "POST":
        reserva = get_object_or_404(ReservaEstoque, codigo_reserva=codigo_reserva)
        try:
            converter_reserva(reserva, usuario=request.user, motivo="Conversao manual")
            messages.success(request, f"Reserva {reserva.codigo_reserva} convertida.")
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("estoque:reservas_clientes")


@role_required(STOCK_MANAGE_ROLES)
def cancelar_reserva_web(request, codigo_reserva):
    if request.method == "POST":
        reserva = get_object_or_404(ReservaEstoque, codigo_reserva=codigo_reserva)
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
