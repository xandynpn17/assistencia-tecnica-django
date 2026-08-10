import csv
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.forms import formset_factory
from django.db import transaction
from django.db.models import F, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from configuracoes.permissions import STOCK_MANAGE_ROLES, STOCK_VIEW_ROLES, require_sensitive_permission, role_required
from configuracoes.models import MarcaGarantia
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa

from ..forms import EntradaMercadoriaForm, ImportarDocumentoConferenciaForm, ImportarXMLCompraForm, ItemEntradaMercadoriaForm, ResolverItemXMLForm
from ..models import CategoriaProduto, DocumentoFiscalConferencia, EntradaMercadoria, ItemImportacaoXML, LoteImportacaoCompra, ParcelaEntradaMercadoria, Produto
from ..services import receber_entrada_mercadoria
from ..services_xml import (
    confirmar_fornecedor_xml,
    importar_documentos_compra,
    inicializar_pre_cadastro_item_xml,
    rateios_despesas_xml,
    resolver_item_xml,
    resolver_itens_xml_em_massa,
    resolver_lote_importacao,
    salvar_rascunhos_produtos_xml,
)
from ..services_documentos_fiscais import confirmar_documento_conferencia, importar_documento_conferencia
from .helpers import _registrar_evento_estoque


EntradaMercadoriaItemFormSet = formset_factory(ItemEntradaMercadoriaForm, extra=5, min_num=1, validate_min=True)


def _entrada_queryset(empresa):
    return filtrar_queryset_empresa(
        EntradaMercadoria.objects.select_related("fornecedor_config", "ponto_operacional", "ubicacao", "usuario"),
        empresa,
    )


def _ajustes_pre_cadastro_request(request, *, empresa, item_ids):
    categoria_comum = (request.POST.get("categoria") or "").strip()
    marca_comum = (request.POST.get("marca") or "").strip()
    tipo_comum = (request.POST.get("tipo_item") or "produto").strip()
    margem_comum = Decimal((request.POST.get("margem_lucro") or "0").replace(",", "."))
    margem_minima_comum = Decimal((request.POST.get("margem_minima") or "0").replace(",", "."))
    ajustes = {}
    for item_id in item_ids:
        if not str(item_id).isdigit():
            continue
        pk = int(item_id)
        categoria_id = (request.POST.get(f"categoria_{pk}") or categoria_comum).strip()
        marca_id = (request.POST.get(f"marca_{pk}") or marca_comum).strip()
        categoria = CategoriaProduto.objects.filter(
            pk=categoria_id, empresa=empresa, ativo=True
        ).first() if categoria_id.isdigit() else None
        marca = MarcaGarantia.objects.filter(
            pk=marca_id, empresa=empresa, ativo=True
        ).first() if marca_id.isdigit() else None
        ajustes[pk] = {
            "nome": request.POST.get(f"nome_{pk}") or "",
            "tipo_item": (request.POST.get(f"tipo_item_{pk}") or tipo_comum).strip(),
            "categoria": categoria,
            "marca": marca,
            "ncm": request.POST.get(f"ncm_{pk}") or "",
            "margem_lucro": Decimal((request.POST.get(f"margem_lucro_{pk}") or str(margem_comum)).replace(",", ".")),
            "margem_minima": Decimal((request.POST.get(f"margem_minima_{pk}") or str(margem_minima_comum)).replace(",", ".")),
            "preco_final": Decimal((request.POST.get(f"preco_final_{pk}") or "0").replace(",", ".")),
        }
    return ajustes


def _initial_item_entrada(item):
    return {
        "produto": item.produto_id,
        "quantidade": item.quantidade,
        "custo_unitario": item.custo_unitario,
        "impostos_entrada_unitario": item.impostos_entrada_unitario,
        "frete_rateado_unitario": item.frete_rateado_unitario,
        "outras_despesas_rateadas_unitario": item.outras_despesas_rateadas_unitario,
        "desconto_unitario": item.desconto_unitario,
        "lote_codigo": item.lote_codigo,
        "lote_validade": item.lote_validade,
        "numeros_serie": item.numeros_serie,
        "observacao": item.observacao,
    }


def _salvar_itens_formset(entrada, formset):
    itens = []
    for item_form in formset:
        cleaned = getattr(item_form, "cleaned_data", None) or {}
        if not cleaned or not cleaned.get("produto"):
            continue
        item = item_form.save(commit=False)
        item.entrada = entrada
        itens.append(item)
    if not itens:
        raise ValueError("Adicione pelo menos um item valido para salvar a entrada.")
    ItemEntradaMercadoria = entrada.itens.model
    ItemEntradaMercadoria.objects.bulk_create(itens)
    return len(itens)


@role_required(STOCK_VIEW_ROLES)
def entradas_mercadoria(request):
    empresa = obter_empresa_ativa(request, strict=False)
    status = (request.GET.get("status") or "").strip()
    q = (request.GET.get("q") or "").strip()
    quick = (request.GET.get("quick") or "").strip()
    lote_id = (request.GET.get("lote") or "").strip()
    page_number = request.GET.get("page")
    entradas = _entrada_queryset(empresa).order_by("-criado_em", "-id")
    resumo_qs = entradas

    if quick == "rascunho":
        status = "rascunho"
    elif quick == "recebida":
        status = "recebida"
    elif quick == "cancelada":
        status = "cancelada"

    if status:
        entradas = entradas.filter(status=status)
    if q:
        entradas = entradas.filter(
            Q(numero__icontains=q)
            | Q(documento_numero__icontains=q)
            | Q(fornecedor_manual__icontains=q)
            | Q(fornecedor_config__nome__icontains=q)
        )
    if lote_id.isdigit():
        entradas = entradas.filter(documentos_lote__lote_id=int(lote_id)).distinct()
    entradas_page = Paginator(entradas, 20).get_page(page_number)
    context = {
        "menu_app": "estoque",
        "menu_sub": "entradas_mercadoria",
        "entradas": entradas_page,
        "entradas_page": entradas_page,
        "status_filtro": status,
        "q": q,
        "quick": quick,
        "lote_id": int(lote_id) if lote_id.isdigit() else None,
        "lotes_recentes": LoteImportacaoCompra.objects.filter(empresa=empresa).prefetch_related("documentos__entrada")[:10],
        "resumo": {
            "rascunho": resumo_qs.filter(status="rascunho").count(),
            "recebida": resumo_qs.filter(status="recebida").count(),
            "cancelada": resumo_qs.filter(status="cancelada").count(),
            "total": resumo_qs.count(),
            "resultado": entradas.count(),
        },
    }
    return render(request, "estoque/entradas_mercadoria.html", context)


@role_required(STOCK_MANAGE_ROLES)
def importar_xml_compra_view(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    form = ImportarXMLCompraForm(request.POST or None, request.FILES or None, empresa=empresa)
    if request.method == "POST" and form.is_valid():
        dados = form.cleaned_data
        try:
            resultados = importar_documentos_compra(
                empresa=empresa, arquivo=dados["arquivo_xml"], ponto_operacional=dados["ponto_operacional"],
                ubicacao=dados["ubicacao"], usuario=request.user, gerar_conta_pagar=dados["gerar_conta_pagar"],
                vencimento_conta_pagar=dados.get("vencimento_conta_pagar"),
            )
        except ValidationError as exc:
            form.add_error("arquivo_xml", exc)
        else:
            criadas = sum(1 for _, item_criado in resultados if item_criado)
            existentes = len(resultados) - criadas
            if len(resultados) > 1:
                messages.success(
                    request,
                    f"Lote processado: {criadas} novo(s) rascunho(s) e {existentes} documento(s) jÃ¡ existente(s).",
                )
                return redirect("estoque:entradas_mercadoria")
            entrada, criada = resultados[0]
            messages.success(request, "XML importado como rascunho para conferência." if criada else "Esta NF-e já havia sido importada; o rascunho existente foi aberto.")
            return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    return render(request, "estoque/importar_xml_compra.html", {"form": form, "menu_app": "estoque", "menu_sub": "entradas_mercadoria"})


@role_required(STOCK_MANAGE_ROLES)
def documentos_fiscais_conferencia(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    form = ImportarDocumentoConferenciaForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            documento, criado = importar_documento_conferencia(
                empresa=empresa, tipo=form.cleaned_data["tipo"], arquivo=form.cleaned_data["arquivo"],
                usuario=request.user, observacao=form.cleaned_data.get("observacao"),
            )
        except ValidationError as exc:
            form.add_error("arquivo", exc)
        else:
            messages.success(request, "Documento armazenado para conferencia." if criado else "Este documento ja estava armazenado; o registro existente foi preservado.")
            return redirect("estoque:documentos_fiscais_conferencia")
    documentos = DocumentoFiscalConferencia.objects.filter(empresa=empresa).order_by("-criado_em")[:100]
    return render(request, "estoque/documentos_fiscais_conferencia.html", {
        "menu_app": "estoque", "menu_sub": "entradas_mercadoria", "form": form, "documentos": documentos,
    })


@require_POST
@role_required(STOCK_MANAGE_ROLES)
def confirmar_documento_fiscal_conferencia(request, documento_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    documento = get_object_or_404(DocumentoFiscalConferencia, pk=documento_id, empresa=empresa)
    confirmar_documento_conferencia(documento=documento, usuario=request.user)
    _registrar_evento_estoque("documento_fiscal_conferencia_confirmado", usuario=request.user, documento_id=documento.pk, tipo=documento.tipo)
    messages.success(request, "Documento marcado como conferido sem movimentar estoque ou financeiro.")
    return redirect("estoque:documentos_fiscais_conferencia")


@role_required(STOCK_MANAGE_ROLES)
def nova_entrada_mercadoria(request):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    produto_inicial = None
    if request.method == "POST":
        form = EntradaMercadoriaForm(request.POST, empresa=empresa)
        formset = EntradaMercadoriaItemFormSet(request.POST, prefix="itens", form_kwargs={"empresa": empresa})
        if form.is_valid() and formset.is_valid():
            entrada = form.save(commit=False)
            entrada.empresa = empresa
            entrada.usuario = request.user
            entrada.save()
            try:
                itens_salvos = _salvar_itens_formset(entrada, formset)
            except ValueError as exc:
                entrada.delete()
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Entrada {entrada.numero} criada com {itens_salvos} item(ns).")
                return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    else:
        produto_id = (request.GET.get("produto") or "").strip()
        fornecedor_id = (request.GET.get("fornecedor") or "").strip()
        fornecedor_manual = " ".join((request.GET.get("fornecedor_manual") or "").strip().split())
        ponto_id = (request.GET.get("ponto") or "").strip()
        ubicacao_id = (request.GET.get("ubicacao") or "").strip()

        if produto_id.isdigit():
            produto_inicial = filtrar_queryset_empresa(Produto.objects.all(), empresa).filter(id=int(produto_id), ativo=True).first()

        initial_form = {}
        if fornecedor_id.isdigit():
            initial_form["fornecedor_config"] = int(fornecedor_id)
        elif fornecedor_manual:
            initial_form["fornecedor_manual"] = fornecedor_manual
        if ponto_id.isdigit():
            initial_form["ponto_operacional"] = int(ponto_id)
        elif getattr(produto_inicial, "ponto_operacional_id", None):
            initial_form["ponto_operacional"] = produto_inicial.ponto_operacional_id
        if ubicacao_id.isdigit():
            initial_form["ubicacao"] = int(ubicacao_id)
        elif getattr(produto_inicial, "ubicacao_padrao_id", None):
            initial_form["ubicacao"] = produto_inicial.ubicacao_padrao_id

        initial_itens = []
        if produto_inicial:
            initial_itens.append(
                {
                    "produto": produto_inicial.id,
                    "quantidade": 1,
                    "custo_unitario": produto_inicial.custo_unitario or produto_inicial.custo_medio or 0,
                }
            )

        form = EntradaMercadoriaForm(initial=initial_form or None, empresa=empresa)
        formset = EntradaMercadoriaItemFormSet(prefix="itens", initial=initial_itens or None, form_kwargs={"empresa": empresa})
    return render(
        request,
        "estoque/entrada_mercadoria_form.html",
        {
            "menu_app": "estoque",
            "menu_sub": "entradas_mercadoria",
            "form": form,
            "formset": formset,
            "produto_inicial": produto_inicial,
            "modo_edicao": False,
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def editar_entrada_mercadoria(request, entrada_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    entrada = get_object_or_404(_entrada_queryset(empresa).prefetch_related("itens__produto"), id=entrada_id)
    if entrada.status != "rascunho":
        messages.error(request, "Somente entradas em rascunho podem ser editadas.")
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    if entrada.importada_xml:
        messages.error(request, "Entradas importadas devem ser conferidas item a item na tela do XML.")
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)

    if request.method == "POST":
        form = EntradaMercadoriaForm(request.POST, instance=entrada, empresa=empresa)
        formset = EntradaMercadoriaItemFormSet(request.POST, prefix="itens", form_kwargs={"empresa": empresa})
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                entrada = form.save()
                entrada.itens.all().delete()
                try:
                    itens_salvos = _salvar_itens_formset(entrada, formset)
                except ValueError as exc:
                    transaction.set_rollback(True)
                    messages.error(request, str(exc))
                else:
                    messages.success(request, f"Entrada {entrada.numero} atualizada com {itens_salvos} item(ns).")
                    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    else:
        form = EntradaMercadoriaForm(instance=entrada, empresa=empresa)
        initial_itens = [_initial_item_entrada(item) for item in entrada.itens.all()]
        formset = EntradaMercadoriaItemFormSet(prefix="itens", initial=initial_itens, form_kwargs={"empresa": empresa})

    return render(
        request,
        "estoque/entrada_mercadoria_form.html",
        {
            "menu_app": "estoque",
            "menu_sub": "entradas_mercadoria",
            "form": form,
            "formset": formset,
            "produto_inicial": None,
            "entrada": entrada,
            "modo_edicao": True,
        },
    )


@role_required(STOCK_VIEW_ROLES)
def detalhe_entrada_mercadoria(request, entrada_id):
    empresa = obter_empresa_ativa(request, strict=False)
    entrada = get_object_or_404(_entrada_queryset(empresa).prefetch_related("itens__produto"), id=entrada_id)
    itens_xml = list(entrada.itens_xml.select_related(
        "produto", "entrada__empresa", "categoria_proposta", "marca_proposta"
    ))
    from estoque.services_xml import rateios_despesas_xml

    rateios = rateios_despesas_xml(entrada, itens_xml)
    for item in itens_xml:
        inicializar_pre_cadastro_item_xml(item)
        item.custo_anterior_preview = Decimal(str(getattr(item.produto, "custo_medio", 0) or getattr(item.produto, "custo_unitario", 0) or 0))
        rateio_item = rateios[item.pk]["frete"] + rateios[item.pk]["outras"]
        item.custo_entrada_preview = item.valor_unitario + ((item.impostos_custo_total + rateio_item - item.desconto_total) / item.quantidade if item.quantidade else Decimal("0.00"))
        qtd_atual = Decimal(int(getattr(item.produto, "quantidade", 0) or 0))
        item.custo_medio_preview = ((item.custo_anterior_preview * qtd_atual) + (item.custo_entrada_preview * item.quantidade)) / (qtd_atual + item.quantidade) if qtd_atual + item.quantidade else item.custo_entrada_preview
    formularios_xml = [(item, ResolverItemXMLForm(empresa=empresa, item=item)) for item in itens_xml]
    return render(
        request,
        "estoque/entrada_mercadoria_detalhe.html",
        {
            "menu_app": "estoque",
            "menu_sub": "entradas_mercadoria",
            "entrada": entrada,
            "formularios_xml": formularios_xml,
            "itens_xml_pendentes": sum(1 for item in itens_xml if not item.resolvido),
            "fornecedor_xml_pendente": entrada.importada_xml and not entrada.xml_resumo.get("fornecedor_confirmado"),
            "parcelas_financeiras": entrada.parcelas_financeiras.select_related("conta_pagar").all(),
            "categorias_massa": CategoriaProduto.objects.filter(empresa=empresa, ativo=True).order_by("ordem", "nome"),
            "marcas_massa": MarcaGarantia.objects.filter(empresa=empresa, ativo=True).order_by("nome"),
        },
    )


@role_required(STOCK_MANAGE_ROLES)
def detalhe_lote_importacao(request, lote_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    lote = get_object_or_404(
        LoteImportacaoCompra.objects.filter(empresa=empresa).prefetch_related("documentos__entrada"),
        pk=lote_id,
    )
    itens_sem_pre_cadastro = ItemImportacaoXML.objects.filter(
        entrada__documentos_lote__lote=lote, status_pre_cadastro="nao_iniciado"
    ).select_related("entrada__empresa", "produto")
    for item_sem_pre_cadastro in itens_sem_pre_cadastro:
        inicializar_pre_cadastro_item_xml(item_sem_pre_cadastro)
    itens_qs = ItemImportacaoXML.objects.filter(
        entrada__documentos_lote__lote=lote
    ).select_related(
        "entrada", "entrada__empresa", "produto", "entrada__fornecedor_config",
        "categoria_proposta", "marca_proposta",
    ).order_by("entrada__documento_numero", "numero_item")
    situacao = (request.GET.get("situacao") or "pendentes").strip()
    busca = " ".join((request.GET.get("q") or "").strip().split())
    if situacao == "pendentes":
        itens_qs = itens_qs.filter(Q(produto__isnull=True) | Q(revisao_tributaria_confirmada=False))
    elif situacao == "resolvidos":
        itens_qs = itens_qs.filter(produto__isnull=False, revisao_tributaria_confirmada=True)
    elif situacao in {"exato", "provavel", "novo", "conflito"}:
        itens_qs = itens_qs.filter(nivel_correspondencia=situacao)
    elif situacao == "sem_classificacao":
        itens_qs = itens_qs.filter(Q(ncm="") | Q(ncm__isnull=True))
    elif situacao == "abaixo_minimo":
        itens_qs = itens_qs.filter(produto__isnull=False, produto__preco_final__lt=F("produto__preco_minimo"))
    elif situacao in {"rascunho", "pronto"}:
        itens_qs = itens_qs.filter(status_pre_cadastro=situacao)
    elif situacao == "aguardando_categoria":
        itens_qs = itens_qs.filter(produto__isnull=True, categoria_proposta__isnull=True)
    elif situacao == "aguardando_marca":
        itens_qs = itens_qs.filter(produto__isnull=True, marca_proposta__isnull=True)
    if busca:
        itens_qs = itens_qs.filter(
            Q(descricao__icontains=busca) | Q(codigo_fornecedor__icontains=busca)
            | Q(gtin__icontains=busca) | Q(ncm__icontains=busca)
            | Q(produto__nome__icontains=busca) | Q(entrada__documento_numero__icontains=busca)
        )
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="lote_{str(lote.codigo)[:8]}.csv"'
        response.write("\ufeff")
        escritor = csv.writer(response, delimiter=";")
        escritor.writerow(["nota", "item", "situacao", "descricao", "gtin", "ncm", "cfop", "quantidade", "valor_unitario", "produto", "revisado"])
        for item in itens_qs:
            escritor.writerow([item.entrada.documento_numero, item.numero_item, item.nivel_correspondencia, item.descricao, item.gtin, item.ncm, item.cfop, item.quantidade, item.valor_unitario, item.produto.nome if item.produto_id else "", "sim" if item.resolvido else "nao"])
        return response
    itens = list(itens_qs[:500])
    entradas_rateio = {}
    for item in itens:
        inicializar_pre_cadastro_item_xml(item)
        if item.entrada_id not in entradas_rateio:
            todos = list(item.entrada.itens_xml.all())
            entradas_rateio[item.entrada_id] = rateios_despesas_xml(item.entrada, todos)
        rateio = entradas_rateio[item.entrada_id].get(item.pk, {"frete": Decimal("0"), "outras": Decimal("0")})
        adicionais = item.impostos_custo_total + rateio["frete"] + rateio["outras"] - item.desconto_total
        item.custo_projetado_lote = item.valor_unitario + (adicionais / item.quantidade if item.quantidade else Decimal("0"))
        if item.produto_id:
            comparacoes = [
                ("nome", "Nome", item.produto.nome, item.descricao[:100]),
                ("ncm", "NCM", item.produto.ncm, item.ncm),
                ("cest", "CEST", item.produto.cest, item.cest),
                ("cfop_padrao", "CFOP", item.produto.cfop_padrao, item.cfop),
                ("unidade_comercial", "Unidade", item.produto.unidade_comercial, item.unidade),
            ]
            item.comparacoes_lote = [
                {"campo": campo, "rotulo": rotulo, "atual": atual or "-", "importado": importado or "-", "diferente": bool(importado and str(atual or "") != str(importado))}
                for campo, rotulo, atual, importado in comparacoes
            ]
        else:
            item.comparacoes_lote = []

    if request.method == "POST":
        item_ids = request.POST.getlist("item_ids")
        categoria_id = (request.POST.get("categoria") or "").strip()
        marca_id = (request.POST.get("marca") or "").strip()
        categoria = CategoriaProduto.objects.filter(pk=categoria_id, empresa=empresa, ativo=True).first() if categoria_id.isdigit() else None
        marca = MarcaGarantia.objects.filter(pk=marca_id, empresa=empresa, ativo=True).first() if marca_id.isdigit() else None
        ajustes, atualizacoes, produtos_escolhidos = {}, {}, {}
        try:
            ajustes = _ajustes_pre_cadastro_request(request, empresa=empresa, item_ids=item_ids)
            if request.POST.get("acao") == "salvar_rascunho":
                itens_por_entrada = {}
                for item in ItemImportacaoXML.objects.filter(
                    pk__in=[int(valor) for valor in item_ids if str(valor).isdigit()],
                    entrada__documentos_lote__lote=lote,
                ).select_related("entrada"):
                    itens_por_entrada.setdefault(item.entrada, []).append(item.pk)
                total_salvos = total_prontos = 0
                with transaction.atomic():
                    for entrada_item, ids_entrada in itens_por_entrada.items():
                        resultado_rascunho = salvar_rascunhos_produtos_xml(
                            entrada=entrada_item, usuario=request.user, item_ids=ids_entrada, ajustes=ajustes
                        )
                        total_salvos += resultado_rascunho["salvos"]
                        total_prontos += resultado_rascunho["prontos"]
                messages.success(
                    request,
                    f"Pré-cadastro salvo: {total_salvos} rascunho(s), {total_prontos} pronto(s) para aprovação.",
                )
                return redirect("estoque:detalhe_lote_importacao", lote_id=lote.pk)
            if request.POST.get("confirmar_revisao") != "1":
                raise ValidationError("Confirme a revisão do lote antes de aprovar produtos.")
            for item_id in item_ids:
                if not str(item_id).isdigit():
                    continue
                pk = int(item_id)
                campos = request.POST.getlist(f"campos_{pk}")
                atualizacoes[pk] = {
                    "campos": campos,
                    "valores": {
                        "preco_final": Decimal((request.POST.get(f"preco_existente_{pk}") or "0").replace(",", ".")),
                        "margem_lucro": Decimal((request.POST.get(f"margem_existente_{pk}") or "0").replace(",", ".")),
                    },
                }
                produto_id = (request.POST.get(f"produto_escolhido_{pk}") or "").strip()
                if produto_id.isdigit():
                    produtos_escolhidos[pk] = int(produto_id)
            resultado = resolver_lote_importacao(
                lote=lote, usuario=request.user, item_ids=item_ids,
                tipo_item=(request.POST.get("tipo_item") or "produto").strip(),
                categoria=categoria, marca=marca,
                margem_lucro=Decimal((request.POST.get("margem_lucro") or "0").replace(",", ".")),
                margem_minima=Decimal((request.POST.get("margem_minima") or "0").replace(",", ".")),
                ajustes=ajustes, atualizacoes=atualizacoes, produtos_escolhidos=produtos_escolhidos,
            )
        except (ValidationError, InvalidOperation) as exc:
            messages.error(request, str(exc))
        else:
            _registrar_evento_estoque("lote_xml_revisao_coletiva", usuario=request.user, lote_id=lote.pk, **resultado)
            messages.success(request, f"Lote revisado: {resultado['confirmados']} confirmado(s), {resultado['criados']} criado(s) e {resultado['atualizados']} atualizado(s).")
            return redirect("estoque:detalhe_lote_importacao", lote_id=lote.pk)

    todos_lote = ItemImportacaoXML.objects.filter(entrada__documentos_lote__lote=lote)
    resumo = {
        "total": todos_lote.count(),
        "pendentes": todos_lote.filter(Q(produto__isnull=True) | Q(revisao_tributaria_confirmada=False)).count(),
        "resolvidos": todos_lote.filter(produto__isnull=False, revisao_tributaria_confirmada=True).count(),
        "novos": todos_lote.filter(nivel_correspondencia="novo").count(),
        "provaveis": todos_lote.filter(nivel_correspondencia="provavel").count(),
        "conflitos": todos_lote.filter(nivel_correspondencia="conflito").count(),
        "rascunhos": todos_lote.filter(status_pre_cadastro="rascunho").count(),
        "prontos": todos_lote.filter(status_pre_cadastro="pronto").count(),
    }
    return render(request, "estoque/lote_importacao_detalhe.html", {
        "menu_app": "estoque", "menu_sub": "entradas_mercadoria", "lote": lote,
        "itens": itens, "resumo": resumo, "situacao": situacao, "q": busca,
        "categorias": CategoriaProduto.objects.filter(empresa=empresa, ativo=True).order_by("ordem", "nome"),
        "marcas": MarcaGarantia.objects.filter(empresa=empresa, ativo=True).order_by("nome"),
        "produtos": Produto.objects.filter(empresa=empresa, ativo=True, is_servico=False).order_by("nome")[:1000],
    })


@require_POST
@role_required(STOCK_MANAGE_ROLES)
def resolver_itens_xml_massa_view(request, entrada_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    entrada = get_object_or_404(_entrada_queryset(empresa), pk=entrada_id, status="rascunho", importada_xml=True)
    item_ids = request.POST.getlist("item_ids")
    categoria_id = (request.POST.get("categoria") or "").strip()
    marca_id = (request.POST.get("marca") or "").strip()
    categoria = CategoriaProduto.objects.filter(pk=int(categoria_id), empresa=empresa, ativo=True).first() if categoria_id.isdigit() else None
    marca = MarcaGarantia.objects.filter(pk=int(marca_id), empresa=empresa, ativo=True).first() if marca_id.isdigit() else None
    try:
        ajustes = _ajustes_pre_cadastro_request(request, empresa=empresa, item_ids=item_ids)
        if request.POST.get("acao") == "salvar_rascunho":
            resultado = salvar_rascunhos_produtos_xml(
                entrada=entrada, usuario=request.user, item_ids=item_ids, ajustes=ajustes
            )
            messages.success(
                request,
                f"Pré-cadastro salvo: {resultado['salvos']} rascunho(s), {resultado['prontos']} pronto(s) para aprovação.",
            )
            return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
        if request.POST.get("confirmar_revisao") != "1":
            raise ValidationError("Confirme que os produtos, custos e dados fiscais foram revisados antes de aprovar.")
        resultado = resolver_itens_xml_em_massa(
            entrada=entrada,
            usuario=request.user,
            item_ids=item_ids,
            tipo_item=(request.POST.get("tipo_item") or "produto").strip(),
            categoria=categoria,
            marca=marca,
            margem_lucro=Decimal((request.POST.get("margem_lucro") or "0").replace(",", ".")),
            margem_minima=Decimal((request.POST.get("margem_minima") or "0").replace(",", ".")),
            ajustes=ajustes,
        )
    except (ValidationError, InvalidOperation) as exc:
        messages.error(request, str(exc))
    else:
        _registrar_evento_estoque(
            "xml_revisao_em_massa",
            usuario=request.user,
            entrada_id=entrada.pk,
            entrada_numero=entrada.numero,
            itens_confirmados=resultado["confirmados"],
            produtos_criados=resultado["criados"],
            produto_ids=resultado["produtos"],
        )
        messages.success(
            request,
            f"Revisão em massa concluída: {resultado['confirmados']} item(ns) confirmado(s) e {resultado['criados']} produto(s) criado(s).",
        )
    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)


@require_POST
@role_required(STOCK_MANAGE_ROLES)
def revisar_parcelas_entrada(request, entrada_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    entrada = get_object_or_404(_entrada_queryset(empresa), pk=entrada_id, status="rascunho")
    parcelas = list(ParcelaEntradaMercadoria.objects.filter(entrada=entrada).order_by("id"))
    if not parcelas:
        messages.error(request, "Esta entrada não possui parcelas para revisão.")
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    alteracoes = []
    try:
        for parcela in parcelas:
            vencimento = date.fromisoformat(request.POST.get(f"parcela_{parcela.id}_vencimento", ""))
            valor = Decimal(request.POST.get(f"parcela_{parcela.id}_valor", "")).quantize(Decimal("0.01"))
            if valor <= 0:
                raise ValueError("O valor de cada parcela deve ser positivo.")
            alteracoes.append((parcela, vencimento, valor))
    except (ValueError, InvalidOperation):
        messages.error(request, "Revise os vencimentos e informe valores positivos válidos.")
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)

    total_financeiro = Decimal(str(entrada.xml_resumo.get("valor_nfe") or entrada.total_geral)).quantize(Decimal("0.01"))
    soma = sum((valor for _, _, valor in alteracoes), Decimal("0.00"))
    if soma != total_financeiro:
        messages.error(request, f"A soma das parcelas deve ser R$ {total_financeiro:.2f}; valor informado: R$ {soma:.2f}.")
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    with transaction.atomic():
        bloqueadas = {
            parcela.pk: parcela for parcela in ParcelaEntradaMercadoria.objects.select_for_update().filter(
                entrada_id=entrada.pk, entrada__status="rascunho"
            )
        }
        if set(bloqueadas) != {parcela.pk for parcela, _, _ in alteracoes}:
            messages.error(request, "As parcelas foram alteradas por outro usuário. Recarregue a página.")
            return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
        for parcela, vencimento, valor in alteracoes:
            bloqueada = bloqueadas[parcela.pk]
            bloqueada.vencimento = vencimento
            bloqueada.valor = valor
            bloqueada.revisada = True
            bloqueada.save(update_fields=["vencimento", "valor", "revisada"])
        primeira = min(alteracoes, key=lambda item: item[1])[0]
        entrada.vencimento_conta_pagar = next(vencimento for parcela, vencimento, _ in alteracoes if parcela.pk == primeira.pk)
        entrada.save(update_fields=["vencimento_conta_pagar"])
    messages.success(request, "Condições e vencimentos da compra revisados.")
    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)


@require_POST
@role_required(STOCK_MANAGE_ROLES)
def confirmar_fornecedor_xml_view(request, entrada_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    entrada = get_object_or_404(_entrada_queryset(empresa), pk=entrada_id, importada_xml=True)
    try:
        confirmar_fornecedor_xml(entrada=entrada, usuario=request.user)
        messages.success(request, "Fornecedor do XML confirmado para esta entrada.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)


@require_POST
@role_required(STOCK_MANAGE_ROLES)
def resolver_item_xml_view(request, item_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    item = get_object_or_404(ItemImportacaoXML.objects.select_related("entrada", "produto"), pk=item_id, entrada__empresa=empresa)
    inicializar_pre_cadastro_item_xml(item)
    form = ResolverItemXMLForm(request.POST, empresa=empresa, item=item)
    if form.is_valid():
        try:
            resolver_item_xml(
                item=item, usuario=request.user, produto=form.cleaned_data.get("produto"), criar_produto=form.cleaned_data["criar_produto"],
                impostos_custo_total=form.cleaned_data["impostos_custo_total"], tributos_recuperaveis_total=form.cleaned_data["tributos_recuperaveis_total"],
                dados_produto={
                    "nome": form.cleaned_data.get("nome_produto"),
                    "tipo_item": form.cleaned_data.get("tipo_item"),
                    "categoria": form.cleaned_data.get("categoria"),
                    "marca": form.cleaned_data.get("marca"),
                    "ncm": form.cleaned_data.get("ncm"),
                    "margem_lucro": form.cleaned_data.get("margem_lucro"),
                    "margem_minima": form.cleaned_data.get("margem_minima"),
                    "preco_final": form.cleaned_data.get("preco_final"),
                },
            )
            messages.success(request, f"Item {item.numero_item} conferido.")
        except ValidationError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Corrija a associação e a revisão tributária do item.")
    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=item.entrada_id)


@require_POST
@role_required(STOCK_MANAGE_ROLES)
def receber_entrada_mercadoria_view(request, entrada_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=False)
    entrada = get_object_or_404(_entrada_queryset(empresa), id=entrada_id)
    try:
        receber_entrada_mercadoria(entrada, usuario=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
    messages.success(request, f"Entrada {entrada.numero} recebida no estoque com sucesso.")
    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)


@require_POST
@role_required(STOCK_MANAGE_ROLES)
def cancelar_entrada_mercadoria(request, entrada_id):
    require_sensitive_permission(request.user, "perm_estoque_cadastro_produto")
    empresa = obter_empresa_ativa(request, strict=True)
    entrada = get_object_or_404(_entrada_queryset(empresa), id=entrada_id)
    if entrada.status != "rascunho":
        messages.error(request, "Somente entradas em rascunho podem ser canceladas.")
        return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)

    motivo = " ".join((request.POST.get("motivo") or "Cancelada antes do recebimento").strip().split())
    entrada.status = "cancelada"
    entrada.usuario = request.user
    entrada.observacao = " | ".join(filter(None, [entrada.observacao, f"Cancelamento: {motivo}"]))[:220]
    entrada.save(update_fields=["status", "usuario", "observacao"])
    if entrada.importada_xml:
        from estoque.services_xml import atualizar_status_lotes_entrada

        atualizar_status_lotes_entrada(entrada)
    _registrar_evento_estoque(
        "entrada_mercadoria_cancelada",
        usuario=request.user,
        entrada_id=entrada.id,
        entrada_numero=entrada.numero,
        motivo=motivo,
    )
    messages.success(request, f"Entrada {entrada.numero} cancelada sem movimentar o estoque.")
    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.id)
