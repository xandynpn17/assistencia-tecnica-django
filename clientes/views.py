from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q, Sum
from django.http import JsonResponse
import logging
from ordens.models import OrdemServico, LinhaTrabalho
from caixa.models import Pagamento
from configuracoes.permissions import has_role, role_required, STAFF_ROLES

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
    """Tela principal: apenas busca, não lista todos."""
    query = request.GET.get("query", "").strip()
    clientes = []

    if query:
        query_digits = "".join(filter(str.isdigit, query))
        clientes = Cliente.objects.filter(
            Q(nome__icontains=query)
            | Q(telefone__icontains=query)
            | Q(telefone__icontains=query_digits)
            | Q(email__icontains=query)
            | Q(documento__icontains=query_digits or query)
            | Q(cpf__icontains=query_digits or query)
            | Q(cnpj__icontains=query_digits or query)
            | Q(numero_cliente__icontains=query)
        ).order_by("nome")[:20]

    return render(
        request,
        "clientes/clientes.html",
        {
            "clientes": clientes,
            "query": query,
            "houve_busca": bool(query),
        },
    )


@role_required(STAFF_ROLES)
def buscar_cliente(request):
    """Busca cliente via AJAX para busca em tempo real"""
    query = request.GET.get("q", "").strip()
    cliente = None

    if query:
        query_limpa = "".join(filter(str.isdigit, query))

        cliente = Cliente.objects.filter(
            Q(documento__icontains=query_limpa)
            | Q(cpf__icontains=query_limpa)
            | Q(cnpj__icontains=query_limpa)
            | Q(telefone__icontains=query)
            | Q(telefone__icontains=query_limpa)
            | Q(email__icontains=query)
            | Q(numero_cliente__icontains=query)
            | Q(nome__icontains=query)
        ).first()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        if cliente:
            return JsonResponse(
                {
                    "existe": True,
                    "id": cliente.id,
                    "nome": cliente.nome,
                    "telefone": cliente.telefone or "",
                    "email": cliente.email or "",
                    "numero_cliente": cliente.numero_cliente or "",
                    "cpf": cliente.documento or "",
                }
            )
        return JsonResponse({"existe": False})

    return JsonResponse({"erro": "Requisição inválida"}, status=400)


@role_required(STAFF_ROLES)
def detalhes_cliente(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)

    ordens = list(
        OrdemServico.objects.filter(cliente=cliente).order_by("-data_abertura")
    )
    ordens_ativas_lista = [ordem for ordem in ordens if not ordem.fechada]
    ordens_concluidas_lista = [ordem for ordem in ordens if ordem.fechada]

    try:
        orcamentos = Orcamento.objects.filter(cliente=cliente).order_by("-data_criacao")
    except Exception:
        orcamentos = []

    total_ordens = len(ordens)
    ordens_ativas = len(ordens_ativas_lista)
    ordens_concluidas = len(ordens_concluidas_lista)
    total_gasto = (
        Pagamento.objects.filter(ordem_servico__cliente=cliente)
        .aggregate(total=Sum("valor"))
        .get("total")
        or 0
    )

    totais_por_ordem = {
        row["ordem_servico_id"]: row["total"] or 0
        for row in (
            Pagamento.objects.filter(ordem_servico__cliente=cliente)
            .values("ordem_servico_id")
            .annotate(total=Sum("valor"))
        )
    }
    for ordem in ordens:
        ordem.total_pago = totais_por_ordem.get(ordem.id, 0)

    tempos_segundos = []
    for ordem in ordens_concluidas_lista:
        linha_pronto = (
            LinhaTrabalho.objects.filter(ordem=ordem, status="pronto_contactado")
            .order_by("criado_em")
            .first()
        )
        if not linha_pronto:
            continue
        referencia_fim = ordem.data_conclusao
        if not referencia_fim:
            linha_concluida = (
                LinhaTrabalho.objects.filter(
                    ordem=ordem,
                    status="concluida",
                    criado_em__gte=linha_pronto.criado_em,
                )
                .order_by("criado_em")
                .first()
            )
            referencia_fim = linha_concluida.criado_em if linha_concluida else None
        if not referencia_fim or referencia_fim <= linha_pronto.criado_em:
            continue
        tempos_segundos.append((referencia_fim - linha_pronto.criado_em).total_seconds())

    tempo_medio_retirada = "-"
    if tempos_segundos:
        media = int(sum(tempos_segundos) / len(tempos_segundos))
        dias = media // 86400
        horas = (media % 86400) // 3600
        minutos = (media % 3600) // 60
        if dias > 0:
            tempo_medio_retirada = f"{dias}d {horas}h"
        elif horas > 0:
            tempo_medio_retirada = f"{horas}h {minutos}min"
        else:
            tempo_medio_retirada = f"{minutos}min"

    return render(
        request,
        "clientes/detalhes_cliente.html",
        {
            "cliente": cliente,
            "ordens": ordens,
            "ordens_ativas_lista": ordens_ativas_lista,
            "ordens_concluidas_lista": ordens_concluidas_lista,
            "orcamentos": orcamentos,
            "total_ordens": total_ordens,
            "ordens_ativas": ordens_ativas,
            "ordens_concluidas": ordens_concluidas,
            "total_gasto": total_gasto,
            "tempo_medio_retirada": tempo_medio_retirada,
        },
    )


@role_required(STAFF_ROLES)
def editar_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)

    if request.method == "POST":
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            return redirect("clientes:detalhes_cliente", pk=cliente.id)
    else:
        form = ClienteForm(instance=cliente)

    return render(
        request,
        "clientes/editar_cliente.html",
        {
            "form": form,
            "cliente": cliente,
            "menu_app": "clientes",
        },
    )


@role_required({"gerente"})
def excluir_cliente(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)
    ordens = OrdemServico.objects.filter(cliente=cliente).count()

    if request.method == "POST":
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
        return redirect("clientes:lista_clientes")

    return render(
        request,
        "clientes/excluir_cliente.html",
        {
            "cliente": cliente,
            "ordens": ordens,
        },
    )


@role_required({"adm", "gerente"})
def unificar_clientes(request):
    query = request.GET.get("query", "").strip()
    candidatos = Cliente.objects.none()
    if query:
        query_digits = "".join(filter(str.isdigit, query))
        candidatos = Cliente.objects.filter(
            Q(nome__icontains=query)
            | Q(documento__icontains=query_digits or query)
            | Q(cpf__icontains=query_digits or query)
            | Q(cnpj__icontains=query_digits or query)
            | Q(telefone__icontains=query)
            | Q(email__icontains=query)
            | Q(numero_cliente__icontains=query)
        ).order_by("nome")[:50]

    if request.method == "POST":
        principal_id = request.POST.get("principal_id")
        duplicado_id = request.POST.get("duplicado_id")
        if not principal_id or not duplicado_id:
            return render(
                request,
                "clientes/unificar_clientes.html",
                {
                    "query": query,
                    "candidatos": candidatos,
                    "erro": "Selecione cliente principal e cliente duplicado.",
                    "menu_app": "clientes",
                },
            )
        if principal_id == duplicado_id:
            return render(
                request,
                "clientes/unificar_clientes.html",
                {
                    "query": query,
                    "candidatos": candidatos,
                    "erro": "Principal e duplicado não podem ser o mesmo cliente.",
                    "menu_app": "clientes",
                },
            )

        principal = get_object_or_404(Cliente, id=principal_id)
        duplicado = get_object_or_404(Cliente, id=duplicado_id)

        OrdemServico.objects.filter(cliente=duplicado).update(cliente=principal)
        Orcamento.objects.filter(cliente=duplicado).update(cliente=principal)

        if not principal.telefone and duplicado.telefone:
            principal.telefone = duplicado.telefone
        if not principal.email and duplicado.email:
            principal.email = duplicado.email
        if not principal.codigo_postal and duplicado.codigo_postal:
            principal.codigo_postal = duplicado.codigo_postal
        if not principal.logradouro and duplicado.logradouro:
            principal.logradouro = duplicado.logradouro
        if not principal.numero and duplicado.numero:
            principal.numero = duplicado.numero
        if not principal.complemento and duplicado.complemento:
            principal.complemento = duplicado.complemento
        if not principal.bairro and duplicado.bairro:
            principal.bairro = duplicado.bairro
        if not principal.cidade and duplicado.cidade:
            principal.cidade = duplicado.cidade
        if not principal.estado and duplicado.estado:
            principal.estado = duplicado.estado
        if duplicado.observacoes:
            base_obs = principal.observacoes or ""
            principal.observacoes = (base_obs + "\n" if base_obs else "") + f"Importado de {duplicado.numero_cliente}: {duplicado.observacoes}"
        principal.save()

        logger.info(
            "auditoria_operacional",
            extra={
                "acao": "cliente_unificado",
                "usuario": request.user.username,
                "ip": _request_ip(request),
                "cliente_principal_id": principal.id,
                "cliente_duplicado_id": duplicado.id,
            },
        )
        duplicado.delete()
        return redirect("clientes:detalhes_cliente", pk=principal.id)

    return render(
        request,
        "clientes/unificar_clientes.html",
        {
            "query": query,
            "candidatos": candidatos,
            "menu_app": "clientes",
            "can_unificar": has_role(request.user, {"adm", "gerente"}),
        },
    )
