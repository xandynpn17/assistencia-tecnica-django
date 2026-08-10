from ..models import Caixa
from .helpers import _upsert_auditoria_garantia_ordem


def caixa_atual(empresa=None):
    caixas = Caixa.objects.filter(aberto=True)
    caixas = caixas.filter(empresa=empresa) if empresa is not None else caixas.filter(empresa__isnull=True)
    return caixas.last()


__all__ = ["_upsert_auditoria_garantia_ordem", "caixa_atual"]
