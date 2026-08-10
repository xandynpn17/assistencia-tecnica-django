from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from configuracoes.forms import FornecedorGarantiaForm, MarcaGarantiaForm, ParceiroExpedicaoForm, RegraGarantiaMarcaForm
from configuracoes.models import FornecedorGarantia, MarcaGarantia, ParceiroExpedicao, RegraGarantiaMarca
from configuracoes.services.auditoria import registrar_evento_configuracao
from configuracoes.services.integracoes import emitir_evento_interno
from configuracoes.services.tenant_guard import filtrar_catalogo_empresa, obter_empresa_ativa


def _audit_catalogo(request, acao: str, alvo: str, antes=None, depois=None):
    registrar_evento_configuracao(
        usuario=request.user,
        acao=acao,
        origem="ui",
        alvo=alvo,
        antes=antes,
        depois=depois,
    )
    emitir_evento_interno("configuracoes.alterada", {"escopo": "catalogo", "acao": acao, "alvo": alvo})


def marcas_fornecedores_impl(request):
    empresa = obter_empresa_ativa(request, strict=False)
    busca_fornecedor = (request.GET.get("qf") or "").strip()
    busca_marca = (request.GET.get("qm") or "").strip()
    busca_parceiro = (request.GET.get("qp") or "").strip()
    edit_fornecedor_id = (request.GET.get("edit_fornecedor") or "").strip()
    edit_marca_id = (request.GET.get("edit_marca") or "").strip()
    edit_parceiro_id = (request.GET.get("edit_parceiro") or "").strip()
    edit_regra_id = (request.GET.get("edit_regra") or "").strip()

    fornecedor_form = FornecedorGarantiaForm(empresa=empresa)
    marca_form = MarcaGarantiaForm(empresa=empresa)
    parceiro_form = ParceiroExpedicaoForm(empresa=empresa)
    regra_form = RegraGarantiaMarcaForm(empresa=empresa)
    marca_em_edicao = None
    regra_em_edicao = None
    aba_ativa = (request.GET.get("aba") or "").strip()

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "fornecedor":
            aba_ativa = "fornecedor-cad"
            fornecedor_form = FornecedorGarantiaForm(request.POST, request.FILES, empresa=empresa)
            if fornecedor_form.is_valid():
                fornecedor = fornecedor_form.save()
                _audit_catalogo(request, "fornecedor_criado", f"fornecedor:{fornecedor.id}", depois={"nome": fornecedor.nome})
                messages.success(request, "Fornecedor salvo com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "fornecedor_edit":
            aba_ativa = "fornecedor-cad"
            fornecedor = get_object_or_404(filtrar_catalogo_empresa(FornecedorGarantia.objects.all(), empresa), id=request.POST.get("fornecedor_id"))
            fornecedor_form = FornecedorGarantiaForm(request.POST, request.FILES, instance=fornecedor, empresa=empresa)
            if fornecedor_form.is_valid():
                fornecedor = fornecedor_form.save()
                _audit_catalogo(request, "fornecedor_editado", f"fornecedor:{fornecedor.id}", depois={"nome": fornecedor.nome})
                messages.success(request, "Fornecedor atualizado com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "fornecedor_delete":
            aba_ativa = "fornecedor-cons"
            fornecedor = get_object_or_404(filtrar_catalogo_empresa(FornecedorGarantia.objects.all(), empresa), id=request.POST.get("fornecedor_id"))
            try:
                _audit_catalogo(request, "fornecedor_excluido", f"fornecedor:{fornecedor.id}", antes={"nome": fornecedor.nome})
                fornecedor.delete()
                messages.success(request, "Fornecedor excluido com sucesso.")
            except ProtectedError:
                messages.error(request, "Fornecedor vinculado a marcas. Remova os vinculos antes de excluir.")
            return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "marca":
            aba_ativa = "marca-cad"
            marca_form = MarcaGarantiaForm(request.POST, empresa=empresa)
            if marca_form.is_valid():
                marca = marca_form.save()
                _audit_catalogo(request, "marca_criada", f"marca:{marca.id}", depois={"nome": marca.nome})
                messages.success(request, "Marca de garantia salva com sucesso.")
                return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
        elif form_type == "marca_edit":
            aba_ativa = "marca-cad"
            marca = get_object_or_404(filtrar_catalogo_empresa(MarcaGarantia.objects.all(), empresa), id=request.POST.get("marca_id"))
            marca_form = MarcaGarantiaForm(request.POST, instance=marca, empresa=empresa)
            if marca_form.is_valid():
                marca = marca_form.save()
                _audit_catalogo(request, "marca_editada", f"marca:{marca.id}", depois={"nome": marca.nome})
                messages.success(request, "Marca atualizada com sucesso.")
                return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
        elif form_type == "marca_delete":
            aba_ativa = "marca-cons"
            marca = get_object_or_404(filtrar_catalogo_empresa(MarcaGarantia.objects.all(), empresa), id=request.POST.get("marca_id"))
            _audit_catalogo(request, "marca_excluida", f"marca:{marca.id}", antes={"nome": marca.nome})
            marca.delete()
            messages.success(request, "Marca excluida com sucesso.")
            return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "parceiro":
            aba_ativa = "parceiro-cad"
            parceiro_form = ParceiroExpedicaoForm(request.POST, empresa=empresa)
            if parceiro_form.is_valid():
                parceiro = parceiro_form.save()
                _audit_catalogo(request, "parceiro_criado", f"parceiro:{parceiro.id}", depois={"nome": parceiro.nome})
                messages.success(request, "Parceiro salvo com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "parceiro_edit":
            aba_ativa = "parceiro-cad"
            parceiro = get_object_or_404(
                filtrar_catalogo_empresa(ParceiroExpedicao.objects.all(), empresa),
                id=request.POST.get("parceiro_id"),
            )
            parceiro_form = ParceiroExpedicaoForm(request.POST, instance=parceiro, empresa=empresa)
            if parceiro_form.is_valid():
                parceiro = parceiro_form.save()
                _audit_catalogo(request, "parceiro_editado", f"parceiro:{parceiro.id}", depois={"nome": parceiro.nome})
                messages.success(request, "Parceiro atualizado com sucesso.")
                return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "parceiro_delete":
            aba_ativa = "parceiro-cons"
            parceiro = get_object_or_404(
                filtrar_catalogo_empresa(ParceiroExpedicao.objects.all(), empresa),
                id=request.POST.get("parceiro_id"),
            )
            _audit_catalogo(request, "parceiro_excluido", f"parceiro:{parceiro.id}", antes={"nome": parceiro.nome})
            parceiro.delete()
            messages.success(request, "Parceiro excluido com sucesso.")
            return redirect("configuracoes:marcas_fornecedores")
        elif form_type == "regra_add":
            aba_ativa = "marca-cad"
            marca_id_post = (request.POST.get("marca_id") or "").strip()
            marca = get_object_or_404(filtrar_catalogo_empresa(MarcaGarantia.objects.all(), empresa), id=marca_id_post)
            marca_form = MarcaGarantiaForm(instance=marca, empresa=empresa)
            marca_em_edicao = marca
            regra_payload = request.POST.copy()
            regra_payload["marca"] = str(marca.id)
            regra_form = RegraGarantiaMarcaForm(regra_payload, empresa=empresa)
            if regra_form.is_valid():
                regra = regra_form.save(commit=False)
                regra.marca = marca
                regra.save()
                _audit_catalogo(request, "regra_garantia_criada", f"regra:{regra.id}", depois={"marca": marca.id})
                messages.success(request, "Regra de garantia salva com sucesso.")
                return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
        elif form_type == "regra_edit":
            aba_ativa = "marca-cad"
            marca_id_post = (request.POST.get("marca_id") or "").strip()
            regra_id_post = (request.POST.get("regra_id") or "").strip()
            marca = get_object_or_404(filtrar_catalogo_empresa(MarcaGarantia.objects.all(), empresa), id=marca_id_post)
            regra_obj = get_object_or_404(RegraGarantiaMarca, id=regra_id_post, marca=marca)
            marca_form = MarcaGarantiaForm(instance=marca, empresa=empresa)
            marca_em_edicao = marca
            regra_em_edicao = regra_obj
            regra_payload = request.POST.copy()
            regra_payload["marca"] = str(marca.id)
            regra_form = RegraGarantiaMarcaForm(regra_payload, instance=regra_obj, empresa=empresa)
            if regra_form.is_valid():
                regra = regra_form.save(commit=False)
                regra.marca = marca
                regra.save()
                _audit_catalogo(request, "regra_garantia_editada", f"regra:{regra.id}", depois={"marca": marca.id})
                messages.success(request, "Item de mao de obra atualizado com sucesso.")
                return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
        elif form_type == "regra_delete":
            aba_ativa = "marca-cad"
            marca_id_post = (request.POST.get("marca_id") or "").strip()
            regra_id_post = (request.POST.get("regra_id") or "").strip()
            marca = get_object_or_404(filtrar_catalogo_empresa(MarcaGarantia.objects.all(), empresa), id=marca_id_post)
            regra_obj = get_object_or_404(RegraGarantiaMarca, id=regra_id_post, marca=marca)
            _audit_catalogo(request, "regra_garantia_excluida", f"regra:{regra_obj.id}", antes={"marca": marca.id})
            regra_obj.delete()
            messages.success(request, "Item de mao de obra removido com sucesso.")
            return redirect(f"{reverse('configuracoes:marcas_fornecedores')}?edit_marca={marca.id}#tab-marca-cad")
    else:
        if edit_fornecedor_id.isdigit():
            aba_ativa = aba_ativa or "fornecedor-cad"
            fornecedor_obj = filtrar_catalogo_empresa(FornecedorGarantia.objects.all(), empresa).filter(id=int(edit_fornecedor_id)).first()
            fornecedor_form = FornecedorGarantiaForm(instance=fornecedor_obj, empresa=empresa)

        if edit_marca_id.isdigit():
            aba_ativa = aba_ativa or "marca-cad"
            marca_em_edicao = filtrar_catalogo_empresa(MarcaGarantia.objects.all(), empresa).filter(id=int(edit_marca_id)).first()
            if marca_em_edicao:
                marca_form = MarcaGarantiaForm(instance=marca_em_edicao, empresa=empresa)
                if edit_regra_id.isdigit():
                    regra_em_edicao = RegraGarantiaMarca.objects.filter(
                        id=int(edit_regra_id),
                        marca=marca_em_edicao,
                    ).first()
                if regra_em_edicao:
                    regra_form = RegraGarantiaMarcaForm(instance=regra_em_edicao, empresa=empresa)
                else:
                    regra_form = RegraGarantiaMarcaForm(initial={"marca": marca_em_edicao.id}, empresa=empresa)
        if edit_parceiro_id.isdigit():
            aba_ativa = aba_ativa or "parceiro-cad"
            parceiro_obj = filtrar_catalogo_empresa(ParceiroExpedicao.objects.all(), empresa).filter(
                id=int(edit_parceiro_id)
            ).first()
            if parceiro_obj:
                parceiro_form = ParceiroExpedicaoForm(instance=parceiro_obj, empresa=empresa)

    if not aba_ativa:
        if busca_fornecedor:
            aba_ativa = "fornecedor-cons"
        elif busca_marca:
            aba_ativa = "marca-cons"
        elif busca_parceiro:
            aba_ativa = "parceiro-cons"
        else:
            aba_ativa = "fornecedor-cad"

    fornecedores_empresa_qs = filtrar_catalogo_empresa(FornecedorGarantia.objects.all(), empresa)
    marcas_empresa_qs = filtrar_catalogo_empresa(
        MarcaGarantia.objects.select_related("fornecedor").prefetch_related("regras_garantia"),
        empresa,
    )
    fornecedores_qs = (
        fornecedores_empresa_qs.filter(nome__icontains=busca_fornecedor)
        if busca_fornecedor
        else fornecedores_empresa_qs
    )
    marcas_qs = (
        marcas_empresa_qs.filter(nome__icontains=busca_marca)
        if busca_marca
        else marcas_empresa_qs
    )
    parceiros_empresa_qs = filtrar_catalogo_empresa(ParceiroExpedicao.objects.all(), empresa)
    parceiros_qs = (
        parceiros_empresa_qs.filter(nome__icontains=busca_parceiro)
        if busca_parceiro
        else parceiros_empresa_qs
    )
    fornecedores_page = Paginator(fornecedores_qs.order_by("nome"), 10).get_page(request.GET.get("page_f"))
    marcas_page = Paginator(marcas_qs.order_by("nome"), 10).get_page(request.GET.get("page_m"))
    parceiros_page = Paginator(parceiros_qs.order_by("nome"), 10).get_page(request.GET.get("page_p"))
    regras_marca = RegraGarantiaMarca.objects.none()
    if marca_em_edicao:
        regras_marca = RegraGarantiaMarca.objects.filter(marca=marca_em_edicao).order_by("-inicio_vigencia", "tipo_produto")
    resumo_catalogo = {
        "fornecedores_total": fornecedores_empresa_qs.count(),
        "fornecedores_ativos": fornecedores_empresa_qs.filter(ativo=True).count(),
        "marcas_total": marcas_empresa_qs.count(),
        "marcas_com_fornecedor": marcas_empresa_qs.filter(fornecedor__isnull=False).count(),
        "marcas_sem_fornecedor": marcas_empresa_qs.filter(fornecedor__isnull=True).count(),
        "marcas_com_regras": marcas_empresa_qs.annotate(
            regras_ativas=Count("regras_garantia", filter=Q(regras_garantia__ativo=True))
        ).filter(regras_ativas__gt=0).count(),
        "parceiros_total": parceiros_empresa_qs.count(),
        "parceiros_ativos": parceiros_empresa_qs.filter(ativo=True).count(),
        "regras_total": RegraGarantiaMarca.objects.filter(marca__empresa=empresa).count(),
        "regras_ativas": RegraGarantiaMarca.objects.filter(ativo=True, marca__empresa=empresa).count(),
    }

    return render(
        request,
        "configuracoes/marcas_fornecedores.html",
        {
            "fornecedor_form": fornecedor_form,
            "marca_form": marca_form,
            "parceiro_form": parceiro_form,
            "regra_form": regra_form,
            "fornecedores": fornecedores_page,
            "marcas": marcas_page,
            "parceiros": parceiros_page,
            "regras": RegraGarantiaMarca.objects.select_related("marca", "marca__fornecedor").filter(marca__empresa=empresa),
            "regras_marca": regras_marca,
            "busca_fornecedor": busca_fornecedor,
            "busca_marca": busca_marca,
            "busca_parceiro": busca_parceiro,
            "edit_fornecedor_id": int(edit_fornecedor_id) if edit_fornecedor_id.isdigit() else None,
            "edit_marca_id": int(edit_marca_id) if edit_marca_id.isdigit() else None,
            "edit_parceiro_id": int(edit_parceiro_id) if edit_parceiro_id.isdigit() else None,
            "edit_regra_id": int(edit_regra_id) if edit_regra_id.isdigit() else None,
            "marca_em_edicao": marca_em_edicao,
            "aba_ativa": aba_ativa,
            "resumo_catalogo": resumo_catalogo,
            "catalogo_tab": "marcas",
            "catalogo_title": "Marcas, fornecedores e parceiros",
            "catalogo_subtitle": (
                "Cadastre a base de marcas atendidas, fornecedores de garantia e parceiros externos "
                "numa unica area, com consulta e manutencao operacional."
            ),
            "menu_app": "configuracoes",
            "menu_sub": "marcas_fornecedores",
        },
    )

