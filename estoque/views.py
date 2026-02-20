from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from .models import Produto
from .forms import ProdutoForm
from django.db.models import Q
from django.contrib import messages
from configuracoes.permissions import role_required, STOCK_VIEW_ROLES, STOCK_MANAGE_ROLES


@role_required(STOCK_VIEW_ROLES)
def buscar_produtos(request):
    termo = request.GET.get('q', '').strip()
    produtos = []
    if termo:
        produtos = Produto.objects.filter(
            Q(nome__icontains=termo) | Q(ean__icontains=termo),
            ativo=True
        )[:50]  # limite para não sobrecarregar
    context = {
        'produtos': produtos,
        'termo': termo,
        'menu_app': 'estoque',
        'menu_sub': 'buscar_produtos',
    }
    return render(request, 'estoque/buscar_produtos.html', context)

@role_required(STOCK_VIEW_ROLES)
def lista_produtos(request):
    filtro = request.GET.get("tipo", "todos")

    if filtro == "servicos":
        produtos = Produto.objects.filter(ativo=True, is_servico=True)
    elif filtro == "produtos":
        produtos = Produto.objects.filter(ativo=True, is_servico=False)
    else:
        produtos = Produto.objects.filter(ativo=True)

    context = {
        'produtos': produtos,
        'menu_app': 'estoque',
        'menu_sub': 'lista_produtos',
        'filtro': filtro,
    }
    return render(request, 'estoque/lista_produtos.html', context)


@role_required(STOCK_MANAGE_ROLES)
def criar_produto(request):
    # Busca o último produto para pegar valores padrão
    ultimo = Produto.objects.order_by('-id').first()
    initial = {}
    if ultimo:
        initial = {
            'icms': ultimo.icms,
            'ipi': ultimo.ipi,
            'pis_cofins': ultimo.pis_cofins,
            'margem_lucro': ultimo.margem_lucro,
            'custo_operacional': ultimo.custo_operacional,
        }

    if request.method == 'POST':
        form = ProdutoForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('estoque:lista_produtos')
    else:
        form = ProdutoForm(initial=initial)

    context = {
        'form': form,
        'menu_app': 'estoque',
        'menu_sub': 'criar_produto',
    }
    return render(request, 'estoque/form_produto.html', context)

@role_required(STOCK_MANAGE_ROLES)
def editar_produto(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    if request.method == "POST":
        form = ProdutoForm(request.POST, instance=produto)
        if form.is_valid():
            form.save()
            messages.success(request, "Produto atualizado com sucesso!")
            return redirect('estoque:lista_produtos')
    else:
        form = ProdutoForm(instance=produto)

    return render(request, 'estoque/form_produto.html', {'form': form})

@role_required(STOCK_MANAGE_ROLES)
def excluir_produto(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    if request.method == "POST":
        produto.delete()
        messages.success(request, "Produto excluído com sucesso!")
        return redirect('estoque:lista_produtos')
    return render(request, 'estoque/confirm_delete.html', {'produto': produto})


@role_required(STOCK_VIEW_ROLES)
def buscar_produto(request):
    q = request.GET.get('q', '').strip()
    produtos = Produto.objects.filter(nome__icontains=q) | Produto.objects.filter(ean__icontains=q)
    data = list(produtos.values('id','ean','nome','descricao','preco'))
    return JsonResponse(data, safe=False)
