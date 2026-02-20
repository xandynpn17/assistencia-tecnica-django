from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.http import JsonResponse
import logging
from ordens.models import OrdemServico
from configuracoes.permissions import role_required, STAFF_ROLES, MANAGER_ROLES

from .models import Cliente
from .forms import ClienteForm
from orcamentos.models import Orcamento

logger = logging.getLogger(__name__)


def _request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


@role_required(STAFF_ROLES)
def lista_clientes(request):
    """Tela principal - apenas busca, não lista todos"""
    query = request.GET.get('query', '')
    clientes = []

    # SE HOUVER BUSCA, PROCURA
    if query:
        clientes = Cliente.objects.filter(
            Q(nome__icontains=query) |
            Q(telefone__icontains=query) |
            Q(email__icontains=query) |
            Q(cpf__icontains=query) |
            Q(cnpj__icontains=query) |
            Q(numero_cliente__icontains=query)
        ).order_by('nome')[:20]  # Limita a 20 resultados
    # SE NÃO HOUVER BUSCA, MOSTRA APENAS UMA MENSAGEM

    return render(request, 'clientes/clientes.html', {
        'clientes': clientes,
        'query': query,
        'houve_busca': bool(query),
    })


@role_required(STAFF_ROLES)
def buscar_cliente(request):
    """Busca cliente via AJAX para busca em tempo real"""
    query = request.GET.get("q", "").strip()
    cliente = None

    if query:
        # Limpa formatação para CPF/CNPJ
        query_limpa = ''.join(filter(str.isdigit, query))

        # Tenta encontrar o cliente
        cliente = Cliente.objects.filter(
            Q(cpf__icontains=query_limpa) |
            Q(cnpj__icontains=query_limpa) |
            Q(telefone__icontains=query) |
            Q(email__icontains=query) |
            Q(numero_cliente__icontains=query) |
            Q(nome__icontains=query)
        ).first()

    # Responde apenas a requisições AJAX
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        if cliente:
            return JsonResponse({
                "existe": True,
                "id": cliente.id,
                "nome": cliente.nome,
                "telefone": cliente.telefone or "",
                "email": cliente.email or "",
                "numero_cliente": cliente.numero_cliente or "",
                "cpf": cliente.get_documento() or ""
            })
        else:
            return JsonResponse({"existe": False})

    return JsonResponse({"erro": "Requisição inválida"}, status=400)


@role_required(STAFF_ROLES)
def detalhes_cliente(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)

    # Ordens de serviço
    ordens = OrdemServico.objects.filter(cliente=cliente).order_by('-data_abertura')

    # Orçamentos (se existir)
    try:
        orcamentos = Orcamento.objects.filter(cliente=cliente).order_by('-data_criacao')
    except:
        orcamentos = []

    # Estatísticas
    total_ordens = ordens.count()
    ordens_ativas = ordens.filter(status__in=['aberta', 'em_andamento']).count()
    ordens_concluidas = ordens.filter(status='concluida').count()

    # Valor total
    total_gasto = 0
    for ordem in ordens:
        try:
            if hasattr(ordem, 'total'):
                total_gasto += ordem.total
            elif hasattr(ordem, 'valor_total'):
                total_gasto += ordem.valor_total
        except:
            pass

    return render(request, 'clientes/detalhes_cliente.html', {
        'cliente': cliente,
        'ordens': ordens,
        'orcamentos': orcamentos,
        'total_ordens': total_ordens,
        'ordens_ativas': ordens_ativas,
        'ordens_concluidas': ordens_concluidas,
        'total_gasto': total_gasto,
    })


@role_required(STAFF_ROLES)
def editar_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)

    if request.method == 'POST':
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            return redirect('clientes:detalhes_cliente', pk=cliente.id)
    else:
        form = ClienteForm(instance=cliente)

    return render(request, 'clientes/editar_cliente.html', {
        'form': form,
        'cliente': cliente
    })


@role_required(MANAGER_ROLES)
def excluir_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)
    ordens = OrdemServico.objects.filter(cliente=cliente).count()

    if request.method == 'POST':
        logger.info(
            "auditoria_operacional",
            extra={
                "acao": "cliente_excluido",
                "usuario": request.user.username,
                "ip": _request_ip(request),
                "cliente_id": cliente.id,
                "documento": cliente.documento,
                "ordens_vinculadas": ordens,
            },
        )
        cliente.delete()
        return redirect('clientes:lista_clientes')

    return render(request, 'clientes/excluir_cliente.html', {
        'cliente': cliente,
        'ordens': ordens
    })
