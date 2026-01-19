from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse

from .models import Cliente
from .forms import ClienteForm
from orcamentos.forms import OrcamentoForm
from orcamentos.models import Orcamento


@login_required(login_url='configuracoes:login')
def lista_clientes(request):
    clientes_procurados = []
    form = ClienteForm()

    if request.method == 'POST':
        form = ClienteForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('clientes:lista_clientes')  # ✅ namespace adicionado

    query = request.GET.get('query', '')
    if query:
        clientes_procurados = Cliente.objects.filter(
            Q(nome__icontains=query) |
            Q(telefone__icontains=query) |
            Q(email__icontains=query) |
            Q(cpf__icontains=query)
        )
    else:
        clientes_procurados = Cliente.objects.all().order_by('nome')

    return render(request, 'clientes/clientes.html', {
        'clientes_procurados': clientes_procurados,
        'form': form,
    })


@login_required(login_url='configuracoes:login')
def buscar_cliente(request):
    query = request.GET.get("q", "").strip()
    cliente = None

    if query:
        cliente = Cliente.objects.filter(
            Q(cpf=query) | Q(telefone=query) | Q(email=query)
        ).first()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        if cliente:
            return JsonResponse({
                "existe": True,
                "id": cliente.id,
                "nome": cliente.nome,
                "telefone": cliente.telefone,
                "email": cliente.email,
            })
        else:
            return JsonResponse({"existe": False})

    return JsonResponse({"erro": "Requisição inválida"}, status=400)


@login_required(login_url='configuracoes:login')
def detalhes_cliente(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    ordens = cliente.ordens.all()

    return render(request, 'clientes/detalhes_cliente.html', {
        'cliente': cliente,
        'ordens': ordens,
    })


@login_required(login_url='configuracoes:login')
def editar_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)

    if request.method == 'POST':
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            return redirect('clientes:detalhes_cliente', pk=cliente.id)  # ✅ namespace
    else:
        form = ClienteForm(instance=cliente)

    return render(request, 'clientes/editar_cliente.html', {'form': form, 'cliente': cliente})


@login_required(login_url='configuracoes:login')
def excluir_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)
    if request.method == 'POST':
        cliente.delete()
        return redirect('clientes:lista_clientes')  # ✅ namespace
    return render(request, 'clientes/excluir_cliente.html', {'cliente': cliente})
