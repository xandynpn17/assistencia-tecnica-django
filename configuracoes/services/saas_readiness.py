from django.apps import apps
from django.conf import settings


MODELOS_CRITICOS = [
    "clientes.Cliente",
    "ordens.OrdemServico",
    "orcamentos.Orcamento",
    "estoque.Produto",
    "caixa.ContaReceber",
    "caixa.ContaPagar",
]


def _modelo_por_label(label):
    try:
        app_label, model_name = label.split(".", 1)
        return apps.get_model(app_label, model_name)
    except Exception:
        return None


def diagnostico_tenant_scope():
    resultados = []
    for label in MODELOS_CRITICOS:
        model = _modelo_por_label(label)
        if not model:
            resultados.append({"modelo": label, "status": "ausente", "detalhe": "Modelo nao encontrado."})
            continue
        campos = {field.name for field in model._meta.get_fields()}
        if "empresa" in campos:
            resultados.append({"modelo": label, "status": "ok", "detalhe": "Escopo por empresa identificado."})
        elif "tenant_id" in campos:
            resultados.append({"modelo": label, "status": "ok", "detalhe": "Escopo por tenant_id identificado."})
        else:
            resultados.append({"modelo": label, "status": "pendente", "detalhe": "Sem escopo tenant explicito."})
    return resultados


def diagnostico_ambiente_saas():
    return {
        "tenant_middleware_ativo": getattr(settings, "TENANT_CONTEXT_ENABLED", False),
        "db_engine": settings.DATABASES.get("default", {}).get("ENGINE", ""),
        "resultados_modelos": diagnostico_tenant_scope(),
    }
