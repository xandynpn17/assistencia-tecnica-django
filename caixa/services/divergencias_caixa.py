from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from configuracoes.permissions import require_sensitive_permission


@transaction.atomic
def aprovar_divergencia(*, divergencia, observacao, usuario):
    from caixa.models import DivergenciaCaixa

    require_sensitive_permission(usuario, "perm_caixa_corrigir_lancamentos")
    observacao = (observacao or "").strip()
    if len(observacao) < 12:
        raise ValidationError("Informe uma observacao de aprovacao com pelo menos 12 caracteres.")
    divergencia = DivergenciaCaixa.objects.select_for_update().get(pk=divergencia.pk)
    if divergencia.status == "aprovada":
        return divergencia
    if divergencia.status != "pendente":
        raise ValidationError("Somente divergencias pendentes podem ser aprovadas.")
    divergencia.status = "aprovada"
    divergencia.observacao_analise = observacao
    divergencia.aprovada_por = usuario
    divergencia.aprovada_em = timezone.now()
    divergencia.save(
        update_fields=["status", "observacao_analise", "aprovada_por", "aprovada_em"]
    )
    return divergencia
