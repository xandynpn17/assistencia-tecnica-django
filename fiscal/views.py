from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa

from .forms import CertificadoA1Form, ConfiguracaoFiscalForm, DocumentoFiscalForm, FaixaTributariaForm, ImportarDocumentoDFeForm, NovaVersaoRegraForm, PerfilTributarioForm, RegraTributariaForm, SimulacaoImpactoTributarioForm, TributoParametrizadoForm
from .models import ConfiguracaoFiscal, DocumentoDistribuicaoDFe, DocumentoFiscal, ExecucaoSincronizacaoDFe, PerfilTributario, RegraTributaria


@role_required(CAIXA_FINANCIAL_ROLES)
def painel_fiscal(request):
    empresa = obter_empresa_ativa(request, strict=True)
    config = ConfiguracaoFiscal.get_solo(empresa)
    if request.method == "POST":
        form = ConfiguracaoFiscalForm(request.POST, instance=config)
        if form.is_valid():
            ambiente_anterior = config.ambiente
            form.save()
            if config.ambiente != ambiente_anterior:
                config.ultimo_nsu = "000000000000000"
                config.max_nsu = "000000000000000"
                config.proxima_sincronizacao_dfe = None
                config.ultimo_status_dfe = ""
                config.ultima_mensagem_dfe = ""
                config.save(update_fields=[
                    "ultimo_nsu", "max_nsu", "proxima_sincronizacao_dfe",
                    "ultimo_status_dfe", "ultima_mensagem_dfe", "atualizado_em",
                ])
                messages.info(request, "O controle de NSU foi reiniciado porque o ambiente fiscal mudou.")
            messages.success(request, "Configuração fiscal atualizada.")
            return redirect("fiscal:painel_fiscal")
    else:
        form = ConfiguracaoFiscalForm(instance=config)

    docs = DocumentoFiscal.objects.filter(empresa=empresa).order_by("-id")[:300]
    return render(
        request,
        "fiscal/painel_fiscal.html",
        {
            "form": form,
            "documentos": docs,
            "menu_app": "fiscal",
            "menu_sub": "painel_fiscal",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def caixa_entrada_dfe(request):
    empresa = obter_empresa_ativa(request, strict=True)
    config = ConfiguracaoFiscal.get_solo(empresa)
    documentos = DocumentoDistribuicaoDFe.objects.filter(empresa=empresa).select_related("entrada_mercadoria")
    busca = (request.GET.get("q") or "").strip()
    disponibilidade = (request.GET.get("disponibilidade") or "").strip()
    importacao = (request.GET.get("importacao") or "").strip()
    if busca:
        documentos = documentos.filter(
            Q(numero__icontains=busca) | Q(chave_acesso__icontains=busca) |
            Q(nome_emitente__icontains=busca) | Q(cnpj_emitente__icontains=busca)
        )
    if disponibilidade in dict(DocumentoDistribuicaoDFe.DISPONIBILIDADE_CHOICES):
        documentos = documentos.filter(disponibilidade=disponibilidade)
    if importacao == "importado":
        documentos = documentos.filter(entrada_mercadoria__isnull=False)
    elif importacao == "pendente":
        documentos = documentos.filter(entrada_mercadoria__isnull=True, disponibilidade="xml_completo")
    return render(request, "fiscal/caixa_entrada_dfe.html", {
        "menu_app": "fiscal", "menu_sub": "caixa_entrada_dfe", "config": config,
        "certificado_form": CertificadoA1Form(empresa=empresa),
        "importar_form": ImportarDocumentoDFeForm(empresa=empresa),
        "documentos": documentos[:300], "busca": busca,
        "disponibilidade": disponibilidade, "importacao": importacao,
        "disponibilidade_choices": DocumentoDistribuicaoDFe.DISPONIBILIDADE_CHOICES,
        "execucoes": ExecucaoSincronizacaoDFe.objects.filter(empresa=empresa)[:15],
        "agora": timezone.now(),
    })


@require_POST
@role_required(CAIXA_FINANCIAL_ROLES)
def salvar_certificado_a1(request):
    empresa = obter_empresa_ativa(request, strict=True)
    config = ConfiguracaoFiscal.get_solo(empresa)
    form = CertificadoA1Form(request.POST, request.FILES, empresa=empresa)
    if form.is_valid():
        form.salvar(config)
        messages.success(request, "Certificado A1 validado e armazenado de forma protegida para a empresa ativa.")
    else:
        for erros in form.errors.values():
            for erro in erros:
                messages.error(request, str(erro))
    return redirect("fiscal:caixa_entrada_dfe")


@require_POST
@role_required(CAIXA_FINANCIAL_ROLES)
def remover_certificado_a1(request):
    empresa = obter_empresa_ativa(request, strict=True)
    if request.POST.get("confirmar") != "1":
        messages.error(request, "Confirme explicitamente a remoção do certificado.")
        return redirect("fiscal:caixa_entrada_dfe")
    config = ConfiguracaoFiscal.get_solo(empresa)
    for campo in (
        "certificado_a1_protegido", "senha_certificado_protegida", "certificado_titular",
        "certificado_cnpj", "certificado_serial", "certificado_fingerprint_sha256",
    ):
        setattr(config, campo, "")
    config.certificado_inicio = None
    config.certificado_validade = None
    config.save(update_fields=[
        "certificado_a1_protegido", "senha_certificado_protegida", "certificado_titular",
        "certificado_cnpj", "certificado_serial", "certificado_fingerprint_sha256",
        "certificado_inicio", "certificado_validade", "atualizado_em",
    ])
    messages.success(request, "Certificado A1 removido desta empresa. O histórico fiscal foi preservado.")
    return redirect("fiscal:caixa_entrada_dfe")


@require_POST
@role_required(CAIXA_FINANCIAL_ROLES)
def sincronizar_caixa_dfe(request):
    empresa = obter_empresa_ativa(request, strict=True)
    config = ConfiguracaoFiscal.get_solo(empresa)
    from .services_distribuicao_dfe import sincronizar_distribuicao_dfe
    try:
        resultado = sincronizar_distribuicao_dfe(config=config, usuario=request.user)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        if resultado["novos"]:
            messages.success(request, f"Sincronização concluída: {resultado['novos']} documento(s) novo(s).")
        else:
            messages.info(request, "Sincronização concluída sem documentos novos.")
    return redirect("fiscal:caixa_entrada_dfe")


@require_POST
@role_required(CAIXA_FINANCIAL_ROLES)
def importar_documento_dfe(request, documento_id):
    empresa = obter_empresa_ativa(request, strict=True)
    documento = get_object_or_404(DocumentoDistribuicaoDFe, pk=documento_id, empresa=empresa)
    form = ImportarDocumentoDFeForm(request.POST, empresa=empresa)
    if not form.is_valid():
        for erros in form.errors.values():
            for erro in erros:
                messages.error(request, str(erro))
        return redirect("fiscal:caixa_entrada_dfe")
    from .services_distribuicao_dfe import importar_documento_dfe_no_estoque
    try:
        entrada, criada = importar_documento_dfe_no_estoque(
            documento=documento, usuario=request.user, **form.cleaned_data
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("fiscal:caixa_entrada_dfe")
    messages.success(
        request,
        "NF-e preparada para conferência no estoque." if criada else "Esta NF-e já estava vinculada a uma entrada.",
    )
    return redirect("estoque:detalhe_entrada_mercadoria", entrada_id=entrada.pk)


@role_required(CAIXA_FINANCIAL_ROLES)
def novo_documento_fiscal(request):
    empresa = obter_empresa_ativa(request, strict=True)
    if request.method == "POST":
        form = DocumentoFiscalForm(request.POST)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.empresa = empresa
            doc.criado_por = request.user
            doc.status = "fila"
            doc.save()
            messages.success(request, "Documento fiscal enviado para validação interna.")
            return redirect("fiscal:painel_fiscal")
    else:
        initial = {"origem": request.GET.get("origem") or "MANUAL"}
        if request.GET.get("tipo"):
            initial["tipo"] = request.GET.get("tipo")
        if request.GET.get("origem_referencia"):
            initial["origem_referencia"] = request.GET.get("origem_referencia")
        if request.GET.get("valor_total"):
            initial["valor_total"] = request.GET.get("valor_total")
        form = DocumentoFiscalForm(initial=initial)
    return render(
        request,
        "fiscal/form_documento_fiscal.html",
        {"form": form, "menu_app": "fiscal", "menu_sub": "novo_documento_fiscal"},
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def motor_tributario(request):
    empresa = obter_empresa_ativa(request, strict=True)
    perfil_form = PerfilTributarioForm(prefix="perfil")
    regra_form = RegraTributariaForm(prefix="regra", empresa=empresa)
    faixa_form = FaixaTributariaForm(prefix="faixa", empresa=empresa)
    tributo_form = TributoParametrizadoForm(prefix="tributo", empresa=empresa)
    versao_form = NovaVersaoRegraForm(prefix="versao", empresa=empresa)
    simulacao_form = SimulacaoImpactoTributarioForm(prefix="simulacao")
    simulacoes = []
    if request.method == "POST":
        tipo = request.POST.get("form_tipo")
        if tipo == "perfil":
            perfil_form = PerfilTributarioForm(request.POST, prefix="perfil")
            form = perfil_form
        elif tipo == "regra":
            regra_form = RegraTributariaForm(request.POST, prefix="regra", empresa=empresa)
            form = regra_form
        elif tipo == "faixa":
            faixa_form = FaixaTributariaForm(request.POST, prefix="faixa", empresa=empresa)
            form = faixa_form
        elif tipo == "tributo":
            tributo_form = TributoParametrizadoForm(request.POST, prefix="tributo", empresa=empresa)
            form = tributo_form
        elif tipo == "versao":
            versao_form = NovaVersaoRegraForm(request.POST, prefix="versao", empresa=empresa)
            form = versao_form
        else:
            simulacao_form = SimulacaoImpactoTributarioForm(request.POST, prefix="simulacao")
            form = simulacao_form
        if form.is_valid() and tipo == "versao":
            from fiscal.services_versionamento import criar_nova_versao_regra
            try:
                nova = criar_nova_versao_regra(usuario=request.user, **form.cleaned_data)
                messages.success(request, f"Nova versão {nova.codigo} criada em rascunho; revise e homologue antes do uso.")
                return redirect("fiscal:motor_tributario")
            except Exception as exc:
                form.add_error(None, exc)
        elif form.is_valid() and tipo == "simulacao":
            from fiscal.services_tributacao import simular_impacto_precificacao

            dados = form.cleaned_data
            simulacoes = simular_impacto_precificacao(
                empresa=empresa, custo_base=dados["custo_base"], preco_atual=dados["preco_atual"],
                margem_alvo=dados["margem_alvo"], taxa_recebimento=dados["taxa_recebimento"],
                tipo_item=dados["tipo_item"], datas=[dados["data_atual"], dados["data_futura"]],
            )
        elif form.is_valid():
            objeto = form.save(commit=False)
            if tipo == "perfil":
                objeto.empresa = empresa
            if getattr(objeto, "status", None) == "homologado":
                objeto.homologado_por = request.user
                objeto.homologado_em = timezone.now()
            objeto.full_clean()
            objeto.save()
            messages.success(request, "Configuração tributária adicionada e versionada.")
            return redirect("fiscal:motor_tributario")

    perfis = PerfilTributario.objects.filter(empresa=empresa).prefetch_related("regras__faixas", "regras__tributos_parametrizados").order_by("-inicio_vigencia", "-id")
    from estoque.models import Produto

    produtos_pendentes_qs = Produto.objects.filter(empresa=empresa, ativo=True).filter(
        Q(tipo_item="servico", codigo_servico="") | (~Q(tipo_item="servico") & Q(ncm=""))
    ).order_by("nome")
    produtos_pendentes_total = produtos_pendentes_qs.count()
    from .services_prontidao import diagnosticar_prontidao_precificacao

    prontidao = diagnosticar_prontidao_precificacao(empresa=empresa)
    return render(request, "fiscal/motor_tributario.html", {
        "menu_app": "fiscal", "menu_sub": "motor_tributario", "perfis": perfis,
        "perfil_form": perfil_form, "regra_form": regra_form, "faixa_form": faixa_form, "tributo_form": tributo_form,
        "versao_form": versao_form,
        "simulacao_form": simulacao_form, "simulacoes": simulacoes,
        "produtos_pendentes": produtos_pendentes_qs[:100], "produtos_pendentes_total": produtos_pendentes_total,
        "prontidao": prontidao,
    })


@role_required(CAIXA_FINANCIAL_ROLES)
def processar_fila_fiscal(request):
    if request.method != "POST":
        messages.error(request, "Ação inválida para validação da fila fiscal.")
        return redirect("fiscal:painel_fiscal")

    empresa = obter_empresa_ativa(request, strict=True)
    docs = DocumentoFiscal.objects.filter(empresa=empresa, status="fila").order_by("id")[:100]
    if not docs.exists():
        messages.info(request, "Fila fiscal vazia.")
        return redirect("fiscal:painel_fiscal")

    bloqueados = 0
    with transaction.atomic():
        for doc in docs:
            doc.marcar_rejeitada(
                "Emissão bloqueada: integração fiscal real ainda não configurada. "
                "Nenhum documento foi transmitido ou autorizado."
            )
            bloqueados += 1

    messages.warning(
        request,
        f"Emissão fiscal indisponível. {bloqueados} documento(s) bloqueado(s), sem transmissão ou autorização.",
    )
    return redirect("fiscal:painel_fiscal")
