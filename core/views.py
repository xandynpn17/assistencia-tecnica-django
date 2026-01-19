from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import models
from django.contrib import messages

from clientes.models import Cliente
from ordens.models import OrdemServico
from configuracoes.models import Empresa


# ---------------------
# DASHBOARD
# ---------------------
@login_required(login_url='configuracoes:login')
def dashboard(request):
    total_clientes = Cliente.objects.count()
    total_ordens = OrdemServico.objects.count()
    empresa = Empresa.objects.first()

    status_counts = OrdemServico.objects.values("status").annotate(total=models.Count("id"))
    status_dict = {item["status"]: item["total"] for item in status_counts}

    # Garantir que todas as chaves de status existam
    for status in [
        'diagnosticar', 'pendente_tecnico', 'pendente_marca', 'pendente_pecas',
        'pendente_orcamento', 'orcamentado', 'autorizado', 'em_andamento',
        'pronto_contactado', 'pronto_contactar', 'concluida'
    ]:
        status_dict.setdefault(status, 0)

    ultimos_clientes = Cliente.objects.all().order_by('-id')[:5]
    ultimas_ordens = OrdemServico.objects.select_related('cliente').order_by('-id')[:5]

    total_ordens_abertas = OrdemServico.objects.exclude(status='concluida').count()
    total_ordens_finalizadas = OrdemServico.objects.filter(status='concluida').count()

    context = {
        'total_clientes': total_clientes,
        'total_ordens': total_ordens,
        'total_ordens_abertas': total_ordens_abertas,
        'total_ordens_finalizadas': total_ordens_finalizadas,
        'status_dict': status_dict,
        'ultimos_clientes': ultimos_clientes,
        'ultimas_ordens': ultimas_ordens,
        'menu_app': 'core',
        'menu_sub': 'dashboard',
    }
    return render(request, 'core/dashboard.html', context)


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
        else:
            messages.error(request, "Usuário ou senha inválidos.",extra_tags="login")
            return render(request, "core/login.html")
    return render(request, "core/login.html")


@login_required(login_url='configuracoes:login')
def logout_view(request):
    logout(request)
    messages.info(request, "Você saiu do sistema com sucesso.", extra_tags="logout")
    return redirect("core:login")


# ---------------------
# PÁGINA INICIAL / REDIRECIONAMENTO
# ---------------------
def home_redirect(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return redirect("core:login")


@login_required(login_url='configuracoes:login')
def painel(request):
    context = {
        'user': request.user,
        'tipo_usuario': request.user.get_tipo_display(),
    }
    return render(request, 'configuracoes/painel.html', context)