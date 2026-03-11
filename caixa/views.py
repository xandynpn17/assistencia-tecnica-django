from decimal import Decimal
from calendar import monthrange
from datetime import date, timedelta
import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, CAIXA_OPERATIONAL_ROLES, has_role, role_required
from configuracoes.models import ConfiguracaoSistema, Empresa, FornecedorGarantia, MarcaGarantia, RegraGarantiaMarca
from ordens.models import OrdemServico

from .forms import (
    BaixaContaReceberForm,
    CategoriaFinanceiraForm,
    CentroCustoForm,
    ComissaoItemOrcamentoForm,
    ComissaoTecnicoForm,
    ContaPagarForm,
    ContaReceberForm,
    DespesaRecorrenteForm,
    FaixaPremioMetaForm,
    FormaPagamentoForm,
    LancamentoCaixaForm,
    PagamentoContaPagarForm,
    PagamentoForm,
    RegraPremioMetaForm,
    RegraComissaoTecnicoForm,
)
from .models import (
    AuditoriaFinanceira,
    AuditoriaGarantia,
    Caixa,
    Comissao,
    ComissaoItemOrcamento,
    ComissaoTecnico,
    CategoriaFinanceira,
    CentroCusto,
    ContaPagar,
    ContaReceber,
    DespesaRecorrente,
    FaixaPremioMeta,
    FormaPagamento,
    LancamentoCaixa,
    Pagamento,
    PagamentoContaPagar,
    PremioColaboradorCompetencia,
    RegraPremioMeta,
    RegraComissaoTecnico,
    RecebimentoConta,
)
from configuracoes.permissions import PERFORMANCE_VIEW_ROLES
from caixa.services.comissoes import (
    processar_evento_retirada_cliente,
    processar_evento_servico_finalizado,
    recalcular_comissoes_servico_finalizado,
)
from caixa.services.comissao_status import ComissaoStatusError, aplicar_acao_comissao


def caixa_atual():
    return Caixa.objects.filter(aberto=True).last()


def _redirect_pos_operacao(request, fallback_route):
    if has_role(request.user, CAIXA_FINANCIAL_ROLES):
        return redirect("caixa:dashboard_caixa")
    return redirect(fallback_route)


def _log_financeiro(evento, usuario, conta=None, pagamento=None, valor=None, descricao=""):
    AuditoriaFinanceira.objects.create(
        evento=evento,
        usuario=usuario,
        conta=conta,
        pagamento=pagamento,
        valor=valor,
        descricao=descricao,
    )


def _forma_pagamento_por_codigo(codigo):
    return FormaPagamento.objects.filter(codigo=codigo, ativa=True).first()


def _garantir_formas_pagamento_padrao():
    defaults = [
        {"nome": "Dinheiro", "codigo": "dinheiro", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 0, "ativa": True},
        {"nome": "PIX", "codigo": "pix", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 0, "ativa": True},
        {"nome": "Cartao Credito", "codigo": "cartao_credito", "tipo": "aprazo", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 30, "ativa": True},
        {"nome": "Cartao Debito", "codigo": "cartao_debito", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 1, "ativa": True},
        {"nome": "Transferencia", "codigo": "transferencia", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 0, "ativa": True},
        {"nome": "Garantia Fabricante", "codigo": "garantia_fabricante", "tipo": "aprazo", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 30, "ativa": True},
        {"nome": "Custo da Loja", "codigo": "loja", "tipo": "avista", "taxa_percentual": Decimal("0.00"), "dias_recebimento": 0, "ativa": True},
    ]
    for row in defaults:
        FormaPagamento.objects.get_or_create(codigo=row["codigo"], defaults=row)


def _forma_pagamento_padrao():
    return FormaPagamento.objects.filter(ativa=True).order_by("nome").first()


def _resolver_forma_pagamento_codigo_legacy(codigo):
    if not codigo:
        return _forma_pagamento_padrao()
    forma = _forma_pagamento_por_codigo(codigo)
    if forma:
        return forma
    mapeamento = {
        "credito": "cartao_credito",
        "debito": "cartao_debito",
    }
    return _forma_pagamento_por_codigo(mapeamento.get(codigo, codigo))


def _payload_pagamento_normalizado(request):
    data = request.POST.copy()
    if not data.get("forma_pagamento"):
        forma = _resolver_forma_pagamento_codigo_legacy(data.get("metodo"))
        if forma:
            data["forma_pagamento"] = str(forma.id)
    return data


def _buscar_ordem_por_numero(texto):
    valor = (texto or "").strip()
    if not valor:
        return None

    termo = valor.upper().replace(" ", "")
    if termo.startswith("OS-"):
        candidatos = [termo]
    elif termo.startswith("OS"):
        candidatos = [termo[:2] + "-" + termo[2:]]
    elif termo.isdigit():
        candidatos = [f"OS-{int(termo):04d}", f"OS-{termo}"]
    else:
        candidatos = [termo]

    for candidato in candidatos:
        ordem = OrdemServico.objects.filter(numero_os__iexact=candidato).first()
        if ordem:
            return ordem
    return OrdemServico.objects.filter(numero_os__icontains=valor).order_by("-id").first()


def _resumo_movimento_caixa(caixa):
    if not caixa:
        return {
            "pagamentos": Pagamento.objects.none(),
            "lancamentos": LancamentoCaixa.objects.none(),
            "entradas_orfas_pagamento": Decimal("0.00"),
            "total_entradas": Decimal("0.00"),
            "total_saidas": Decimal("0.00"),
            "saldo": Decimal("0.00"),
        }

    pagamentos = caixa.pagamentos.all()
    lancamentos = caixa.lancamentos.all()
    total_entradas_lancamentos = sum((l.valor for l in lancamentos if l.tipo == "entrada"), Decimal("0.00"))
    entradas_orfas_pagamento = pagamentos.filter(lancamento_caixa__isnull=True).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas = total_entradas_lancamentos + entradas_orfas_pagamento
    total_saidas = sum((l.valor for l in lancamentos if l.tipo == "saida"), Decimal("0.00"))
    saldo = caixa.saldo_inicial + total_entradas - total_saidas
    return {
        "pagamentos": pagamentos,
        "lancamentos": lancamentos,
        "entradas_orfas_pagamento": entradas_orfas_pagamento,
        "total_entradas": total_entradas,
        "total_saidas": total_saidas,
        "saldo": saldo,
    }


def _vincular_talao_itens_ordem(ordem, numero_talao, pagamento=None):
    if not ordem or not numero_talao:
        return 0
    try:
        from ordens.models import OrdemTalao
    except Exception:
        OrdemTalao = None
    atualizados = 0
    for item in ordem.servicos_pecas.all():
        if item.adicionar_numero_talao(numero_talao):
            item.save(update_fields=["numeros_taloes"])
            atualizados += 1
    if OrdemTalao:
        nomes_itens = [i.nome for i in ordem.servicos_pecas.all()[:3]]
        resumo_itens = ", ".join(nomes_itens) if nomes_itens else "Servicos/Pecas da OS"
        empresa = Empresa.objects.first()
        descricao_auto = (
            f"Recibo referente a OS {ordem.numero_os}. "
            f"Empresa: {empresa.nome if empresa else '-'}."
        )
        talao, created = OrdemTalao.objects.get_or_create(
            ordem=ordem,
            numero=numero_talao,
            defaults={
                "origem": "pagamento",
                "pagamento": pagamento,
                "valor": pagamento.valor if pagamento else None,
                "item_referencia": resumo_itens,
                "descricao": descricao_auto,
            },
        )
        if not created:
            changed = []
            if pagamento and talao.pagamento_id != pagamento.id:
                talao.pagamento = pagamento
                changed.append("pagamento")
            if pagamento and talao.valor != pagamento.valor:
                talao.valor = pagamento.valor
                changed.append("valor")
            if not talao.item_referencia:
                talao.item_referencia = resumo_itens
                changed.append("item_referencia")
            if not talao.descricao:
                talao.descricao = descricao_auto
                changed.append("descricao")
            if changed:
                talao.save(update_fields=changed)
    return atualizados


def _garantir_conta_os(ordem, ignorar_pagamento_id=None):
    total_os = sum((item.total() for item in ordem.servicos_pecas.all()), Decimal("0.00"))
    pagamentos_qs = Pagamento.objects.filter(ordem_servico=ordem)
    if ignorar_pagamento_id:
        pagamentos_qs = pagamentos_qs.exclude(id=ignorar_pagamento_id)
    total_pago = sum((pag.valor for pag in pagamentos_qs), Decimal("0.00"))
    valor_aberto = max(Decimal("0.00"), total_os - total_pago)
    if total_os <= Decimal("0.00"):
        contas_existentes = ContaReceber.objects.filter(
            ordem_servico=ordem,
            tipo_origem="cliente_os",
            status__in=["aberta", "parcial", "vencida"],
        )
        for conta_existente in contas_existentes:
            conta_existente.valor_aberto = Decimal("0.00")
            conta_existente.atualizar_status_automatico()
            conta_existente.save(update_fields=["valor_aberto", "status", "atualizado_em"])
        return None

    conta = (
        ContaReceber.objects.filter(
            ordem_servico=ordem,
            tipo_origem="cliente_os",
            status__in=["aberta", "parcial", "vencida"],
        )
        .order_by("-id")
        .first()
    )
    if not conta:
        conta = ContaReceber.objects.create(
            ordem_servico=ordem,
            descricao=f"OS {ordem.numero_os}",
            tipo_origem="cliente_os",
            cliente_nome=ordem.cliente.nome,
            valor_original=total_os,
            valor_aberto=valor_aberto,
            vencimento=timezone.localdate(),
        )
    else:
        conta.valor_original = total_os
        conta.valor_aberto = valor_aberto
        conta.tipo_origem = "cliente_os"
    conta.atualizar_status_automatico()
    conta.save()
    return conta


def _garantir_conta_garantia(ordem, dados_garantia=None, ignorar_pagamento_id=None):
    if not ordem or ordem.tipo_reparo != "Garantia":
        return None
    dados = dados_garantia or _dados_garantia_ordem(ordem)
    if not dados:
        return None

    categoria, _ = CategoriaFinanceira.objects.get_or_create(
        nome="Garantia Fabricante",
        defaults={"tipo": "receber", "ativa": True},
    )
    if categoria.tipo != "receber":
        categoria.tipo = "receber"
        categoria.ativa = True
        categoria.save(update_fields=["tipo", "ativa"])

    valor_previsto = Decimal(dados.get("valor_previsto_fabricante") or Decimal("0.00"))
    pagamentos_qs = Pagamento.objects.filter(ordem_servico=ordem).filter(
        Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")
    )
    if ignorar_pagamento_id:
        pagamentos_qs = pagamentos_qs.exclude(id=ignorar_pagamento_id)
    total_pago = sum((p.valor for p in pagamentos_qs), Decimal("0.00"))
    valor_aberto = max(Decimal("0.00"), valor_previsto - total_pago)

    regra = dados.get("regra")
    prazo = int(getattr(regra, "prazo_pagamento_dias", 0) or 0)
    data_base = ordem.data_conclusao.date() if ordem.data_conclusao else timezone.localdate()
    vencimento = data_base + timedelta(days=prazo if prazo > 0 else 30)

    fornecedor = dados.get("fornecedor")
    marca = dados.get("marca")
    cliente_nome = fornecedor.nome if fornecedor else (marca.nome if marca else "Fabricante")
    descricao = f"Garantia fabricante - OS {ordem.numero_os}"

    conta = (
        ContaReceber.objects.filter(ordem_servico=ordem, tipo_origem="garantia_fabricante")
        .order_by("-id")
        .first()
    )
    if not conta:
        conta = ContaReceber.objects.create(
            ordem_servico=ordem,
            categoria=categoria,
            descricao=descricao,
            tipo_origem="garantia_fabricante",
            cliente_nome=cliente_nome,
            valor_original=valor_previsto,
            valor_aberto=valor_aberto,
            vencimento=vencimento,
        )
    else:
        conta.categoria = categoria
        conta.descricao = descricao
        conta.tipo_origem = "garantia_fabricante"
        conta.cliente_nome = cliente_nome
        conta.valor_original = valor_previsto
        conta.valor_aberto = valor_aberto
        conta.vencimento = vencimento
    conta.atualizar_status_automatico()
    conta.save()
    return conta


def _atualizar_status_contas_abertas():
    for conta in ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"]):
        status_anterior = conta.status
        conta.atualizar_status_automatico()
        if conta.status != status_anterior:
            conta.save(update_fields=["status", "valor_aberto", "atualizado_em"])


def _valor_garantia_sugerido(ordem):
    if not ordem or ordem.tipo_reparo != "Garantia":
        return None
    nome_marca = (ordem.marca_equipamento or "").strip()
    if not nome_marca:
        return None
    marca = MarcaGarantia.objects.filter(nome__iexact=nome_marca, ativo=True, parceira_garantia=True).first()
    if marca:
        data_ref = ordem.data_abertura.date() if ordem.data_abertura else timezone.localdate()
        regra = RegraGarantiaMarca.buscar_regra_vigente(marca, ordem.tipo_equipamento, data_ref=data_ref)
        if regra:
            return regra.valor_mao_obra
    return None


def _dados_garantia_ordem(ordem):
    if not ordem or ordem.tipo_reparo != "Garantia":
        return None
    marca = None
    nome_marca = (ordem.marca_equipamento or "").strip()
    if nome_marca:
        marca = MarcaGarantia.objects.filter(nome__iexact=nome_marca, ativo=True, parceira_garantia=True).first()

    if not marca:
        return None

    data_ref = ordem.data_abertura.date() if ordem.data_abertura else timezone.localdate()
    regra = RegraGarantiaMarca.buscar_regra_vigente(marca, ordem.tipo_equipamento, data_ref=data_ref)
    if regra:
        valor_previsto = regra.valor_mao_obra
    else:
        valor_previsto = Decimal(marca.valor_mao_obra_garantia or 0)
        if valor_previsto <= 0:
            return None
    fornecedor = marca.fornecedor if marca else None
    return {
        "fornecedor": fornecedor,
        "marca": marca,
        "regra": regra,
        "valor_previsto_fabricante": valor_previsto,
    }


def _upsert_auditoria_garantia_ordem(ordem):
    dados = _dados_garantia_ordem(ordem)
    if not dados:
        return None

    comissao_prevista = Decimal("0.00")
    tecnico = ordem.tecnico_responsavel
    if tecnico:
        regra_comissao = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
        if regra_comissao and regra_comissao.comissionar_garantia:
            base_servico, base_peca = _base_comissao(ordem)
            comissao_prevista = (base_servico * regra_comissao.percentual_servico / Decimal("100.00"))
            comissao_prevista += (base_peca * regra_comissao.percentual_peca / Decimal("100.00"))

    # Se houver valor tecnico definido na regra de garantia da marca/equipamento, prioriza essa referencia.
    regra_garantia = dados.get("regra")
    if regra_garantia and regra_garantia.valor_mao_obra_tecnico and regra_garantia.valor_mao_obra_tecnico > 0:
        comissao_prevista = regra_garantia.valor_mao_obra_tecnico

    auditoria, _ = AuditoriaGarantia.objects.update_or_create(
        ordem_servico=ordem,
        defaults={
            "fornecedor": dados["fornecedor"],
            "marca": dados["marca"],
            "regra_garantia": dados["regra"],
            "valor_previsto_fabricante": dados["valor_previsto_fabricante"],
            "comissao_prevista_tecnica": comissao_prevista,
        },
    )
    _garantir_conta_garantia(ordem, dados)
    return auditoria


def _base_comissao(ordem):
    base_servico = Decimal("0.00")
    base_peca = Decimal("0.00")
    for item in ordem.servicos_pecas.all():
        total_item = item.total()
        if item.tipo == "servico":
            base_servico += total_item
        else:
            base_peca += total_item
    return base_servico, base_peca


def _ordem_tem_pagamento(ordem):
    return Pagamento.objects.filter(ordem_servico=ordem).exists()


def _ordem_execucao_confirmada(ordem):
    if ordem.status in {"pronto_contactado", "pronto_contactar", "concluida"}:
        return True
    relatorio = (ordem.relatorio_tecnico or "").strip()
    if ordem.status == "autorizado" and relatorio:
        return True
    tipo_reparacao_ok = (ordem.tipo_reparacao or "").strip() in {"substituicao", "reparacao_sem_pecas"}
    return bool(relatorio and tipo_reparacao_ok)


def _ordem_qualifica_para_comissao(ordem, regra):
    if not _ordem_execucao_confirmada(ordem):
        return False

    momento = getattr(regra, "momento_liberacao", "entregue_pago")
    exigir_pagamento = bool(getattr(regra, "exigir_pagamento_para_liberar", True))

    if momento == "pronto_contactado":
        status_ok = ordem.status in {"pronto_contactado", "pronto_contactar", "concluida"} or bool(ordem.fechada)
    else:
        status_ok = ordem.status == "concluida" or bool(ordem.fechada)

    if not status_ok:
        return False
    if exigir_pagamento and not _ordem_tem_pagamento(ordem):
        return False
    return True


def _gerar_comissao_ordem(ordem, considerar_pecas=False):
    tecnico = ordem.tecnico_responsavel
    if not tecnico:
        return None

    regra = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
    if not regra:
        regra = RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )

    if not _ordem_qualifica_para_comissao(ordem, regra):
        return None

    base_servico, base_peca = _base_comissao(ordem)
    valor = (base_servico * regra.percentual_servico / Decimal("100.00"))
    if considerar_pecas:
        valor += (base_peca * regra.percentual_peca / Decimal("100.00"))

    comissao, _ = ComissaoTecnico.objects.update_or_create(
        ordem_servico=ordem,
        tecnico=tecnico,
        considerar_pecas=considerar_pecas,
        defaults={
            "regra": regra,
            "base_servico": base_servico,
            "base_peca": base_peca,
            "valor_comissao": valor,
        },
    )
    return comissao


def _gerar_comissao_item_orcamento(item, modo_pagamento="fechamento"):
    tecnico = item.tecnico_responsavel
    if not tecnico:
        return None

    ordem = item.orcamento.ordem_servico
    if modo_pagamento == "fechamento" and not ordem.fechada:
        return None

    regra = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
    if not regra:
        regra = RegraComissaoTecnico.objects.create(
            usuario=tecnico,
            percentual_servico=Decimal("10.00"),
            percentual_peca=Decimal("0.00"),
            momento_liberacao="pronto_contactado",
            exigir_pagamento_para_liberar=False,
            ativo=True,
        )

    if not _ordem_qualifica_para_comissao(ordem, regra):
        return None
    if item.status != "aprovado":
        return None

    base = Decimal(item.total() or 0)
    tipo_item = (getattr(item, "tipo_item", "") or "").strip()
    if not tipo_item:
        tipo_item = "peca" if item.origem == "estoque" else "servico"
    percentual = regra.percentual_peca if tipo_item == "peca" else regra.percentual_servico
    valor = base * percentual / Decimal("100.00")

    comissao, _ = ComissaoItemOrcamento.objects.update_or_create(
        item_orcamento=item,
        modo_pagamento=modo_pagamento,
        defaults={
            "ordem_servico": ordem,
            "tecnico": tecnico,
            "regra": regra,
            "base_calculo": base,
            "percentual_aplicado": percentual,
            "valor_comissao": valor,
        },
    )
    return comissao


def _competencia_atual():
    hoje = timezone.localdate()
    return date(hoje.year, hoje.month, 1)


def _recalcular_comissoes_itens_antecipado(queryset):
    total = 0
    for item in queryset:
        if _gerar_comissao_item_orcamento(item, modo_pagamento="antecipado"):
            total += 1
    return total


def _recalcular_comissoes_motor_novo(ordens_qs):
    resumo = recalcular_comissoes_servico_finalizado(ordens=ordens_qs, evento="SERVICO_FINALIZADO")
    return resumo["ordens_processadas"], resumo["comissoes_criadas"]


def _data_referencia_ordem(ordem):
    if ordem.data_conclusao:
        return ordem.data_conclusao.date()
    if ordem.data_abertura:
        return ordem.data_abertura.date()
    return None


def _percentuais_padrao_desempenho(tecnico=None):
    config = ConfiguracaoSistema.get_configuracao()
    try:
        percentual_servico = Decimal(str(getattr(config, "percentual_padrao_desempenho_servico", 0) or 0))
    except Exception:
        percentual_servico = Decimal("0.00")
    try:
        percentual_peca = Decimal(str(getattr(config, "percentual_padrao_desempenho_peca", 0) or 0))
    except Exception:
        percentual_peca = Decimal("0.00")

    if not tecnico:
        return max(percentual_servico, Decimal("0.00")), max(percentual_peca, Decimal("0.00"))

    try:
        percentual_usuario_servico = Decimal(str(getattr(tecnico, "percentual_comissao_servico", 0) or 0))
    except Exception:
        percentual_usuario_servico = Decimal("0.00")
    try:
        percentual_usuario_peca = Decimal(str(getattr(tecnico, "percentual_comissao_peca", 0) or 0))
    except Exception:
        percentual_usuario_peca = Decimal("0.00")

    regra = RegraComissaoTecnico.objects.filter(usuario=tecnico, ativo=True).first()
    if percentual_usuario_servico > 0:
        percentual_servico = percentual_usuario_servico
    elif regra:
        percentual_servico = Decimal(str(regra.percentual_servico or 0))

    if percentual_usuario_peca > 0:
        percentual_peca = percentual_usuario_peca
    elif regra:
        percentual_peca = Decimal(str(regra.percentual_peca or 0))

    return max(percentual_servico, Decimal("0.00")), max(percentual_peca, Decimal("0.00"))


def _resumo_produtividade_por_tecnico(*, tecnico_id=None, data_inicio=None, data_fim=None):
    ordens_qs = (
        OrdemServico.objects.select_related("tecnico_responsavel")
        .prefetch_related("servicos_pecas")
        .filter(tecnico_responsavel__isnull=False)
    )
    if tecnico_id and str(tecnico_id).isdigit():
        ordens_qs = ordens_qs.filter(tecnico_responsavel_id=int(tecnico_id))

    resumo_map = {}
    for ordem in ordens_qs:
        if not _ordem_execucao_confirmada(ordem):
            continue
        data_ref = _data_referencia_ordem(ordem)
        if data_inicio and (not data_ref or data_ref < data_inicio):
            continue
        if data_fim and (not data_ref or data_ref > data_fim):
            continue

        tecnico = ordem.tecnico_responsavel
        base_servico, base_peca = _base_comissao(ordem)
        total_ordem = base_servico + base_peca
        row = resumo_map.setdefault(
            tecnico.id,
            {
                "tecnico": tecnico,
                "os_concluidas": 0,
                "total_mao_obra": Decimal("0.00"),
                "total_pecas": Decimal("0.00"),
                "faturamento_total": Decimal("0.00"),
                "ticket_medio": Decimal("0.00"),
            },
        )
        row["os_concluidas"] += 1
        row["total_mao_obra"] += base_servico
        row["total_pecas"] += base_peca
        row["faturamento_total"] += total_ordem

    resumo = list(resumo_map.values())
    for row in resumo:
        if row["os_concluidas"] > 0:
            row["ticket_medio"] = row["faturamento_total"] / Decimal(row["os_concluidas"])

    resumo.sort(key=lambda x: (x["tecnico"].username if x["tecnico"] else ""))
    totais = {
        "os_concluidas": sum((r["os_concluidas"] for r in resumo), 0),
        "total_mao_obra": sum((r["total_mao_obra"] for r in resumo), Decimal("0.00")),
        "total_pecas": sum((r["total_pecas"] for r in resumo), Decimal("0.00")),
        "faturamento_total": sum((r["faturamento_total"] for r in resumo), Decimal("0.00")),
    }
    if totais["os_concluidas"] > 0:
        totais["ticket_medio"] = totais["faturamento_total"] / Decimal(totais["os_concluidas"])
    else:
        totais["ticket_medio"] = Decimal("0.00")
    return resumo, totais


def _periodo_competencia(competencia):
    inicio = date(competencia.year, competencia.month, 1)
    _, ultimo_dia = monthrange(competencia.year, competencia.month)
    fim = date(competencia.year, competencia.month, ultimo_dia)
    return inicio, fim


def _valor_metrica_regra(regra, competencia):
    inicio, fim = _periodo_competencia(competencia)
    pagamentos = Pagamento.objects.filter(data__date__gte=inicio, data__date__lte=fim).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    if regra.metrica == "faturamento_loja":
        return pagamentos
    saidas = LancamentoCaixa.objects.filter(tipo="saida", data__date__gte=inicio, data__date__lte=fim).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    return pagamentos - saidas


def _faixa_para_valor(regra, valor):
    faixas = list(regra.faixas.all())
    for faixa in faixas:
        if valor < faixa.meta_minima:
            continue
        if faixa.meta_maxima is None or valor <= faixa.meta_maxima:
            return faixa
    return None


def _usuarios_alvo_regra(regra):
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    base = user_model.objects.filter(is_active=True)
    if regra.publico == "tecnico":
        return base.filter(tipo_usuario="tecnico")
    if regra.publico == "atendente":
        return base.filter(tipo_usuario="atendente")
    return base.filter(tipo_usuario__in=["tecnico", "atendente"])


def _recalcular_premios_competencia(competencia):
    total = 0
    for regra in RegraPremioMeta.objects.filter(ativo=True).prefetch_related("faixas"):
        valor_metrica = _valor_metrica_regra(regra, competencia)
        faixa = _faixa_para_valor(regra, valor_metrica)
        premio_valor = faixa.premio_valor if faixa else Decimal("0.00")
        percentual = Decimal("0.00")
        if regra.meta_alvo and regra.meta_alvo > 0:
            percentual = (valor_metrica / regra.meta_alvo) * Decimal("100.00")
        for colaborador in _usuarios_alvo_regra(regra):
            PremioColaboradorCompetencia.objects.update_or_create(
                colaborador=colaborador,
                regra=regra,
                competencia=competencia,
                defaults={
                    "faixa": faixa,
                    "valor_metrica": valor_metrica,
                    "percentual_atingimento": percentual,
                    "premio_valor": premio_valor,
                    "observacao": "Atualizado automaticamente",
                },
            )
            total += 1
    return total


@role_required(CAIXA_FINANCIAL_ROLES)
def dashboard_caixa(request):
    _atualizar_status_contas_abertas()
    caixa = caixa_atual()
    resumo_caixa = _resumo_movimento_caixa(caixa)
    pagamentos = resumo_caixa["pagamentos"]
    lancamentos = resumo_caixa["lancamentos"]
    total_entradas = resumo_caixa["total_entradas"]
    total_saidas = resumo_caixa["total_saidas"]
    saldo = resumo_caixa["saldo"]

    contas_abertas = ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"])
    a_receber_total = contas_abertas.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    vencidas_total = contas_abertas.filter(vencimento__lt=timezone.localdate()).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    a_receber_garantia = contas_abertas.filter(tipo_origem="garantia_fabricante").aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    a_receber_cliente = max(Decimal("0.00"), a_receber_total - a_receber_garantia)
    contas_prontas_sem_recebimento = contas_abertas.filter(
        tipo_origem="cliente_os",
        ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
    )
    prontas_sem_recebimento_total = (
        contas_prontas_sem_recebimento.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    )
    prontas_sem_recebimento_qtd = contas_prontas_sem_recebimento.count()
    receita_garantia = (
        pagamentos.filter(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"]
        if caixa
        else Decimal("0.00")
    ) or Decimal("0.00")
    receita_cliente = (
        pagamentos.exclude(Q(forma_pagamento__codigo="garantia_fabricante") | Q(metodo="garantia_fabricante")).aggregate(total=Sum("valor"))["total"]
        if caixa
        else Decimal("0.00")
    ) or Decimal("0.00")

    return render(
        request,
        "caixa/dashboard_caixa.html",
        {
            "caixa": caixa,
            "pagamentos": pagamentos,
            "lancamentos": lancamentos,
            "total_entradas": total_entradas,
            "total_saidas": total_saidas,
            "saldo": saldo,
            "a_receber_total": a_receber_total,
            "a_receber_cliente": a_receber_cliente,
            "a_receber_garantia": a_receber_garantia,
            "prontas_sem_recebimento_total": prontas_sem_recebimento_total,
            "prontas_sem_recebimento_qtd": prontas_sem_recebimento_qtd,
            "receita_cliente": receita_cliente,
            "receita_garantia": receita_garantia,
            "vencidas_total": vencidas_total,
            "menu_app": "caixa",
            "menu_sub": "dashboard_caixa",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def abrir_caixa(request):
    caixa = caixa_atual()
    if caixa:
        return render(
            request,
            "caixa/abrir_caixa.html",
            {
                "caixa": caixa,
                "mensagem": "O caixa ja esta aberto.",
                "menu_app": "caixa",
                "menu_sub": "abrir_caixa",
            },
        )

    if request.method == "POST":
        saldo_inicial = Decimal(str(request.POST.get("saldo_inicial", 0) or 0))
        novo_caixa = Caixa.objects.create(saldo_inicial=saldo_inicial, aberto=True)
        _log_financeiro("caixa_aberto", request.user, valor=saldo_inicial, descricao=f"Caixa #{novo_caixa.id}")
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    return render(
        request,
        "caixa/abrir_caixa.html",
        {"caixa": None, "mensagem": "", "menu_app": "caixa", "menu_sub": "abrir_caixa"},
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def fechar_caixa(request):
    caixa = caixa_atual()
    if not caixa:
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    resumo_caixa = _resumo_movimento_caixa(caixa)
    total_entradas = resumo_caixa["total_entradas"]
    total_saidas = resumo_caixa["total_saidas"]
    saldo_atual = resumo_caixa["saldo"]

    if request.method == "POST":
        valor_contado = Decimal(str(request.POST.get("valor_contado_fisico", saldo_atual) or saldo_atual))
        diferenca = valor_contado - saldo_atual
        justificativa = (request.POST.get("justificativa_diferenca") or "").strip()
        if diferenca != Decimal("0.00") and not justificativa:
            messages.error(request, "Informe justificativa para diferenca no fechamento.")
            return render(
                request,
                "caixa/fechar_caixa.html",
                {
                    "caixa": caixa,
                    "total_entradas": total_entradas,
                    "total_saidas": total_saidas,
                    "saldo": saldo_atual,
                    "valor_contado_fisico": valor_contado,
                    "diferenca_fechamento": diferenca,
                    "menu_app": "caixa",
                    "menu_sub": "fechar_caixa",
                },
            )
        caixa.aberto = False
        caixa.saldo_final = saldo_atual
        caixa.valor_contado_fisico = valor_contado
        caixa.diferenca_fechamento = diferenca
        caixa.justificativa_diferenca = justificativa
        caixa.save()
        _log_financeiro(
            "caixa_fechado",
            request.user,
            valor=saldo_atual,
            descricao=f"Caixa #{caixa.id} | contado={valor_contado:.2f} | diferenca={diferenca:.2f}",
        )
        return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    return render(
        request,
        "caixa/fechar_caixa.html",
        {
            "caixa": caixa,
            "total_entradas": total_entradas,
            "total_saidas": total_saidas,
            "saldo": saldo_atual,
            "valor_contado_fisico": saldo_atual,
            "diferenca_fechamento": Decimal("0.00"),
            "menu_app": "caixa",
            "menu_sub": "fechar_caixa",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def registrar_pagamento(request):
    _garantir_formas_pagamento_padrao()
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")

    os_id = request.GET.get("os")
    os_numero_get = (request.GET.get("os_numero") or "").strip()
    stock_id = request.GET.get("stock")
    venda_id = request.GET.get("venda")
    guia_codigo = (request.GET.get("guia") or "").strip()
    valor_query = request.GET.get("valor")

    ordem = OrdemServico.objects.filter(id=os_id).first() if os_id else None
    numero_os_busca = os_numero_get
    if not ordem and os_numero_get:
        ordem = _buscar_ordem_por_numero(os_numero_get)
        if not ordem:
            messages.error(request, f"OS '{os_numero_get}' não encontrada.")
    item = None
    if stock_id:
        from estoque.models import Produto

        item = Produto.objects.filter(id=stock_id).first()
    venda = None
    vendas_guia = []
    if venda_id:
        from estoque.models import VendaRapidaEstoque

        venda = (
            VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional")
            .filter(id=venda_id, status="pre_reserva")
            .first()
        )
        if not venda:
            messages.error(request, "Pré-reserva de venda não encontrada ou já finalizada.")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")
    if guia_codigo:
        from estoque.models import VendaRapidaEstoque

        vendas_guia = list(
            VendaRapidaEstoque.objects.select_related("produto", "ponto_operacional")
            .filter(guia_pagamento=guia_codigo, status="pre_reserva")
            .order_by("id")
        )
        if not vendas_guia:
            messages.error(request, "Guia não encontrada ou já finalizada.")
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")

    garantia_sugerida = _valor_garantia_sugerido(ordem)

    if request.method == "POST":
        os_numero_post = (request.POST.get("os_numero") or "").strip()
        if not ordem and os_numero_post:
            numero_os_busca = os_numero_post
            ordem = _buscar_ordem_por_numero(os_numero_post)
            if not ordem:
                messages.error(request, f"OS '{os_numero_post}' não encontrada.")
        form = PagamentoForm(_payload_pagamento_normalizado(request))
        if os_numero_post and not ordem:
            form.add_error(None, "OS informada nao encontrada. Verifique o numero.")
            return render(
                request,
                "caixa/registrar_pagamento.html",
                {
                    "form": form,
                    "ordem": ordem,
                    "item": item,
                    "venda": venda,
                    "vendas_guia": vendas_guia,
                    "guia_codigo": guia_codigo,
                    "garantia_sugerida": garantia_sugerida,
                    "caixa": caixa,
                    "numero_os_busca": numero_os_busca,
                    "menu_app": "caixa",
                    "menu_sub": "registrar_pagamento",
                },
            )
        if form.is_valid():
            pagamento_preview = form.save(commit=False)
            forma_preview = pagamento_preview.forma_pagamento
            codigo_forma = forma_preview.codigo if forma_preview else ""
            if venda and pagamento_preview.valor != venda.valor_total:
                form.add_error("valor", f"Valor divergente da pre-reserva. Esperado: {venda.valor_total:.2f}.")
            if vendas_guia:
                total_guia = sum((v.valor_total for v in vendas_guia), Decimal("0.00"))
                if pagamento_preview.valor != total_guia:
                    form.add_error("valor", f"Valor divergente do total da guia. Esperado: {total_guia:.2f}.")
            if form.errors:
                return render(
                    request,
                    "caixa/registrar_pagamento.html",
                    {
                        "form": form,
                        "ordem": ordem,
                        "item": item,
                        "venda": venda,
                        "vendas_guia": vendas_guia,
                        "guia_codigo": guia_codigo,
                        "garantia_sugerida": garantia_sugerida,
                        "caixa": caixa,
                        "numero_os_busca": numero_os_busca,
                        "menu_app": "caixa",
                        "menu_sub": "registrar_pagamento",
                    },
                )
            if ordem and ordem.tipo_reparo == "Garantia" and codigo_forma == "garantia_fabricante":
                marca = MarcaGarantia.objects.filter(
                    nome__iexact=(ordem.marca_equipamento or "").strip(),
                    ativo=True,
                    parceira_garantia=True,
                ).first()
                if not marca:
                    erro_metodo = "Pagamento em garantia bloqueado: a marca da OS nao esta cadastrada como parceira de garantia."
                    form.add_error("forma_pagamento", erro_metodo)
                    form.add_error("metodo", erro_metodo)
                    return render(
                        request,
                        "caixa/registrar_pagamento.html",
                        {
                            "form": form,
                            "ordem": ordem,
                            "item": item,
                            "venda": venda,
                            "vendas_guia": vendas_guia,
                            "guia_codigo": guia_codigo,
                            "garantia_sugerida": garantia_sugerida,
                            "caixa": caixa,
                            "menu_app": "caixa",
                            "menu_sub": "registrar_pagamento",
                        },
                    )
                data_ref = ordem.data_abertura.date() if ordem.data_abertura else timezone.localdate()
                regra_garantia = RegraGarantiaMarca.buscar_regra_vigente(
                    marca,
                    ordem.tipo_equipamento,
                    data_ref=data_ref,
                )
                if not regra_garantia:
                    erro_regra = "Pagamento em garantia bloqueado: configure uma regra de garantia para a marca e o tipo de equipamento desta OS."
                    form.add_error("forma_pagamento", erro_regra)
                    form.add_error("metodo", erro_regra)
                    return render(
                        request,
                        "caixa/registrar_pagamento.html",
                        {
                            "form": form,
                            "ordem": ordem,
                            "item": item,
                            "venda": venda,
                            "vendas_guia": vendas_guia,
                            "guia_codigo": guia_codigo,
                            "garantia_sugerida": garantia_sugerida,
                            "caixa": caixa,
                            "menu_app": "caixa",
                            "menu_sub": "registrar_pagamento",
                        },
                    )
            try:
                with transaction.atomic():
                    pagamento = form.save(commit=False)
                    pagamento.caixa = caixa
                    pagamento.ordem_servico = ordem if ordem else pagamento.ordem_servico
                    pagamento.metodo = pagamento.forma_pagamento.codigo if pagamento.forma_pagamento else (pagamento.metodo or "")
                    if venda:
                        pagamento.stock_item = venda.produto
                    else:
                        pagamento.stock_item = item if item else pagamento.stock_item
                    pagamento.save()
                    _vincular_talao_itens_ordem(pagamento.ordem_servico, pagamento.numero_talao, pagamento=pagamento)

                    descricao = (
                        f"Pagamento OS {pagamento.ordem_servico.numero_os}"
                        if pagamento.ordem_servico
                        else f"Pagamento Stock {pagamento.stock_item.id}"
                        if pagamento.stock_item
                        else "Pagamento Avulso"
                    )

                    LancamentoCaixa.objects.create(
                        caixa=caixa,
                        pagamento=pagamento,
                        descricao=descricao,
                        valor=pagamento.valor,
                        tipo="entrada",
                        usuario=request.user,
                    )
                    _log_financeiro("pagamento_registrado", request.user, pagamento=pagamento, valor=pagamento.valor, descricao=descricao)

                    if venda:
                        from estoque.models import MovimentacaoEstoque
                        from estoque.services import ajustar_saldo

                        config = ConfiguracaoSistema.get_configuracao()
                        try:
                            ajustar_saldo(
                                venda.produto,
                                venda.ponto_operacional,
                                -int(venda.quantidade),
                                allow_negative=bool(config.estoque_permitir_negativo),
                            )
                        except ValueError:
                            raise ValueError(
                                f"Saldo insuficiente para concluir venda #{venda.id} em {venda.ponto_operacional.codigo}."
                            )
                        MovimentacaoEstoque.objects.create(
                            produto=venda.produto,
                            tipo="venda",
                            quantidade=-int(venda.quantidade),
                            origem=venda.ponto_operacional,
                            observacao=f"Venda finalizada no caixa #{pagamento.id} (pre-reserva {venda.id})",
                            usuario=request.user,
                        )
                        venda.pagamento = pagamento
                        venda.status = "vendida"
                        venda.concluido_em = timezone.now()
                        venda.save(update_fields=["pagamento", "status", "concluido_em"])
                    elif vendas_guia:
                        from estoque.models import MovimentacaoEstoque
                        from estoque.services import ajustar_saldo

                        config = ConfiguracaoSistema.get_configuracao()
                        for item_guia in vendas_guia:
                            try:
                                ajustar_saldo(
                                    item_guia.produto,
                                    item_guia.ponto_operacional,
                                    -int(item_guia.quantidade),
                                    allow_negative=bool(config.estoque_permitir_negativo),
                                )
                            except ValueError:
                                raise ValueError(
                                    f"Saldo insuficiente para concluir item da guia {guia_codigo} no ponto {item_guia.ponto_operacional.codigo}."
                                )
                            MovimentacaoEstoque.objects.create(
                                produto=item_guia.produto,
                                tipo="venda",
                                quantidade=-int(item_guia.quantidade),
                                origem=item_guia.ponto_operacional,
                                observacao=f"Venda finalizada no caixa #{pagamento.id} (guia {guia_codigo})",
                                usuario=request.user,
                            )
                            item_guia.pagamento = pagamento
                            item_guia.status = "vendida"
                            item_guia.concluido_em = timezone.now()
                            item_guia.save(update_fields=["pagamento", "status", "concluido_em"])

                    if pagamento.ordem_servico:
                        if pagamento.forma_pagamento and pagamento.forma_pagamento.codigo == "garantia_fabricante":
                            conta = _garantir_conta_garantia(
                                pagamento.ordem_servico,
                                ignorar_pagamento_id=pagamento.id,
                            )
                        else:
                            conta = _garantir_conta_os(
                                pagamento.ordem_servico,
                                ignorar_pagamento_id=pagamento.id,
                            )
                        if conta and conta.status in {"aberta", "parcial", "vencida"} and conta.valor_aberto > 0:
                            abatimento = min(pagamento.valor, conta.valor_aberto)
                            conta.valor_aberto -= abatimento
                            conta.atualizar_status_automatico()
                            conta.save()
                            RecebimentoConta.objects.create(
                                conta=conta,
                                pagamento=pagamento,
                                valor=abatimento,
                                referencia=pagamento.referencia or "",
                                usuario=request.user,
                            )
                            _log_financeiro("conta_receber_baixa_pagamento", request.user, conta=conta, pagamento=pagamento, valor=abatimento)
                        processar_evento_servico_finalizado(
                            pagamento.ordem_servico,
                            evento="SERVICO_FINALIZADO",
                        )
                        if (
                            pagamento.ordem_servico.status == "concluida"
                            and conta
                            and conta.status == "paga"
                        ):
                            processar_evento_retirada_cliente(
                                pagamento.ordem_servico,
                                evento="RETIRADA_CLIENTE",
                            )
            except ValueError as exc:
                form.add_error(None, str(exc))
                return render(
                    request,
                    "caixa/registrar_pagamento.html",
                    {
                        "form": form,
                        "ordem": ordem,
                        "item": item,
                        "venda": venda,
                        "vendas_guia": vendas_guia,
                        "guia_codigo": guia_codigo,
                        "garantia_sugerida": garantia_sugerida,
                        "caixa": caixa,
                        "numero_os_busca": numero_os_busca,
                        "menu_app": "caixa",
                        "menu_sub": "registrar_pagamento",
                    },
                )

            messages.success(
                request,
                f"Pagamento de {pagamento.valor:.2f} registrado. Talao: {pagamento.numero_talao}.",
            )
            return _redirect_pos_operacao(request, "caixa:registrar_pagamento")
    else:
        initial = {}
        if ordem:
            initial["ordem_servico"] = ordem.id
            if garantia_sugerida is not None:
                forma_garantia = _forma_pagamento_por_codigo("garantia_fabricante")
                if forma_garantia:
                    initial["forma_pagamento"] = forma_garantia.id
                initial["metodo"] = "garantia_fabricante"
                initial["valor"] = garantia_sugerida
        if venda:
            initial["valor"] = venda.valor_total
        if vendas_guia:
            initial["valor"] = sum((v.valor_total for v in vendas_guia), Decimal("0.00"))
        if valor_query:
            initial["valor"] = valor_query
        form = PagamentoForm(initial=initial)

    return render(
        request,
        "caixa/registrar_pagamento.html",
        {
            "form": form,
            "ordem": ordem,
            "item": item,
            "venda": venda,
            "vendas_guia": vendas_guia,
            "guia_codigo": guia_codigo,
            "garantia_sugerida": garantia_sugerida,
            "caixa": caixa,
            "numero_os_busca": numero_os_busca,
            "menu_app": "caixa",
            "menu_sub": "registrar_pagamento",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def registrar_saida(request):
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")

    if request.method == "POST":
        form = LancamentoCaixaForm(request.POST)
        if form.is_valid():
            saida = form.save(commit=False)
            saida.caixa = caixa
            saida.tipo = "saida"
            saida.usuario = request.user
            saida.save()
            _log_financeiro("saida_registrada", request.user, valor=saida.valor, descricao=saida.descricao)
            return _redirect_pos_operacao(request, "caixa:registrar_saida")
    else:
        form = LancamentoCaixaForm()

    return render(
        request,
        "caixa/registrar_saida.html",
        {
            "form": form,
            "menu_app": "caixa",
            "menu_sub": "registrar_saida",
            "caixa": caixa,
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def contas_receber(request):
    _atualizar_status_contas_abertas()
    status = request.GET.get("status", "")
    prontas_filtro = request.GET.get("prontas_sem_recebimento") == "1"
    queryset = ContaReceber.objects.select_related("ordem_servico", "ponto_operacional", "categoria").all()
    if status:
        queryset = queryset.filter(status=status)
    if prontas_filtro:
        queryset = queryset.filter(
            tipo_origem="cliente_os",
            status__in=["aberta", "parcial", "vencida"],
            ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
        )

    total_aberto = queryset.filter(status__in=["aberta", "parcial", "vencida"]).aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    prontas_qs = ContaReceber.objects.filter(
        tipo_origem="cliente_os",
        status__in=["aberta", "parcial", "vencida"],
        ordem_servico__status__in=["pronto_contactado", "pronto_contactar"],
    )
    prontas_sem_recebimento_total = prontas_qs.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    prontas_sem_recebimento_qtd = prontas_qs.count()

    return render(
        request,
        "caixa/contas_receber_list.html",
        {
            "contas": queryset[:200],
            "status_filtro": status,
            "prontas_filtro": prontas_filtro,
            "total_aberto": total_aberto,
            "prontas_sem_recebimento_total": prontas_sem_recebimento_total,
            "prontas_sem_recebimento_qtd": prontas_sem_recebimento_qtd,
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def criar_conta_receber(request):
    if request.method == "POST":
        form = ContaReceberForm(request.POST)
        if form.is_valid():
            conta = form.save()
            conta.tipo_origem = "cliente_os" if conta.ordem_servico_id else "avulso"
            conta.save(update_fields=["tipo_origem"])
            _log_financeiro("conta_receber_criada", request.user, conta=conta, valor=conta.valor_original)
            messages.success(request, "Conta a receber criada com sucesso.")
            return redirect("caixa:contas_receber")
    else:
        form = ContaReceberForm()

    return render(
        request,
        "caixa/contas_receber_form.html",
        {"form": form, "menu_app": "caixa", "menu_sub": "contas_receber"},
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def detalhe_conta_receber(request, conta_id):
    _garantir_formas_pagamento_padrao()
    conta = get_object_or_404(ContaReceber.objects.select_related("ordem_servico"), id=conta_id)
    recebimentos = conta.recebimentos.select_related("usuario", "pagamento")

    if request.method == "POST":
        form = BaixaContaReceberForm(_payload_pagamento_normalizado(request))
        if form.is_valid():
            if conta.status in {"paga", "cancelada"}:
                messages.error(request, "Esta conta não permite nova baixa.")
                return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)

            caixa = caixa_atual()
            if not caixa:
                messages.error(request, "Abra o caixa antes de registrar baixa.")
                return redirect("caixa:abrir_caixa")

            valor = form.cleaned_data["valor"]
            desconto = form.cleaned_data.get("desconto") or Decimal("0.00")
            juros = form.cleaned_data.get("juros") or Decimal("0.00")
            referencia = form.cleaned_data.get("referencia") or ""
            observacao = form.cleaned_data.get("observacao") or ""
            forma_pagamento = form.cleaned_data["forma_pagamento"]

            with transaction.atomic():
                abatimento = min(conta.valor_aberto, valor + desconto)
                pagamento = Pagamento.objects.create(
                    caixa=caixa,
                    ordem_servico=conta.ordem_servico,
                    valor=valor,
                    forma_pagamento=forma_pagamento,
                    metodo=forma_pagamento.codigo if forma_pagamento else "",
                    referencia=referencia,
                    observacao=observacao,
                )
                _vincular_talao_itens_ordem(pagamento.ordem_servico, pagamento.numero_talao, pagamento=pagamento)
                LancamentoCaixa.objects.create(
                    caixa=caixa,
                    pagamento=pagamento,
                    descricao=f"Baixa conta receber #{conta.id}",
                    valor=valor,
                    tipo="entrada",
                    usuario=request.user,
                )
                RecebimentoConta.objects.create(
                    conta=conta,
                    pagamento=pagamento,
                    valor=valor,
                    desconto=desconto,
                    juros=juros,
                    referencia=referencia,
                    observacao=observacao,
                    usuario=request.user,
                )

                conta.valor_aberto = max(Decimal("0.00"), conta.valor_aberto - abatimento)
                conta.atualizar_status_automatico()
                conta.save()
                if conta.ordem_servico and conta.ordem_servico.status == "concluida" and conta.status == "paga":
                    processar_evento_retirada_cliente(
                        conta.ordem_servico,
                        evento="RETIRADA_CLIENTE",
                    )
            _log_financeiro("conta_receber_baixa_manual", request.user, conta=conta, pagamento=pagamento, valor=abatimento)
            messages.success(request, "Baixa registrada com sucesso.")
            return redirect("caixa:detalhe_conta_receber", conta_id=conta.id)
    else:
        form = BaixaContaReceberForm(initial={"valor": conta.valor_aberto})

    return render(
        request,
        "caixa/contas_receber_detalhe.html",
        {
            "conta": conta,
            "form": form,
            "recebimentos": recebimentos,
            "menu_app": "caixa",
            "menu_sub": "contas_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def aging_receber(request):
    _atualizar_status_contas_abertas()
    hoje = timezone.localdate()
    contas = ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"]) 

    buckets = {
        "a_vencer": Decimal("0.00"),
        "vencidas_1_30": Decimal("0.00"),
        "vencidas_31_60": Decimal("0.00"),
        "vencidas_61_90": Decimal("0.00"),
        "vencidas_90_plus": Decimal("0.00"),
    }
    for conta in contas:
        dias = (hoje - conta.vencimento).days
        if dias < 0:
            buckets["a_vencer"] += conta.valor_aberto
        elif dias <= 30:
            buckets["vencidas_1_30"] += conta.valor_aberto
        elif dias <= 60:
            buckets["vencidas_31_60"] += conta.valor_aberto
        elif dias <= 90:
            buckets["vencidas_61_90"] += conta.valor_aberto
        else:
            buckets["vencidas_90_plus"] += conta.valor_aberto

    return render(
        request,
        "caixa/aging_receber.html",
        {
            "buckets": buckets,
            "menu_app": "caixa",
            "menu_sub": "aging_receber",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def categorias_financeiras(request):
    if request.method == "POST":
        form = CategoriaFinanceiraForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Categoria financeira salva.")
            return redirect("caixa:categorias_financeiras")
    else:
        form = CategoriaFinanceiraForm()
    categorias = CategoriaFinanceira.objects.all()
    return render(
        request,
        "caixa/categorias_financeiras.html",
        {
            "form": form,
            "categorias": categorias,
            "menu_app": "caixa",
            "menu_sub": "categorias_financeiras",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def formas_pagamento(request):
    if request.method == "POST":
        form = FormaPagamentoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Forma de pagamento salva.")
            return redirect("caixa:formas_pagamento")
    else:
        form = FormaPagamentoForm()
    formas = FormaPagamento.objects.all()
    return render(
        request,
        "caixa/formas_pagamento.html",
        {
            "form": form,
            "formas": formas,
            "menu_app": "caixa",
            "menu_sub": "formas_pagamento",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def centros_custo(request):
    if request.method == "POST":
        form = CentroCustoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Centro de custo salvo.")
            return redirect("caixa:centros_custo")
    else:
        form = CentroCustoForm()
    centros = CentroCusto.objects.all()
    return render(
        request,
        "caixa/centros_custo.html",
        {
            "form": form,
            "centros": centros,
            "menu_app": "caixa",
            "menu_sub": "centros_custo",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def taloes(request):
    busca = (request.GET.get("q") or "").strip()
    pagamentos = Pagamento.objects.select_related("ordem_servico", "forma_pagamento").order_by("-data")
    if busca:
        pagamentos = pagamentos.filter(
            Q(numero_talao__icontains=busca)
            | Q(referencia__icontains=busca)
            | Q(ordem_servico__numero_os__icontains=busca)
        )

    return render(
        request,
        "caixa/taloes_list.html",
        {
            "pagamentos": pagamentos[:200],
            "q": busca,
            "menu_app": "caixa",
            "menu_sub": "taloes",
        },
    )


@role_required(CAIXA_OPERATIONAL_ROLES)
def imprimir_talao(request, pagamento_id):
    pagamento = get_object_or_404(Pagamento.objects.select_related("ordem_servico", "forma_pagamento"), id=pagamento_id)
    empresa = Empresa.objects.first()
    return render(
        request,
        "caixa/talao_print.html",
        {
            "pagamento": pagamento,
            "empresa": empresa,
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def contas_pagar(request):
    status = (request.GET.get("status") or "").strip()
    queryset = ContaPagar.objects.select_related("centro_custo").all()
    for conta in queryset:
        status_ant = conta.status
        conta.atualizar_status_automatico()
        if conta.status != status_ant:
            conta.save(update_fields=["status", "atualizado_em"])
    if status:
        queryset = queryset.filter(status=status)

    total_aberto = sum((c.valor_aberto for c in queryset if c.status in {"aberta", "parcial", "vencida"}), Decimal("0.00"))
    return render(
        request,
        "caixa/contas_pagar_list.html",
        {
            "contas": queryset[:300],
            "status_filtro": status,
            "total_aberto": total_aberto,
            "menu_app": "caixa",
            "menu_sub": "contas_pagar",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def criar_conta_pagar(request):
    if request.method == "POST":
        form = ContaPagarForm(request.POST)
        if form.is_valid():
            conta = form.save(commit=False)
            conta.valor_pago = Decimal("0.00")
            conta.atualizar_status_automatico()
            conta.save()
            _log_financeiro("conta_pagar_criada", request.user, valor=conta.valor_total, descricao=f"Conta pagar #{conta.id}")
            messages.success(request, "Conta a pagar criada.")
            return redirect("caixa:contas_pagar")
    else:
        form = ContaPagarForm()
    return render(
        request,
        "caixa/contas_pagar_form.html",
        {"form": form, "menu_app": "caixa", "menu_sub": "contas_pagar"},
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def detalhe_conta_pagar(request, conta_id):
    _garantir_formas_pagamento_padrao()
    conta = get_object_or_404(ContaPagar.objects.select_related("centro_custo"), id=conta_id)
    pagamentos = conta.pagamentos.select_related("forma_pagamento", "usuario")

    if request.method == "POST":
        action = (request.POST.get("action") or "pagar").strip()
        if action == "cancelar":
            if pagamentos.exists():
                messages.error(request, "Não é permitido cancelar/excluir conta com pagamentos vinculados.")
            else:
                conta.status = "cancelada"
                conta.save(update_fields=["status", "atualizado_em"])
                _log_financeiro("conta_pagar_cancelada", request.user, valor=conta.valor_total, descricao=f"Conta pagar #{conta.id}")
                messages.success(request, "Conta cancelada.")
            return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)

        form = PagamentoContaPagarForm(request.POST)
        if form.is_valid():
            valor_pg = form.cleaned_data["valor"]
            if valor_pg <= 0:
                messages.error(request, "Valor de pagamento inválido.")
                return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)
            if conta.status in {"paga", "cancelada"}:
                messages.error(request, "Conta não permite novos pagamentos.")
                return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)
            if valor_pg > conta.valor_aberto:
                messages.error(request, "Valor maior que o saldo em aberto da conta.")
                return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)

            caixa = caixa_atual()
            if not caixa:
                messages.error(request, "Abra o caixa antes de registrar pagamento de conta a pagar.")
                return redirect("caixa:abrir_caixa")
            with transaction.atomic():
                pagamento = form.save(commit=False)
                pagamento.conta = conta
                pagamento.usuario = request.user
                pagamento.caixa = caixa
                pagamento.save()

                conta.valor_pago = (conta.valor_pago or Decimal("0.00")) + valor_pg
                conta.atualizar_status_automatico()
                conta.save(update_fields=["valor_pago", "status", "atualizado_em"])

                LancamentoCaixa.objects.create(
                    caixa=caixa,
                    descricao=f"Pagamento conta a pagar #{conta.id}",
                    centro_custo=conta.centro_custo,
                    valor=valor_pg,
                    tipo="saida",
                    usuario=request.user,
                )
                _log_financeiro(
                    "conta_pagar_pagamento",
                    request.user,
                    valor=valor_pg,
                    descricao=f"Conta pagar #{conta.id}",
                )
            messages.success(request, "Pagamento registrado.")
            return redirect("caixa:detalhe_conta_pagar", conta_id=conta.id)
    else:
        form = PagamentoContaPagarForm(initial={"valor": conta.valor_aberto})

    return render(
        request,
        "caixa/contas_pagar_detalhe.html",
        {
            "conta": conta,
            "pagamentos": pagamentos,
            "form": form,
            "menu_app": "caixa",
            "menu_sub": "contas_pagar",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def comissoes_tecnicos(request):
    from orcamentos.models import ItemOrcamento

    def _parse_intervalo_datas(raw_inicio, raw_fim):
        inicio = None
        fim = None
        try:
            if raw_inicio:
                inicio = date.fromisoformat(raw_inicio)
        except ValueError:
            inicio = None
        try:
            if raw_fim:
                fim = date.fromisoformat(raw_fim)
        except ValueError:
            fim = None
        return inicio, fim

    def _ordens_por_intervalo(data_inicio, data_fim):
        ordens_qs = OrdemServico.objects.filter(
            status__in=["autorizado", "pronto_contactar", "pronto_contactado", "concluida"]
        ).select_related("tecnico_responsavel")
        if data_inicio:
            ordens_qs = ordens_qs.filter(
                Q(data_conclusao__date__gte=data_inicio)
                | Q(data_conclusao__isnull=True, data_abertura__date__gte=data_inicio)
            )
        if data_fim:
            ordens_qs = ordens_qs.filter(
                Q(data_conclusao__date__lte=data_fim)
                | Q(data_conclusao__isnull=True, data_abertura__date__lte=data_fim)
            )
        return ordens_qs

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        comissao_id = request.POST.get("comissao_id")
        data_inicio_post_raw = (request.POST.get("data_inicio") or "").strip()
        data_fim_post_raw = (request.POST.get("data_fim") or "").strip()
        data_inicio_post, data_fim_post = _parse_intervalo_datas(data_inicio_post_raw, data_fim_post_raw)
        if action == "recalcular":
            ordens_qs = OrdemServico.objects.filter(
                status__in=["autorizado", "pronto_contactar", "pronto_contactado", "concluida"]
            ).select_related("tecnico_responsavel")
            ordens_processadas, total_novo = _recalcular_comissoes_motor_novo(ordens_qs)
            messages.success(
                request,
                f"Motor novo recalculado. Ordens processadas: {ordens_processadas}. Novas comissoes: {total_novo}.",
            )
            return redirect("caixa:comissoes_tecnicos")
        if action in {"recalcular_servicos", "recalcular_pecas"}:
            tipos = {"servico"} if action == "recalcular_servicos" else {"peca"}
            ordens_qs = _ordens_por_intervalo(data_inicio_post, data_fim_post)
            resumo = recalcular_comissoes_servico_finalizado(
                ordens=ordens_qs,
                evento="SERVICO_FINALIZADO",
                tipos=tipos,
            )
            tipo_label = "servicos" if action == "recalcular_servicos" else "pecas"
            periodo_msg = ""
            if data_inicio_post or data_fim_post:
                de = data_inicio_post.strftime("%d/%m/%Y") if data_inicio_post else "inicio"
                ate = data_fim_post.strftime("%d/%m/%Y") if data_fim_post else "hoje"
                periodo_msg = f" (periodo {de} a {ate})"
            messages.success(
                request,
                (
                    f"Recalculo de {tipo_label} concluido{periodo_msg}. "
                    f"Ordens processadas: {resumo['ordens_processadas']}. "
                    f"Novas comissoes: {resumo['comissoes_criadas']}."
                ),
            )
            return redirect("caixa:comissoes_tecnicos")
        if action == "recalcular_itens_antecipado":
            itens = (
                ItemOrcamento.objects.select_related("orcamento__ordem_servico", "tecnico_responsavel")
                .filter(status="aprovado", tecnico_responsavel__isnull=False)
            )
            ordens_ids = list(itens.values_list("orcamento__ordem_servico_id", flat=True).distinct())
            total_legado = 0
            for item in itens:
                if _gerar_comissao_item_orcamento(item, modo_pagamento="antecipado"):
                    total_legado += 1
            ordens_processadas, total_novo = _recalcular_comissoes_motor_novo(
                OrdemServico.objects.filter(id__in=ordens_ids).select_related("tecnico_responsavel")
            )
            messages.success(
                request,
                (
                    "Comissoes por item (antecipado) recalculadas. "
                    f"Motor novo: {total_novo} novas ({ordens_processadas} ordens). "
                    f"Legado: {total_legado}."
                ),
            )
            return redirect("caixa:comissoes_tecnicos")
        if action == "recalcular_itens_fechamento":
            itens = (
                ItemOrcamento.objects.select_related("orcamento__ordem_servico", "tecnico_responsavel")
                .filter(
                    status="aprovado",
                    tecnico_responsavel__isnull=False,
                    orcamento__ordem_servico__fechada=True,
                )
            )
            ordens_ids = list(itens.values_list("orcamento__ordem_servico_id", flat=True).distinct())
            total_legado = 0
            for item in itens:
                if _gerar_comissao_item_orcamento(item, modo_pagamento="fechamento"):
                    total_legado += 1
            ordens_processadas, total_novo = _recalcular_comissoes_motor_novo(
                OrdemServico.objects.filter(id__in=ordens_ids).select_related("tecnico_responsavel")
            )
            messages.success(
                request,
                (
                    "Comissoes por item (fechamento) recalculadas. "
                    f"Motor novo: {total_novo} novas ({ordens_processadas} ordens). "
                    f"Legado: {total_legado}."
                ),
            )
            return redirect("caixa:comissoes_tecnicos")
        if action in {"liberar", "pagar", "cancelar"} and comissao_id:
            comissao = get_object_or_404(Comissao, id=comissao_id)
            try:
                resultado = aplicar_acao_comissao(
                    comissao,
                    acao=action,
                    usuario=request.user,
                    referencia_pagamento=request.POST.get("referencia_pagamento") or "",
                    motivo_cancelamento=request.POST.get("motivo_cancelamento") or "",
                )
                if resultado.changed:
                    messages.success(request, resultado.message)
                else:
                    messages.info(request, resultado.message)
            except ComissaoStatusError as exc:
                messages.warning(request, str(exc))
            return redirect("caixa:comissoes_tecnicos")

        if action == "reprocessar_os":
            os_id = request.POST.get("os_id")
            if os_id and os_id.isdigit():
                ordem = OrdemServico.objects.filter(id=int(os_id)).first()
                if ordem:
                    total = processar_evento_servico_finalizado(ordem, evento="SERVICO_FINALIZADO")
                    messages.success(request, f"Reprocessamento executado. Novas comissões: {total}.")
            return redirect("caixa:comissoes_tecnicos")

    tecnico_id = (request.GET.get("tecnico") or "").strip()
    status_filtro = (request.GET.get("status") or "").strip()
    os_filtro = (request.GET.get("os") or "").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()

    data_inicio = None
    data_fim = None
    data_inicio, data_fim = _parse_intervalo_datas(data_inicio_raw, data_fim_raw)

    comissoes_qs = Comissao.objects.select_related("tecnico", "ordem_servico", "item_orcamento", "produto").all()
    if tecnico_id and tecnico_id.isdigit():
        comissoes_qs = comissoes_qs.filter(tecnico_id=int(tecnico_id))
    if status_filtro in {"GERADA", "LIBERADA", "PAGA", "CANCELADA"}:
        comissoes_qs = comissoes_qs.filter(status=status_filtro)
    if os_filtro:
        comissoes_qs = comissoes_qs.filter(ordem_servico__numero_os__icontains=os_filtro)
    if data_inicio:
        comissoes_qs = comissoes_qs.filter(data_criacao__date__gte=data_inicio)
    if data_fim:
        comissoes_qs = comissoes_qs.filter(data_criacao__date__lte=data_fim)

    comissoes = comissoes_qs.order_by("-data_criacao", "-id")[:500]
    total_geral = comissoes_qs.exclude(status="CANCELADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_gerada = comissoes_qs.filter(status="GERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_liberada = comissoes_qs.filter(status="LIBERADA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")
    total_paga = comissoes_qs.filter(status="PAGA").aggregate(total=Sum("valor_comissao"))["total"] or Decimal("0.00")

    resumo_tipos = (
        comissoes_qs.exclude(status="CANCELADA")
        .values("tipo")
        .annotate(total=Sum("valor_comissao"))
        .order_by("tipo")
    )
    tecnicos = get_user_model().objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username")

    return render(
        request,
        "caixa/comissoes_tecnicos.html",
        {
            "comissoes": comissoes,
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_id,
            "status_filtro": status_filtro,
            "os_filtro": os_filtro,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "total_geral": total_geral,
            "total_gerada": total_gerada,
            "total_liberada": total_liberada,
            "total_paga": total_paga,
            "resumo_tipos": resumo_tipos,
            "menu_app": "caixa",
            "menu_sub": "comissoes_tecnicos",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def premios_meta(request):
    if request.method == "POST":
        if request.POST.get("action") == "regra_premio":
            regra_premio_form = RegraPremioMetaForm(request.POST)
            if regra_premio_form.is_valid():
                regra_premio_form.save()
                messages.success(request, "Regra de prêmio salva.")
                return redirect("caixa:premios_meta")
        elif request.POST.get("action") == "faixa_premio":
            faixa_premio_form = FaixaPremioMetaForm(request.POST)
            if faixa_premio_form.is_valid():
                faixa_premio_form.save()
                messages.success(request, "Faixa de prêmio salva.")
                return redirect("caixa:premios_meta")
        elif request.POST.get("action") == "recalcular_premios":
            competencia = _competencia_atual()
            total = _recalcular_premios_competencia(competencia)
            messages.success(request, f"Prêmios recalculados para {competencia:%m/%Y}: {total} registros.")
            return redirect("caixa:premios_meta")

    regras_premios = RegraPremioMeta.objects.prefetch_related("faixas").all()
    premios_competencia = PremioColaboradorCompetencia.objects.select_related("colaborador", "regra", "faixa").all()[:300]
    regra_premio_form = RegraPremioMetaForm()
    faixa_premio_form = FaixaPremioMetaForm()
    return render(
        request,
        "caixa/premios_meta.html",
        {
            "regras_premios": regras_premios,
            "premios_competencia": premios_competencia,
            "regra_premio_form": regra_premio_form,
            "faixa_premio_form": faixa_premio_form,
            "menu_app": "caixa",
            "menu_sub": "premios_meta",
        },
    )


@role_required(PERFORMANCE_VIEW_ROLES)
def meu_desempenho(request):
    from caixa.services.comissoes import _fontes_comissionaveis

    tipo_usuario = getattr(request.user, "tipo_usuario", "")
    pode_filtrar_tecnicos = bool(request.user.is_superuser or tipo_usuario in {"adm", "gerente"})
    tecnico_filtro = (request.GET.get("tecnico") or "").strip()
    status_filtro = (request.GET.get("status") or "").strip()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    percentual_servicos_raw = (request.GET.get("percentual_servicos") or "").strip()
    percentual_pecas_raw = (request.GET.get("percentual_pecas") or "").strip()
    aplicar_servicos = request.GET.get("aplicar_servicos", "1") == "1"
    aplicar_pecas = request.GET.get("aplicar_pecas", "1") == "1"
    somente_fechadas = request.GET.get("somente_fechadas") == "1"
    filtro_aplicado = bool(request.GET)

    data_inicio = None
    data_fim = None
    try:
        if data_inicio_raw:
            data_inicio = date.fromisoformat(data_inicio_raw)
    except ValueError:
        data_inicio = None
    try:
        if data_fim_raw:
            data_fim = date.fromisoformat(data_fim_raw)
    except ValueError:
        data_fim = None

    periodo_valido = True
    if filtro_aplicado:
        if not data_inicio or not data_fim:
            periodo_valido = False
            messages.warning(request, "Informe data de início e data de fim para pesquisar.")
        elif data_inicio > data_fim:
            periodo_valido = False
            messages.warning(request, "A data de início não pode ser maior que a data de fim.")
        elif (data_fim - data_inicio).days > 366:
            periodo_valido = False
            messages.warning(request, "O intervalo máximo permitido para consulta é de 12 meses.")

    if not pode_filtrar_tecnicos:
        tecnico_filtro = str(request.user.id)

    tecnico_percentual = None
    if tecnico_filtro and tecnico_filtro.isdigit():
        tecnico_percentual = get_user_model().objects.filter(id=int(tecnico_filtro), tipo_usuario="tecnico").first()
    padrao_servicos, padrao_pecas = _percentuais_padrao_desempenho(tecnico_percentual)

    try:
        percentual_servicos = (
            Decimal(percentual_servicos_raw.replace(",", ".")) if percentual_servicos_raw else padrao_servicos
        )
    except Exception:
        percentual_servicos = padrao_servicos
    try:
        percentual_pecas = Decimal(percentual_pecas_raw.replace(",", ".")) if percentual_pecas_raw else padrao_pecas
    except Exception:
        percentual_pecas = padrao_pecas

    percentual_servicos = max(percentual_servicos, Decimal("0.00"))
    percentual_pecas = max(percentual_pecas, Decimal("0.00"))

    tecnicos = get_user_model().objects.filter(is_active=True, tipo_usuario="tecnico").order_by("username")
    comissoes_qs = Comissao.objects.select_related("tecnico", "ordem_servico", "item_orcamento").all()
    if somente_fechadas:
        comissoes_qs = comissoes_qs.filter(Q(ordem_servico__status="concluida") | Q(ordem_servico__fechada=True))
    else:
        comissoes_qs = comissoes_qs.filter(
            ordem_servico__status__in=["autorizado", "pronto_contactar", "pronto_contactado", "concluida"]
        )
    if tecnico_filtro and tecnico_filtro.isdigit():
        comissoes_qs = comissoes_qs.filter(tecnico_id=int(tecnico_filtro))
    if status_filtro in {"GERADA", "LIBERADA", "PAGA", "CANCELADA"}:
        comissoes_qs = comissoes_qs.filter(status=status_filtro)
    else:
        comissoes_qs = comissoes_qs.exclude(status="CANCELADA")
    if periodo_valido and data_inicio:
        comissoes_qs = comissoes_qs.filter(data_criacao__date__gte=data_inicio)
    if periodo_valido and data_fim:
        comissoes_qs = comissoes_qs.filter(data_criacao__date__lte=data_fim)

    if filtro_aplicado and periodo_valido:
        comissoes = list(comissoes_qs.order_by("-data_criacao", "-id")[:500])
    else:
        comissoes = []

    ordens_relatorio = []
    total_servicos_relatorio = Decimal("0.00")
    total_pecas_relatorio = Decimal("0.00")
    total_base_relatorio = Decimal("0.00")
    total_comissao_servicos_relatorio = Decimal("0.00")
    total_comissao_pecas_relatorio = Decimal("0.00")
    total_comissao_relatorio = Decimal("0.00")
    chaves_fontes_validas = set()
    if filtro_aplicado and periodo_valido and (aplicar_servicos or aplicar_pecas):
        if somente_fechadas:
            ordens_base = OrdemServico.objects.filter(Q(status="concluida") | Q(fechada=True)).order_by("-id")
        else:
            ordens_base = (
                OrdemServico.objects.filter(status__in=["autorizado", "pronto_contactar", "pronto_contactado", "concluida"])
                .order_by("-id")
            )
        agregados = {}
        tecnico_id_filtro = int(tecnico_filtro) if tecnico_filtro and tecnico_filtro.isdigit() else None
        for ordem in ordens_base:
            if not somente_fechadas and not _ordem_execucao_confirmada(ordem):
                continue

            data_ref = _data_referencia_ordem(ordem)
            if data_inicio and (not data_ref or data_ref < data_inicio):
                continue
            if data_fim and (not data_ref or data_ref > data_fim):
                continue

            for fonte in _fontes_comissionaveis(ordem):
                tecnico = fonte.get("tecnico")
                if not tecnico:
                    continue
                if tecnico_id_filtro and tecnico.id != tecnico_id_filtro:
                    continue
                valor_item = Decimal(fonte.get("base") or 0)
                if valor_item <= Decimal("0.00"):
                    continue
                tipo_item = (fonte.get("tipo_item") or "").strip().lower()
                if tipo_item not in {"servico", "peca"}:
                    continue
                chave_ref = fonte.get("chave_ref")
                if chave_ref:
                    if tipo_item == "servico":
                        chaves_fontes_validas.add(f"SERVICO_FINALIZADO:SERVICO:{chave_ref}")
                    else:
                        chaves_fontes_validas.add(f"SERVICO_FINALIZADO:PECA:{chave_ref}")
                        chaves_fontes_validas.add(f"SERVICO_FINALIZADO:BONUS_PRODUTO:{chave_ref}")
                chave = (ordem.id, tecnico.id)
                row = agregados.setdefault(
                    chave,
                    {
                        "numero_os": ordem.numero_os,
                        "data_conclusao": ordem.data_conclusao.date() if ordem.data_conclusao else None,
                        "tecnico": tecnico,
                        "valor_servicos": Decimal("0.00"),
                        "valor_pecas": Decimal("0.00"),
                        "valor_base": Decimal("0.00"),
                        "valor_comissao": Decimal("0.00"),
                    },
                )
                if tipo_item == "peca":
                    row["valor_pecas"] += valor_item
                else:
                    row["valor_servicos"] += valor_item

        for row in agregados.values():
            base = Decimal("0.00")
            comissao_servicos = Decimal("0.00")
            comissao_pecas = Decimal("0.00")
            if aplicar_servicos:
                base += row["valor_servicos"]
                comissao_servicos = (row["valor_servicos"] * percentual_servicos) / Decimal("100.00")
            if aplicar_pecas:
                base += row["valor_pecas"]
                comissao_pecas = (row["valor_pecas"] * percentual_pecas) / Decimal("100.00")
            if base <= Decimal("0.00"):
                continue
            row["valor_base"] = base
            row["comissao_servicos"] = comissao_servicos
            row["comissao_pecas"] = comissao_pecas
            row["valor_comissao"] = comissao_servicos + comissao_pecas
            ordens_relatorio.append(row)
            total_servicos_relatorio += row["valor_servicos"]
            total_pecas_relatorio += row["valor_pecas"]
            total_base_relatorio += row["valor_base"]
            total_comissao_servicos_relatorio += row["comissao_servicos"]
            total_comissao_pecas_relatorio += row["comissao_pecas"]
            total_comissao_relatorio += row["valor_comissao"]
    ordens_relatorio.sort(key=lambda x: (x["data_conclusao"] or date.min, x["numero_os"]), reverse=True)

    resumo_calculo = {
        "base_servicos": total_servicos_relatorio,
        "base_pecas": total_pecas_relatorio,
        "comissao_servicos": total_comissao_servicos_relatorio,
        "comissao_pecas": total_comissao_pecas_relatorio,
        "total": total_comissao_relatorio,
    }

    resumo = {
        "servicos": Decimal("0.00"),
        "pecas": Decimal("0.00"),
        "bonus_produto": Decimal("0.00"),
        "bonus_retirada": Decimal("0.00"),
        "bonus_servico": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    for comissao in comissoes:
        if comissao.status == "CANCELADA":
            continue
        if comissao.tipo == "SERVICO":
            resumo["servicos"] += comissao.valor_comissao
        elif comissao.tipo == "PECA":
            resumo["pecas"] += comissao.valor_comissao
        elif comissao.tipo == "BONUS_PRODUTO":
            resumo["bonus_produto"] += comissao.valor_comissao
        elif comissao.tipo == "BONUS_RETIRADA":
            resumo["bonus_retirada"] += comissao.valor_comissao
        elif comissao.tipo == "BONUS_SERVICO":
            resumo["bonus_servico"] += comissao.valor_comissao
        resumo["total"] += comissao.valor_comissao

    comissoes_calculadas = []
    for comissao in comissoes:
        if comissao.tipo in {"SERVICO", "PECA", "BONUS_PRODUTO"}:
            if comissao.chave_unica not in chaves_fontes_validas:
                continue
        percentual_aplicado = comissao.percentual
        valor_calculado = comissao.valor_comissao
        if comissao.tipo == "SERVICO":
            percentual_aplicado = percentual_servicos if aplicar_servicos else Decimal("0.00")
            valor_calculado = (comissao.valor_base * percentual_aplicado) / Decimal("100.00")
        elif comissao.tipo == "PECA":
            percentual_aplicado = percentual_pecas if aplicar_pecas else Decimal("0.00")
            valor_calculado = (comissao.valor_base * percentual_aplicado) / Decimal("100.00")
        comissoes_calculadas.append(
            {
                "comissao": comissao,
                "percentual_aplicado": percentual_aplicado,
                "valor_calculado": valor_calculado,
            }
        )

    return render(
        request,
        "caixa/meu_desempenho.html",
        {
            "tecnicos": tecnicos,
            "tecnico_filtro": tecnico_filtro,
            "status_filtro": status_filtro,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "percentual_servicos": f"{percentual_servicos:.2f}",
            "percentual_pecas": f"{percentual_pecas:.2f}",
            "aplicar_servicos": aplicar_servicos,
            "aplicar_pecas": aplicar_pecas,
            "somente_fechadas": somente_fechadas,
            "filtro_aplicado": filtro_aplicado,
            "comissoes": comissoes,
            "comissoes_calculadas": comissoes_calculadas,
            "resumo": resumo,
            "resumo_calculo": resumo_calculo,
            "ordens_relatorio": ordens_relatorio,
            "total_servicos_relatorio": total_servicos_relatorio,
            "total_pecas_relatorio": total_pecas_relatorio,
            "total_base_relatorio": total_base_relatorio,
            "total_comissao_servicos_relatorio": total_comissao_servicos_relatorio,
            "total_comissao_pecas_relatorio": total_comissao_pecas_relatorio,
            "total_comissao_relatorio": total_comissao_relatorio,
            "total_comissao_itens": total_comissao_relatorio,
            "pode_filtrar_tecnicos": pode_filtrar_tecnicos,
            "menu_app": "caixa",
            "menu_sub": "meu_desempenho",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def dre(request):
    periodo = request.GET.get("periodo", "30")
    dias = {"7": 7, "30": 30, "90": 90}.get(periodo)
    data_inicio = timezone.localdate() - timedelta(days=dias) if dias else None

    pagamentos_qs = Pagamento.objects.all()
    saidas_qs = LancamentoCaixa.objects.filter(tipo="saida")
    if data_inicio:
        pagamentos_qs = pagamentos_qs.filter(data__date__gte=data_inicio)
        saidas_qs = saidas_qs.filter(data__date__gte=data_inicio)

    receita_bruta = pagamentos_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    despesas_operacionais = saidas_qs.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    resultado_operacional = receita_bruta - despesas_operacionais
    margem = (resultado_operacional / receita_bruta * Decimal("100.00")) if receita_bruta > 0 else Decimal("0.00")

    return render(
        request,
        "caixa/dre.html",
        {
            "periodo": periodo,
            "receita_bruta": receita_bruta,
            "despesas_operacionais": despesas_operacionais,
            "resultado_operacional": resultado_operacional,
            "margem": margem,
            "menu_app": "caixa",
            "menu_sub": "dre",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def fluxo_projetado(request):
    if request.method == "POST":
        form = DespesaRecorrenteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Despesa recorrente salva.")
            return redirect("caixa:fluxo_projetado")
    else:
        form = DespesaRecorrenteForm()

    hoje = timezone.localdate()
    meses = []
    for offset in range(6):
        mes_num = ((hoje.month - 1 + offset) % 12) + 1
        ano = hoje.year + ((hoje.month - 1 + offset) // 12)
        ultimo_dia = monthrange(ano, mes_num)[1]
        inicio_mes = date(ano, mes_num, 1)
        fim_mes = date(ano, mes_num, ultimo_dia)

        entradas_previstas = (
            ContaReceber.objects.filter(status__in=["aberta", "parcial", "vencida"], vencimento__gte=inicio_mes, vencimento__lte=fim_mes)
            .aggregate(total=Sum("valor_aberto"))["total"]
            or Decimal("0.00")
        )
        despesas = Decimal("0.00")
        for despesa in DespesaRecorrente.objects.filter(ativo=True):
            if despesa.dia_vencimento <= ultimo_dia:
                despesas += despesa.valor_mensal

        saldo_previsto = entradas_previstas - despesas
        meses.append(
            {
                "competencia": f"{mes_num:02d}/{ano}",
                "entradas_previstas": entradas_previstas,
                "despesas_previstas": despesas,
                "saldo_previsto": saldo_previsto,
            }
        )

    return render(
        request,
        "caixa/fluxo_projetado.html",
        {
            "form": form,
            "despesas_recorrentes": DespesaRecorrente.objects.select_related("ponto_operacional").all(),
            "meses": meses,
            "menu_app": "caixa",
            "menu_sub": "fluxo_projetado",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def relatorios(request):
    caixa = caixa_atual()
    data_inicio_raw = (request.GET.get("data_inicio") or "").strip()
    data_fim_raw = (request.GET.get("data_fim") or "").strip()
    data_inicio = None
    data_fim = None
    try:
        if data_inicio_raw:
            data_inicio = date.fromisoformat(data_inicio_raw)
    except ValueError:
        data_inicio = None
    try:
        if data_fim_raw:
            data_fim = date.fromisoformat(data_fim_raw)
    except ValueError:
        data_fim = None

    pagamentos = Pagamento.objects.select_related("ordem_servico", "forma_pagamento").order_by("-data")
    lancamentos = LancamentoCaixa.objects.select_related("centro_custo").order_by("-data")
    if caixa:
        pagamentos = pagamentos.filter(caixa=caixa)
        lancamentos = lancamentos.filter(caixa=caixa)
    if data_inicio:
        pagamentos = pagamentos.filter(data__date__gte=data_inicio)
        lancamentos = lancamentos.filter(data__date__gte=data_inicio)
    if data_fim:
        pagamentos = pagamentos.filter(data__date__lte=data_fim)
        lancamentos = lancamentos.filter(data__date__lte=data_fim)

    total_entradas_pagamentos = pagamentos.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas_lancamentos = lancamentos.filter(tipo="entrada").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_saidas = lancamentos.filter(tipo="saida").aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    entradas_orfas_pagamento = pagamentos.filter(lancamento_caixa__isnull=True).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    total_entradas = total_entradas_lancamentos + entradas_orfas_pagamento
    saldo_base = caixa.saldo_inicial if caixa else Decimal("0.00")
    saldo = saldo_base + total_entradas - total_saidas

    return render(
        request,
        "caixa/relatorios.html",
        {
            "caixa": caixa,
            "pagamentos": pagamentos[:500],
            "lancamentos": lancamentos[:500],
            "total_entradas": total_entradas,
            "total_entradas_pagamentos": total_entradas_pagamentos,
            "entradas_orfas_pagamento": entradas_orfas_pagamento,
            "total_saidas": total_saidas,
            "saldo": saldo,
            "data_inicio": data_inicio_raw,
            "data_fim": data_fim_raw,
            "menu_app": "caixa",
            "menu_sub": "relatorios",
        },
    )


@role_required(CAIXA_FINANCIAL_ROLES)
def garantias_fabricante(request):
    if request.method == "POST":
        if request.POST.get("action") == "sincronizar":
            total_sync = 0
            ordens_garantia = OrdemServico.objects.filter(tipo_reparo="Garantia", fechada=True).order_by("-id")
            for ordem in ordens_garantia:
                auditoria = _upsert_auditoria_garantia_ordem(ordem)
                if auditoria:
                    total_sync += 1
            messages.success(request, f"Sincronização concluída. Garantias processadas: {total_sync}.")
            return redirect("caixa:garantias_fabricante")

        auditoria = get_object_or_404(AuditoriaGarantia, id=request.POST.get("auditoria_id"))
        novo_status = (request.POST.get("status_faturamento") or "").strip()
        if novo_status in {"pendente", "enviado", "pago"}:
            auditoria.status_faturamento = novo_status
        auditoria.referencia_faturamento = (request.POST.get("referencia_faturamento") or "").strip()
        auditoria.observacoes = (request.POST.get("observacoes") or "").strip()
        auditoria.save(update_fields=["status_faturamento", "referencia_faturamento", "observacoes", "atualizado_em"])
        conta = _garantir_conta_garantia(auditoria.ordem_servico)
        if conta and auditoria.status_faturamento == "pago" and conta.status in {"aberta", "parcial", "vencida"}:
            valor_baixa = conta.valor_aberto
            conta.valor_aberto = Decimal("0.00")
            conta.atualizar_status_automatico()
            conta.save(update_fields=["valor_aberto", "status", "atualizado_em"])
            if valor_baixa > 0:
                RecebimentoConta.objects.create(
                    conta=conta,
                    valor=valor_baixa,
                    referencia=auditoria.referencia_faturamento or "BAIXA-GARANTIA",
                    observacao=f"Baixa manual via faturamento de garantia OS {auditoria.ordem_servico.numero_os}",
                    usuario=request.user,
                )
        messages.success(request, "Garantia atualizada.")
        return redirect("caixa:garantias_fabricante")

    status_filtro = (request.GET.get("status") or "").strip()
    fornecedor_id = (request.GET.get("fornecedor") or "").strip()
    garantias = AuditoriaGarantia.objects.select_related("ordem_servico", "fornecedor", "marca").all()
    if status_filtro:
        garantias = garantias.filter(status_faturamento=status_filtro)
    if fornecedor_id.isdigit():
        garantias = garantias.filter(fornecedor_id=int(fornecedor_id))

    hoje_local = timezone.localdate()
    try:
        competencia_mes = int(request.GET.get("mes") or hoje_local.month)
    except (TypeError, ValueError):
        competencia_mes = hoje_local.month
    try:
        competencia_ano = int(request.GET.get("ano") or hoje_local.year)
    except (TypeError, ValueError):
        competencia_ano = hoje_local.year
    if competencia_mes < 1 or competencia_mes > 12:
        competencia_mes = hoje_local.month
    mes_inicio = date(competencia_ano, competencia_mes, 1)
    _, ultimo_dia = monthrange(competencia_ano, competencia_mes)
    mes_fim = date(competencia_ano, competencia_mes, ultimo_dia)
    garantias_mes = garantias.filter(criado_em__date__gte=mes_inicio, criado_em__date__lte=mes_fim)

    resumo_marca_fornecedor = list(
        garantias_mes.values("fornecedor__nome", "marca__nome")
        .annotate(
            total_valor_pago=Sum("valor_previsto_fabricante"),
            total_mao_tecnico=Sum("comissao_prevista_tecnica"),
        )
        .order_by("fornecedor__nome", "marca__nome")
    )
    for row in resumo_marca_fornecedor:
        total_pago = row["total_valor_pago"] or Decimal("0.00")
        total_tecnico = row["total_mao_tecnico"] or Decimal("0.00")
        row["margem"] = total_pago - total_tecnico

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="garantias_{competencia_ano}_{competencia_mes:02d}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Fornecedor", "Marca", "Valor Pago", "Mao de Obra Tecnico", "Margem"])
        for row in resumo_marca_fornecedor:
            writer.writerow(
                [
                    row.get("fornecedor__nome") or "-",
                    row.get("marca__nome") or "-",
                    f'{row.get("total_valor_pago") or Decimal("0.00"):.2f}',
                    f'{row.get("total_mao_tecnico") or Decimal("0.00"):.2f}',
                    f'{row.get("margem") or Decimal("0.00"):.2f}',
                ]
            )
        return response

    resumo = {
        "pendente": garantias.filter(status_faturamento="pendente").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
        "enviado": garantias.filter(status_faturamento="enviado").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
        "pago": garantias.filter(status_faturamento="pago").aggregate(total=Sum("valor_previsto_fabricante"))["total"] or Decimal("0.00"),
    }
    contas_garantia_abertas = ContaReceber.objects.filter(
        tipo_origem="garantia_fabricante",
        status__in=["aberta", "parcial", "vencida"],
    )
    resumo["contas_abertas"] = contas_garantia_abertas.aggregate(total=Sum("valor_aberto"))["total"] or Decimal("0.00")
    return render(
        request,
        "caixa/garantias_fabricante.html",
        {
            "garantias": garantias[:300],
            "fornecedores": FornecedorGarantia.objects.filter(ativo=True).order_by("nome"),
            "status_filtro": status_filtro,
            "fornecedor_filtro": fornecedor_id,
            "resumo": resumo,
            "resumo_marca_fornecedor": resumo_marca_fornecedor,
            "competencia_mes": competencia_mes,
            "competencia_ano": competencia_ano,
            "menu_app": "caixa",
            "menu_sub": "garantias_fabricante",
        },
    )
