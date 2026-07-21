from decimal import Decimal
import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.permissions import (
    ORDER_ROLES,
    STOCK_MANAGE_ROLES,
    STOCK_VIEW_ROLES,
    has_sensitive_permission,
    require_sensitive_permission,
    role_required,
)
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa

from ..forms import CategoriaProdutoForm, ProdutoEquivalenteForm, ProdutoFornecedorForm, ProdutoForm, ProdutoKitItemForm, ProdutoPrecoTabelaForm, TabelaPrecoForm
from ..models import CategoriaProduto, EstoqueLote, EstoqueSerie, ItemEntradaMercadoria, PontoOperacional, Produto, ProdutoEquivalente, ProdutoFornecedor, ProdutoKitItem, ProdutoPrecoTabela, ReservaEstoque, SaldoEstoquePonto, TabelaPreco, UbicacaoEstoque
from .helpers import (
    Empresa,
    FornecedorGarantia,
    MarcaGarantia,
    _aplicar_estoque_inicial,
    _contexto_precificacao_produto,
    _contexto_rateio_produto,
    _initial_produto_from_origem,
    _ler_arquivo_importacao_produtos,
    _normalizar_linha_importacao,
    _normalizar_saldos_produto,
    _normalizar_texto,
    _recalcular_total_produto,
    _registrar_historico_produto,
    _snapshot_produto,
)

logger = logging.getLogger(__name__)


def _categorias_catalogo_payload():
    categorias = CategoriaProduto.objects.filter(ativo=True).order_by("ordem", "nome")
    return [
        {
            "id": categoria.id,
            "nome": categoria.nome,
            "margem_padrao": float(categoria.margem_padrao or 0),
        }
        for categoria in categorias
    ]


def _comparativo_fornecedores_produto(produto):
    fornecedores = list(
        ProdutoFornecedor.objects.select_related("fornecedor_config")
        .filter(produto=produto)
        .order_by("-preferencial", "custo_referencia", "fornecedor_manual", "id")
    )
    if not fornecedores:
        return {
            "linhas": [],
            "menor_custo": None,
            "preferencial": None,
            "ultimo_custo_entrada": Decimal("0.00"),
            "fornecedores_ativos": 0,
        }

    ultimo_item = (
        ItemEntradaMercadoria.objects.select_related("entrada", "entrada__fornecedor_config")
        .filter(produto=produto, entrada__status="recebida")
        .order_by("-entrada__data_entrada", "-entrada__id", "-id")
        .first()
    )
    ultimo_custo = Decimal(str(getattr(ultimo_item, "custo_entrada_unitario", 0) or 0))
    menor_custo = None
    preferencial = None
    for item in fornecedores:
        custo_ref = Decimal(str(item.custo_referencia or 0))
        custo_menor_atual = Decimal(str(getattr(menor_custo, "custo_referencia", 0) or 0))
        if item.ativo and (
            menor_custo is None
            or (custo_ref > 0 and (custo_menor_atual <= 0 or custo_ref < custo_menor_atual))
        ):
            menor_custo = item
        if item.preferencial and preferencial is None:
            preferencial = item

    linhas = []
    for item in fornecedores:
        custo_ref = Decimal(str(item.custo_referencia or 0))
        delta_ultimo = custo_ref - ultimo_custo if ultimo_custo > 0 and custo_ref > 0 else None
        delta_menor = custo_ref - Decimal(str(menor_custo.custo_referencia or 0)) if menor_custo and custo_ref > 0 else None
        acao_recompra = "Revisar"
        if not item.ativo:
            acao_recompra = "Inativo"
        elif menor_custo and item.id == menor_custo.id and preferencial and preferencial.id != item.id:
            acao_recompra = "Negociar / comprar"
        elif preferencial and item.id == preferencial.id and menor_custo and menor_custo.id != item.id:
            acao_recompra = "Negociar custo"
        elif preferencial and item.id == preferencial.id:
            acao_recompra = "Comprar"
        elif menor_custo and item.id == menor_custo.id:
            acao_recompra = "Comprar"
        linhas.append(
            {
                "item": item,
                "fornecedor_nome": item.fornecedor_nome,
                "custo_referencia": custo_ref,
                "delta_ultimo": delta_ultimo,
                "delta_menor": delta_menor,
                "eh_melhor_preco": bool(menor_custo and item.id == menor_custo.id),
                "eh_preferencial": bool(preferencial and item.id == preferencial.id),
                "acao_recompra": acao_recompra,
            }
        )

    return {
        "linhas": linhas,
        "menor_custo": menor_custo,
        "preferencial": preferencial,
        "ultimo_custo_entrada": ultimo_custo,
        "fornecedores_ativos": sum(1 for item in fornecedores if item.ativo),
    }


def _recomendacao_recompra_produto(produto, fornecedores_contexto):
    menor_custo = fornecedores_contexto.get("menor_custo")
    preferencial = fornecedores_contexto.get("preferencial")
    ultimo_custo = Decimal(str(fornecedores_contexto.get("ultimo_custo_entrada") or 0))

    if not menor_custo and not preferencial:
        return {
            "status": "sem_base",
            "titulo": "Sem base de recompra",
            "mensagem": "Cadastre pelo menos um fornecedor para transformar esta ficha em apoio real de recompra.",
            "fornecedor_recomendado": None,
            "economia_unitaria": Decimal("0.00"),
            "variacao_ultima_compra": None,
            "link_entrada": reverse("estoque:nova_entrada_mercadoria"),
        }

    fornecedor_recomendado = preferencial or menor_custo
    titulo = "Recompra orientada"
    mensagem = "O fornecedor preferencial segue como referencia principal para recompra."
    status = "preferencial"

    if menor_custo and preferencial and menor_custo.id != preferencial.id:
        custo_pref = Decimal(str(preferencial.custo_referencia or 0))
        custo_menor = Decimal(str(menor_custo.custo_referencia or 0))
        if custo_pref > 0 and custo_menor > 0 and custo_menor < custo_pref:
            fornecedor_recomendado = menor_custo
            status = "melhor_custo"
            titulo = "Recompra com economia"
            mensagem = (
                f"O melhor custo atual esta com {menor_custo.fornecedor_nome}. "
                "Use esta base para negociar ou comprar direto se a operacao exigir reposicao rapida."
            )

    custo_recomendado = Decimal(str(getattr(fornecedor_recomendado, "custo_referencia", 0) or 0))
    economia_unitaria = Decimal("0.00")
    variacao_ultima_compra = None
    if menor_custo and preferencial and menor_custo.id != preferencial.id:
        custo_pref = Decimal(str(preferencial.custo_referencia or 0))
        custo_menor = Decimal(str(menor_custo.custo_referencia or 0))
        if custo_pref > 0 and custo_menor > 0 and custo_menor < custo_pref:
            economia_unitaria = custo_pref - custo_menor

    if ultimo_custo > 0 and custo_recomendado > 0:
        variacao_ultima_compra = custo_recomendado - ultimo_custo

    params = {"produto": produto.id}
    if getattr(fornecedor_recomendado, "fornecedor_config_id", None):
        params["fornecedor"] = fornecedor_recomendado.fornecedor_config_id
    elif fornecedor_recomendado and fornecedor_recomendado.fornecedor_manual:
        params["fornecedor_manual"] = fornecedor_recomendado.fornecedor_manual
    if getattr(produto, "ponto_operacional_id", None):
        params["ponto"] = produto.ponto_operacional_id
    if getattr(produto, "ubicacao_padrao_id", None):
        params["ubicacao"] = produto.ubicacao_padrao_id

    return {
        "status": status,
        "titulo": titulo,
        "mensagem": mensagem,
        "fornecedor_recomendado": fornecedor_recomendado,
        "economia_unitaria": economia_unitaria,
        "variacao_ultima_compra": variacao_ultima_compra,
        "link_entrada": f"{reverse('estoque:nova_entrada_mercadoria')}?{urlencode(params)}",
    }


def _contexto_form_produto(*, form, empresa, menu_sub, modo_edicao, produto=None, produto_origem=None):
    referencia_rateio = produto if modo_edicao else produto_origem
    referencia_precificacao = produto if modo_edicao else produto_origem
    return {
        "form": form,
        "produto": produto,
        "menu_app": "estoque",
        "menu_sub": menu_sub,
        "produto_origem": produto_origem,
        "modo_edicao": modo_edicao,
        "precificacao_context": _contexto_precificacao_produto(referencia_precificacao),
        "rateio_context": _contexto_rateio_produto(referencia_rateio, empresa=empresa),
        "empresa": empresa,
        "categorias_catalogo": _categorias_catalogo_payload(),
    }


def _url_retorno_produto_salvo(produto):
    params = {
        "carregar": 1,
        "q": produto.nome,
        "tipo": "servicos" if produto.eh_servico else "produtos",
    }
    return f"{reverse('estoque:lista_produtos')}?{urlencode(params)}"


def _mensagem_erro_produto(exc):
    detalhe = " ".join(str(exc or "").strip().split())
    detalhe_lower = detalhe.lower()
    if ("unique" in detalhe_lower or "duplicate" in detalhe_lower) and "ean" in detalhe_lower:
        return "Ja existe um produto cadastrado com este EAN."
    if ("unique" in detalhe_lower or "duplicate" in detalhe_lower) and "sku" in detalhe_lower:
        return "Ja existe um produto cadastrado com este SKU."
    if "nome" in detalhe_lower and ("unique" in detalhe_lower or "duplicate" in detalhe_lower):
        return "Ja existe um produto cadastrado com este nome."
    if "ubicacao" in detalhe_lower and "ponto" in detalhe_lower:
        return "A ubicacao informada nao pertence ao ponto operacional selecionado."
    if "13 digitos" in detalhe_lower or ("ean" in detalhe_lower and "13" in detalhe_lower):
        return "O EAN precisa ter exatamente 13 digitos."
    if detalhe:
        return f"Nao foi possivel salvar o produto: {detalhe}"
    return "Nao foi possivel salvar o produto. Revise os dados informados e tente novamente."


def _resolver_ponto_importacao(valor, *, pontos_ativos, fallback=None):
    texto = _normalizar_texto(valor)
    if not texto:
        return fallback
    for ponto in pontos_ativos:
        if _normalizar_texto(ponto.codigo) == texto or _normalizar_texto(ponto.nome) == texto:
            return ponto
    return None


def _resolver_ubicacao_importacao(valor, *, ubicacoes_ativas, ponto=None, fallback=None):
    texto = _normalizar_texto(valor)
    if not texto:
        return fallback
    for ubicacao in ubicacoes_ativas:
        if ponto and ubicacao.ponto_operacional_id != ponto.id:
            continue
        if _normalizar_texto(ubicacao.codigo) == texto or _normalizar_texto(ubicacao.descricao) == texto:
            return ubicacao
    return None


def _obter_ou_criar_ubicacao_importacao(valor, *, ponto, ubicacoes_ativas):
    texto = " ".join(str(valor or "").strip().split())
    if not texto or not ponto:
        return None
    existente = _resolver_ubicacao_importacao(texto, ubicacoes_ativas=ubicacoes_ativas, ponto=ponto)
    if existente:
        return existente
    nova = UbicacaoEstoque.objects.create(
        ponto_operacional=ponto,
        codigo=texto[:30].upper(),
        descricao="",
        ativo=True,
    )
    ubicacoes_ativas.append(nova)
    return nova


@role_required(STOCK_VIEW_ROLES)
def buscar_produtos(request):
    messages.info(request, "A tela 'Buscar Produto' foi descontinuada. Use 'Consulta de Artigos'.")
    return redirect("estoque:consulta_artigos")


@role_required(STOCK_VIEW_ROLES)
def lista_produtos(request):
    empresa = obter_empresa_ativa(request, strict=False)
    filtro = request.GET.get("tipo", "todos")
    ponto_id = request.GET.get("ponto")
    q = (request.GET.get("q") or "").strip()
    quick = (request.GET.get("quick") or "").strip()
    page_number = request.GET.get("page")
    carregar = (request.GET.get("carregar") or "").strip() == "1"
    carregar = carregar or bool(q or quick or ponto_id or page_number or filtro != "todos")

    produtos_base = filtrar_queryset_empresa(Produto.objects.all(), empresa)
    if filtro == "servicos":
        produtos_ativos = produtos_base.ativos().servicos()
    elif filtro == "produtos":
        produtos_ativos = produtos_base.ativos().nao_servicos()
    else:
        produtos_ativos = produtos_base.ativos()

    if ponto_id:
        produtos_ativos = produtos_ativos.filter(ponto_operacional_id=ponto_id)

    if q:
        produtos_ativos = produtos_ativos.filter(
            Q(nome__icontains=q)
            | Q(sku__icontains=q)
            | Q(ean__icontains=q)
            | Q(descricao__icontains=q)
            | Q(modelos_compativeis__icontains=q)
            | Q(marca__nome__icontains=q)
            | Q(categoria_config__nome__icontains=q)
            | Q(fornecedor_config__nome__icontains=q)
            | Q(fornecedor_manual__icontains=q)
            | Q(ponto_operacional__codigo__icontains=q)
            | Q(ponto_operacional__nome__icontains=q)
            | Q(ubicacao_padrao__codigo__icontains=q)
            | Q(ubicacao_padrao__descricao__icontains=q)
            | Q(localizacao__icontains=q)
        ).distinct()

    resumo_qs = produtos_ativos
    resumo = {
        "total": resumo_qs.count(),
        "baixo_estoque": resumo_qs.filter(quantidade__lte=F("estoque_minimo")).count(),
        "sem_saldo": resumo_qs.filter(quantidade__lte=0).count(),
        "permite_os": resumo_qs.filter(permite_os=True).count(),
        "sem_estrutura": resumo_qs.nao_servicos().filter(Q(ponto_operacional__isnull=True) | Q(ubicacao_padrao__isnull=True)).count(),
    }

    produtos_page = None
    if carregar:
        produtos = produtos_ativos
        if quick == "baixo_estoque":
            produtos = produtos.filter(quantidade__lte=F("estoque_minimo"))
        elif quick == "sem_saldo":
            produtos = produtos.filter(quantidade__lte=0)
        elif quick == "permite_os":
            produtos = produtos.filter(permite_os=True)
        elif quick == "sem_estrutura":
            produtos = produtos.nao_servicos().filter(Q(ponto_operacional__isnull=True) | Q(ubicacao_padrao__isnull=True))

        produtos = produtos.select_related("ponto_operacional", "ubicacao_padrao", "categoria_config", "marca", "fornecedor_config").order_by("nome")
        produtos_page = Paginator(produtos, 30).get_page(page_number)
        produtos_pagina = list(produtos_page.object_list)
        produto_ids = [item.id for item in produtos_pagina if getattr(item, "ponto_operacional_id", None)]
        saldos_map = {}
        reservas_map = {}
        if produto_ids:
            for saldo in SaldoEstoquePonto.objects.filter(produto_id__in=produto_ids).values("produto_id", "ponto_operacional_id", "quantidade"):
                saldos_map[(saldo["produto_id"], saldo["ponto_operacional_id"])] = int(saldo["quantidade"] or 0)
            for reserva in (
                ReservaEstoque.objects.filter(
                    produto_id__in=produto_ids,
                    status="ativa",
                    valido_ate__gte=timezone.localdate(),
                )
                .values("produto_id", "ponto_operacional_id")
                .annotate(total=Sum("quantidade"))
            ):
                reservas_map[(reserva["produto_id"], reserva["ponto_operacional_id"])] = int(reserva["total"] or 0)
        for item in produtos_pagina:
            key = (item.id, getattr(item, "ponto_operacional_id", None))
            saldo_ponto = saldos_map.get(key, int(item.quantidade or 0))
            saldo_reservado = reservas_map.get(key, 0)
            item.saldo_ponto = saldo_ponto
            item.saldo_reservado = saldo_reservado
            item.saldo_disponivel = max(0, saldo_ponto - saldo_reservado)
        produtos_page.object_list = produtos_pagina

    context = {
        "produtos": produtos_page or [],
        "produtos_page": produtos_page,
        "pontos": PontoOperacional.objects.filter(ativo=True),
        "menu_app": "estoque",
        "menu_sub": "lista_produtos",
        "filtro": filtro,
        "ponto_filtro": ponto_id or "",
        "q": q,
        "quick": quick,
        "carregar": carregar,
        "resumo": resumo,
    }
    return render(request, "estoque/lista_produtos.html", context)


@role_required(STOCK_MANAGE_ROLES)
def categorias_produto(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    q = (request.GET.get("q") or "").strip()
    editar_id = request.GET.get("editar")
    next_url = (request.GET.get("next") or request.POST.get("next") or "").strip()

    categoria_edicao = None
    if editar_id and str(editar_id).isdigit():
        categoria_edicao = CategoriaProduto.objects.filter(id=int(editar_id)).first()

    if request.method == "POST":
        categoria_id = request.POST.get("categoria_id")
        instancia = None
        if categoria_id and str(categoria_id).isdigit():
            instancia = CategoriaProduto.objects.filter(id=int(categoria_id)).first()
        form = CategoriaProdutoForm(request.POST, instance=instancia)
        if form.is_valid():
            categoria = form.save()
            messages.success(request, f"Categoria '{categoria.nome}' salva com sucesso.")
            if next_url:
                return redirect(next_url)
            return redirect("estoque:categorias_produto")
    else:
        form = CategoriaProdutoForm(instance=categoria_edicao)

    categorias = CategoriaProduto.objects.order_by("ordem", "nome")
    if q:
        categorias = categorias.filter(nome__icontains=q)
    categorias = categorias.annotate(
        total_produtos=Count("produtos", distinct=True),
        total_produtos_ativos=Count("produtos", filter=Q(produtos__ativo=True), distinct=True),
    )

    return render(
        request,
        "estoque/categorias_produto.html",
        {
            "form": form,
            "categorias": categorias,
            "categoria_edicao": categoria_edicao,
            "q": q,
            "next_url": next_url,
            "menu_app": "estoque",
            "menu_sub": "categorias_produto",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def api_categoria_produto_criar(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo nao permitido."}, status=405)

    nome = " ".join((request.POST.get("nome") or "").strip().split())
    margem_padrao = (request.POST.get("margem_padrao") or "0").strip()

    if not nome:
        return JsonResponse({"ok": False, "erro": "Informe o nome da categoria."}, status=400)

    categoria_existente = CategoriaProduto.encontrar_por_nome(nome, incluir_inativas=True)
    if categoria_existente:
        if not categoria_existente.ativo:
            categoria_existente.ativo = True
            categoria_existente.save(update_fields=["ativo"])
        return JsonResponse(
            {
                "ok": True,
                "criada": False,
                "mensagem": "Categoria existente reaproveitada.",
                "categoria": {
                    "id": categoria_existente.id,
                    "nome": categoria_existente.nome,
                    "margem_padrao": float(categoria_existente.margem_padrao or 0),
                },
            }
        )

    form = CategoriaProdutoForm(
        data={
            "nome": nome,
            "margem_padrao": margem_padrao or "0",
            "ordem": "0",
            "ativo": "on",
        }
    )
    if not form.is_valid():
        erros = []
        for campo, mensagens in form.errors.items():
            for mensagem in mensagens:
                erros.append(f"{campo}: {mensagem}")
        return JsonResponse({"ok": False, "erro": " ".join(erros) or "Nao foi possivel salvar a categoria."}, status=400)

    categoria = form.save()
    return JsonResponse(
        {
            "ok": True,
            "criada": True,
            "mensagem": "Categoria criada e pronta para uso.",
            "categoria": {
                "id": categoria.id,
                "nome": categoria.nome,
                "margem_padrao": float(categoria.margem_padrao or 0),
            },
        }
    )


@role_required(STOCK_MANAGE_ROLES)
def criar_produto(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    ultimo = filtrar_queryset_empresa(Produto.objects.all(), empresa).order_by("-id").first()
    initial = {}
    if ultimo:
        initial = {
            "icms": ultimo.icms,
            "ipi": ultimo.ipi,
            "pis_cofins": ultimo.pis_cofins,
            "margem_lucro": ultimo.margem_lucro,
            "custo_operacional": ultimo.custo_operacional,
            "custo_cac": getattr(ultimo, "custo_cac", 0),
            "previsao_venda_mensal": getattr(ultimo, "previsao_venda_mensal", 0),
            "incluir_rateio_custo_fixo": getattr(ultimo, "incluir_rateio_custo_fixo", False),
            "ponto_operacional": ultimo.ponto_operacional_id,
            "ubicacao_padrao": ultimo.ubicacao_padrao_id,
        }
    duplicar_id = request.GET.get("duplicar")
    produto_origem = None
    if duplicar_id and str(duplicar_id).isdigit():
        produto_origem = filtrar_queryset_empresa(Produto.objects.all(), empresa).filter(id=int(duplicar_id), ativo=True).first()
        if produto_origem:
            initial.update(_initial_produto_from_origem(produto_origem))
            initial["nome"] = f"{produto_origem.nome} (copia)"
            initial["sku"] = ""
            initial["ean"] = ""
            initial["estoque_inicial"] = 0

    if request.method == "POST":
        form = ProdutoForm(request.POST, request.FILES)
        if empresa:
            form.instance.empresa = empresa
        if form.is_valid():
            abaixo_minimo = bool(form.cleaned_data.get("preco_abaixo_minimo_detectado"))
            permitir_abaixo = bool(form.cleaned_data.get("permitir_preco_abaixo_minimo"))
            justificativa_abaixo = (form.cleaned_data.get("justificativa_preco_abaixo_minimo") or "").strip()
            if abaixo_minimo and permitir_abaixo and not has_sensitive_permission(request.user, "perm_caixa_aplicar_desconto"):
                form.add_error("permitir_preco_abaixo_minimo", "Somente gerente/administrador pode aprovar preco abaixo do minimo.")
                return render(request, "estoque/form_produto.html", _contexto_form_produto(form=form, empresa=empresa, menu_sub="criar_produto", modo_edicao=False, produto_origem=produto_origem))
            try:
                produto = form.save()
                if produto.empresa_id != getattr(empresa, "id", None):
                    produto.empresa = empresa
                    produto.save(update_fields=["empresa"])
                estoque_inicial = form.cleaned_data.get("estoque_inicial") or 0
                custo_entrada = form.cleaned_data.get("custo_entrada_inicial")
                _aplicar_estoque_inicial(produto, estoque_inicial=estoque_inicial, custo_entrada=custo_entrada, usuario=request.user, observacao="Entrada inicial gerada no cadastro do produto.")
                _normalizar_saldos_produto(produto)
                _recalcular_total_produto(produto)
                observacao_historico = "Cadastro inicial de produto."
                if abaixo_minimo and permitir_abaixo and justificativa_abaixo:
                    observacao_historico = f"{observacao_historico} Aprovado abaixo do minimo: {justificativa_abaixo}"
                _registrar_historico_produto(
                    produto,
                    usuario=request.user,
                    acao="DUPLICACAO" if produto_origem else "CRIACAO",
                    dados_antes=_snapshot_produto(produto_origem) if produto_origem else {},
                    observacao=observacao_historico,
                )
            except IntegrityError as exc:
                logger.exception(
                    "Falha de integridade ao salvar produto",
                    extra={"produto_nome": request.POST.get("nome", ""), "modo_edicao": False},
                )
                erro = _mensagem_erro_produto(exc)
                form.add_error(None, erro)
                messages.error(request, erro)
                return render(
                    request,
                    "estoque/form_produto.html",
                    _contexto_form_produto(
                        form=form,
                        empresa=empresa,
                        menu_sub="criar_produto",
                        modo_edicao=False,
                        produto_origem=produto_origem,
                    ),
                )
            except Exception as exc:
                logger.exception("Falha ao salvar produto", extra={"produto_nome": request.POST.get("nome", ""), "modo_edicao": False})
                erro = _mensagem_erro_produto(exc)
                form.add_error(None, erro)
                messages.error(request, erro)
                return render(request, "estoque/form_produto.html", _contexto_form_produto(form=form, empresa=empresa, menu_sub="criar_produto", modo_edicao=False, produto_origem=produto_origem))
            if "_save_and_new" in request.POST:
                messages.success(request, "Produto cadastrado. Pronto para incluir o proximo.")
                return redirect("estoque:criar_produto")
            if "_save_and_structure" in request.POST:
                messages.success(request, "Produto cadastrado. Agora complete a estrutura comercial e operacional do item.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)
            messages.success(request, "Produto cadastrado com sucesso.")
            return redirect(_url_retorno_produto_salvo(produto))
    else:
        form = ProdutoForm(initial=initial)

    return render(request, "estoque/form_produto.html", _contexto_form_produto(form=form, empresa=empresa, menu_sub="criar_produto", modo_edicao=False, produto_origem=produto_origem))


@role_required(STOCK_MANAGE_ROLES)
def editar_produto(request, produto_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    produto = get_object_or_404(filtrar_queryset_empresa(Produto.objects.all(), empresa), id=produto_id)
    if request.method == "POST":
        snapshot_antes = _snapshot_produto(produto)
        form = ProdutoForm(request.POST, request.FILES, instance=produto)
        if form.is_valid():
            abaixo_minimo = bool(form.cleaned_data.get("preco_abaixo_minimo_detectado"))
            permitir_abaixo = bool(form.cleaned_data.get("permitir_preco_abaixo_minimo"))
            justificativa_abaixo = (form.cleaned_data.get("justificativa_preco_abaixo_minimo") or "").strip()
            if abaixo_minimo and permitir_abaixo and not has_sensitive_permission(request.user, "perm_caixa_aplicar_desconto"):
                form.add_error("permitir_preco_abaixo_minimo", "Somente gerente/administrador pode aprovar preco abaixo do minimo.")
                return render(request, "estoque/form_produto.html", _contexto_form_produto(form=form, empresa=empresa, menu_sub="lista_produtos", modo_edicao=True, produto=produto))
            try:
                produto = form.save()
                estoque_inicial = form.cleaned_data.get("estoque_inicial") or 0
                custo_entrada = form.cleaned_data.get("custo_entrada_inicial")
                _aplicar_estoque_inicial(produto, estoque_inicial=estoque_inicial, custo_entrada=custo_entrada, usuario=request.user, observacao="Entrada manual adicional no cadastro do produto.")
                _normalizar_saldos_produto(produto)
                _recalcular_total_produto(produto)
                observacao_historico = "Atualizacao de cadastro do produto."
                if abaixo_minimo and permitir_abaixo and justificativa_abaixo:
                    observacao_historico = f"{observacao_historico} Aprovado abaixo do minimo: {justificativa_abaixo}"
                _registrar_historico_produto(
                    produto,
                    usuario=request.user,
                    acao="EDICAO",
                    dados_antes=snapshot_antes,
                    observacao=observacao_historico,
                )
            except IntegrityError as exc:
                logger.exception(
                    "Falha de integridade ao atualizar produto",
                    extra={"produto_id": produto.id, "modo_edicao": True},
                )
                erro = _mensagem_erro_produto(exc)
                form.add_error(None, erro)
                messages.error(request, erro)
                return render(
                    request,
                    "estoque/form_produto.html",
                    _contexto_form_produto(
                        form=form,
                        empresa=empresa,
                        menu_sub="lista_produtos",
                        modo_edicao=True,
                        produto=produto,
                    ),
                )
            except Exception as exc:
                logger.exception("Falha ao atualizar produto", extra={"produto_id": produto.id, "modo_edicao": True})
                erro = _mensagem_erro_produto(exc)
                form.add_error(None, erro)
                messages.error(request, erro)
                return render(request, "estoque/form_produto.html", _contexto_form_produto(form=form, empresa=empresa, menu_sub="lista_produtos", modo_edicao=True, produto=produto))
            if "_save_and_new" in request.POST:
                messages.success(request, "Produto atualizado com sucesso!")
                return redirect("estoque:criar_produto")
            if "_save_and_structure" in request.POST:
                messages.success(request, "Ficha atualizada. Agora revise fornecedores, equivalencias e estrutura complementar.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)
            messages.success(request, "Produto atualizado com sucesso!")
            return redirect(_url_retorno_produto_salvo(produto))
    else:
        form = ProdutoForm(instance=produto)

    return render(request, "estoque/form_produto.html", _contexto_form_produto(form=form, empresa=empresa, menu_sub="lista_produtos", modo_edicao=True, produto=produto))


@role_required(STOCK_MANAGE_ROLES)
def duplicar_produto(request, produto_id):
    return redirect(f"{reverse('estoque:criar_produto')}?duplicar={produto_id}")


@role_required(STOCK_MANAGE_ROLES)
def importar_produtos(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    preview = []
    erros = []
    importados = 0
    pontos_ativos = list(PontoOperacional.objects.filter(ativo=True).order_by("codigo"))
    ubicacoes_ativas = list(
        UbicacaoEstoque.objects.filter(ativo=True).select_related("ponto_operacional").order_by("ponto_operacional__codigo", "codigo")
    )
    ultimo_produto = filtrar_queryset_empresa(Produto.objects.all(), empresa).order_by("-id").first()
    ponto_default_id = (request.POST.get("ponto_operacional_padrao") or "").strip()
    ubicacao_default_id = (request.POST.get("ubicacao_padrao_importacao") or "").strip()
    ubicacao_default_texto = " ".join((request.POST.get("ubicacao_padrao_importacao_texto") or "").strip().split())

    ponto_padrao = None
    if ponto_default_id.isdigit():
        ponto_padrao = next((item for item in pontos_ativos if item.id == int(ponto_default_id)), None)
    if not ponto_padrao and getattr(ultimo_produto, "ponto_operacional_id", None):
        ponto_padrao = next((item for item in pontos_ativos if item.id == ultimo_produto.ponto_operacional_id), None)
    if not ponto_padrao and pontos_ativos:
        ponto_padrao = pontos_ativos[0]

    ubicacao_padrao = None
    if ubicacao_default_id.isdigit():
        ubicacao_padrao = next((item for item in ubicacoes_ativas if item.id == int(ubicacao_default_id)), None)
    if not ubicacao_padrao and getattr(ultimo_produto, "ubicacao_padrao_id", None):
        ubicacao_padrao = next((item for item in ubicacoes_ativas if item.id == ultimo_produto.ubicacao_padrao_id), None)
    if not ubicacao_padrao and ponto_padrao:
        ubicacao_padrao = next((item for item in ubicacoes_ativas if item.ponto_operacional_id == ponto_padrao.id), None)
    if ubicacao_default_texto and ponto_padrao:
        ubicacao_padrao = _obter_ou_criar_ubicacao_importacao(
            ubicacao_default_texto,
            ponto=ponto_padrao,
            ubicacoes_ativas=ubicacoes_ativas,
        )

    if request.method == "POST":
        arquivo = request.FILES.get("arquivo")
        acao = (request.POST.get("acao") or "validar").strip().lower()
        if not arquivo:
            messages.error(request, "Selecione um arquivo CSV ou XLSX para importar.")
            return redirect("estoque:importar_produtos")
        try:
            linhas = _ler_arquivo_importacao_produtos(arquivo)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("estoque:importar_produtos")

        normalizadas = []
        nomes_arquivo = set()
        eans_arquivo = set()
        produtos_empresa_qs = filtrar_queryset_empresa(Produto.objects.all(), empresa)
        for idx, linha in enumerate(linhas, start=2):
            row = _normalizar_linha_importacao(linha)
            row["linha"] = idx
            row["erros"] = []
            ponto_resolvido = _resolver_ponto_importacao(row.get("ponto_operacional"), pontos_ativos=pontos_ativos, fallback=ponto_padrao)
            ubicacao_resolvida = _resolver_ubicacao_importacao(
                row.get("ubicacao"),
                ubicacoes_ativas=ubicacoes_ativas,
                ponto=ponto_resolvido,
                fallback=ubicacao_padrao if ponto_resolvido and ubicacao_padrao and ubicacao_padrao.ponto_operacional_id == ponto_resolvido.id else None,
            )
            if not row["nome"]:
                row["erros"].append("Nome obrigatorio.")
            nome_key = _normalizar_texto(row["nome"])
            if nome_key in nomes_arquivo and nome_key:
                row["erros"].append("Nome duplicado no arquivo.")
            elif nome_key:
                nomes_arquivo.add(nome_key)
            if row["tipo_item"] not in {"produto", "peca", "consumivel", "servico"}:
                row["erros"].append("Tipo de item invalido.")
            ean_limpo = "".join(ch for ch in (row["ean"] or "") if ch.isdigit())
            row["ean"] = ean_limpo
            if ean_limpo and len(ean_limpo) != 13:
                row["erros"].append("EAN deve ter 13 digitos.")
            if ean_limpo:
                if ean_limpo in eans_arquivo:
                    row["erros"].append("EAN duplicado no arquivo.")
                else:
                    eans_arquivo.add(ean_limpo)
            try:
                row["preco_final_dec"] = Decimal(str(row["preco_final"] or "0"))
                if row["preco_final_dec"] < 0:
                    row["erros"].append("Preco final nao pode ser negativo.")
            except (ArithmeticError, ValueError, TypeError):
                row["erros"].append("Preco final invalido.")
                row["preco_final_dec"] = Decimal("0")
            try:
                row["custo_unitario_dec"] = Decimal(str(row["custo_unitario"] or "0"))
                if row["custo_unitario_dec"] < 0:
                    row["erros"].append("Custo unitario nao pode ser negativo.")
            except (ArithmeticError, ValueError, TypeError):
                row["erros"].append("Custo unitario invalido.")
                row["custo_unitario_dec"] = Decimal("0")
            try:
                row["estoque_minimo_int"] = max(0, int(str(row["estoque_minimo"] or "0")))
                row["estoque_inicial_int"] = max(0, int(str(row["estoque_inicial"] or "0")))
            except (TypeError, ValueError):
                row["erros"].append("Estoque minimo/inicial invalido.")
                row["estoque_minimo_int"] = 0
                row["estoque_inicial_int"] = 0
            row["ponto_resolvido"] = ponto_resolvido
            row["ubicacao_resolvida"] = ubicacao_resolvida
            if row["tipo_item"] != "servico":
                if not ponto_resolvido:
                    row["erros"].append("Informe um ponto operacional valido na linha ou escolha um padrao para itens fisicos.")
                if not ubicacao_resolvida:
                    row["erros"].append("Informe uma ubicacao valida na linha ou escolha uma ubicacao padrao para itens fisicos.")
            if row.get("ponto_operacional") and not ponto_resolvido:
                row["erros"].append("Ponto operacional da linha nao encontrado.")
            if row.get("ubicacao") and not ubicacao_resolvida:
                row["erros"].append("Ubicacao da linha nao encontrada para o ponto operacional informado.")
            if row["nome"] and produtos_empresa_qs.filter(nome__iexact=row["nome"]).exists():
                row["erros"].append("Ja existe produto com este nome no sistema.")
            if row["ean"] and produtos_empresa_qs.filter(ean=row["ean"]).exists():
                row["erros"].append("Ja existe produto com este EAN no sistema.")

            normalizadas.append(row)
            if row["erros"]:
                erros.append((idx, list(row["erros"])))

        preview = normalizadas[:200]
        if acao == "importar" and not erros:
            with transaction.atomic():
                for row in normalizadas:
                    marca = MarcaGarantia.objects.filter(nome__iexact=row["marca_nome"], ativo=True).first() if row["marca_nome"] else None
                    fornecedor = FornecedorGarantia.objects.filter(nome__iexact=row["fornecedor_nome"], ativo=True).first() if row["fornecedor_nome"] else None
                    categoria_config = None
                    categoria_manual = (row.get("categoria") or "").strip()
                    if categoria_manual:
                        categoria_config, _ = CategoriaProduto.obter_ou_criar_por_nome(categoria_manual)
                        categoria_manual = categoria_config.nome
                    produto = Produto.objects.create(
                        empresa=empresa,
                        nome=row["nome"],
                        sku=row["sku"] or None,
                        ean=row["ean"] or None,
                        tipo_item=row["tipo_item"],
                        categoria=categoria_manual,
                        categoria_config=categoria_config,
                        marca=marca,
                        fornecedor_config=fornecedor,
                        fornecedor_manual=row.get("fornecedor_manual", ""),
                        modelos_compativeis=row.get("modelos_compativeis", ""),
                        custo_unitario=row["custo_unitario_dec"],
                        preco_final=row["preco_final_dec"],
                        estoque_minimo=row["estoque_minimo_int"],
                        quantidade=0,
                        ponto_operacional=row.get("ponto_resolvido"),
                        ubicacao_padrao=row.get("ubicacao_resolvida"),
                        localizacao=(row.get("ubicacao_resolvida").codigo if row.get("ubicacao_resolvida") else ""),
                        ativo=True,
                    )
                    _aplicar_estoque_inicial(produto, estoque_inicial=row["estoque_inicial_int"], usuario=request.user, observacao="Entrada inicial por importacao.")
                    _normalizar_saldos_produto(produto)
                    _recalcular_total_produto(produto)
                    _registrar_historico_produto(produto, usuario=request.user, acao="IMPORTACAO", dados_antes={}, observacao="Produto criado via importacao de arquivo.")
                    importados += 1
            messages.success(request, f"Importacao concluida: {importados} produto(s).")
            return redirect("estoque:lista_produtos")

        if erros:
            messages.warning(request, f"Foram encontradas {len(erros)} linha(s) com erro. Corrija antes de importar.")
        else:
            messages.info(request, "Validacao concluida sem erros. Clique em importar para confirmar.")

    return render(
        request,
        "estoque/importar_produtos.html",
        {
            "preview": preview,
            "erros": erros[:50],
            "menu_app": "estoque",
            "menu_sub": "importar_produtos",
            "pontos_ativos": pontos_ativos,
            "ubicacoes_ativas": ubicacoes_ativas,
            "ponto_padrao_id": ponto_padrao.id if ponto_padrao else "",
            "ubicacao_padrao_id": ubicacao_padrao.id if ubicacao_padrao else "",
            "ubicacao_padrao_texto": (
                ubicacao_default_texto
                or (ubicacao_padrao.codigo if ubicacao_padrao else "")
            ),
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def tabelas_preco(request):
    require_sensitive_permission(request.user, "perm_estoque_configurar_estrutura")
    if request.method == "POST":
        acao = (request.POST.get("acao") or "").strip()
        if acao == "excluir":
            tabela_id = request.POST.get("tabela_id")
            if tabela_id and tabela_id.isdigit():
                tabela = TabelaPreco.objects.filter(id=int(tabela_id)).first()
                if tabela:
                    tabela.delete()
                    messages.success(request, "Tabela de preco excluida.")
            return redirect("estoque:tabelas_preco")
        form = TabelaPrecoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Tabela de preco salva.")
            return redirect("estoque:tabelas_preco")
    else:
        form = TabelaPrecoForm()

    return render(request, "estoque/tabelas_preco.html", {"form": form, "tabelas": TabelaPreco.objects.order_by("nome"), "menu_app": "estoque", "menu_sub": "tabelas_preco"})


@role_required(STOCK_MANAGE_ROLES)
def estrutura_produto(request, produto_id):
    require_sensitive_permission(request.user, "perm_estoque_configurar_estrutura")
    empresa = obter_empresa_ativa(request, strict=True)
    produto = get_object_or_404(filtrar_queryset_empresa(Produto.objects.all(), empresa), id=produto_id)
    if request.method == "POST":
        acao = (request.POST.get("acao") or "").strip()
        if acao == "adicionar_preco_tabela":
            preco_form = ProdutoPrecoTabelaForm(request.POST)
            if preco_form.is_valid():
                item, _ = ProdutoPrecoTabela.objects.update_or_create(produto=produto, tabela=preco_form.cleaned_data["tabela"], defaults={"preco": preco_form.cleaned_data["preco"]})
                messages.success(request, f"Preco da tabela '{item.tabela.nome}' atualizado.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)
        elif acao == "adicionar_equivalente":
            equivalente_form = ProdutoEquivalenteForm(request.POST, produto=produto)
            if equivalente_form.is_valid():
                eq = equivalente_form.save(commit=False)
                eq.produto = produto
                eq.save()
                messages.success(request, "Produto equivalente adicionado.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)
        elif acao == "adicionar_kit_item":
            kit_form = ProdutoKitItemForm(request.POST, produto=produto)
            if kit_form.is_valid():
                kit_item = kit_form.save(commit=False)
                kit_item.produto_kit = produto
                kit_item.save()
                messages.success(request, "Componente de kit adicionado.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)
        elif acao == "adicionar_fornecedor":
            fornecedor_form = ProdutoFornecedorForm(request.POST)
            if fornecedor_form.is_valid():
                rel = fornecedor_form.save(commit=False)
                rel.produto = produto
                rel.save()
                messages.success(request, "Fornecedor relacionado ao produto.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)
        elif acao == "excluir_preco_tabela":
            item_id = request.POST.get("item_id")
            if item_id and item_id.isdigit():
                ProdutoPrecoTabela.objects.filter(id=int(item_id), produto=produto).delete()
                messages.success(request, "Preco de tabela removido.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)
        elif acao == "excluir_equivalente":
            item_id = request.POST.get("item_id")
            if item_id and item_id.isdigit():
                ProdutoEquivalente.objects.filter(id=int(item_id), produto=produto).delete()
                messages.success(request, "Equivalente removido.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)
        elif acao == "excluir_kit_item":
            item_id = request.POST.get("item_id")
            if item_id and item_id.isdigit():
                ProdutoKitItem.objects.filter(id=int(item_id), produto_kit=produto).delete()
                messages.success(request, "Componente do kit removido.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)
        elif acao == "excluir_fornecedor":
            item_id = request.POST.get("item_id")
            if item_id and item_id.isdigit():
                ProdutoFornecedor.objects.filter(id=int(item_id), produto=produto).delete()
                messages.success(request, "Fornecedor removido do produto.")
                return redirect("estoque:estrutura_produto", produto_id=produto.id)

    fornecedores_contexto = _comparativo_fornecedores_produto(produto)
    return render(
        request,
        "estoque/estrutura_produto.html",
        {
            "produto": produto,
            "preco_form": ProdutoPrecoTabelaForm(),
            "equivalente_form": ProdutoEquivalenteForm(produto=produto),
            "kit_form": ProdutoKitItemForm(produto=produto),
            "fornecedor_form": ProdutoFornecedorForm(),
            "precos_tabela": ProdutoPrecoTabela.objects.select_related("tabela").filter(produto=produto),
            "equivalentes": ProdutoEquivalente.objects.select_related("equivalente").filter(produto=produto),
            "kit_componentes": ProdutoKitItem.objects.select_related("componente").filter(produto_kit=produto),
            "fornecedores_relacionados": ProdutoFornecedor.objects.select_related("fornecedor_config").filter(produto=produto),
            "fornecedores_contexto": fornecedores_contexto,
            "recompra_contexto": _recomendacao_recompra_produto(produto, fornecedores_contexto),
            "historicos": produto.historicos.select_related("usuario").all()[:20],
            "lotes_ativos": EstoqueLote.objects.select_related("ponto_operacional", "ubicacao").filter(
                produto=produto,
                quantidade_disponivel__gt=0,
            )[:20],
            "series_disponiveis": EstoqueSerie.objects.select_related(
                "ponto_operacional",
                "ubicacao",
                "entrada_item__entrada",
            ).filter(
                produto=produto,
                status=EstoqueSerie.STATUS_DISPONIVEL,
            )[:50],
            "menu_app": "estoque",
            "menu_sub": "lista_produtos",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def excluir_produto(request, produto_id):
    require_sensitive_permission(request.user, "perm_estoque_excluir_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    produto = get_object_or_404(filtrar_queryset_empresa(Produto.objects.all(), empresa), id=produto_id)
    if request.method == "POST":
        produto.delete()
        messages.success(request, "Produto excluido com sucesso!")
        return redirect("estoque:lista_produtos")
    return render(request, "estoque/confirm_delete.html", {"produto": produto, "menu_app": "estoque", "menu_sub": "lista_produtos"})


@role_required(STOCK_VIEW_ROLES)
def buscar_produto(request):
    empresa = obter_empresa_ativa(request, strict=False)
    q = (request.GET.get("q") or "").strip()
    tipo = (request.GET.get("tipo") or "").strip().lower()
    if len(q) < 2:
        return JsonResponse([], safe=False)

    produtos = filtrar_queryset_empresa(Produto.objects.filter(ativo=True, permite_os=True), empresa)
    if tipo == "servico":
        produtos = produtos.filter(tipo_item="servico")
    elif tipo in {"peca", "nao_servico"}:
        produtos = produtos.exclude(tipo_item="servico")
    elif tipo in {"produto", "consumivel"}:
        produtos = produtos.filter(tipo_item=tipo)

    produtos = produtos.filter(
        Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q) | Q(modelos_compativeis__icontains=q)
    ).order_by("nome")
    data = list(
        produtos.values(
            "id",
            "ean",
            "sku",
            "nome",
            "descricao",
            "preco",
            "tipo_item",
            "modelos_compativeis",
            "garantia_peca_dias",
        )[:50]
    )
    return JsonResponse(data, safe=False)


@role_required(STOCK_MANAGE_ROLES)
def api_gerar_ean(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    if request.method != "POST":
        return JsonResponse({"ok": False, "erro": "Metodo invalido."}, status=405)
    produto_tmp = Produto()
    codigo = produto_tmp._gerar_codigo_ean()
    return JsonResponse({"ok": True, "ean": codigo})


@role_required(ORDER_ROLES)
def api_sugerir_pecas_os(request):
    empresa = obter_empresa_ativa(request, strict=True)
    q = (request.GET.get("q") or "").strip()
    modelo = (request.GET.get("modelo") or "").strip()
    servico = (request.GET.get("servico") or "").strip()
    defeito = (request.GET.get("defeito") or "").strip()
    tipo_equipamento = (request.GET.get("tipo_equipamento") or "").strip()
    if not modelo and not servico and not q:
        return JsonResponse({"ok": True, "resultados": []})

    base_qs = filtrar_queryset_empresa(
        Produto.objects.ativos().nao_servicos().filter(permite_os=True),
        empresa,
    ).prefetch_related("servicos_compativeis")
    produtos = base_qs
    if q:
        produtos = produtos.filter(
            Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q) | Q(modelos_compativeis__icontains=q)
        )
    if modelo:
        produtos = produtos.filter(modelos_compativeis__icontains=modelo)
    if servico:
        produtos = produtos.filter(Q(servicos_compativeis__nome__icontains=servico) | Q(nome__icontains=servico)).distinct()

    candidatos = list(produtos.select_related("categoria_config", "ponto_operacional", "ubicacao_padrao").order_by("nome")[:120])
    if not candidatos:
        fallback = base_qs
        if q:
            fallback = fallback.filter(Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q))
        candidatos = list(fallback.select_related("categoria_config", "ponto_operacional", "ubicacao_padrao").order_by("nome")[:60])

    historico_por_nome = {}
    try:
        from ordens.models import ServicoPeca

        historico = ServicoPeca.objects.filter(tipo="peca")
        if empresa:
            historico = historico.filter(ordem__empresa=empresa)
        if modelo:
            historico = historico.filter(ordem__modelo_equipamento__icontains=modelo)
        if tipo_equipamento:
            historico = historico.filter(ordem__tipo_equipamento__icontains=tipo_equipamento)
        if defeito:
            historico = historico.filter(ordem__defeito__icontains=defeito)
        if servico:
            historico = historico.filter(
                Q(nome__icontains=servico) | Q(descricao__icontains=servico) | Q(ordem__relatorio_tecnico__icontains=servico)
            )

        for row in historico.values("nome").annotate(total=Count("id")):
            chave = _normalizar_texto(row.get("nome"))
            if not chave:
                continue
            atual = int(historico_por_nome.get(chave, 0))
            historico_por_nome[chave] = max(atual, int(row.get("total") or 0))
    except Exception:
        logger.exception(
            "falha_sugestao_pecas_os",
            extra={
                "empresa_id": getattr(empresa, "id", None),
                "modelo": modelo,
                "servico": servico,
                "tipo_equipamento": tipo_equipamento,
            },
        )
        historico_por_nome = {}

    modelo_norm = _normalizar_texto(modelo)
    servico_norm = _normalizar_texto(servico)
    q_norm = _normalizar_texto(q)
    ranked = []
    for produto in candidatos:
        nome_norm = _normalizar_texto(produto.nome)
        modelos_norm = _normalizar_texto(produto.modelos_compativeis)
        historico = int(historico_por_nome.get(nome_norm, 0))
        if historico == 0:
            for chave, total in historico_por_nome.items():
                if nome_norm and chave and (nome_norm in chave or chave in nome_norm):
                    historico = max(historico, int(total or 0))

        score = 0
        motivos = []
        if modelo_norm and modelos_norm and modelo_norm in modelos_norm:
            score += 55
            motivos.append("Modelo compativel")
        if servico_norm and any(servico_norm in _normalizar_texto(serv.nome) for serv in produto.servicos_compativeis.all()):
            score += 24
            motivos.append("Servico compativel")
        if q_norm and (q_norm in nome_norm or q_norm in _normalizar_texto(produto.ean) or q_norm in _normalizar_texto(produto.sku)):
            score += 14
            motivos.append("Termo da busca")
        if historico > 0:
            score += min(45, historico * 9)
            motivos.append(f"Historico ({historico}x)")
        if int(produto.quantidade or 0) > 0:
            score += 6
            motivos.append("Com estoque")
        else:
            score -= 8
        if produto.garantia_peca_dias:
            score += 2

        ranked.append(
            {
                "id": produto.id,
                "nome": produto.nome,
                "ean": produto.ean or "",
                "sku": produto.sku or "",
                "preco": float(produto.preco_final),
                "garantia_peca_dias": produto.garantia_peca_dias or 0,
                "modelos_compativeis": produto.modelos_compativeis or "",
                "quantidade": int(produto.quantidade or 0),
                "ponto_operacional_id": produto.ponto_operacional_id or None,
                "ponto_operacional_codigo": (produto.ponto_operacional.codigo if produto.ponto_operacional_id and produto.ponto_operacional else ""),
                "ubicacao_padrao_id": getattr(produto, "ubicacao_padrao_id", None),
                "ubicacao_padrao_codigo": (produto.ubicacao_padrao.codigo if getattr(produto, "ubicacao_padrao_id", None) and produto.ubicacao_padrao else ""),
                "score": int(score),
                "frequencia_historica": int(historico),
                "motivos": motivos[:3],
            }
        )

    ranked.sort(key=lambda item: (item["score"], item["frequencia_historica"], item["quantidade"], item["nome"]), reverse=True)
    return JsonResponse({"ok": True, "resultados": ranked[:30]})


__all__ = [
    "buscar_produtos",
    "lista_produtos",
    "categorias_produto",
    "api_categoria_produto_criar",
    "criar_produto",
    "editar_produto",
    "duplicar_produto",
    "importar_produtos",
    "tabelas_preco",
    "estrutura_produto",
    "excluir_produto",
    "buscar_produto",
    "api_gerar_ean",
    "api_sugerir_pecas_os",
]

