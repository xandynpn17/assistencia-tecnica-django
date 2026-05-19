from decimal import Decimal
import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from configuracoes.permissions import (
    ORDER_ROLES,
    STOCK_MANAGE_ROLES,
    STOCK_VIEW_ROLES,
    has_sensitive_permission,
    require_sensitive_permission,
    role_required,
)
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa

from ..forms import ProdutoEquivalenteForm, ProdutoForm, ProdutoKitItemForm, ProdutoPrecoTabelaForm, TabelaPrecoForm
from ..models import CategoriaProduto, PontoOperacional, Produto, ProdutoEquivalente, ProdutoKitItem, ProdutoPrecoTabela, TabelaPreco
from .helpers import (
    Empresa,
    FornecedorGarantia,
    MarcaGarantia,
    _aplicar_estoque_inicial,
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

    produtos_base = filtrar_queryset_empresa(Produto.objects.all(), empresa)
    if filtro == "servicos":
        produtos = produtos_base.ativos().servicos()
    elif filtro == "produtos":
        produtos = produtos_base.ativos().nao_servicos()
    else:
        produtos = produtos_base.ativos()

    if ponto_id:
        produtos = produtos.filter(ponto_operacional_id=ponto_id)

    if q:
        produtos = produtos.filter(
            Q(nome__icontains=q)
            | Q(sku__icontains=q)
            | Q(ean__icontains=q)
            | Q(descricao__icontains=q)
            | Q(marca__nome__icontains=q)
            | Q(categoria_config__nome__icontains=q)
            | Q(fornecedor_config__nome__icontains=q)
        ).distinct()

    resumo_qs = produtos
    resumo = {
        "total": resumo_qs.count(),
        "baixo_estoque": resumo_qs.filter(quantidade__lte=F("estoque_minimo")).count(),
        "sem_saldo": resumo_qs.filter(quantidade__lte=0).count(),
        "permite_os": resumo_qs.filter(permite_os=True).count(),
    }

    if quick == "baixo_estoque":
        produtos = produtos.filter(quantidade__lte=F("estoque_minimo"))
    elif quick == "sem_saldo":
        produtos = produtos.filter(quantidade__lte=0)
    elif quick == "permite_os":
        produtos = produtos.filter(permite_os=True)

    produtos = produtos.select_related("ponto_operacional", "categoria_config", "marca", "fornecedor_config").order_by("nome")
    produtos_page = Paginator(produtos, 30).get_page(page_number)

    context = {
        "produtos": produtos_page,
        "produtos_page": produtos_page,
        "pontos": PontoOperacional.objects.filter(ativo=True),
        "menu_app": "estoque",
        "menu_sub": "lista_produtos",
        "filtro": filtro,
        "ponto_filtro": ponto_id or "",
        "q": q,
        "quick": quick,
        "resumo": resumo,
    }
    return render(request, "estoque/lista_produtos.html", context)


@role_required(STOCK_MANAGE_ROLES)
def criar_produto(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=False)
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
                return render(
                    request,
                    "estoque/form_produto.html",
                    {
                        "form": form,
                        "menu_app": "estoque",
                        "menu_sub": "criar_produto",
                        "produto_origem": produto_origem,
                        "modo_edicao": False,
                        "rateio_context": _contexto_rateio_produto(produto_origem, empresa=empresa),
                        "empresa": empresa,
                    },
                )
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
            if "_save_and_new" in request.POST:
                messages.success(request, "Produto cadastrado. Pronto para incluir o proximo.")
                return redirect("estoque:criar_produto")
            messages.success(request, "Produto cadastrado com sucesso.")
            return redirect("estoque:lista_produtos")
    else:
        form = ProdutoForm(initial=initial)

    return render(
        request,
        "estoque/form_produto.html",
        {
            "form": form,
            "menu_app": "estoque",
            "menu_sub": "criar_produto",
            "produto_origem": produto_origem,
            "modo_edicao": False,
            "rateio_context": _contexto_rateio_produto(produto_origem, empresa=empresa),
            "empresa": empresa,
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def editar_produto(request, produto_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=False)
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
                return render(
                    request,
                    "estoque/form_produto.html",
                    {
                        "form": form,
                        "produto": produto,
                        "empresa": empresa,
                        "menu_app": "estoque",
                        "menu_sub": "lista_produtos",
                        "modo_edicao": True,
                        "rateio_context": _contexto_rateio_produto(produto, empresa=empresa),
                    },
                )
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
            messages.success(request, "Produto atualizado com sucesso!")
            if "_save_and_new" in request.POST:
                return redirect("estoque:criar_produto")
            return redirect("estoque:lista_produtos")
    else:
        form = ProdutoForm(instance=produto)

    return render(
        request,
        "estoque/form_produto.html",
        {
            "form": form,
            "produto": produto,
            "empresa": empresa,
            "menu_app": "estoque",
            "menu_sub": "lista_produtos",
            "modo_edicao": True,
            "rateio_context": _contexto_rateio_produto(produto, empresa=empresa),
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def duplicar_produto(request, produto_id):
    return redirect(f"{reverse('estoque:criar_produto')}?duplicar={produto_id}")


@role_required(STOCK_MANAGE_ROLES)
def importar_produtos(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=False)
    preview = []
    erros = []
    importados = 0
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
                        categoria_canonica = CategoriaProduto.nome_canonico(categoria_manual)
                        for categoria in CategoriaProduto.objects.filter(ativo=True).only("id", "nome"):
                            if CategoriaProduto.nome_canonico(categoria.nome) == categoria_canonica:
                                categoria_config = categoria
                                categoria_manual = categoria.nome
                                break
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
                        custo_unitario=row["custo_unitario_dec"],
                        preco_final=row["preco_final_dec"],
                        estoque_minimo=row["estoque_minimo_int"],
                        quantidade=0,
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

    return render(request, "estoque/importar_produtos.html", {"preview": preview, "erros": erros[:50], "menu_app": "estoque", "menu_sub": "importar_produtos"})


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
    empresa = obter_empresa_ativa(request, strict=False)
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

    return render(
        request,
        "estoque/estrutura_produto.html",
        {
            "produto": produto,
            "preco_form": ProdutoPrecoTabelaForm(),
            "equivalente_form": ProdutoEquivalenteForm(produto=produto),
            "kit_form": ProdutoKitItemForm(produto=produto),
            "precos_tabela": ProdutoPrecoTabela.objects.select_related("tabela").filter(produto=produto),
            "equivalentes": ProdutoEquivalente.objects.select_related("equivalente").filter(produto=produto),
            "kit_componentes": ProdutoKitItem.objects.select_related("componente").filter(produto_kit=produto),
            "historicos": produto.historicos.select_related("usuario").all()[:20],
            "menu_app": "estoque",
            "menu_sub": "lista_produtos",
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def excluir_produto(request, produto_id):
    require_sensitive_permission(request.user, "perm_estoque_excluir_produto")
    empresa = obter_empresa_ativa(request, strict=False)
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
    empresa = obter_empresa_ativa(request, strict=False)
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

    candidatos = list(produtos.select_related("categoria_config", "ponto_operacional").order_by("nome")[:120])
    if not candidatos:
        fallback = base_qs
        if q:
            fallback = fallback.filter(Q(nome__icontains=q) | Q(ean__icontains=q) | Q(sku__icontains=q))
        candidatos = list(fallback.select_related("categoria_config", "ponto_operacional").order_by("nome")[:60])

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


