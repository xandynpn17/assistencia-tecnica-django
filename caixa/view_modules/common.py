from ..models import Caixa
from .helpers import _upsert_auditoria_garantia_ordem


def caixa_atual():
    return Caixa.objects.filter(aberto=True).last()


__all__ = ["_upsert_auditoria_garantia_ordem", "caixa_atual"]
