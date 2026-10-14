from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import (
    CAIXA_FINANCIAL_ROLES,
    has_sensitive_permission,
    role_required,
)
from configuracoes.services.tenant_guard import obter_empresa_ativa

from ..forms import AbsorverCorrecaoForm, DocumentarCorrecaoRetroativaForm, FundoTrocoForm, SaldoCorteDinheiroForm, TransferenciaDinheiroFisicoForm
from ..models import Caixa, CorrecaoRetroativaCaixa, DivergenciaCaixa, LocalDinheiroFisico, OperacaoDinheiroFisico
from ..services.correcoes_retroativas import absorver_correcao, documentar_correcao_existente
from ..services.divergencias_caixa import aprovar_divergencia
from ..services.dinheiro_fisico import (
    definir_fundo_troco,
    garantir_locais_padrao,
    registrar_saldo_corte,
    registrar_transferencia_entre_locais,
    saldo_local,
)
from ..services.fechamento_caixa import componentes_pagamento


def _data_filtro(valor, padrao):
    try:
        return datetime.strptime(valor or "", "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return padrao


def _extrato_legado(empresa, data_inicio, data_fim):
    caixas = Caixa.objects.filter(
        empresa=empresa, data__range=(data_inicio, data_fim)
    ).prefetch_related("pagamentos__forma_pagamento", "lancamentos", "fechamentos_versionados").order_by("data", "id")
    dias = []
    for caixa in caixas:
        saldo = Decimal(caixa.saldo_inicial or 0)
        linhas = [
            {
                "momento": None,
                "tipo": "abertura",
                "descricao": "Saldo inicial da gaveta",
                "entrada": saldo,
                "saida": Decimal("0.00"),
                "saldo": saldo,
                "referencia": f"Caixa #{caixa.pk}",
            }
        ]
        eventos = []
        for pagamento in caixa.pagamentos.all():
            valor_dinheiro = sum(
                (item["valor"] for item in componentes_pagamento(pagamento) if item["dinheiro"]),
                Decimal("0.00"),
            )
            if valor_dinheiro > Decimal("0.00"):
                eventos.append(
                    (
                        pagamento.data,
                        "recebimento",
                        f"Recebimento {pagamento.numero_talao or pagamento.referencia or pagamento.pk}",
                        valor_dinheiro,
                        Decimal("0.00"),
                        f"Pagamento #{pagamento.pk}",
                    )
                )
        for lancamento in caixa.lancamentos.all():
            if lancamento.pagamento_id:
                continue
            entrada = Decimal(lancamento.valor) if lancamento.tipo == "entrada" else Decimal("0.00")
            saida = Decimal(lancamento.valor) if lancamento.tipo == "saida" else Decimal("0.00")
            eventos.append(
                (
                    lancamento.data,
                    lancamento.natureza,
                    lancamento.descricao,
                    entrada,
                    saida,
                    f"Lancamento #{lancamento.pk}",
                )
            )
        for momento, tipo, descricao, entrada, saida, referencia in sorted(
            eventos, key=lambda item: (item[0], item[5])
        ):
            saldo += entrada - saida
            linhas.append(
                {
                    "momento": momento,
                    "tipo": tipo,
                    "descricao": descricao,
                    "entrada": entrada,
                    "saida": saida,
                    "saldo": saldo,
                    "referencia": referencia,
                }
            )
        fechamento = caixa.fechamentos_versionados.order_by("-versao", "-id").first()
        dias.append(
            {
                "caixa": caixa,
                "linhas": linhas,
                "esperado": fechamento.dinheiro_esperado if fechamento else saldo,
                "contado": fechamento.dinheiro_contado if fechamento else (caixa.valor_contado_fisico if not caixa.aberto else None),
                "diferenca": fechamento.diferenca if fechamento else (caixa.diferenca_fechamento if not caixa.aberto else None),
                "versao": fechamento.versao if fechamento else None,
            }
        )
    return dias


@role_required(CAIXA_FINANCIAL_ROLES)
def dinheiro_fisico(request):
    empresa = obter_empresa_ativa(request, strict=True)
    garantir_locais_padrao(empresa)
    hoje = timezone.localdate()
    data_inicio = _data_filtro(request.GET.get("data_inicio"), hoje - timedelta(days=30))
    data_fim = _data_filtro(request.GET.get("data_fim"), hoje)
    if data_inicio > data_fim:
        data_inicio, data_fim = data_fim, data_inicio

    acao = request.POST.get("acao") if request.method == "POST" else ""
    transferencia_form = TransferenciaDinheiroFisicoForm(
        request.POST if acao == "transferir" else None, empresa=empresa
    )
    saldo_corte_form = SaldoCorteDinheiroForm(
        request.POST if acao == "saldo_corte" else None, empresa=empresa
    )
    fundo_form = FundoTrocoForm(request.POST if acao == "fundo_troco" else None, empresa=empresa)
    correcao_form = DocumentarCorrecaoRetroativaForm(
        request.POST if acao == "documentar_correcao" else None, empresa=empresa
    )
    absorcao_form = AbsorverCorrecaoForm(
        request.POST if acao == "absorver_correcao" else None, empresa=empresa
    )

    try:
        if acao == "transferir" and transferencia_form.is_valid():
            registrar_transferencia_entre_locais(
                empresa=empresa,
                usuario=request.user,
                chave=transferencia_form.cleaned_data["chave_idempotencia"],
                **{k: transferencia_form.cleaned_data[k] for k in (
                    "origem", "destino", "valor", "tipo", "data_movimento", "descricao", "justificativa"
                )},
            )
            messages.success(request, "Movimentacao fisica registrada com auditoria.")
            return redirect("caixa:dinheiro_fisico")
        if acao == "saldo_corte" and saldo_corte_form.is_valid():
            registrar_saldo_corte(
                empresa=empresa,
                usuario=request.user,
                **saldo_corte_form.cleaned_data,
            )
            messages.success(request, "Saldo inicial de corte registrado.")
            return redirect("caixa:dinheiro_fisico")
        if acao == "fundo_troco" and fundo_form.is_valid():
            definir_fundo_troco(empresa=empresa, usuario=request.user, **fundo_form.cleaned_data)
            messages.success(request, "Fundo de troco atualizado.")
            return redirect("caixa:dinheiro_fisico")
        if acao == "aprovar_divergencia":
            divergencia = get_object_or_404(
                DivergenciaCaixa, pk=request.POST.get("divergencia_id"), empresa=empresa
            )
            aprovar_divergencia(
                divergencia=divergencia,
                observacao=request.POST.get("observacao_aprovacao"),
                usuario=request.user,
            )
            messages.success(request, "Divergencia aprovada para investigacao, sem gerar receita ou despesa.")
            return redirect("caixa:dinheiro_fisico")
        if acao == "documentar_correcao" and correcao_form.is_valid():
            correcao = documentar_correcao_existente(
                usuario=request.user, **correcao_form.cleaned_data
            )
            messages.success(
                request,
                f"Correcao #{correcao.pk} documentada. Nenhum valor ou contagem foi alterado.",
            )
            return redirect("caixa:dinheiro_fisico")
        if acao == "absorver_correcao" and absorcao_form.is_valid():
            absorver_correcao(usuario=request.user, **absorcao_form.cleaned_data)
            messages.success(
                request,
                "Absorcao registrada sem criar nova entrada ou saida de dinheiro.",
            )
            return redirect("caixa:dinheiro_fisico")
    except (PermissionDenied, ValidationError) as exc:
        mensagem = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        messages.error(request, mensagem)

    locais = list(LocalDinheiroFisico.objects.filter(empresa=empresa, ativo=True))
    for local in locais:
        local.saldo_calculado = saldo_local(local)
        local.fundo_troco = getattr(getattr(local, "configuracao_fundo_troco", None), "valor_alvo", None)

    return render(
        request,
        "caixa/dinheiro_fisico.html",
        {
            "menu_app": "caixa",
            "menu_sub": "dinheiro_fisico",
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "dias": _extrato_legado(empresa, data_inicio, data_fim),
            "locais": locais,
            "operacoes": OperacaoDinheiroFisico.objects.filter(
                empresa=empresa, data_movimento__range=(data_inicio, data_fim)
            ).prefetch_related("partidas__local")[:100],
            "divergencias": DivergenciaCaixa.objects.filter(empresa=empresa).select_related(
                "caixa", "fechamento", "criada_por", "aprovada_por"
            )[:50],
            "transferencia_form": transferencia_form,
            "saldo_corte_form": saldo_corte_form,
            "fundo_form": fundo_form,
            "correcao_form": correcao_form,
            "absorcao_form": absorcao_form,
            "correcoes_retroativas": CorrecaoRetroativaCaixa.objects.filter(
                empresa=empresa
            ).select_related("lancamento", "caixa_origem")[:50],
            "pode_configurar": has_sensitive_permission(request.user, "perm_caixa_corrigir_lancamentos"),
        },
    )
