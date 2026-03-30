from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from datetime import timedelta

from django.utils import timezone

from clientes.models import Cliente
from configuracoes.models import Empresa
from configuracoes.permissions import ORDER_ROLES, has_role
from ordens.models import LinhaTrabalho, OrdemServico


# ---------------------
# DASHBOARD
# ---------------------
@login_required(login_url="core:login")
def dashboard(request):
    if not has_role(request.user, ORDER_ROLES):
        raise PermissionDenied

    tipo_usuario = getattr(request.user, "tipo_usuario", "")
    is_managerial = request.user.is_superuser or tipo_usuario in {"adm", "gerente"}
    is_operational = (tipo_usuario in {"atendente", "tecnico"}) and not is_managerial

    total_clientes = Cliente.objects.count()
    total_ordens = OrdemServico.objects.count()
    total_ordens_abertas = OrdemServico.objects.filter(fechada=False).count()
    total_ordens_finalizadas = OrdemServico.objects.filter(fechada=True).count()
    sem_tecnico_q = Q(tecnico_responsavel__isnull=True) | ~Q(tecnico_responsavel__tipo_usuario="tecnico")

    status_counts = (
        OrdemServico.objects.filter(fechada=False)
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

    context = {
        "empresa": Empresa.objects.first(),
        "total_clientes": total_clientes,
        "total_ordens": total_ordens,
        "total_ordens_abertas": total_ordens_abertas,
        "total_ordens_finalizadas": total_ordens_finalizadas,
        "status_cards": status_cards,
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
        "menu_sub": "dashboard",
    }

    if is_managerial:
        today = timezone.localdate()
        ordens_sem_tecnico = OrdemServico.objects.filter(fechada=False).filter(sem_tecnico_q).count()
        ordens_prontas = OrdemServico.objects.filter(
            fechada=False, status="pronto_contactado"
        ).count()
        ordens_criticas = OrdemServico.objects.filter(
            fechada=False,
            status__in={"pendente_cliente", "pendente_tecnico", "pendente_pecas", "pendente_marca"},
        ).count()
        limite_parada = timezone.now() - timedelta(days=15)
        ordens_paradas = OrdemServico.objects.filter(
            fechada=False,
            status__in={"pendente_cliente", "pendente_tecnico", "pendente_pecas", "pendente_marca"},
            data_abertura__lte=limite_parada,
        ).count()

        ordens_recentes = (
            OrdemServico.objects.select_related("cliente", "tecnico_responsavel")
            .prefetch_related(
                Prefetch(
                    "linhas_trabalho",
                    queryset=LinhaTrabalho.objects.select_related("usuario").order_by("id"),
                )
            )
            .filter(fechada=False)
            .order_by("-data_abertura")[:5]
        )

        context.update(
            {
                "gerencial_cards": {
                    "abertas_total": total_ordens_abertas,
                    "fechadas_total": total_ordens_finalizadas,
                    "sem_tecnico": ordens_sem_tecnico,
                    "prontas": ordens_prontas,
                    "criticas": ordens_criticas,
                    "paradas": ordens_paradas,
                },
                "ordens_recentes": ordens_recentes,
            }
        )

    return render(request, "core/dashboard.html", context)


# ---------------------
# LOGIN / LOGOUT
# ---------------------
def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("core:dashboard")
        messages.error(request, "Usuario ou senha invalidos.", extra_tags="login")
        return render(request, "core/login.html")
    return render(request, "core/login.html")


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

    sem_tecnico_q = Q(tecnico_responsavel__isnull=True) | ~Q(tecnico_responsavel__tipo_usuario="tecnico")
