from dataclasses import dataclass
from datetime import timedelta

from django.db import models
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from configuracoes.models import RegraSLAAlerta
from estoque.models import ReservaEstoque
from ordens.models import GuiaExpedicaoItem, LinhaTrabalho, OrdemServico


REGRAS_SLA_DEFAULT = {
    "os_sem_movimentacao": {
        "prazo_valor": 2,
        "prazo_unidade": "dias",
        "severidade": "alta",
        "responsavel_padrao": "Atendimento",
        "acao_sugerida": "Atualizar linha de trabalho e validar proximo passo.",
        "canal_notificacao": "painel",
        "observacoes": "Monitora ordens sem qualquer evolucao tecnica recente.",
    },
    "orcamento_sem_resposta": {
        "prazo_valor": 2,
        "prazo_unidade": "dias",
        "severidade": "alta",
        "responsavel_padrao": "Atendimento",
        "acao_sugerida": "Reforcar contato com cliente para decisao do orcamento.",
        "canal_notificacao": "painel",
        "observacoes": "Considera OS em status Orcamentado sem evolucao.",
    },
    "peca_reservada_vencendo": {
        "prazo_valor": 2,
        "prazo_unidade": "dias",
        "severidade": "media",
        "responsavel_padrao": "Estoque",
        "acao_sugerida": "Converter, renovar ou cancelar a reserva conforme contexto.",
        "canal_notificacao": "painel",
        "observacoes": "Inclui reservas vencidas e proximas do vencimento.",
    },
    "equipamento_pronto_parado": {
        "prazo_valor": 3,
        "prazo_unidade": "dias",
        "severidade": "media",
        "responsavel_padrao": "Atendimento",
        "acao_sugerida": "Recontatar cliente e registrar tentativa.",
        "canal_notificacao": "painel",
        "observacoes": "Monitora OS prontas para retirada sem fechamento.",
    },
    "parceiro_externo_atrasado": {
        "prazo_valor": 5,
        "prazo_unidade": "dias",
        "severidade": "alta",
        "responsavel_padrao": "Atendimento tecnico",
        "acao_sugerida": "Cobrar parceiro e atualizar referencia de retorno.",
        "canal_notificacao": "painel",
        "observacoes": "Ordens expedidas sem recepcao dentro do prazo esperado.",
    },
}


@dataclass
class PendenciaSLA:
    codigo_regra: str
    regra_label: str
    severidade: str
    severidade_label: str
    descricao: str
    referencia: str
    acao_sugerida: str
    responsavel_padrao: str
    destino_url: str
    ordem_id: int | None = None
    reserva_id: int | None = None
    guia_item_id: int | None = None


def _prazo_delta(regra: RegraSLAAlerta) -> timedelta:
    valor = int(regra.prazo_valor or 0)
    valor = max(valor, 1)
    if regra.prazo_unidade == "horas":
        return timedelta(hours=valor)
    return timedelta(days=valor)


def garantir_regras_sla_padrao():
    for codigo, defaults in REGRAS_SLA_DEFAULT.items():
        RegraSLAAlerta.objects.get_or_create(codigo=codigo, defaults=defaults)


def carregar_regras_sla():
    garantir_regras_sla_padrao()
    return RegraSLAAlerta.objects.all().order_by("codigo")


def calcular_pendencias_sla(*, empresa=None):
    garantir_regras_sla_padrao()
    agora = timezone.now()
    hoje = timezone.localdate()
    pendencias: list[PendenciaSLA] = []
    regras = {r.codigo: r for r in RegraSLAAlerta.objects.filter(ativo=True)}

    regra_os = regras.get("os_sem_movimentacao")
    if regra_os:
        limite = agora - _prazo_delta(regra_os)
        ordens = (
            OrdemServico.objects.filter(fechada=False)
            .annotate(ultima_movimentacao=Max("linhas_trabalho__criado_em"))
            .select_related("cliente")
        )
        if empresa:
            ordens = ordens.filter(empresa=empresa)
        for ordem in ordens:
            referencia = ordem.ultima_movimentacao or ordem.data_abertura
            if referencia and referencia <= limite:
                dias = max((agora.date() - referencia.date()).days, 0)
                pendencias.append(
                    PendenciaSLA(
                        codigo_regra=regra_os.codigo,
                        regra_label=regra_os.get_codigo_display(),
                        severidade=regra_os.severidade,
                        severidade_label=regra_os.get_severidade_display(),
                        descricao=f"OS {ordem.numero_os} sem movimentacao recente (status {ordem.get_status_display()}).",
                        referencia=f"Ultima evolucao ha {dias} dia(s).",
                        acao_sugerida=regra_os.acao_sugerida,
                        responsavel_padrao=regra_os.responsavel_padrao,
                        destino_url=reverse("ordens:detalhes_ordem", kwargs={"pk": ordem.pk}),
                        ordem_id=ordem.pk,
                    )
                )

    regra_orc = regras.get("orcamento_sem_resposta")
    if regra_orc:
        limite = agora - _prazo_delta(regra_orc)
        ultimas_orcadas = (
            LinhaTrabalho.objects.filter(status="orcamentado")
            .values("ordem_id")
            .annotate(data_max=Max("criado_em"))
        )
        mapa_ultima_orc = {linha["ordem_id"]: linha["data_max"] for linha in ultimas_orcadas}
        ordens_orc = OrdemServico.objects.filter(fechada=False, status="orcamentado")
        if empresa:
            ordens_orc = ordens_orc.filter(empresa=empresa)
        for ordem in ordens_orc:
            referencia = mapa_ultima_orc.get(ordem.id) or ordem.data_abertura
            if referencia and referencia <= limite:
                dias = max((agora.date() - referencia.date()).days, 0)
                pendencias.append(
                    PendenciaSLA(
                        codigo_regra=regra_orc.codigo,
                        regra_label=regra_orc.get_codigo_display(),
                        severidade=regra_orc.severidade,
                        severidade_label=regra_orc.get_severidade_display(),
                        descricao=f"OS {ordem.numero_os} esta orcamentada sem resposta do cliente.",
                        referencia=f"Orcamento pendente ha {dias} dia(s).",
                        acao_sugerida=regra_orc.acao_sugerida,
                        responsavel_padrao=regra_orc.responsavel_padrao,
                        destino_url=reverse("ordens:detalhes_ordem", kwargs={"pk": ordem.pk}),
                        ordem_id=ordem.pk,
                    )
                )

    regra_res = regras.get("peca_reservada_vencendo")
    if regra_res:
        dias_alerta = max(int(regra_res.prazo_valor or 1), 1)
        limite_data = hoje + timedelta(days=dias_alerta)
        reservas = (
            ReservaEstoque.objects.filter(status="ativa", valido_ate__isnull=False, valido_ate__lte=limite_data)
            .select_related("produto", "ordem_servico")
            .order_by("valido_ate")
        )
        if empresa:
            reservas = reservas.filter(
                models.Q(ordem_servico__empresa=empresa)
                | models.Q(ordem_servico__isnull=True, produto__empresa=empresa)
            ).distinct()
        for reserva in reservas:
            dias = (reserva.valido_ate - hoje).days
            if dias < 0:
                referencia = f"Vencida ha {abs(dias)} dia(s)."
            elif dias == 0:
                referencia = "Vence hoje."
            else:
                referencia = f"Vence em {dias} dia(s)."
            os_desc = f"OS {reserva.ordem_servico.numero_os}" if reserva.ordem_servico_id else "Sem OS vinculada"
            pendencias.append(
                PendenciaSLA(
                    codigo_regra=regra_res.codigo,
                    regra_label=regra_res.get_codigo_display(),
                    severidade=regra_res.severidade,
                    severidade_label=regra_res.get_severidade_display(),
                    descricao=f"Reserva {reserva.codigo_reserva} ({reserva.produto.nome}) - {os_desc}.",
                    referencia=referencia,
                    acao_sugerida=regra_res.acao_sugerida,
                    responsavel_padrao=regra_res.responsavel_padrao,
                    destino_url=reverse("estoque:reservas_clientes"),
                    ordem_id=reserva.ordem_servico_id,
                    reserva_id=reserva.pk,
                )
            )

    regra_pronto = regras.get("equipamento_pronto_parado")
    if regra_pronto:
        limite = agora - _prazo_delta(regra_pronto)
        ultimos_prontos = (
            LinhaTrabalho.objects.filter(status="pronto_contactado")
            .values("ordem_id")
            .annotate(data_max=Max("criado_em"))
        )
        mapa_pronto = {linha["ordem_id"]: linha["data_max"] for linha in ultimos_prontos}
        ordens_prontas = OrdemServico.objects.filter(fechada=False, status="pronto_contactado")
        if empresa:
            ordens_prontas = ordens_prontas.filter(empresa=empresa)
        for ordem in ordens_prontas:
            referencia = mapa_pronto.get(ordem.id) or ordem.data_conclusao or ordem.data_abertura
            if referencia and referencia <= limite:
                dias = max((agora.date() - referencia.date()).days, 0)
                pendencias.append(
                    PendenciaSLA(
                        codigo_regra=regra_pronto.codigo,
                        regra_label=regra_pronto.get_codigo_display(),
                        severidade=regra_pronto.severidade,
                        severidade_label=regra_pronto.get_severidade_display(),
                        descricao=f"OS {ordem.numero_os} pronta e ainda sem fechamento/retirada.",
                        referencia=f"Pronta ha {dias} dia(s).",
                        acao_sugerida=regra_pronto.acao_sugerida,
                        responsavel_padrao=regra_pronto.responsavel_padrao,
                        destino_url=reverse("ordens:detalhes_ordem", kwargs={"pk": ordem.pk}),
                        ordem_id=ordem.pk,
                    )
                )

    regra_parc = regras.get("parceiro_externo_atrasado")
    if regra_parc:
        limite = agora - _prazo_delta(regra_parc)
        itens = (
            GuiaExpedicaoItem.objects.filter(status="expedida")
            .select_related("guia", "ordem_servico")
            .order_by("guia__expedida_em")
        )
        if empresa:
            itens = itens.filter(ordem_servico__empresa=empresa)
        for item in itens:
            referencia = item.guia.expedida_em
            if referencia and referencia <= limite:
                dias = max((agora.date() - referencia.date()).days, 0)
                pendencias.append(
                    PendenciaSLA(
                        codigo_regra=regra_parc.codigo,
                        regra_label=regra_parc.get_codigo_display(),
                        severidade=regra_parc.severidade,
                        severidade_label=regra_parc.get_severidade_display(),
                        descricao=(
                            f"{item.guia.numero_guia} - OS {item.ordem_servico.numero_os} "
                            f"enviada para {item.guia.parceiro_nome}."
                        ),
                        referencia=f"Expedida ha {dias} dia(s), aguardando recepcao.",
                        acao_sugerida=regra_parc.acao_sugerida,
                        responsavel_padrao=regra_parc.responsavel_padrao,
                        destino_url=reverse("ordens:recepcionar_parceiro"),
                        ordem_id=item.ordem_servico_id,
                        guia_item_id=item.pk,
                    )
                )

    severidade_ordem = {"critica": 0, "alta": 1, "media": 2, "baixa": 3}
    pendencias.sort(key=lambda p: (severidade_ordem.get(p.severidade, 9), p.codigo_regra, p.descricao))
    return pendencias


def resumo_pendencias_por_regra(pendencias: list[PendenciaSLA]):
    resumo = {}
    for item in pendencias:
        bloco = resumo.setdefault(
            item.codigo_regra,
            {
                "codigo": item.codigo_regra,
                "label": item.regra_label,
                "severidade": item.severidade,
                "severidade_label": item.severidade_label,
                "total": 0,
            },
        )
        bloco["total"] += 1
    return sorted(resumo.values(), key=lambda x: x["label"])


