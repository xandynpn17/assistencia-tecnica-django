from datetime import date
from decimal import Decimal

from django.db import migrations


def migrar_configuracoes_legadas(apps, schema_editor):
    Empresa = apps.get_model("configuracoes", "Empresa")
    Perfil = apps.get_model("fiscal", "PerfilTributario")
    Regra = apps.get_model("fiscal", "RegraTributaria")
    for empresa in Empresa.objects.all().iterator():
        if Perfil.objects.filter(empresa_id=empresa.id).exists():
            continue
        perfil = Perfil.objects.create(
            empresa_id=empresa.id,
            nome="Configuração legada migrada",
            regime=empresa.regime_tributario or "simples",
            inicio_vigencia=date(2000, 1, 1),
            status="rascunho",
            parametros={"origem": "migração automática", "homologacao_pendente": True},
        )
        if empresa.regime_tributario == "simples" and empresa.modo_tributario == "basico":
            aliquota_produto = Decimal(str(empresa.aliquota_comercio or 0))
            aliquota_servico = Decimal(str(empresa.aliquota_servico or 0))
        else:
            aliquota_produto = aliquota_servico = sum(
                (Decimal(str(valor or 0)) for valor in (empresa.icms, empresa.ipi, empresa.pis, empresa.cofins)),
                Decimal("0"),
            )
        Regra.objects.create(
            perfil_id=perfil.id, codigo="LEGADO-COMERCIO", nome="Comércio migrado — revisar",
            tipo_item="produto", finalidade="revenda", anexo_simples=empresa.anexo_simples or "",
            aliquota_estimativa=aliquota_produto, inicio_vigencia=date(2000, 1, 1), status="rascunho",
            observacao="Regra criada da configuração anterior. Validar CNAE, anexo, faixa, segregações e tratamentos com o contador.",
        )
        Regra.objects.create(
            perfil_id=perfil.id, codigo="LEGADO-SERVICO", nome="Serviço migrado — revisar",
            tipo_item="servico", finalidade="prestacao", anexo_simples=empresa.anexo_simples or "",
            aliquota_estimativa=aliquota_servico, inicio_vigencia=date(2000, 1, 1), status="rascunho",
            observacao="Regra criada da configuração anterior. Validar anexo, Fator R, retenções e código do serviço com o contador.",
        )


def reverter(apps, schema_editor):
    Perfil = apps.get_model("fiscal", "PerfilTributario")
    Perfil.objects.filter(nome="Configuração legada migrada", parametros__origem="migração automática").delete()


class Migration(migrations.Migration):
    dependencies = [("fiscal", "0005_tributo_parametrizado_reforma")]
    operations = [migrations.RunPython(migrar_configuracoes_legadas, reverter)]
