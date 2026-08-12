from uuid import uuid4

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, has_sensitive_permission, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa

from ..forms import AporteCapitalForm, ConciliacaoBancariaGrupoForm, ConciliarExtratoForm, ContaBancariaForm, FechamentoBancarioForm, ImportarExtratoForm, MovimentoSocioForm, TransferenciaTesourariaForm
from ..models import AporteCapital, CategoriaFinanceira, CentroCusto, ConciliacaoBancaria, ContaBancaria, FechamentoBancario, ImportacaoExtratoBancario, LinhaExtratoBancario, MovimentoBancario, MovimentoSocio, TransferenciaTesouraria
from ..services.tesouraria import conciliar_grupo, conciliar_linha, criar_movimento_de_linha_extrato, desfazer_conciliacao, fechar_periodo_bancario, ignorar_linha, importar_extrato_arquivo, movimentos_bancarios_disponiveis, reabrir_periodo_bancario, registrar_aporte_capital, registrar_movimento_socio, registrar_transferencia, sugerir_correspondencias


@role_required(CAIXA_FINANCIAL_ROLES)
def tesouraria(request):
    empresa = obter_empresa_ativa(request, strict=False)
    acao = request.POST.get("acao") if request.method == "POST" else ""
    conta_form = ContaBancariaForm(request.POST if acao == "conta" else None)
    transferencia_form = TransferenciaTesourariaForm(request.POST if acao == "transferencia" else None, empresa=empresa)
    aporte_form = AporteCapitalForm(request.POST if acao == "aporte" else None, empresa=empresa)
    movimento_socio_form = MovimentoSocioForm(
        request.POST if acao == "movimento_socio" else None,
        request.FILES if acao == "movimento_socio" else None,
        empresa=empresa,
    )
    extrato_form = ImportarExtratoForm(request.POST if acao == "extrato" else None, request.FILES if acao == "extrato" else None, empresa=empresa)
    fechamento_form = FechamentoBancarioForm(request.POST if acao == "fechar_periodo" else None, empresa=empresa)

    if acao == "conta" and conta_form.is_valid():
        conta = conta_form.save(commit=False)
        conta.empresa = empresa
        conta.save()
        messages.success(request, "Conta bancária cadastrada.")
        return redirect("caixa:tesouraria")
    if acao == "transferencia" and transferencia_form.is_valid():
        dados = transferencia_form.cleaned_data
        try:
            registrar_transferencia(
                empresa=empresa,
                valor=dados["valor"],
                data_movimento=dados["data_movimento"],
                chave=uuid4().hex,
                usuario=request.user,
                conta_origem=dados.get("conta_origem"),
                caixa_origem=dados.get("caixa_origem"),
                conta_destino=dados.get("conta_destino"),
                caixa_destino=dados.get("caixa_destino"),
                descricao=dados.get("descricao") or "",
            )
            messages.success(request, "Transferência registrada sem afetar receita ou despesa.")
            return redirect("caixa:tesouraria")
        except ValidationError as exc:
            transferencia_form.add_error(None, exc)
    if acao == "aporte" and aporte_form.is_valid():
        require_sensitive_permission(request.user, "perm_caixa_gerir_capital")
        dados = aporte_form.cleaned_data
        hoje = timezone.localdate()
        retroativo = dados["data_competencia"] != hoje or dados["data_movimento"] != hoje
        if retroativo and not has_sensitive_permission(request.user, "perm_caixa_lancamento_retroativo"):
            aporte_form.add_error(None, "Você não tem permissão para registrar aportes em data retroativa.")
        else:
            try:
                registrar_aporte_capital(
                    empresa=empresa, tipo=dados["tipo"], descricao=dados["descricao"], aportante=dados["aportante"],
                    documento_referencia=dados["documento_referencia"], valor=dados["valor"],
                    data_competencia=dados["data_competencia"], data_movimento=dados["data_movimento"],
                    conta_bancaria=dados.get("conta_bancaria"), caixa=dados.get("caixa"),
                    chave=uuid4().hex, usuario=request.user,
                )
                messages.success(request, "Capital/aporte registrado sem compor receita operacional.")
                return redirect("caixa:tesouraria")
            except ValidationError as exc:
                aporte_form.add_error(None, exc)
    if acao == "movimento_socio" and movimento_socio_form.is_valid():
        require_sensitive_permission(request.user, "perm_caixa_gerir_capital")
        dados = movimento_socio_form.cleaned_data
        retroativo = dados["data_competencia"] != timezone.localdate() or dados["data_movimento"] != timezone.localdate()
        if retroativo and not has_sensitive_permission(request.user, "perm_caixa_lancamento_retroativo"):
            movimento_socio_form.add_error(None, "Você não pode registrar este movimento retroativamente.")
        else:
            try:
                registrar_movimento_socio(
                    aporte=dados["aporte_origem"], tipo=dados["tipo"], descricao=dados["descricao"],
                    valor=dados["valor"], data_competencia=dados["data_competencia"],
                    data_movimento=dados["data_movimento"], conta_bancaria=dados.get("conta_bancaria"),
                    caixa=dados.get("caixa"), documento_referencia=dados.get("documento_referencia") or "",
                    comprovante=dados.get("comprovante"), chave=uuid4().hex, usuario=request.user,
                )
                messages.success(request, "Movimento de sócio registrado fora da receita operacional.")
                return redirect("caixa:tesouraria")
            except ValidationError as exc:
                movimento_socio_form.add_error(None, exc)
    if acao == "extrato" and extrato_form.is_valid():
        require_sensitive_permission(request.user, "perm_caixa_importar_extrato")
        try:
            arquivo = extrato_form.cleaned_data["arquivo"]
            criadas = importar_extrato_arquivo(
                conta=extrato_form.cleaned_data["conta"],
                conteudo=arquivo.read(),
                nome_arquivo=arquivo.name,
                usuario=request.user,
            )
            messages.success(request, f"Extrato importado: {len(criadas)} linha(s) nova(s).")
            return redirect("caixa:tesouraria")
        except ValidationError as exc:
            extrato_form.add_error("arquivo", exc)
    if acao == "fechar_periodo" and fechamento_form.is_valid():
        require_sensitive_permission(request.user, "perm_caixa_fechar_banco")
        try:
            fechar_periodo_bancario(usuario=request.user, **fechamento_form.cleaned_data)
            messages.success(request, "Período bancário fechado com saldo conciliado.")
            return redirect("caixa:tesouraria")
        except ValidationError as exc:
            fechamento_form.add_error(None, exc)
    if acao == "reabrir_periodo":
        require_sensitive_permission(request.user, "perm_caixa_fechar_banco")
        fechamento = get_object_or_404(FechamentoBancario, pk=request.POST.get("fechamento_id"), empresa=empresa)
        try:
            reabrir_periodo_bancario(
                fechamento=fechamento, usuario=request.user, motivo=request.POST.get("motivo_reabertura")
            )
            messages.success(request, "Período bancário reaberto com auditoria preservada.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return redirect("caixa:tesouraria")

    contas = ContaBancaria.objects.filter(empresa=empresa).prefetch_related("movimentos")
    return render(request, "caixa/tesouraria.html", {
        "contas": contas,
        "conta_form": conta_form,
        "transferencia_form": transferencia_form,
        "aporte_form": aporte_form,
        "movimento_socio_form": movimento_socio_form,
        "extrato_form": extrato_form,
        "fechamento_form": fechamento_form,
        "movimentos": movimentos_bancarios_disponiveis(
            MovimentoBancario.objects.filter(empresa=empresa).select_related("conta")
        )[:100],
        "linhas_extrato": LinhaExtratoBancario.objects.filter(empresa=empresa).select_related("conta", "movimento")[:100],
        "transferencias": TransferenciaTesouraria.objects.filter(empresa=empresa).select_related("conta_origem", "conta_destino", "caixa_origem", "caixa_destino")[:50],
        "aportes": AporteCapital.objects.filter(empresa=empresa).select_related("conta_bancaria", "caixa", "registrado_por")[:50],
        "movimentos_socios": MovimentoSocio.objects.filter(empresa=empresa).select_related("aporte_origem", "conta_bancaria", "caixa")[:50],
        "conciliacoes": ConciliacaoBancaria.objects.filter(empresa=empresa).select_related("conta", "conciliado_por", "desfeito_por")[:50],
        "importacoes_extrato": ImportacaoExtratoBancario.objects.filter(empresa=empresa).select_related("conta", "importado_por")[:30],
        "fechamentos_bancarios": FechamentoBancario.objects.filter(empresa=empresa).select_related("conta", "fechado_por", "reaberto_por")[:30],
        "menu_app": "caixa",
        "menu_sub": "tesouraria",
    })


@role_required(CAIXA_FINANCIAL_ROLES)
def tratar_linha_extrato(request, linha_id):
    require_sensitive_permission(request.user, "perm_caixa_conciliar_banco")
    empresa = obter_empresa_ativa(request, strict=False)
    linha = get_object_or_404(LinhaExtratoBancario, pk=linha_id, empresa=empresa)
    valor_esperado = abs(linha.valor)
    tipo_esperado = "entrada" if linha.valor > 0 else "saida"
    correspondencias_exatas = movimentos_bancarios_disponiveis(
        MovimentoBancario.objects.filter(
            empresa=empresa, conta=linha.conta, tipo=tipo_esperado,
            valor=valor_esperado, data_movimento=linha.data_movimento,
        )
    )
    if request.method == "POST" and request.POST.get("criar_movimento") == "1":
        try:
            if correspondencias_exatas.exists() and request.POST.get("confirmar_novo_movimento") != "1":
                raise ValidationError(
                    "Já existe movimento disponível com o mesmo valor e data. "
                    "Concilie-o ou confirme expressamente que este é outro fato."
                )
            movimento = criar_movimento_de_linha_extrato(
                linha=linha, classificacao=request.POST.get("classificacao"),
                descricao=request.POST.get("descricao_movimento") or linha.descricao,
                categoria=CategoriaFinanceira.objects.filter(pk=request.POST.get("categoria"), empresa=empresa).first(),
                centro_custo=CentroCusto.objects.filter(pk=request.POST.get("centro_custo"), empresa=empresa).first(),
                usuario=request.user,
            )
            conciliar_linha(linha=linha, movimento=movimento, usuario=request.user)
            messages.success(request, "Movimento criado com confirmação humana e linha conciliada.")
            return redirect("caixa:tesouraria")
        except (ValidationError, IntegrityError) as exc:
            texto = "; ".join(exc.messages) if isinstance(exc, ValidationError) else (
                "A conciliação foi alterada por outra operação. Atualize a tela e tente novamente."
            )
            messages.error(request, texto)
    if request.method == "POST" and request.POST.get("ignorar") == "1":
        try:
            ignorar_linha(linha=linha, usuario=request.user, justificativa=request.POST.get("justificativa"))
            messages.success(request, "Linha ignorada com justificativa.")
            return redirect("caixa:tesouraria")
        except ValidationError as exc:
            messages.error(request, str(exc))
    form = ConciliarExtratoForm(request.POST or None, linha=linha, empresa=empresa)
    if request.method == "POST" and form.is_valid():
        try:
            resultado = conciliar_linha(linha=linha, movimento=form.cleaned_data["movimento"], usuario=request.user, justificativa=form.cleaned_data["justificativa"])
            messages.success(request, f"Linha tratada como {resultado.get_status_display().lower()}.")
            return redirect("caixa:tesouraria")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else (
                "A conciliação foi alterada por outra operação. Atualize a tela e tente novamente."
            ))
    return render(request, "caixa/conciliar_extrato.html", {
        "linha": linha, "form": form, "sugestoes": sugerir_correspondencias(linha=linha, limite=5),
        "possui_correspondencia_exata": correspondencias_exatas.exists(),
        "categorias": CategoriaFinanceira.objects.filter(empresa=empresa, tipo="saida", ativa=True),
        "centros_custo": CentroCusto.objects.filter(empresa=empresa, ativo=True),
        "menu_app": "caixa", "menu_sub": "tesouraria",
    })


@role_required(CAIXA_FINANCIAL_ROLES)
def conciliar_extrato_grupo(request):
    require_sensitive_permission(request.user, "perm_caixa_conciliar_banco")
    empresa = obter_empresa_ativa(request, strict=False)
    initial = {"conta": request.GET.get("conta")} if request.method == "GET" and request.GET.get("conta") else None
    form = ConciliacaoBancariaGrupoForm(request.POST or None, empresa=empresa, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            conciliacao = conciliar_grupo(
                linhas=form.cleaned_data["linhas"],
                movimentos=form.cleaned_data["movimentos"],
                usuario=request.user,
                justificativa=form.cleaned_data["justificativa"],
                registrar_diferenca=form.cleaned_data["registrar_diferenca"],
                tipo_diferenca=form.cleaned_data["tipo_diferenca"],
                descricao_diferenca=form.cleaned_data["descricao_diferenca"],
            )
            messages.success(request, f"Conciliação #{conciliacao.pk} registrada como {conciliacao.get_status_display().lower()}.")
            return redirect("caixa:tesouraria")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else (
                "A conciliação foi alterada por outra operação. Atualize a tela e tente novamente."
            ))
    return render(request, "caixa/conciliar_extrato_grupo.html", {"form": form, "menu_app": "caixa", "menu_sub": "tesouraria"})


@role_required(CAIXA_FINANCIAL_ROLES)
def desfazer_conciliacao_bancaria(request, conciliacao_id):
    require_sensitive_permission(request.user, "perm_caixa_conciliar_banco")
    empresa = obter_empresa_ativa(request, strict=False)
    conciliacao = get_object_or_404(ConciliacaoBancaria, pk=conciliacao_id, empresa=empresa)
    if request.method != "POST":
        return redirect("caixa:tesouraria")
    try:
        desfazer_conciliacao(
            conciliacao=conciliacao,
            usuario=request.user,
            motivo=request.POST.get("motivo_desfazimento"),
        )
        messages.success(request, f"Conciliação #{conciliacao.pk} desfeita; as linhas voltaram a ficar pendentes.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect("caixa:tesouraria")
