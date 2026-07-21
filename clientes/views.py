from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import DecimalField, ExpressionWrapper, F, Prefetch, Q, Sum
from django.http import JsonResponse, HttpResponseNotFound
import logging
from decimal import Decimal
from ordens.models import OrdemServico, LinhaTrabalho
from caixa.models import Pagamento
from configuracoes.permissions import has_role, role_required, STAFF_ROLES
from configuracoes.services.documentos import normalizar_cnpj
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa

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
def rota_cliente_invalida(request, rota_invalida):
    """Evita que URLs digitadas como /clientes/Nome virem listagens amplas."""
    logger.warning(
        "rota_cliente_invalida",
        extra={
            "rota": rota_invalida,
            "usuario": getattr(request.user, "username", ""),
            "ip": _request_ip(request),
        },
    )
    return HttpResponseNotFound(
        "Cliente não encontrado. Use a busca de clientes ou abra o cadastro pelo ID interno."
    )


@role_required(STAFF_ROLES)
def lista_clientes(request):
    """Tela principal: apenas busca, não lista todos."""
    query = request.GET.get("query", "").strip()
    clientes = []
    empresa = obter_empresa_ativa(request, strict=False)

    if query:
        query_digits = "".join(filter(str.isdigit, query))
        query_doc = normalizar_cnpj(query)
        clientes = filtrar_queryset_empresa(Cliente.objects.all(), empresa).filter(
            Q(nome__icontains=query)
            | Q(telefone__icontains=query)
            | Q(telefone__icontains=query_digits)
            | Q(email__icontains=query)
            | Q(documento__icontains=query_doc or query_digits or query)
            | Q(cpf__icontains=query_digits or query)
            | Q(cnpj__icontains=query_doc or query_digits or query)
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
    empresa = obter_empresa_ativa(request, strict=False)

    if query:
        query_limpa = "".join(filter(str.isdigit, query))
        query_doc = normalizar_cnpj(query)

        cliente = filtrar_queryset_empresa(Cliente.objects.all(), empresa).filter(
            Q(documento__icontains=query_doc or query_limpa)
            | Q(cpf__icontains=query_limpa)
            | Q(cnpj__icontains=query_doc or query_limpa)
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
    empresa = obter_empresa_ativa(request, strict=False)
    cliente = get_object_or_404(filtrar_queryset_empresa(Cliente.objects.all(), empresa), pk=pk)

    total_item_expr = ExpressionWrapper(
        F("servicos_pecas__quantidade") * F("servicos_pecas__valor_unitario"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    linhas_retirada = LinhaTrabalho.objects.filter(
        status__in=["pronto_contactado", "concluida"]
    ).order_by("criado_em")
    ordens = list(
        OrdemServico.objects.filter(cliente=cliente)
        .annotate(total_os_calculado=Sum(total_item_expr))
        .prefetch_related(
            Prefetch("linhas_trabalho", queryset=linhas_retirada, to_attr="linhas_retirada"),
        )
        .order_by("-data_abertura")
    )
    ordens_ativas_lista = [ordem for ordem in ordens if not ordem.fechada]
    ordens_concluidas_lista = [ordem for ordem in ordens if ordem.fechada]

    orcamentos = filtrar_queryset_empresa(Orcamento.objects.filter(cliente=cliente), empresa).order_by("-data_criacao")

    total_ordens = len(ordens)
    ordens_ativas = len(ordens_ativas_lista)
    ordens_concluidas = len(ordens_concluidas_lista)
    pagamentos_cliente = Pagamento.objects.filter(ordem_servico__cliente=cliente)
    total_gasto = pagamentos_cliente.aggregate(total=Sum("valor")).get("total") or Decimal("0.00")
    ultimo_pagamento = pagamentos_cliente.order_by("-data").first()

    totais_por_ordem = {
        row["ordem_servico_id"]: row["total"] or 0
        for row in (
            Pagamento.objects.filter(ordem_servico__cliente=cliente)
            .values("ordem_servico_id")
            .annotate(total=Sum("valor"))
        )
    }
    total_em_aberto = Decimal("0.00")
    total_os = Decimal("0.00")
    for ordem in ordens:
        ordem.total_pago = totais_por_ordem.get(ordem.id, 0)
        ordem.total_os = Decimal(ordem.total_os_calculado or Decimal("0.00"))
        ordem.saldo_aberto = max(Decimal("0.00"), ordem.total_os - Decimal(ordem.total_pago or 0))
        total_em_aberto += ordem.saldo_aberto
        total_os += ordem.total_os

    ordens_com_pagamento = [ordem for ordem in ordens if Decimal(ordem.total_pago or 0) > 0]
    ticket_medio = (
        (total_gasto / len(ordens_com_pagamento)).quantize(Decimal("0.01"))
        if ordens_com_pagamento
        else Decimal("0.00")
    )
    ultima_ordem = ordens[0] if ordens else None

    tempos_segundos = []
    for ordem in ordens_concluidas_lista:
        linhas = list(getattr(ordem, "linhas_retirada", []))
        linha_pronto = next((linha for linha in linhas if linha.status == "pronto_contactado"), None)
        if not linha_pronto:
            continue
        referencia_fim = ordem.data_conclusao
        if not referencia_fim:
            linha_concluida = next(
                (
                    linha
                    for linha in linhas
                    if linha.status == "concluida" and linha.criado_em >= linha_pronto.criado_em
                ),
                None,
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
            "total_em_aberto": total_em_aberto,
            "ticket_medio": ticket_medio,
            "total_os_cliente": total_os,
            "tempo_medio_retirada": tempo_medio_retirada,
            "ultimo_pagamento": ultimo_pagamento,
            "ultima_ordem": ultima_ordem,
        },
    )


@role_required(STAFF_ROLES)
def editar_cliente(request, cliente_id):
    empresa = obter_empresa_ativa(request, strict=False)
    cliente = get_object_or_404(filtrar_queryset_empresa(Cliente.objects.all(), empresa), id=cliente_id)

    if request.method == "POST":
        form = ClienteForm(request.POST, instance=cliente, empresa=empresa)
        if form.is_valid():
            form.save()
            return redirect("clientes:detalhes_cliente", pk=cliente.id)
    else:
        form = ClienteForm(instance=cliente, empresa=empresa)

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
    empresa = obter_empresa_ativa(request, strict=False)
    cliente = get_object_or_404(filtrar_queryset_empresa(Cliente.objects.all(), empresa), id=cliente_id)
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
    empresa = obter_empresa_ativa(request, strict=False)
    candidatos = Cliente.objects.none()
    if query:
        query_digits = "".join(filter(str.isdigit, query))
        query_doc = normalizar_cnpj(query)
        candidatos = filtrar_queryset_empresa(Cliente.objects.all(), empresa).filter(
            Q(nome__icontains=query)
            | Q(documento__icontains=query_doc or query_digits or query)
            | Q(cpf__icontains=query_digits or query)
            | Q(cnpj__icontains=query_doc or query_digits or query)
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

        clientes_empresa = filtrar_queryset_empresa(Cliente.objects.all(), empresa)
        principal = get_object_or_404(clientes_empresa, id=principal_id)
        duplicado = get_object_or_404(clientes_empresa, id=duplicado_id)

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

