from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Max, QuerySet
from django.utils import timezone

from ordens.models import OrdemServico


STATUS_ATIVOS_FILA = {
    "diagnosticar",
    "em_andamento",
    "pendente_tecnico",
    "pendente_pecas",
    "pendente_marca",
    "orcamentado",
    "autorizado",
    "recepcionado",
}


@dataclass
class ItemFilaBancada:
    ordem: OrdemServico
    ultima_movimentacao: object
    horas_parada: int
    prioridade_score: int
    prioridade_label: str
    proxima_acao: str


def _score_por_status(status: str) -> int:
    mapa = {
        "em_andamento": 70,
        "autorizado": 65,
        "diagnosticar": 60,
        "recepcionado": 58,
        "pendente_tecnico": 48,
        "pendente_pecas": 40,
        "pendente_marca": 36,
        "orcamentado": 30,
    }
    return mapa.get((status or "").strip(), 25)


def _proxima_acao(status: str, sem_tecnico: bool) -> str:
    if sem_tecnico:
        return "Definir tecnico responsavel para iniciar o fluxo."
    mapa = {
        "diagnosticar": "Executar diagnostico e registrar laudo inicial.",
        "em_andamento": "Continuar reparo e atualizar progresso tecnico.",
        "autorizado": "Priorizar execucao e confirmar pecas necessarias.",
        "recepcionado": "Retomar triagem apos retorno do parceiro.",
        "pendente_tecnico": "Cobrar retorno tecnico e atualizar cliente.",
        "pendente_pecas": "Validar previsao de chegada das pecas.",
        "pendente_marca": "Cobrar protocolo/retorno junto a marca.",
        "orcamentado": "Reforcar follow-up com cliente para aprovacao.",
    }
    return mapa.get((status or "").strip(), "Atualizar linha de trabalho e definir proximo passo.")


def montar_fila_bancada(*, empresa=None, tecnico_id=None, status=None, prioridade=None) -> list[ItemFilaBancada]:
    now = timezone.now()
    ordens_qs: QuerySet = OrdemServico.objects.filter(fechada=False, status__in=STATUS_ATIVOS_FILA).select_related(
        "cliente",
        "tecnico_responsavel",
    )
    if empresa:
        ordens_qs = ordens_qs.filter(empresa=empresa)
    if tecnico_id and str(tecnico_id).isdigit():
        ordens_qs = ordens_qs.filter(tecnico_responsavel_id=int(tecnico_id))
    if status:
        ordens_qs = ordens_qs.filter(status=status)

    ordens_qs = ordens_qs.annotate(ultima_movimentacao=Max("linhas_trabalho__criado_em")).order_by("data_abertura")
    itens: list[ItemFilaBancada] = []
    for ordem in ordens_qs:
        referencia = ordem.ultima_movimentacao or ordem.data_abertura
        horas_parada = max(int((now - referencia).total_seconds() // 3600), 0) if referencia else 0
        dias_parada = horas_parada // 24
        sem_tecnico = ordem.tecnico_responsavel_valido is None

        score = _score_por_status(ordem.status)
        score += min(dias_parada * 2, 40)
        if horas_parada >= 72:
            score += 10
        if sem_tecnico:
            score += 14

        if score >= 90:
            prioridade_label = "Critica"
        elif score >= 70:
            prioridade_label = "Alta"
        elif score >= 50:
            prioridade_label = "Media"
        else:
            prioridade_label = "Baixa"

        itens.append(
            ItemFilaBancada(
                ordem=ordem,
                ultima_movimentacao=referencia,
                horas_parada=horas_parada,
                prioridade_score=score,
                prioridade_label=prioridade_label,
                proxima_acao=_proxima_acao(ordem.status, sem_tecnico),
            )
        )

    if prioridade:
        prioridade_norm = (prioridade or "").strip().lower()
        itens = [item for item in itens if item.prioridade_label.lower() == prioridade_norm]
    itens.sort(key=lambda i: (-i.prioridade_score, -i.horas_parada, i.ordem.numero_os))
    return itens

