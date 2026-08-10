from copy import copy
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import RegraTributaria


@transaction.atomic
def criar_nova_versao_regra(*, regra, inicio_vigencia, aliquota_estimativa, fonte_normativa, observacao, usuario):
    regra = RegraTributaria.objects.select_for_update().get(pk=regra.pk)
    if regra.status != "homologado":
        raise ValidationError("Somente uma regra homologada pode originar nova versão.")
    if inicio_vigencia <= regra.inicio_vigencia:
        raise ValidationError("A nova vigência deve iniciar depois da versão homologada.")
    if RegraTributaria.objects.filter(perfil=regra.perfil, codigo=regra.codigo, inicio_vigencia=inicio_vigencia).exists():
        raise ValidationError("Já existe uma versão desta regra na data informada.")
    faixas = list(regra.faixas.all())
    tributos = list(regra.tributos_parametrizados.all())
    RegraTributaria.objects.filter(pk=regra.pk).update(fim_vigencia=inicio_vigencia - timedelta(days=1))
    nova = copy(regra)
    nova.pk = None
    nova.inicio_vigencia = inicio_vigencia
    nova.fim_vigencia = None
    nova.status = "rascunho"
    nova.aliquota_estimativa = aliquota_estimativa
    nova.fonte_normativa = (fonte_normativa or "").strip()
    nova.observacao = (observacao or "").strip()
    nova.homologado_por = None
    nova.homologado_em = None
    nova.save()
    for faixa in faixas:
        faixa.pk = None
        faixa.regra = nova
        faixa.save()
    for tributo in tributos:
        tributo.pk = None
        tributo.regra = nova
        tributo.save()
    return nova
