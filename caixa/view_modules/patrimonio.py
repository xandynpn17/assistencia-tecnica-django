from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render
from django.shortcuts import get_object_or_404
from django.utils import timezone

from configuracoes.permissions import (
    CAIXA_FINANCIAL_ROLES,
    has_sensitive_permission,
    require_sensitive_permission,
    role_required,
)
from configuracoes.services.tenant_guard import obter_empresa_ativa

from ..forms_patrimonio import (
    ClassificacaoPessoaForm,
    ContaInvestimentoForm,
    EstornoFinanceiroForm,
    MovimentoInvestimentoForm,
    MovimentoPessoaFinanceiraForm,
    PessoaFinanceiraForm,
    VincularEstornoPendenteForm,
)
from ..models import (
    ClassificacaoPessoaFinanceira,
    ContaInvestimento,
    EstornoFinanceiroVinculado,
    MovimentoInvestimento,
    MovimentoPessoaFinanceira,
    PessoaFinanceira,
    TransacaoAdquirente,
)
from ..services.patrimonio import (
    classificar_movimento_pessoa,
    aprovar_classificacao_pessoa,
    registrar_estorno_vinculado,
    registrar_movimento_investimento,
    registrar_movimento_pessoa,
    vincular_estorno_pendente,
)


def _competencia(request):
    valor = request.GET.get("competencia") or timezone.localdate().strftime("%Y-%m")
    try:
        ano, mes = [int(parte) for parte in valor.split("-", 1)]
        return date(ano, mes, 1)
    except (TypeError, ValueError):
        return timezone.localdate().replace(day=1)


@role_required(CAIXA_FINANCIAL_ROLES)
def patrimonio_financeiro(request):
    require_sensitive_permission(request.user, "perm_caixa_gerir_capital")
    empresa = obter_empresa_ativa(request, strict=False)
    acao = request.POST.get("acao") if request.method == "POST" else ""

    pessoa_form = PessoaFinanceiraForm(request.POST if acao == "pessoa" else None)
    movimento_form = MovimentoPessoaFinanceiraForm(
        request.POST if acao == "movimento_pessoa" else None,
        request.FILES if acao == "movimento_pessoa" else None,
        empresa=empresa,
    )
    classificacao_form = ClassificacaoPessoaForm(
        request.POST if acao == "classificar" else None,
        request.FILES if acao == "classificar" else None,
        empresa=empresa,
    )
    conta_investimento_form = ContaInvestimentoForm(
        request.POST if acao == "conta_investimento" else None, empresa=empresa
    )
    investimento_form = MovimentoInvestimentoForm(
        request.POST if acao == "investimento" else None, empresa=empresa
    )
    estorno_form = EstornoFinanceiroForm(
        request.POST if acao == "estorno" else None, empresa=empresa
    )
    vincular_estorno_form = VincularEstornoPendenteForm(
        request.POST if acao == "vincular_estorno" else None, empresa=empresa
    )

    try:
        if acao == "aprovar_classificacao":
            require_sensitive_permission(request.user, "perm_caixa_corrigir_lancamentos")
            classificacao = get_object_or_404(
                ClassificacaoPessoaFinanceira,
                pk=request.POST.get("classificacao_id"),
                movimento__empresa=empresa,
            )
            aprovar_classificacao_pessoa(classificacao=classificacao, usuario=request.user)
            messages.success(request, "Classificação aprovada.")
            return redirect("caixa:patrimonio_financeiro")
        if acao == "pessoa" and pessoa_form.is_valid():
            pessoa = pessoa_form.save(commit=False)
            pessoa.empresa = empresa
            pessoa.full_clean()
            pessoa.save()
            messages.success(request, "Pessoa financeira cadastrada.")
            return redirect("caixa:patrimonio_financeiro")

        if acao == "movimento_pessoa" and movimento_form.is_valid():
            dados = movimento_form.cleaned_data
            if dados["data_movimento"] != timezone.localdate():
                require_sensitive_permission(request.user, "perm_caixa_lancamento_retroativo")
            registrar_movimento_pessoa(
                empresa=empresa,
                pessoa=dados["pessoa"],
                direcao=dados["direcao"],
                natureza=dados["natureza"],
                valor=dados["valor"],
                data_competencia=dados["data_competencia"],
                data_movimento=dados["data_movimento"],
                descricao=dados["descricao"],
                documento_referencia=dados.get("documento_referencia") or "",
                comprovante=dados.get("comprovante"),
                conta_bancaria=dados.get("conta_bancaria"),
                caixa=dados.get("caixa"),
                movimento_bancario_existente=dados.get("movimento_bancario_existente"),
                chave=dados["chave_idempotencia"],
                usuario=request.user,
            )
            messages.success(request, "Movimento registrado na conta-corrente da pessoa.")
            return redirect("caixa:patrimonio_financeiro")

        if acao == "classificar" and classificacao_form.is_valid():
            dados = classificacao_form.cleaned_data
            aprovar = bool(dados.get("aprovar"))
            if aprovar:
                require_sensitive_permission(request.user, "perm_caixa_corrigir_lancamentos")
            classificar_movimento_pessoa(
                movimento=dados["movimento"],
                natureza_definitiva=dados["natureza_definitiva"],
                valor=dados["valor"],
                competencia=dados["competencia"],
                justificativa=dados["justificativa"],
                documento=dados.get("documento"),
                chave=dados["chave_idempotencia"],
                usuario=request.user,
                aprovar=aprovar,
            )
            messages.success(request, "Classificação registrada com trilha de auditoria.")
            return redirect("caixa:patrimonio_financeiro")

        if acao == "conta_investimento" and conta_investimento_form.is_valid():
            conta = conta_investimento_form.save(commit=False)
            conta.empresa = empresa
            conta.full_clean()
            conta.save()
            messages.success(request, "Conta de investimento cadastrada.")
            return redirect("caixa:patrimonio_financeiro")

        if acao == "investimento" and investimento_form.is_valid():
            dados = investimento_form.cleaned_data
            if dados["data_movimento"] != timezone.localdate():
                require_sensitive_permission(request.user, "perm_caixa_lancamento_retroativo")
            registrar_movimento_investimento(
                conta=dados["conta"], tipo=dados["tipo"], valor=dados["valor"],
                data_competencia=dados["data_competencia"], data_movimento=dados["data_movimento"],
                descricao=dados["descricao"], chave=dados["chave_idempotencia"], usuario=request.user,
                movimento_bancario_existente=dados.get("movimento_bancario_existente"),
            )
            messages.success(request, "Movimento de investimento registrado sem distorcer a operação.")
            return redirect("caixa:patrimonio_financeiro")

        if acao == "estorno" and estorno_form.is_valid():
            require_sensitive_permission(request.user, "perm_caixa_corrigir_lancamentos")
            dados = estorno_form.cleaned_data
            registrar_estorno_vinculado(
                empresa=empresa,
                movimento_original=dados.get("movimento_original"),
                valor=dados["valor"],
                data_movimento=dados["data_movimento"],
                motivo=dados["motivo"],
                referencia_externa=dados.get("referencia_externa") or "",
                chave=dados["chave_idempotencia"],
                usuario=request.user,
            )
            messages.success(request, "Estorno registrado e vinculado à origem quando informada.")
            return redirect("caixa:patrimonio_financeiro")
        if acao == "vincular_estorno" and vincular_estorno_form.is_valid():
            require_sensitive_permission(request.user, "perm_caixa_corrigir_lancamentos")
            vincular_estorno_pendente(
                estorno=vincular_estorno_form.cleaned_data["estorno"],
                movimento_original=vincular_estorno_form.cleaned_data["movimento_original"],
                usuario=request.user,
            )
            messages.success(request, "Estorno pendente vinculado à operação original.")
            return redirect("caixa:patrimonio_financeiro")
    except ValidationError as exc:
        formulario = {
            "pessoa": pessoa_form,
            "movimento_pessoa": movimento_form,
            "classificar": classificacao_form,
            "conta_investimento": conta_investimento_form,
            "investimento": investimento_form,
            "estorno": estorno_form,
            "vincular_estorno": vincular_estorno_form,
        }.get(acao)
        if formulario:
            formulario.add_error(None, exc)

    competencia = _competencia(request)
    movimentos_mes = MovimentoPessoaFinanceira.objects.filter(
        empresa=empresa,
        data_competencia__year=competencia.year,
        data_competencia__month=competencia.month,
    ).select_related("pessoa", "movimento_bancario", "lancamento_caixa")
    zero = Value(0, output_field=DecimalField(max_digits=14, decimal_places=2))
    pessoas = PessoaFinanceira.objects.filter(empresa=empresa).annotate(
        empresa_deve=Coalesce(Sum("movimentos__valor", filter=Q(movimentos__direcao="empresa_deve")), zero),
        pessoa_deve=Coalesce(Sum("movimentos__valor", filter=Q(movimentos__direcao="pessoa_deve")), zero),
    ).annotate(
        saldo_liquido=ExpressionWrapper(
            F("empresa_deve") - F("pessoa_deve"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    )
    transacoes_adquirentes = TransacaoAdquirente.objects.filter(empresa=empresa)
    resumo_adquirente = transacoes_adquirentes.aggregate(
        bruto=Coalesce(Sum("valor_bruto"), zero),
        taxas=Coalesce(Sum("taxa"), zero),
        liquido=Coalesce(Sum("valor_liquido"), zero),
    )
    return render(request, "caixa/patrimonio_financeiro.html", {
        "pessoa_form": pessoa_form,
        "movimento_form": movimento_form,
        "classificacao_form": classificacao_form,
        "conta_investimento_form": conta_investimento_form,
        "investimento_form": investimento_form,
        "estorno_form": estorno_form,
        "vincular_estorno_form": vincular_estorno_form,
        "pessoas": pessoas,
        "movimentos_mes": movimentos_mes[:100],
        "classificacoes": ClassificacaoPessoaFinanceira.objects.filter(
            movimento__empresa=empresa
        ).select_related("movimento", "movimento__pessoa")[:100],
        "contas_investimento": ContaInvestimento.objects.filter(empresa=empresa).prefetch_related("movimentos"),
        "movimentos_investimento": MovimentoInvestimento.objects.filter(
            conta__empresa=empresa
        ).select_related("conta")[:100],
        "estornos": EstornoFinanceiroVinculado.objects.filter(empresa=empresa).select_related(
            "movimento_original", "movimento_contrapartida"
        )[:100],
        "resumo_adquirente": resumo_adquirente,
        "transacoes_adquirentes": transacoes_adquirentes.select_related("conta_liquidacao")[:100],
        "competencia": competencia,
        "pode_aprovar": has_sensitive_permission(request.user, "perm_caixa_corrigir_lancamentos"),
        "menu_app": "caixa",
        "menu_sub": "patrimonio_financeiro",
    })
