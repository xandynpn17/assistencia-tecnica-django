import logging
from dataclasses import dataclass
from typing import Callable

import requests
from django.core.cache import cache


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CepConsultaResultado:
    ok: bool
    status: int
    payload: dict


def _normalizar_cep(cep: str) -> str:
    return (cep or "").replace("-", "").strip()


def _consultar_viacep(cep: str, timeout: int) -> CepConsultaResultado:
    response = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=timeout)
    data = response.json()
    if "erro" in data:
        return CepConsultaResultado(False, 404, {"erro": "CEP não encontrado"})
    return CepConsultaResultado(
        True,
        200,
        {
            "logradouro": data.get("logradouro", ""),
            "bairro": data.get("bairro", ""),
            "cidade": data.get("localidade", ""),
            "estado": data.get("uf", ""),
            "complemento": data.get("complemento", ""),
        },
    )


def _consultar_brasilapi(cep: str, timeout: int) -> CepConsultaResultado:
    response = requests.get(f"https://brasilapi.com.br/api/cep/v1/{cep}", timeout=timeout)
    data = response.json()
    if "street" not in data:
        return CepConsultaResultado(False, 404, {"erro": "CEP não encontrado"})
    return CepConsultaResultado(
        True,
        200,
        {
            "logradouro": data.get("street", ""),
            "bairro": data.get("neighborhood", ""),
            "cidade": data.get("city", ""),
            "estado": data.get("state", ""),
            "complemento": data.get("complement", ""),
        },
    )


def _consultar_awesomeapi(cep: str, timeout: int) -> CepConsultaResultado:
    response = requests.get(f"https://cep.awesomeapi.com.br/json/{cep}", timeout=timeout)
    data = response.json()
    if "address" not in data:
        return CepConsultaResultado(False, 404, {"erro": "CEP não encontrado"})
    return CepConsultaResultado(
        True,
        200,
        {
            "logradouro": data.get("address", ""),
            "bairro": data.get("district", ""),
            "cidade": data.get("city", ""),
            "estado": data.get("state", ""),
            "complemento": data.get("complement", ""),
        },
    )


PROVIDERS: dict[str, Callable[[str, int], CepConsultaResultado]] = {
    "viacep": _consultar_viacep,
    "brasilapi": _consultar_brasilapi,
    "awesomeapi": _consultar_awesomeapi,
}


def consultar_cep(*, cep: str, provedor_prioritario: str, timeout: int = 5, ttl_cache_segundos: int = 900) -> CepConsultaResultado:
    cep_limpo = _normalizar_cep(cep)
    if len(cep_limpo) != 8 or not cep_limpo.isdigit():
        return CepConsultaResultado(False, 400, {"erro": "CEP inválido"})

    cache_key = f"configuracoes:cep:{cep_limpo}"
    cached = cache.get(cache_key)
    if cached:
        return CepConsultaResultado(True, 200, cached)

    ordem = [provedor_prioritario] + [p for p in PROVIDERS.keys() if p != provedor_prioritario]
    for provedor in ordem:
        consulta = PROVIDERS.get(provedor)
        if not consulta:
            continue
        try:
            resultado = consulta(cep_limpo, timeout)
            if resultado.ok:
                cache.set(cache_key, resultado.payload, ttl_cache_segundos)
                return resultado
            if resultado.status == 404:
                return resultado
        except requests.exceptions.RequestException as exc:
            logger.warning("Falha no provedor %s para CEP %s: %s", provedor, cep_limpo, exc)
            continue
        except Exception:
            logger.exception("Erro inesperado no provedor %s para CEP %s", provedor, cep_limpo)
            continue
    return CepConsultaResultado(False, 502, {"erro": "Não foi possível consultar o CEP agora. Tente novamente."})
