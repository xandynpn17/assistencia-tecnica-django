from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.db import transaction

from configuracoes.models import Empresa, SetupInicialSistema
from configuracoes.services.saas_readiness import MODELOS_CRITICOS


@dataclass
class ReparoEmpresaUnicaResultado:
    empresa_id: int | None
    atualizados: dict[str, int]
    setup_atualizado: bool

    @property
    def total_atualizado(self) -> int:
        return sum(self.atualizados.values())


def obter_empresa_padrao_para_restore() -> Empresa | None:
    try:
        setup = SetupInicialSistema.get_setup()
        if setup.empresa_id:
            return setup.empresa
    except SetupInicialSistema.DoesNotExist:
        pass
    return Empresa.objects.order_by("id").first()


def reparar_escopo_empresa_unica(*, empresa: Empresa | None = None, dry_run: bool = False) -> ReparoEmpresaUnicaResultado:
    """
    Corrige dados legados/restaurados sem empresa em ambientes locais de empresa unica.

    Em SaaS real nao devemos associar registros sem tenant automaticamente. Para a
    versao local, isso evita que dados antigos fiquem invisiveis em telas que ja
    filtram pela empresa ativa.
    """
    empresa = empresa or obter_empresa_padrao_para_restore()
    if not empresa:
        return ReparoEmpresaUnicaResultado(empresa_id=None, atualizados={}, setup_atualizado=False)

    atualizados: dict[str, int] = {}
    setup_atualizado = False

    with transaction.atomic():
        try:
            setup = SetupInicialSistema.get_setup()
            if not setup.empresa_id:
                setup_atualizado = True
                if not dry_run:
                    setup.empresa = empresa
                    setup.save(update_fields=["empresa"])
        except SetupInicialSistema.DoesNotExist:
            pass

        for label in MODELOS_CRITICOS:
            app_label, model_name = label.split(".", 1)
            model = apps.get_model(app_label, model_name)
            if model is None:
                continue

            campos = {field.name for field in model._meta.get_fields()}
            if "empresa" not in campos:
                continue

            queryset = model.objects.filter(empresa__isnull=True)
            quantidade = queryset.count()
            if quantidade:
                atualizados[label] = quantidade
                if not dry_run:
                    queryset.update(empresa=empresa)

    return ReparoEmpresaUnicaResultado(
        empresa_id=empresa.id,
        atualizados=atualizados,
        setup_atualizado=setup_atualizado,
    )
