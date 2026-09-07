import logging
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema
from configuracoes.permissions import (
    CAIXA_OPERATIONAL_ROLES,
    has_sensitive_permission,
    require_sensitive_permission,
    role_required,
)
from configuracoes.services.tenant_guard import obter_empresa_ativa

from caixa.services.comissoes import (
    processar_evento_retirada_cliente,
    processar_evento_servico_finalizado,
    processar_evento_venda_mostrador,
)
from caixa.services.pagamentos import (
    calcular_desconto_pagamento,
    composicao_item_eh_dinheiro,
    montar_composicao_pagamento,
    processar_checkout_agrupado,
)
from estoque.models import VendaRapidaEstoque

from ..forms import PagamentoForm
from ..models import ContaReceber, Pagamento
from .common import caixa_atual
from .helpers import (
    _garantir_formas_pagamento_padrao,
    _log_financeiro,
    _payload_pagamento_normalizado,
    _vincular_talao_itens_ordem,
)


logger = logging.getLogger(__name__)


def _ids_contas(request):
    valores = request.POST.getlist("contas_ids") if request.method == "POST" else []
    if request.method != "POST":
        valores = (request.GET.get("contas") or "").split(",")
    return sorted({int(valor) for valor in valores if str(valor).strip().isdigit()})


def _guia_checkout(empresa, codigo):
    codigo = (codigo or "").strip().upper()
    if not codigo:
        return [], Decimal("0.00"), ""
    vendas = list(
        VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional")
        .filter(
            produto__empresa=empresa,
            guia_pagamento=codigo,
            status="pre_reserva",
        )
        .order_by("id")
    )
    total = sum((Decimal(venda.valor_total or Decimal("0.00")) for venda in vendas), Decimal("0.00"))
    return vendas, total, codigo


def _validar_datas(form, usuario):
    hoje = timezone.localdate()
    competencia = form.cleaned_data.get("data_competencia")
    movimento = form.cleaned_data.get("data_movimento")
    if movimento and movimento > hoje:
        form.add_error("data_movimento", "A data da movimentacao nao pode estar no futuro.")
        return False
    if any(data and data != hoje for data in (competencia, movimento)) and not has_sensitive_permission(
        usuario, "perm_caixa_lancamento_retroativo"
    ):
        form.add_error(None, "Voce nao tem permissao para registrar este checkout em outra data.")
        return False
    return True


@role_required(CAIXA_OPERATIONAL_ROLES)
def checkout_agrupado(request):
    empresa = obter_empresa_ativa(request, strict=False)
    _garantir_formas_pagamento_padrao(empresa)
    caixa = caixa_atual(empresa)
    if not caixa:
        return redirect("caixa:abrir_caixa")

    filtro_empresa = {"empresa": empresa} if empresa is not None else {"empresa__isnull": True}
    contas_disponiveis = (
        ContaReceber.objects.filter(
            **filtro_empresa,
            tipo_origem="cliente_os",
            status__in=["aberta", "parcial", "vencida"],
            valor_aberto__gt=0,
            ordem_servico__isnull=False,
        )
        .select_related("ordem_servico", "ordem_servico__cliente")
        .order_by("cliente_nome", "vencimento", "id")
    )
    busca = (request.GET.get("q") or "").strip()
    if busca:
        contas_disponiveis = contas_disponiveis.filter(
            Q(cliente_nome__icontains=busca)
            | Q(ordem_servico__numero_os__icontains=busca)
            | Q(ordem_servico__cliente__documento__icontains=busca)
            | Q(ordem_servico__cliente__telefone__icontains=busca)
            | Q(ordem_servico__tipo_equipamento__icontains=busca)
        )

    contas_ids = _ids_contas(request)
    contas_selecionadas = list(contas_disponiveis.filter(id__in=contas_ids).order_by("id"))
    guia_informada = request.POST.get("guia_codigo") if request.method == "POST" else request.GET.get("guia")
    vendas_guia, total_guia, guia_codigo = _guia_checkout(empresa, guia_informada)
    erro_guia = ""
    if guia_informada and not vendas_guia:
        erro_guia = "Guia nao encontrada, ja recebida ou cancelada."

    total_contas = sum(
        (Decimal(conta.valor_aberto or Decimal("0.00")) for conta in contas_selecionadas),
        Decimal("0.00"),
    )
    total_bruto = total_contas + total_guia
    pagamento_sucesso = None
    sucesso_id = (request.GET.get("sucesso") or "").strip()
    if sucesso_id.isdigit():
        pagamento_sucesso = Pagamento.objects.filter(**filtro_empresa, pk=int(sucesso_id)).first()

    cliente = contas_selecionadas[0].ordem_servico.cliente if contas_selecionadas else None
    initial = {
        "valor": total_bruto if total_bruto > 0 else None,
        "cliente_nome": getattr(cliente, "nome", "") or "",
        "cliente_documento": getattr(cliente, "documento", "") or "",
        "cliente_telefone": getattr(cliente, "telefone", "") or "",
    }
    form = PagamentoForm(empresa=empresa, initial=initial)

    if request.method == "POST":
        form = PagamentoForm(_payload_pagamento_normalizado(request), empresa=empresa)
        if not contas_selecionadas and not vendas_guia:
            form.add_error(None, "Selecione ao menos uma OS ou carregue uma guia de acessorios.")
        clientes_ids = {
            conta.ordem_servico.cliente_id
            for conta in contas_selecionadas
            if conta.ordem_servico_id and conta.ordem_servico.cliente_id
        }
        if len(clientes_ids) > 1:
            form.add_error(None, "As OS do checkout precisam pertencer ao mesmo cliente.")
        if erro_guia:
            form.add_error(None, erro_guia)

        if form.is_valid() and _validar_datas(form, request.user):
            valor_informado = Decimal(form.cleaned_data.get("valor") or Decimal("0.00"))
            if valor_informado != total_bruto:
                form.add_error("valor", "O total mudou. Confira novamente as OS e a guia antes de receber.")
            desconto_aplicado, valor_liquido = calcular_desconto_pagamento(
                valor_bruto=total_bruto,
                desconto_valor=form.cleaned_data.get("desconto_valor") or Decimal("0.00"),
                desconto_percentual=form.cleaned_data.get("desconto_percentual") or Decimal("0.00"),
            )
            if desconto_aplicado > Decimal("0.00"):
                try:
                    require_sensitive_permission(
                        request.user,
                        "perm_caixa_aplicar_desconto",
                        message="Voce nao tem permissao para aplicar desconto no checkout.",
                    )
                except PermissionDenied as exc:
                    form.add_error("desconto_valor", str(exc) or "Permissao insuficiente.")
                config_antifraude = ConfiguracaoSistema.get_configuracao()
                percentual_desconto = (
                    desconto_aplicado / total_bruto * Decimal("100.00")
                    if total_bruto > Decimal("0.00")
                    else Decimal("0.00")
                )
                limiar = Decimal(str(config_antifraude.antifraude_desconto_critico_percentual or 0))
                if (
                    limiar > Decimal("0.00")
                    and percentual_desconto >= limiar
                    and config_antifraude.antifraude_exigir_dupla_confirmacao_desconto
                ):
                    confirmado = request.POST.get("confirmar_desconto_critico") == "1"
                    justificativa = (request.POST.get("justificativa_desconto_critico") or "").strip()
                    minimo = int(config_antifraude.antifraude_motivo_minimo_caracteres or 12)
                    if not confirmado:
                        form.add_error(None, "Desconto critico exige confirmacao adicional.")
                    if len(justificativa) < minimo:
                        form.add_error(
                            "observacao",
                            f"Justifique o desconto critico com pelo menos {minimo} caracteres.",
                        )
            if valor_liquido <= Decimal("0.00"):
                form.add_error("desconto_valor", "O desconto nao pode zerar o checkout.")

            forma_principal = form.cleaned_data.get("forma_pagamento")
            forma_secundaria = form.cleaned_data.get("forma_pagamento_secundaria")
            try:
                composicao = montar_composicao_pagamento(
                    forma_principal=forma_principal,
                    referencia_principal=form.cleaned_data.get("referencia") or "",
                    valor_total_liquido=valor_liquido,
                    parcelas_principal=form.cleaned_data.get("parcelas_principal") or 1,
                    bandeira_principal=form.cleaned_data.get("bandeira_principal") or "",
                    forma_secundaria=forma_secundaria,
                    valor_secundario=form.cleaned_data.get("valor_secundario") or Decimal("0.00"),
                    referencia_secundaria=form.cleaned_data.get("referencia_secundaria") or "",
                    parcelas_secundaria=form.cleaned_data.get("parcelas_secundaria") or 1,
                    bandeira_secundaria=form.cleaned_data.get("bandeira_secundaria") or "",
                )
            except ValueError as exc:
                composicao = []
                form.add_error(None, str(exc))

            valor_dinheiro = sum(
                (
                    Decimal(str(item.get("valor") or 0))
                    for item in composicao
                    if composicao_item_eh_dinheiro(item)
                ),
                Decimal("0.00"),
            )
            valor_recebido = form.cleaned_data.get("valor_recebido")
            if valor_dinheiro > 0 and valor_recebido is None:
                form.add_error("valor_recebido", "Informe o valor recebido em dinheiro para calcular o troco.")
            elif valor_dinheiro > 0 and valor_recebido < valor_dinheiro:
                form.add_error("valor_recebido", "O dinheiro recebido nao pode ser menor que a parcela em dinheiro.")

            if not form.errors:
                chave = (form.cleaned_data.get("chave_idempotencia") or "").strip()
                existente = Pagamento.objects.filter(chave_idempotencia=chave).first() if chave else None
                if existente:
                    return redirect(f"{reverse('caixa:checkout_agrupado')}?sucesso={existente.pk}")
                try:
                    pagamento = processar_checkout_agrupado(
                        form=form,
                        caixa=caixa,
                        contas=contas_selecionadas,
                        vendas_guia=vendas_guia,
                        guia_codigo=guia_codigo,
                        desconto_aplicado=desconto_aplicado,
                        desconto_percentual=form.cleaned_data.get("desconto_percentual") or Decimal("0.00"),
                        composicao_pagamento=composicao,
                        valor_recebido_dinheiro=valor_recebido,
                        chave_idempotencia=chave,
                        usuario=request.user,
                        vincular_talao_cb=_vincular_talao_itens_ordem,
                        log_financeiro_cb=_log_financeiro,
                        processar_evento_servico_finalizado_cb=processar_evento_servico_finalizado,
                        processar_evento_retirada_cliente_cb=processar_evento_retirada_cliente,
                        processar_evento_venda_mostrador_cb=processar_evento_venda_mostrador,
                    )
                except (ValueError, IntegrityError) as exc:
                    logger.warning("checkout_agrupado_falha", exc_info=True)
                    form.add_error(None, str(exc) or "Nao foi possivel concluir o checkout.")
                else:
                    messages.success(request, "Checkout agrupado concluido com sucesso.")
                    return redirect(f"{reverse('caixa:checkout_agrupado')}?sucesso={pagamento.pk}")

    config = ConfiguracaoSistema.get_configuracao()
    return render(
        request,
        "caixa/checkout_agrupado.html",
        {
            "form": form,
            "caixa": caixa,
            "contas_disponiveis": contas_disponiveis[:250],
            "contas_selecionadas_ids": {conta.id for conta in contas_selecionadas},
            "contas_selecionadas": contas_selecionadas,
            "vendas_guia": vendas_guia,
            "guia_codigo": guia_codigo,
            "erro_guia": erro_guia,
            "total_contas": total_contas,
            "total_guia": total_guia,
            "total_bruto": total_bruto,
            "busca": busca,
            "pagamento_sucesso": pagamento_sucesso,
            "pode_aplicar_desconto": has_sensitive_permission(request.user, "perm_caixa_aplicar_desconto"),
            "antifraude_config": config,
            "menu_app": "caixa",
            "menu_sub": "checkout_agrupado",
        },
    )


__all__ = ["checkout_agrupado"]
