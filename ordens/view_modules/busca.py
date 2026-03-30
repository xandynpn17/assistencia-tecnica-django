import re
from datetime import timedelta

from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.generic import ListView

from configuracoes.models import ConfiguracaoSistema
from configuracoes.permissions import ORDER_ROLES, RoleRequiredMixin, role_required

from ..models import LinhaTrabalho, OrdemServico


QUICK_FILTERS = (
    ("minhas", "Minhas OS"),
    ("sem_tecnico", "Sem técnico"),
    ("aguardando_cliente", "Aguardando cliente"),
    ("aguardando_pecas", "Aguardando peças"),
    ("prontas", "Prontas"),
)

QUICK_FILTER_LABELS = {
    **dict(QUICK_FILTERS),
    "criticas": "Pendencias criticas",
    "paradas_15": "Paradas ha 15+ dias",
}


def _aplicar_busca_ordens(queryset, termo_busca):
    termo = (termo_busca or "").strip()
    if not termo:
        return queryset

    termo_lower = termo.lower()
    digits = re.sub(r"\D", "", termo)
    config = ConfiguracaoSistema.get_configuracao()
    minimo_numerico = max(int(getattr(config, "busca_minimo_caracteres", 3) or 3), 3)

    if termo_lower.startswith("tel:"):
        tel = re.sub(r"\D", "", termo_lower.replace("tel:", "").strip())
        if len(tel) < minimo_numerico:
            return queryset.none()
        return queryset.filter(cliente__telefone__icontains=tel)

    if termo_lower.startswith("cpf:"):
        cpf = re.sub(r"\D", "", termo_lower.replace("cpf:", "").strip())
        if len(cpf) < minimo_numerico:
            return queryset.none()
        return queryset.filter(cliente__documento__icontains=cpf)

    if termo_lower.startswith("id:"):
        cliente_id = termo_lower.replace("id:", "").strip()
        return queryset.filter(cliente__id=cliente_id)

    if termo_lower.startswith("sn:"):
        serial = termo[3:].strip()
        if len(serial) < 3:
            return queryset.none()
        return queryset.filter(numero_serie_equipamento__icontains=serial)

    termo_os = termo.upper().replace(" ", "")
    if re.fullmatch(r"OS-\d{4,}", termo_os):
        return queryset.filter(numero_os__iexact=termo_os)
    if digits and termo == digits and len(digits) >= 4:
        return queryset.filter(numero_os__iendswith=f"-{digits}")

    return queryset.none()


def _mensagem_busca_ordens_invalida(termo_busca):
    termo = (termo_busca or "").strip()
    if not termo:
        return ""

    termo_lower = termo.lower()
    digits = re.sub(r"\D", "", termo)
    config = ConfiguracaoSistema.get_configuracao()
    minimo_numerico = max(int(getattr(config, "busca_minimo_caracteres", 3) or 3), 3)

    if termo_lower.startswith(("cpf:", "tel:")) and len(digits) < minimo_numerico:
        return f"Use pelo menos {minimo_numerico} numeros apos cpf: ou tel:."
    if termo_lower.startswith("sn:") and len((termo[3:] or "").strip()) < 3:
        return "Use pelo menos 3 caracteres apos sn:."
    if re.fullmatch(r"OS-\d{4,}", termo.upper().replace(" ", "")):
        return ""
    if digits and termo == digits and len(digits) >= 4:
        return ""
    if termo_lower.startswith(("cpf:", "tel:", "sn:", "id:")):
        return ""
    return "Use o numero exato da OS ou os prefixos cpf:, tel: ou sn:."


def _aplicar_filtro_rapido_ordens(queryset, quick_filter, user):
    quick = (quick_filter or "").strip()
    sem_tecnico_q = Q(tecnico_responsavel__isnull=True) | ~Q(tecnico_responsavel__tipo_usuario="tecnico")
    if not quick:
        return queryset
    if quick == "minhas":
        return queryset.filter(tecnico_responsavel=user)
    if quick == "sem_tecnico":
        return queryset.filter(sem_tecnico_q)
    if quick == "aguardando_cliente":
        return queryset.filter(status="pendente_cliente")
    if quick == "aguardando_pecas":
        return queryset.filter(status="pendente_pecas")
    if quick == "prontas":
        return queryset.filter(status__in=["pronto_contactar", "pronto_contactado"])
    if quick == "criticas":
        return queryset.filter(status__in=["pendente_cliente", "pendente_tecnico", "pendente_pecas", "pendente_marca"])
    if quick == "paradas_15":
        limite_parada = timezone.now() - timedelta(days=15)
        return queryset.filter(
            status__in=["pendente_cliente", "pendente_tecnico", "pendente_pecas", "pendente_marca"],
            data_abertura__lte=limite_parada,
        )
    return queryset.none()


@role_required(ORDER_ROLES)
def buscar_ordens(request):
    query = request.GET.get("q", "").strip()
    resultados = OrdemServico.objects.none()

    if query:
        resultados = _aplicar_busca_ordens(
            OrdemServico.objects.select_related("cliente").all(),
            query,
        ).order_by("-data_abertura")

    data = [
        {
            "id": ordem.pk,
            "numero_os": ordem.numero_os,
            "cliente": ordem.cliente.nome,
            "telefone": ordem.cliente.telefone,
            "cpf": ordem.cliente.documento or "",
            "url": f"/ordens/{ordem.pk}/detalhes/",
        }
        for ordem in resultados[:30]
    ]

    return JsonResponse({"resultados": data})


class OrdemServicoListView(RoleRequiredMixin, ListView):
    allowed_roles = ORDER_ROLES
    model = OrdemServico
    template_name = "ordens/ordem_servico_list.html"
    context_object_name = "ordens"
    paginate_by = 25

    def _tem_filtros_aplicados(self):
        return bool(
            (self.request.GET.get("status") or "").strip()
            or (self.request.GET.get("quick") or "").strip()
            or self.request.GET.get("carregar") == "1"
        )

    def _get_base_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("cliente", "tecnico_responsavel")
            .prefetch_related(
                Prefetch(
                    "linhas_trabalho",
                    queryset=LinhaTrabalho.objects.select_related("usuario").order_by("id"),
                )
            )
            .order_by("-data_abertura")
        )
        q = (self.request.GET.get("q") or "").strip()
        if q:
            queryset = _aplicar_busca_ordens(queryset, q)
        quick_filter = (self.request.GET.get("quick") or "").strip()
        if quick_filter:
            queryset = _aplicar_filtro_rapido_ordens(queryset, quick_filter, self.request.user)
        return queryset

    def get_queryset(self):
        if not self._tem_filtros_aplicados():
            return self.model.objects.none()

        queryset = self._get_base_queryset()
        status = (self.request.GET.get("status") or "").strip()
        if status == "concluida":
            return queryset.filter(fechada=True)
        if status:
            return queryset.filter(fechada=False, status=status)
        return queryset.filter(fechada=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip()
        filtros_aplicados = self._tem_filtros_aplicados()
        status_filtro = self.request.GET.get("status", "")
        quick_filter = (self.request.GET.get("quick") or "").strip()
        context["menu_app"] = "ordens"
        context["menu_sub"] = "lista_ordens"
        context["q"] = q
        context["filtros_aplicados"] = filtros_aplicados
        context["status_filtro"] = status_filtro
        context["status_filtro_label"] = dict(self.model.STATUS_CHOICES).get(status_filtro, "")
        context["quick_filter"] = quick_filter
        context["quick_filter_label"] = QUICK_FILTER_LABELS.get(quick_filter, "")
        context["carregar_lista"] = self.request.GET.get("carregar") == "1"
        context["busca_erro"] = _mensagem_busca_ordens_invalida(q) if filtros_aplicados else ""
        paginator = context.get("paginator")
        context["total_filtrado"] = paginator.count if paginator else len(self.object_list)
        status_cards = []
        if filtros_aplicados:
            base_queryset = self._get_base_queryset()
            abertas_queryset = base_queryset.filter(fechada=False)
            status_totais = dict(
                abertas_queryset.values("status").annotate(total=Count("id")).values_list("status", "total")
            )
            concluidas_total = base_queryset.filter(fechada=True).count()
            total_base = abertas_queryset.count() + concluidas_total
            status_cards.append(
                {
                    "codigo": "",
                    "rotulo": "Todos",
                    "total": total_base,
                    "ativo": not status_filtro,
                }
            )
            for codigo, rotulo in self.model.STATUS_CHOICES:
                status_cards.append(
                    {
                        "codigo": codigo,
                        "rotulo": rotulo,
                        "total": concluidas_total if codigo == "concluida" else status_totais.get(codigo, 0),
                        "ativo": status_filtro == codigo,
                    }
                )
        context["status_cards"] = status_cards
        return context


__all__ = ["OrdemServicoListView", "buscar_ordens"]
