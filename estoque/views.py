from datetime import datetime, timedelta
from decimal import Decimal
import random
import string

from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from caixa.models import Pagamento
from configuracoes.permissions import ORDER_ROLES, STOCK_MANAGE_ROLES, STOCK_VIEW_ROLES, role_required

from .forms import MovimentacaoEstoqueForm, PontoOperacionalForm, ProdutoForm
from .models import (
    InventarioEstoque,
    ItemInventarioEstoque,
    MovimentacaoEstoque,
    PontoOperacional,
    Produto,
    ReservaEstoque,
    SaldoEstoquePonto,
    VendaRapidaEstoque,
)
from .services import (
    ajustar_saldo,
    cancelar_reserva,
    consumir_reservas_ordem,
    converter_reserva,
    devolver_reservas_ordem,
    expirar_reservas_vencidas,
    recalcular_total_produto,
    saldo_disponivel,
)


def _normalizar_saldos_produto(produto):
    if not produto.saldos_por_ponto.exists() and produto.ponto_operacional and produto.quantidade:
        SaldoEstoquePonto.objects.create(
            produto=produto,
            ponto_operacional=produto.ponto_operacional,
            quantidade=produto.quantidade,
        )


def _recalcular_total_produto(produto):
    recalcular_total_produto(produto)


def _codigo_reserva():
    while True:
        codigo = "RES-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if not ReservaEstoque.objects.filter(codigo_reserva=codigo).exists():
            return codigo


@role_required(STOCK_VIEW_ROLES)
def buscar_produtos(request):
    termo = request.GET.get("q", "").strip()
    produtos = []
    if termo:
        produtos = Produto.objects.filter(Q(nome__icontains=termo) | Q(ean__icontains=termo), ativo=True)[:50]
    context = {
        "produtos": produtos,
        "termo": termo,
        "menu_app": "estoque",
        "menu_sub": "buscar_produtos",
    }
    return render(request, "estoque/buscar_produtos.html", context)


@role_required(STOCK_VIEW_ROLES)
def lista_produtos(request):
    filtro = request.GET.get("tipo", "todos")
    ponto_id = request.GET.get("ponto")

    if filtro == "servicos":
        produtos = Produto.objects.filter(ativo=True, is_servico=True)
    elif filtro == "produtos":
        produtos = Produto.objects.filter(ativo=True, is_servico=False)
    else:
        produtos = Produto.objects.filter(ativo=True)

    if ponto_id:
        produtos = produtos.filter(ponto_operacional_id=ponto_id)

    context = {
        "produtos": produtos.select_related("ponto_operacional"),
        "pontos": PontoOperacional.objects.filter(ativo=True),
        "menu_app": "estoque",
        "menu_sub": "lista_produtos",
        "filtro": filtro,
        "ponto_filtro": ponto_id or "",
    }
    return render(request, "estoque/lista_produtos.html", context)


@role_required(STOCK_MANAGE_ROLES)
def criar_produto(request):
    ultimo = Produto.objects.order_by("-id").first()
    initial = {}
    if ultimo:
        initial = {
            "icms": ultimo.icms,
            "ipi": ultimo.ipi,
            "pis_cofins": ultimo.pis_cofins,
            "margem_lucro": ultimo.margem_lucro,
            "custo_operacional": ultimo.custo_operacional,
            "ponto_operacional": ultimo.ponto_operacional_id,
        }

    if request.method == "POST":
        form = ProdutoForm(request.POST)
        if form.is_valid():
            produto = form.save(commit=False)
            po3, _ = PontoOperacional.objects.get_or_create(codigo="PO3", defaults={"nome": "Loja", "ativo": True})
            produto.ponto_operacional = po3
            produto.save()
            _normalizar_saldos_produto(produto)
            _recalcular_total_produto(produto)
            return redirect("estoque:lista_produtos")
    else:
        form = ProdutoForm(initial=initial)

    context = {"form": form, "menu_app": "estoque", "menu_sub": "criar_produto"}
    return render(request, "estoque/form_produto.html", context)


@role_required(STOCK_MANAGE_ROLES)
def editar_produto(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    if request.method == "POST":
        form = ProdutoForm(request.POST, instance=produto)
        if form.is_valid():
            produto = form.save()
            _normalizar_saldos_produto(produto)
            _recalcular_total_produto(produto)
            messages.success(request, "Produto atualizado com sucesso!")
            return redirect("estoque:lista_produtos")
    else:
        form = ProdutoForm(instance=produto)

    return render(request, "estoque/form_produto.html", {"form": form, "menu_app": "estoque", "menu_sub": "lista_produtos"})


@role_required(STOCK_MANAGE_ROLES)
def excluir_produto(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    if request.method == "POST":
        produto.delete()
        messages.success(request, "Produto excluido com sucesso!")
        return redirect("estoque:lista_produtos")
    return render(request, "estoque/confirm_delete.html", {"produto": produto, "menu_app": "estoque", "menu_sub": "lista_produtos"})


@role_required(STOCK_VIEW_ROLES)
def buscar_produto(request):
    q = request.GET.get("q", "").strip()
    produtos = Produto.objects.filter(nome__icontains=q) | Produto.objects.filter(ean__icontains=q)
    data = list(produtos.values("id", "ean", "sku", "nome", "descricao", "preco"))
    return JsonResponse(data, safe=False)


@role_required(STOCK_MANAGE_ROLES)
def registrar_movimentacao(request):
    if request.method == "POST":
        form = MovimentacaoEstoqueForm(request.POST)
        if form.is_valid():
            mov = form.save(commit=False)
            mov.usuario = request.user
            produto = mov.produto
            _normalizar_saldos_produto(produto)

            with transaction.atomic():
                if mov.tipo == "transferencia":
                    origem_saldo, _ = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=mov.origem)
                    destino_saldo, _ = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=mov.destino)
                    if origem_saldo.quantidade < mov.quantidade:
                        messages.error(request, "Saldo insuficiente na origem.")
                        return redirect("estoque:registrar_movimentacao")
                    origem_saldo.quantidade -= mov.quantidade
                    destino_saldo.quantidade += mov.quantidade
                    origem_saldo.save(update_fields=["quantidade"])
                    destino_saldo.save(update_fields=["quantidade"])
                elif mov.tipo in {"ajuste", "avaria", "inventario"} and mov.origem:
                    ajustar_saldo(produto, mov.origem, mov.quantidade)
                elif mov.tipo in {"venda", "consumo_os"} and mov.origem:
                    ajustar_saldo(produto, mov.origem, -abs(int(mov.quantidade)))
                    mov.quantidade = -abs(int(mov.quantidade))
                elif mov.tipo in {"devolucao_reserva"} and mov.destino:
                    ajustar_saldo(produto, mov.destino, abs(int(mov.quantidade)))
                    mov.quantidade = abs(int(mov.quantidade))
                mov.save()
                _recalcular_total_produto(produto)

            messages.success(request, "Movimentacao registrada com sucesso.")
            return redirect("estoque:movimentacoes")
    else:
        form = MovimentacaoEstoqueForm()
    return render(request, "estoque/movimentacao_form.html", {"form": form, "menu_app": "estoque", "menu_sub": "movimentacoes"})


@role_required(STOCK_VIEW_ROLES)
def listar_movimentacoes(request):
    movimentacoes = MovimentacaoEstoque.objects.select_related("produto", "origem", "destino", "usuario")
    tipo = (request.GET.get("tipo") or "").strip()
    ponto = (request.GET.get("ponto") or "").strip()
    if tipo:
        movimentacoes = movimentacoes.filter(tipo=tipo)
    if ponto:
        movimentacoes = movimentacoes.filter(Q(origem_id=ponto) | Q(destino_id=ponto))
    movimentacoes = movimentacoes[:200]
    return render(
        request,
        "estoque/movimentacoes_list.html",
        {
            "movimentacoes": movimentacoes,
            "tipos_mov": MovimentacaoEstoque.TIPO_CHOICES,
            "pontos": PontoOperacional.objects.filter(ativo=True),
            "tipo_filtro": tipo,
            "ponto_filtro": ponto,
            "menu_app": "estoque",
            "menu_sub": "movimentacoes",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def pontos_operacionais(request):
    if request.method == "POST":
        form = PontoOperacionalForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Ponto operacional salvo.")
            return redirect("estoque:pontos_operacionais")
    else:
        form = PontoOperacionalForm()

    return render(
        request,
        "estoque/pontos_operacionais.html",
        {
            "form": form,
            "pontos": PontoOperacional.objects.all(),
            "menu_app": "estoque",
            "menu_sub": "pontos_operacionais",
        },
    )


@role_required(ORDER_ROLES)
def consulta_artigos(request):
    return render(
        request,
        "estoque/consulta_artigos.html",
        {
            "menu_app": "estoque",
            "menu_sub": "consulta_artigos",
            "metodos_pagamento": Pagamento.METODOS,
        },
    )


@role_required(ORDER_ROLES)
def api_consulta_artigos(request):
    q = (request.GET.get("q") or "").strip()
    produtos = Produto.objects.filter(ativo=True, is_servico=False)
    if q:
        q_low = q.lower()
        if q_low.isdigit():
            produtos = produtos.filter(Q(id=int(q_low)) | Q(ean__icontains=q) | Q(sku__icontains=q) | Q(nome__icontains=q))
        else:
            produtos = produtos.filter(Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q))

    data = [
        {
            "id": p.id,
            "nome": p.nome,
            "descricao": p.descricao or "",
            "ean": p.ean or "",
            "sku": p.sku or "",
            "preco": float(p.preco_final),
            "quantidade": p.quantidade,
        }
        for p in produtos.order_by("nome")[:50]
    ]
    return JsonResponse({"resultados": data})


@role_required(ORDER_ROLES)
def api_resumo_artigo(request, produto_id):
    expirar_reservas_vencidas()
    produto = get_object_or_404(Produto, id=produto_id, ativo=True)
    _normalizar_saldos_produto(produto)

    pontos = list(PontoOperacional.objects.filter(ativo=True).order_by("codigo"))
    saldos_map = {s.ponto_operacional_id: s.quantidade for s in produto.saldos_por_ponto.select_related("ponto_operacional")}

    reservas_ativas = (
        ReservaEstoque.objects.filter(produto=produto, status="ativa", valido_ate__gte=timezone.localdate())
        .values("ponto_operacional_id")
        .annotate(total=Sum("quantidade"))
    )
    reservas_map = {r["ponto_operacional_id"]: int(r["total"] or 0) for r in reservas_ativas}

    estoque_pontos = []
    for p in pontos:
        qtd = int(saldos_map.get(p.id, 0))
        reservado = int(reservas_map.get(p.id, 0))
        estoque_pontos.append(
            {
                "id": p.id,
                "codigo": p.codigo,
                "nome": p.nome,
                "quantidade": qtd,
                "reservado": reservado,
                "disponivel": max(0, qtd - reservado),
            }
        )

    reservas_recentes = [
        {
            "codigo": r.codigo_reserva,
            "nome": r.nome_contato,
            "telefone": r.telefone_contato,
            "quantidade": r.quantidade,
            "valido_ate": r.valido_ate.strftime("%d/%m/%Y"),
            "status": r.status,
            "ponto": r.ponto_operacional.codigo if r.ponto_operacional else "-",
        }
        for r in ReservaEstoque.objects.filter(produto=produto).select_related("ponto_operacional")[:15]
    ]

    movimentacoes_recentes = [
        {
            "tipo": m.get_tipo_display(),
            "quantidade": m.quantidade,
            "origem": m.origem.codigo if m.origem else "-",
            "destino": m.destino.codigo if m.destino else "-",
            "quando": timezone.localtime(m.criado_em).strftime("%d/%m/%Y %H:%M"),
            "obs": m.observacao or "",
        }
        for m in produto.movimentacoes.select_related("origem", "destino").all()[:20]
    ]

    return JsonResponse(
        {
            "id": produto.id,
            "nome": produto.nome,
            "ean": produto.ean or "",
            "sku": produto.sku or "",
            "descricao": produto.descricao or "",
            "preco": float(produto.preco_final),
            "quantidade_total": produto.quantidade,
            "estoque_minimo": produto.estoque_minimo,
            "abaixo_minimo": produto.quantidade <= int(produto.estoque_minimo or 0),
            "ponto_padrao_id": produto.ponto_operacional_id,
            "estoque_pontos": estoque_pontos,
            "reservas": reservas_recentes,
            "movimentacoes": movimentacoes_recentes,
        }
    )


@role_required(STOCK_MANAGE_ROLES)
def api_venda_rapida(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)

    produto_id = request.POST.get("produto_id")
    ponto_id = request.POST.get("ponto_id")
    funcionario_numero = (request.POST.get("funcionario_numero") or "").strip()
    metodo = request.POST.get("metodo") or "dinheiro"
    referencia = (request.POST.get("referencia") or "").strip()

    try:
        quantidade = int(request.POST.get("quantidade") or "1")
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)

    if quantidade <= 0:
        return JsonResponse({"ok": False, "erro": "Quantidade deve ser maior que zero."}, status=400)
    if not funcionario_numero:
        return JsonResponse({"ok": False, "erro": "Informe o numero do funcionario."}, status=400)

    produto = get_object_or_404(Produto, id=produto_id, ativo=True)
    ponto = get_object_or_404(PontoOperacional, id=ponto_id, ativo=True)
    _normalizar_saldos_produto(produto)

    codigo_ref = ponto.codigo.upper()
    if codigo_ref not in {"PO3", "PO2"}:
        return JsonResponse({"ok": False, "erro": "Venda permitida apenas para pontos PO3 (Loja) e PO2 (Armazem)."}, status=400)

    with transaction.atomic():
        SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto)
        pre_reservado = (
            VendaRapidaEstoque.objects.filter(
                produto=produto,
                ponto_operacional=ponto,
                status="pre_reserva",
            ).aggregate(total=Sum("quantidade"))["total"]
            or 0
        )
        disponivel = saldo_disponivel(produto, ponto) - int(pre_reservado)
        if disponivel < quantidade:
            return JsonResponse({"ok": False, "erro": "Saldo insuficiente neste ponto operacional."}, status=400)

        valor_unitario = Decimal(str(produto.preco_final))
        valor_total = valor_unitario * quantidade

        venda = VendaRapidaEstoque.objects.create(
            produto=produto,
            ponto_operacional=ponto,
            quantidade=quantidade,
            valor_unitario=valor_unitario,
            valor_total=valor_total,
            funcionario_numero=funcionario_numero,
            status="pre_reserva",
            usuario=request.user,
        )
    return JsonResponse(
        {
            "ok": True,
            "venda_id": venda.id,
            "valor_total": float(venda.valor_total),
            "redirect_caixa": f"{reverse('caixa:registrar_pagamento')}?venda={venda.id}",
        }
    )


@role_required(ORDER_ROLES)
def api_criar_reserva(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)

    produto = get_object_or_404(Produto, id=request.POST.get("produto_id"), ativo=True)
    ponto = get_object_or_404(PontoOperacional, id=request.POST.get("ponto_id"), ativo=True)
    nome = (request.POST.get("nome") or "").strip()
    telefone = (request.POST.get("telefone") or "").strip()

    try:
        quantidade = int(request.POST.get("quantidade") or "1")
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)
    if not nome:
        return JsonResponse({"ok": False, "erro": "Informe nome para reserva."}, status=400)

    try:
        valido_ate = datetime.strptime(request.POST.get("valido_ate"), "%Y-%m-%d").date()
    except Exception:
        valido_ate = timezone.localdate() + timedelta(days=2)

    if quantidade <= 0:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)
    if valido_ate < timezone.localdate():
        return JsonResponse({"ok": False, "erro": "Data de validade da reserva nao pode ser passada."}, status=400)

    expirar_reservas_vencidas()
    _normalizar_saldos_produto(produto)
    SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=ponto)
    disponivel = saldo_disponivel(produto, ponto)
    if disponivel < quantidade:
        return JsonResponse({"ok": False, "erro": "Sem saldo disponivel para reservar neste ponto."}, status=400)

    reserva = ReservaEstoque.objects.create(
        codigo_reserva=_codigo_reserva(),
        produto=produto,
        ponto_operacional=ponto,
        quantidade=quantidade,
        nome_contato=nome,
        telefone_contato=telefone,
        valido_ate=valido_ate,
        status="ativa",
        usuario=request.user,
    )

    return JsonResponse({"ok": True, "codigo_reserva": reserva.codigo_reserva})


@role_required(STOCK_MANAGE_ROLES)
def api_expirar_reservas(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    total = expirar_reservas_vencidas(usuario=request.user)
    return JsonResponse({"ok": True, "reservas_expiradas": total})


@role_required(STOCK_MANAGE_ROLES)
def api_converter_reserva(request, codigo_reserva):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    reserva = get_object_or_404(ReservaEstoque, codigo_reserva=codigo_reserva)
    try:
        converter_reserva(reserva, usuario=request.user, motivo="Conversao manual")
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
        return JsonResponse({"ok": True})
    except ValueError as exc:
        return JsonResponse({"ok": False, "erro": str(exc)}, status=400)


@role_required(STOCK_MANAGE_ROLES)
def api_inventario_iniciar(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    ponto = get_object_or_404(PontoOperacional, id=request.POST.get("ponto_id"), ativo=True)
    inventario = InventarioEstoque.objects.create(
        ponto_operacional=ponto,
        observacao=(request.POST.get("observacao") or "").strip(),
        usuario=request.user,
    )
    return JsonResponse({"ok": True, "inventario_id": inventario.id})


@role_required(STOCK_MANAGE_ROLES)
def api_inventario_adicionar_item(request, inventario_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    inventario = get_object_or_404(InventarioEstoque, id=inventario_id)
    if inventario.status != "aberto":
        return JsonResponse({"ok": False, "erro": "Inventario ja finalizado."}, status=400)
    produto = get_object_or_404(Produto, id=request.POST.get("produto_id"))
    try:
        quantidade_contada = int(request.POST.get("quantidade_contada") or "0")
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Quantidade invalida."}, status=400)

    saldo, _ = SaldoEstoquePonto.objects.get_or_create(produto=produto, ponto_operacional=inventario.ponto_operacional)
    item, _ = ItemInventarioEstoque.objects.get_or_create(
        inventario=inventario,
        produto=produto,
        defaults={"quantidade_sistema": saldo.quantidade},
    )
    item.quantidade_sistema = saldo.quantidade
    item.quantidade_contada = quantidade_contada
    item.ajuste = quantidade_contada - saldo.quantidade
    item.observacao = (request.POST.get("observacao") or "").strip()
    item.save()
    return JsonResponse({"ok": True, "ajuste": item.ajuste})


@role_required(STOCK_MANAGE_ROLES)
def api_inventario_finalizar(request, inventario_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    inventario = get_object_or_404(InventarioEstoque, id=inventario_id)
    if inventario.status != "aberto":
        return JsonResponse({"ok": False, "erro": "Inventario ja finalizado."}, status=400)

    with transaction.atomic():
        for item in inventario.itens.select_related("produto"):
            if item.ajuste == 0:
                continue
            ajustar_saldo(item.produto, inventario.ponto_operacional, item.ajuste)
            MovimentacaoEstoque.objects.create(
                produto=item.produto,
                tipo="inventario",
                quantidade=item.ajuste,
                origem=inventario.ponto_operacional if item.ajuste < 0 else None,
                destino=inventario.ponto_operacional if item.ajuste > 0 else None,
                observacao=f"Ajuste inventario #{inventario.id}",
                usuario=request.user,
            )
        inventario.status = "fechado"
        inventario.fechado_em = timezone.now()
        inventario.save(update_fields=["status", "fechado_em"])
    return JsonResponse({"ok": True})


@role_required(STOCK_VIEW_ROLES)
def api_alertas_estoque(request):
    produtos = Produto.objects.filter(ativo=True, is_servico=False).order_by("nome")
    abaixo = []
    for p in produtos:
        if int(p.quantidade) <= int(p.estoque_minimo or 0):
            abaixo.append(
                {
                    "id": p.id,
                    "nome": p.nome,
                    "sku": p.sku or "",
                    "ean": p.ean or "",
                    "quantidade": int(p.quantidade),
                    "estoque_minimo": int(p.estoque_minimo or 0),
                }
            )
    return JsonResponse({"resultados": abaixo[:100]})


@role_required(STOCK_VIEW_ROLES)
def reservas_clientes(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    reservas = ReservaEstoque.objects.select_related("produto", "ponto_operacional", "ordem_servico")
    if q:
        reservas = reservas.filter(
            Q(codigo_reserva__icontains=q)
            | Q(nome_contato__icontains=q)
            | Q(telefone_contato__icontains=q)
            | Q(produto__nome__icontains=q)
        )
    if status:
        reservas = reservas.filter(status=status)
    reservas = reservas[:200]
    return render(
        request,
        "estoque/reservas_clientes.html",
        {
            "reservas": reservas,
            "q": q,
            "status_filtro": status,
            "status_choices": ReservaEstoque.STATUS_CHOICES,
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


def integrar_reservas_no_fechamento(ordem, usuario=None):
    return consumir_reservas_ordem(ordem, usuario=usuario)


def integrar_reservas_na_reabertura(ordem, usuario=None):
    return devolver_reservas_ordem(ordem, usuario=usuario)

