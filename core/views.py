from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Prefetch, Q, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from datetime import timedelta

from django.utils import timezone

from caixa.models import ContaReceber, Pagamento, PagamentoContaPagar
from clientes.models import Cliente, ORIGEM_CLIENTE_CHOICES
from configuracoes.permissions import ORDER_ROLES, has_role
from configuracoes.services.setup_inicial import setup_inicial_concluido
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa
from ordens.models import LinhaTrabalho, OrdemServico, ServicoPeca
from orcamentos.models import Orcamento
from django.conf import settings


def _dashboard_shared_context(request):
    from configuracoes.services.sla import calcular_pendencias_sla, resumo_pendencias_por_regra

    tipo_usuario = getattr(request.user, "tipo_usuario", "")
    is_managerial = request.user.is_superuser or tipo_usuario in {"adm", "gerente"}
    is_operational = (tipo_usuario in {"atendente", "tecnico"}) and not is_managerial
    empresa = obter_empresa_ativa(request, strict=True)

    clientes_qs = filtrar_queryset_empresa(Cliente.objects.all(), empresa)
    ordens_qs = filtrar_queryset_empresa(OrdemServico.objects.all(), empresa)

    total_clientes = clientes_qs.count()
    total_ordens = ordens_qs.count()
    total_ordens_abertas = ordens_qs.filter(fechada=False).count()
    total_ordens_finalizadas = ordens_qs.filter(fechada=True).count()
    today = timezone.localdate()
    inicio_mes = today.replace(day=1)
    ordens_finalizadas_mes = ordens_qs.filter(
        fechada=True,
        data_conclusao__date__gte=inicio_mes,
        data_conclusao__date__lte=today,
    ).count()

    status_counts = (
        ordens_qs.filter(fechada=False)
        .values("status")
        .annotate(total=Count("id"))
    )
    status_dict = {item["status"]: item["total"] for item in status_counts}
    status_cards = [
        {
            "status": status,
            "label": label,
            "total": status_dict.get(status, 0),
            "url": f"{reverse('ordens:lista_ordens')}?carregar=1&status={status}",
        }
        for status, label in OrdemServico.STATUS_CHOICES
        if status != "concluida"
    ]
    ordens_recentes = (
        ordens_qs.select_related("cliente", "tecnico_responsavel")
        .prefetch_related(
            Prefetch(
                "linhas_trabalho",
                queryset=LinhaTrabalho.objects.select_related("usuario").order_by("id"),
            )
        )
        .filter(fechada=False)
        .order_by("-data_abertura")[:5]
    )
    pendencias_sla = calcular_pendencias_sla(empresa=empresa)
    pendencias_sla_preview = pendencias_sla[:5]
    resumo_sla = resumo_pendencias_por_regra(pendencias_sla)

    return {
        "empresa": empresa,
        "total_clientes": total_clientes,
        "total_ordens": total_ordens,
        "total_ordens_abertas": total_ordens_abertas,
        "total_ordens_finalizadas": total_ordens_finalizadas,
        "ordens_finalizadas_mes": ordens_finalizadas_mes,
        "dashboard_mes_referencia": today,
        "status_cards": status_cards,
        "ordens_recentes": ordens_recentes,
        "pendencias_sla_total": len(pendencias_sla),
        "pendencias_sla_preview": pendencias_sla_preview,
        "pendencias_sla_resumo": resumo_sla,
        "is_operational": is_operational,
        "is_managerial": is_managerial,
        "dashboard_links": {
            "abertas": f"{reverse('ordens:lista_ordens')}?carregar=1",
            "fechadas": f"{reverse('ordens:lista_ordens')}?carregar=1&status=concluida",
            "sem_tecnico": f"{reverse('ordens:lista_ordens')}?carregar=1&quick=sem_tecnico",
            "prontas": f"{reverse('ordens:lista_ordens')}?carregar=1&quick=prontas",
            "criticas": f"{reverse('ordens:lista_ordens')}?carregar=1&quick=criticas",
            "paradas": f"{reverse('ordens:lista_ordens')}?carregar=1&quick=paradas_15",
        },
        "menu_app": "core",
    }


def _dashboard_managerial_context(*, empresa=None):
    from configuracoes.services.sla import calcular_pendencias_sla

    sem_tecnico_q = Q(tecnico_responsavel__isnull=True) | ~Q(tecnico_responsavel__tipo_usuario="tecnico")
    clientes_qs = filtrar_queryset_empresa(Cliente.objects.all(), empresa)
    ordens_qs = filtrar_queryset_empresa(OrdemServico.objects.all(), empresa)
    total_clientes = clientes_qs.count()
    total_ordens = ordens_qs.count()
    total_ordens_abertas = ordens_qs.filter(fechada=False).count()
    total_ordens_finalizadas = ordens_qs.filter(fechada=True).count()
    today = timezone.localdate()
    inicio_mes = today.replace(day=1)
    ordens_finalizadas_mes = ordens_qs.filter(
        fechada=True,
        data_conclusao__date__gte=inicio_mes,
        data_conclusao__date__lte=today,
    ).count()

    ordens_sem_tecnico = ordens_qs.filter(fechada=False).filter(sem_tecnico_q).count()
    ordens_prontas = ordens_qs.filter(
        fechada=False, status="pronto_contactado"
    ).count()
    ordens_criticas = ordens_qs.filter(
        fechada=False,
        status__in={"pendente_cliente", "pendente_tecnico", "pendente_pecas", "pendente_marca"},
    ).count()
    limite_parada = timezone.now() - timedelta(days=15)
    ordens_paradas = ordens_qs.filter(
        fechada=False,
        status__in={"pendente_cliente", "pendente_tecnico", "pendente_pecas", "pendente_marca"},
        data_abertura__lte=limite_parada,
    ).count()
    ordens_pendente_cliente = ordens_qs.filter(fechada=False, status="pendente_cliente").count()
    ordens_pendente_pecas = ordens_qs.filter(fechada=False, status="pendente_pecas").count()
    ordens_autorizadas = ordens_qs.filter(fechada=False, status="autorizado").count()
    ordens_recusadas = ordens_qs.filter(status="recusado").count()
    ordens_reabertas = ordens_qs.filter(fechada=False, status="concluida").count()
    clientes_mes = clientes_qs.filter(data_cadastro__date__gte=inicio_mes, data_cadastro__date__lte=today).count()
    despesas_pagas_mes_qs = PagamentoContaPagar.objects.filter(
        data__date__gte=inicio_mes,
        data__date__lte=today,
    )
    if empresa:
        despesas_pagas_mes_qs = despesas_pagas_mes_qs.filter(conta__empresa=empresa)
    despesas_totais_mes = despesas_pagas_mes_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    despesas_marketing_mes = (
        despesas_pagas_mes_qs.filter(
            Q(conta__categoria__nome__icontains="marketing") | Q(conta__centro_custo__nome__icontains="marketing")
        ).aggregate(total=Sum("valor"))["total"]
        or Decimal("0.00")
    )
    cac_medio = None
    if clientes_mes:
        cac_medio = (despesas_marketing_mes / Decimal(clientes_mes)).quantize(Decimal("0.01"))
    origens_clientes_mes = [
        {
            "origem": dict(ORIGEM_CLIENTE_CHOICES).get(row["origem_cliente"], row["origem_cliente"] or "Não informado"),
            "total": row["total"],
        }
        for row in (
            clientes_qs.filter(data_cadastro__date__gte=inicio_mes, data_cadastro__date__lte=today)
            .values("origem_cliente")
            .annotate(total=Count("id"))
            .order_by("-total", "origem_cliente")
        )
        if row["total"] > 0
    ]
    contas_os_abertas = ContaReceber.objects.filter(
        ordem_servico__isnull=False,
        status__in=["aberta", "parcial", "vencida"],
        valor_aberto__gt=0,
    )
    if empresa:
        contas_os_abertas = contas_os_abertas.filter(ordem_servico__empresa=empresa)
    ordens_concluidas_sem_pagamento = contas_os_abertas.filter(ordem_servico__fechada=True).count()
    valor_aberto_ordens = contas_os_abertas.aggregate(total=Sum("valor_aberto"))["total"] or 0
    ordens_fechadas_com_saldo = list(
        contas_os_abertas.filter(ordem_servico__fechada=True)
        .select_related("ordem_servico", "ordem_servico__cliente")
        .order_by("-valor_aberto", "vencimento")[:10]
    )
    prontas_sem_recebimento_total = (
        contas_os_abertas.filter(ordem_servico__fechada=False, ordem_servico__status="pronto_contactado")
        .aggregate(total=Sum("valor_aberto"))["total"]
        or 0
    )
    recebimentos_mes_qs = Pagamento.objects.filter(
        ordem_servico__isnull=False,
        data__date__gte=inicio_mes,
        data__date__lte=today,
    )
    if empresa:
        recebimentos_mes_qs = recebimentos_mes_qs.filter(ordem_servico__empresa=empresa)
    recebimentos_mes_os = recebimentos_mes_qs.aggregate(total=Sum("valor"))["total"] or 0
    orcamentos_qs = Orcamento.objects.filter(data_criacao__date__gte=inicio_mes, data_criacao__date__lte=today)
    if empresa:
        orcamentos_qs = orcamentos_qs.filter(empresa=empresa)
    orcamentos_total_mes = orcamentos_qs.count()
    orcamentos_aprovados_mes = orcamentos_qs.filter(status="aprovado").count()
    orcamentos_recusados_mes = orcamentos_qs.filter(status="recusado").count()
    conversao_orcamento = 0
    if orcamentos_total_mes:
        conversao_orcamento = round((orcamentos_aprovados_mes / orcamentos_total_mes) * 100, 1)
    taxa_recusa = 0
    decisoes_orcamento = orcamentos_aprovados_mes + orcamentos_recusados_mes
    if decisoes_orcamento:
        taxa_recusa = round((orcamentos_recusados_mes / decisoes_orcamento) * 100, 1)
    ordens_concluidas_mes_qs = ordens_qs.filter(
        fechada=True,
        data_conclusao__date__gte=inicio_mes,
        data_conclusao__date__lte=today,
    )
    ticket_medio_os_mes = 0
    total_concluidas_mes = ordens_concluidas_mes_qs.count()
    if total_concluidas_mes:
        total_item_expr = ExpressionWrapper(
            F("quantidade") * F("valor_unitario"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        total_receita_mes = (
            ServicoPeca.objects.filter(ordem__in=ordens_concluidas_mes_qs)
            .aggregate(total=Sum(total_item_expr))["total"]
            or Decimal("0.00")
        )
        ticket_medio_os_mes = round(total_receita_mes / total_concluidas_mes, 2)
    pendencias_sla = calcular_pendencias_sla(empresa=empresa)
    total_pendencias_sla = len(pendencias_sla)
    pendencias_parceiro = sum(1 for p in pendencias_sla if p.codigo_regra == "parceiro_externo_atrasado")

    return {
        "gerencial_cards": {
            "clientes_total": total_clientes,
            "ordens_total": total_ordens,
            "abertas_total": total_ordens_abertas,
            "fechadas_mes": ordens_finalizadas_mes,
            "fechadas_total": total_ordens_finalizadas,
            "sem_tecnico": ordens_sem_tecnico,
            "prontas": ordens_prontas,
            "criticas": ordens_criticas,
            "paradas": ordens_paradas,
            "pendente_cliente": ordens_pendente_cliente,
            "pendente_pecas": ordens_pendente_pecas,
            "autorizadas": ordens_autorizadas,
            "recusadas": ordens_recusadas,
            "reabertas": ordens_reabertas,
            "clientes_mes": clientes_mes,
            "concluidas_sem_pagamento": ordens_concluidas_sem_pagamento,
            "valor_aberto_ordens": valor_aberto_ordens,
            "prontas_sem_recebimento_total": prontas_sem_recebimento_total,
            "recebimentos_mes_os": recebimentos_mes_os,
            "orcamentos_total_mes": orcamentos_total_mes,
            "orcamentos_aprovados_mes": orcamentos_aprovados_mes,
            "orcamentos_recusados_mes": orcamentos_recusados_mes,
            "conversao_orcamento": conversao_orcamento,
            "taxa_recusa": taxa_recusa,
            "ticket_medio_os_mes": ticket_medio_os_mes,
            "despesas_totais_mes": despesas_totais_mes,
            "despesas_marketing_mes": despesas_marketing_mes,
            "cac_medio": cac_medio,
            "pendencias_sla_total": total_pendencias_sla,
            "pendencias_sla_parceiro": pendencias_parceiro,
        },
        "origens_clientes_mes": origens_clientes_mes,
        "ordens_fechadas_com_saldo": ordens_fechadas_com_saldo,
    }


# ---------------------
# DASHBOARD
# ---------------------
@login_required(login_url="core:login")
def dashboard(request):
    if not has_role(request.user, ORDER_ROLES):
        raise PermissionDenied

    context = _dashboard_shared_context(request)
    context["menu_sub"] = "dashboard"

    return render(request, "core/dashboard.html", context)


@login_required(login_url="core:login")
def dashboard_indicadores(request):
    if not has_role(request.user, ORDER_ROLES):
        raise PermissionDenied

    if not (request.user.is_superuser or getattr(request.user, "tipo_usuario", "") in {"adm", "gerente"}):
        raise PermissionDenied

    context = _dashboard_shared_context(request)
    context.update(_dashboard_managerial_context(empresa=context.get("empresa")))
    context["menu_sub"] = "dashboard_indicadores"
    return render(request, "core/dashboard_indicadores.html", context)


# ---------------------
# LOGIN / LOGOUT
# ---------------------
def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    setup_pendente = not setup_inicial_concluido()
    context = {
        "setup_pendente": setup_pendente,
        "local_recovery_enabled": bool(getattr(settings, "LOCAL_RECOVERY_KEY", "")),
    }

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("core:dashboard")
        messages.error(request, "Usuario ou senha invalidos.", extra_tags="login")
        return render(request, "core/login.html", context)
    return render(request, "core/login.html", context)


@login_required(login_url="core:login")
def logout_view(request):
    logout(request)
    messages.info(request, "Voce saiu do sistema com sucesso.", extra_tags="logout")
    return redirect("core:login")


# ---------------------
# PAGINA INICIAL / REDIRECIONAMENTO
# ---------------------
def home_redirect(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return redirect("core:login")


@login_required(login_url="core:login")
def painel(request):
    context = {
        "user": request.user,
        "tipo_usuario": request.user.get_tipo_display(),
    }
    return render(request, "configuracoes/painel.html", context)


