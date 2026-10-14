import logging
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
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
    estornar_origem_checkout,
    montar_composicao_pagamento,
    processar_checkout_agrupado,
)
from estoque.models import PontoOperacional, Produto, VendaRapidaEstoque
from estoque.services import (
    criar_item_cesto_venda_rapida,
    gerar_codigo_guia_venda_rapida,
    remover_item_cesto_venda_rapida,
)

from ..forms import PagamentoForm
from ..models import CheckoutRascunho, ContaReceber, FormaPagamento, Pagamento
from .common import caixa_atual
from .helpers import (
    _garantir_formas_pagamento_padrao,
    _log_financeiro,
    _payload_pagamento_normalizado,
    _vincular_talao_itens_ordem,
)


logger = logging.getLogger(__name__)


def _ids_contas(request, rascunho=None):
    valores = request.POST.getlist("contas_ids") if request.method == "POST" else []
    if request.method != "POST":
        valores = (request.GET.get("contas") or "").split(",")
        if not any(str(valor).strip() for valor in valores) and rascunho:
            valores = rascunho.contas_ids or []
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


def _valores_contas_checkout(request, contas, rascunho=None):
    valores = {}
    for conta in contas:
        chave = f"conta_valor_{conta.pk}"
        bruto = request.POST.get(chave) if request.method == "POST" else request.GET.get(chave)
        if bruto in (None, "") and rascunho:
            bruto = (rascunho.valores_contas or {}).get(str(conta.pk))
        if bruto in (None, ""):
            valores[conta.pk] = Decimal(conta.valor_aberto or Decimal("0.00"))
            continue
        try:
            valores[conta.pk] = Decimal(str(bruto).replace(",", ".")).quantize(Decimal("0.01"))
        except Exception:
            valores[conta.pk] = Decimal("0.00")
    return valores


def _url_checkout(*, contas_ids=None, valores_contas=None, guia="", rascunho_id=None, extra=None):
    parametros = []
    contas_ids = contas_ids or []
    if contas_ids:
        parametros.append(("contas", ",".join(str(item) for item in contas_ids)))
    for conta_id, valor in (valores_contas or {}).items():
        parametros.append((f"conta_valor_{conta_id}", f"{Decimal(valor):.2f}"))
    if guia:
        parametros.append(("guia", guia))
    if rascunho_id:
        parametros.append(("rascunho", str(rascunho_id)))
    parametros.extend((extra or {}).items())
    base = reverse("caixa:checkout_agrupado")
    return f"{base}?{urlencode(parametros)}" if parametros else base


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
def checkout_previsao_taxas(request):
    empresa = obter_empresa_ativa(request, strict=False)
    try:
        valor = Decimal(str(request.GET.get("valor") or "0").replace(",", "."))
        parcelas = max(1, int(request.GET.get("parcelas") or 1))
        forma_id = int(request.GET.get("forma") or 0)
        data_referencia = date.fromisoformat(request.GET.get("data") or str(timezone.localdate()))
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "erro": "Dados inválidos para calcular a taxa."}, status=400)
    formas = FormaPagamento.objects.filter(pk=forma_id, ativa=True)
    formas = formas.filter(Q(empresa=empresa) | Q(empresa__isnull=True)) if empresa else formas.filter(empresa__isnull=True)
    forma = formas.first()
    if not forma or valor <= Decimal("0.00"):
        return JsonResponse({"ok": True, "taxa": 0, "liquido": float(max(valor, Decimal("0.00"))), "dias": 0, "data_prevista": ""})
    condicao = forma.obter_condicao_vigente(
        data_referencia=data_referencia,
        parcelas=parcelas,
        bandeira=request.GET.get("bandeira") or "",
    )
    percentual = Decimal(str(condicao.get("taxa_percentual") or 0))
    fixa = Decimal(str(condicao.get("taxa_fixa") or 0))
    taxa = ((valor * percentual / Decimal("100")) + fixa).quantize(Decimal("0.01"))
    dias = int(condicao.get("dias_recebimento") or 0)
    prevista = data_referencia + timedelta(days=dias)
    return JsonResponse(
        {
            "ok": True,
            "taxa": float(taxa),
            "liquido": float(max(Decimal("0.00"), valor - taxa)),
            "dias": dias,
            "data_prevista": prevista.strftime("%d/%m/%Y"),
            "fonte": condicao.get("fonte") or "forma_pagamento",
        }
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def checkout_estornar_origem(request, pagamento_id, indice_origem):
    require_sensitive_permission(
        request.user,
        "perm_caixa_excluir_pagamento",
        message="Você não tem permissão para estornar origens de um checkout.",
    )
    empresa = obter_empresa_ativa(request, strict=False)
    filtro_empresa = {"empresa": empresa} if empresa is not None else {"empresa__isnull": True}
    pagamento = get_object_or_404(Pagamento, pk=pagamento_id, **filtro_empresa)
    if request.method != "POST":
        return redirect(f"{reverse('caixa:checkout_agrupado')}?sucesso={pagamento.pk}")
    try:
        estornar_origem_checkout(
            pagamento=pagamento,
            indice_origem=indice_origem,
            usuario=request.user,
            motivo=request.POST.get("motivo_estorno") or "",
            reabrir_cobranca=request.POST.get("reabrir_cobranca") == "1",
        )
        messages.success(request, "Origem estornada com contrapartida financeira e trilha de auditoria.")
    except (ValueError, IntegrityError) as exc:
        messages.error(request, str(exc) or "Não foi possível estornar esta origem.")
    return redirect(f"{reverse('caixa:checkout_agrupado')}?sucesso={pagamento.pk}")


@role_required(CAIXA_OPERATIONAL_ROLES)
def checkout_agrupado(request):
    empresa = obter_empresa_ativa(request, strict=False)
    _garantir_formas_pagamento_padrao(empresa)
    caixa = caixa_atual(empresa)
    if not caixa:
        return redirect("caixa:abrir_caixa")

    filtro_empresa = {"empresa": empresa} if empresa is not None else {"empresa__isnull": True}
    rascunho = None
    rascunho_id = (request.POST.get("rascunho_id") if request.method == "POST" else request.GET.get("rascunho")) or ""
    if empresa is not None and str(rascunho_id).isdigit():
        rascunho = CheckoutRascunho.objects.filter(
            pk=int(rascunho_id), empresa=empresa, status="ativo"
        ).first()
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

    contas_ids = _ids_contas(request, rascunho=rascunho)
    contas_selecionadas = list(contas_disponiveis.filter(id__in=contas_ids).order_by("id"))
    valores_contas = _valores_contas_checkout(request, contas_selecionadas, rascunho=rascunho)
    guia_informada = request.POST.get("guia_codigo") if request.method == "POST" else request.GET.get("guia")
    if not guia_informada and rascunho:
        guia_informada = rascunho.guia_codigo
    vendas_guia, total_guia, guia_codigo = _guia_checkout(empresa, guia_informada)
    erro_guia = ""
    if guia_informada and not vendas_guia:
        erro_guia = "Guia nao encontrada, ja recebida ou cancelada."

    total_contas = sum(
        (Decimal(valores_contas.get(conta.pk) or Decimal("0.00")) for conta in contas_selecionadas),
        Decimal("0.00"),
    )
    total_bruto = total_contas + total_guia

    if request.method == "POST" and request.POST.get("remover_venda_id"):
        venda = get_object_or_404(
            VendaRapidaEstoque.objects.select_related("produto"),
            pk=request.POST.get("remover_venda_id"),
            produto__empresa=empresa,
            status="pre_reserva",
            guia_pagamento=guia_codigo,
        )
        remover_item_cesto_venda_rapida(venda, cesto_codigo=venda.cesto_codigo)
        messages.success(request, f"{venda.produto.nome} removido do checkout.")
        return redirect(
            _url_checkout(
                contas_ids=contas_ids,
                valores_contas=valores_contas,
                guia=guia_codigo,
                rascunho_id=getattr(rascunho, "pk", None),
            )
        )

    acao = (request.POST.get("acao") or "").strip() if request.method == "POST" else ""
    if acao == "adicionar_produto":
        try:
            produto = Produto.objects.get(pk=request.POST.get("produto_id"), empresa=empresa, ativo=True)
            ponto = PontoOperacional.objects.get(
                pk=request.POST.get("ponto_id") or produto.ponto_operacional_id,
                empresa=empresa,
                ativo=True,
            )
            resultado_item = criar_item_cesto_venda_rapida(
                produto=produto,
                ponto_operacional=ponto,
                quantidade=request.POST.get("produto_quantidade") or 1,
                funcionario_numero=(request.POST.get("funcionario_numero") or getattr(request.user, "numero_vendedor", "")),
                usuario=request.user,
            )
            venda_nova = resultado_item["venda"]
            guia_codigo = guia_codigo or gerar_codigo_guia_venda_rapida()
            venda_nova.guia_pagamento = guia_codigo
            venda_nova.save(update_fields=["guia_pagamento"])
            messages.success(request, f"{produto.nome} adicionado ao checkout.")
        except (Produto.DoesNotExist, PontoOperacional.DoesNotExist):
            messages.error(request, "Produto ou ponto de estoque não encontrado para esta empresa.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect(
            _url_checkout(
                contas_ids=contas_ids,
                valores_contas=valores_contas,
                guia=guia_codigo,
                rascunho_id=getattr(rascunho, "pk", None),
            )
        )

    if acao == "salvar_rascunho" and empresa is not None:
        dados_pagamento = {
            chave: request.POST.get(chave) or ""
            for chave in (
                "forma_pagamento", "parcelas_principal", "bandeira_principal",
                "desconto_valor", "desconto_percentual", "valor_recebido",
                "forma_pagamento_secundaria", "valor_secundario", "referencia_secundaria",
                "parcelas_secundaria", "bandeira_secundaria", "referencia",
                "data_competencia", "data_movimento", "observacao", "cliente_nome",
                "cliente_documento", "cliente_telefone", "cliente",
            )
        }
        nome_rascunho = (request.POST.get("nome_rascunho") or "").strip()
        if not nome_rascunho:
            cliente_nome = contas_selecionadas[0].cliente_nome if contas_selecionadas else "Venda de balcão"
            nome_rascunho = f"{cliente_nome} · {timezone.localtime():%d/%m %H:%M}"
        if rascunho:
            rascunho.nome = nome_rascunho[:120]
            rascunho.contas_ids = contas_ids
            rascunho.valores_contas = {str(pk): str(valor) for pk, valor in valores_contas.items()}
            rascunho.guia_codigo = guia_codigo
            rascunho.dados_pagamento = dados_pagamento
            rascunho.save()
        else:
            rascunho = CheckoutRascunho.objects.create(
                empresa=empresa,
                criado_por=request.user,
                nome=nome_rascunho[:120],
                contas_ids=contas_ids,
                valores_contas={str(pk): str(valor) for pk, valor in valores_contas.items()},
                guia_codigo=guia_codigo,
                dados_pagamento=dados_pagamento,
            )
        messages.success(request, "Checkout salvo como rascunho.")
        return redirect(_url_checkout(rascunho_id=rascunho.pk))

    if request.method == "POST" and request.POST.get("excluir_rascunho_id") and empresa is not None:
        CheckoutRascunho.objects.filter(
            pk=request.POST.get("excluir_rascunho_id"), empresa=empresa, status="ativo"
        ).update(status="cancelado")
        messages.success(request, "Rascunho removido.")
        return redirect("caixa:checkout_agrupado")
    pagamento_sucesso = None
    sucesso_id = (request.GET.get("sucesso") or "").strip()
    if sucesso_id.isdigit():
        pagamento_sucesso = Pagamento.objects.filter(**filtro_empresa, pk=int(sucesso_id)).first()

    cliente = contas_selecionadas[0].ordem_servico.cliente if contas_selecionadas else None
    initial = {
        "cliente": getattr(cliente, "pk", None),
        "valor": total_bruto if total_bruto > 0 else None,
        "cliente_nome": getattr(cliente, "nome", "") or "",
        "cliente_documento": getattr(cliente, "documento", "") or "",
        "cliente_telefone": getattr(cliente, "telefone", "") or "",
    }
    if rascunho:
        initial.update({chave: valor for chave, valor in (rascunho.dados_pagamento or {}).items() if valor not in (None, "")})
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
        for conta in contas_selecionadas:
            valor_conta = Decimal(valores_contas.get(conta.pk) or Decimal("0.00"))
            saldo_conta = Decimal(conta.valor_aberto or Decimal("0.00"))
            if valor_conta <= Decimal("0.00"):
                form.add_error(None, f"Informe um valor maior que zero para {conta.ordem_servico.numero_os}.")
            elif valor_conta > saldo_conta:
                form.add_error(
                    None,
                    f"O valor de {conta.ordem_servico.numero_os} supera o saldo aberto de R$ {saldo_conta:.2f}.",
                )
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
                        valores_contas=valores_contas,
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
                    if rascunho:
                        rascunho.status = "concluido"
                        rascunho.save(update_fields=["status", "atualizado_em"])
                    messages.success(request, "Checkout agrupado concluido com sucesso.")
                    return redirect(f"{reverse('caixa:checkout_agrupado')}?sucesso={pagamento.pk}")

    contas_lista = list(contas_disponiveis[:250])
    for conta_item in contas_lista:
        conta_item.valor_checkout = valores_contas.get(
            conta_item.pk,
            Decimal(conta_item.valor_aberto or Decimal("0.00")),
        )

    config = ConfiguracaoSistema.get_configuracao()
    pontos_checkout = PontoOperacional.objects.filter(empresa=empresa, ativo=True).order_by("codigo") if empresa else []
    rascunhos_recentes = (
        CheckoutRascunho.objects.filter(empresa=empresa, status="ativo").select_related("criado_por")[:10]
        if empresa else []
    )
    return render(
        request,
        "caixa/checkout_agrupado.html",
        {
            "form": form,
            "caixa": caixa,
            "contas_disponiveis": contas_lista,
            "contas_selecionadas_ids": {conta.id for conta in contas_selecionadas},
            "contas_selecionadas": contas_selecionadas,
            "valores_contas": valores_contas,
            "vendas_guia": vendas_guia,
            "guia_codigo": guia_codigo,
            "erro_guia": erro_guia,
            "total_contas": total_contas,
            "total_guia": total_guia,
            "total_bruto": total_bruto,
            "busca": busca,
            "pagamento_sucesso": pagamento_sucesso,
            "rascunho": rascunho,
            "rascunhos_recentes": rascunhos_recentes,
            "pontos_checkout": pontos_checkout,
            "funcionario_numero": getattr(request.user, "numero_vendedor", "") or "",
            "pode_aplicar_desconto": has_sensitive_permission(request.user, "perm_caixa_aplicar_desconto"),
            "pode_estornar_origem": has_sensitive_permission(request.user, "perm_caixa_excluir_pagamento"),
            "antifraude_config": config,
            "menu_app": "caixa",
            "menu_sub": "checkout_agrupado",
        },
    )


__all__ = ["checkout_agrupado", "checkout_estornar_origem", "checkout_previsao_taxas"]
