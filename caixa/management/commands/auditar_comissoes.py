from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from caixa.models import Comissao
from caixa.services.comissoes import _fontes_comissionaveis
from estoque.models import VendaRapidaEstoque


TIPOS_COM_FONTE = {"SERVICO", "PECA", "BONUS_PRODUTO", "COMISSAO_VENDAS"}


class Command(BaseCommand):
    help = "Audita inconsistências de comissões (fonte, valores e status)."

    def add_arguments(self, parser):
        parser.add_argument("--os-id", type=int, default=None, help="Filtra auditoria para uma OS específica.")
        parser.add_argument(
            "--status",
            choices=["GERADA", "LIBERADA", "PAGA", "CANCELADA"],
            default=None,
            help="Filtra auditoria por status de comissão.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Limite de linhas detalhadas exibidas no final (padrão: 50).",
        )
        parser.add_argument(
            "--falhar-se-divergir",
            action="store_true",
            help="Retorna erro (exit code != 0) quando encontrar inconsistências.",
        )

    def handle(self, *args, **options):
        os_id = options["os_id"]
        status = options["status"]
        limit = max(int(options["limit"] or 0), 0)
        falhar = bool(options["falhar_se_divergir"])

        queryset = Comissao.objects.select_related("ordem_servico", "item_orcamento", "tecnico").order_by("id")
        if os_id:
            queryset = queryset.filter(ordem_servico_id=os_id)
        if status:
            queryset = queryset.filter(status=status)

        comissoes = list(queryset)
        total = len(comissoes)

        self.stdout.write(f"Comissões analisadas: {total}")

        fontes_cache = {}
        issues = []
        issues_count = defaultdict(int)
        assinaturas = defaultdict(list)

        for comissao in comissoes:
            self._auditar_por_status_e_valor(comissao, issues, issues_count)
            self._auditar_fonte(comissao, fontes_cache, issues, issues_count)
            self._mapear_assinatura_duplicidade(comissao, assinaturas)

        self._auditar_duplicidade_assinatura(assinaturas, issues, issues_count)

        if not issues:
            self.stdout.write(self.style.SUCCESS("Nenhuma inconsistência encontrada."))
            return

        self.stdout.write(self.style.WARNING(f"Inconsistências encontradas: {len(issues)}"))
        self.stdout.write("Resumo por tipo:")
        for tipo, qtd in sorted(issues_count.items(), key=lambda x: x[0]):
            self.stdout.write(f"- {tipo}: {qtd}")

        if limit > 0:
            self.stdout.write(f"Detalhes (até {limit}):")
            for issue in issues[:limit]:
                self.stdout.write(
                    "- [{kind}] comissão #{id} | OS {os} | status {status} | chave {chave} | {detalhe}".format(
                        kind=issue["kind"],
                        id=issue["comissao_id"],
                        os=issue["os_numero"],
                        status=issue["status"],
                        chave=issue["chave_unica"],
                        detalhe=issue["detalhe"],
                    )
                )

        if falhar:
            raise CommandError("Auditoria de comissões encontrou inconsistências.")

    def _fontes_validas_por_ordem(self, ordem):
        if not ordem:
            return {k: set() for k in TIPOS_COM_FONTE}
        validas = {k: set() for k in TIPOS_COM_FONTE}
        for fonte in _fontes_comissionaveis(ordem):
            chave_ref = (fonte.get("chave_ref") or "").strip()
            if not chave_ref:
                continue
            tipo_item = (fonte.get("tipo_item") or "").strip().lower()
            if tipo_item == "servico":
                validas["SERVICO"].add(chave_ref)
            elif tipo_item == "peca":
                validas["PECA"].add(chave_ref)
                validas["BONUS_PRODUTO"].add(chave_ref)
        return validas

    def _venda_rapida_valida(self, chave_ref: str):
        prefixo, _, venda_id = str(chave_ref or "").partition(":")
        if prefixo != "venda" or not venda_id.isdigit():
            return None
        return (
            VendaRapidaEstoque.objects.select_related("produto")
            .filter(id=int(venda_id), status="vendida")
            .first()
        )

    def _parse_chave_unica(self, chave_unica: str):
        parts = str(chave_unica or "").split(":", 2)
        if len(parts) < 3:
            return "", "", ""
        evento, tipo, chave_ref = parts[0], parts[1], parts[2]
        return evento.strip().upper(), tipo.strip().upper(), chave_ref.strip()

    def _registrar_issue(self, issues, issues_count, *, kind: str, comissao: Comissao, detalhe: str):
        issues_count[kind] += 1
        issues.append(
            {
                "kind": kind,
                "comissao_id": comissao.id,
                "os_numero": getattr(comissao.ordem_servico, "numero_os", "-"),
                "status": comissao.status,
                "chave_unica": comissao.chave_unica or "-",
                "detalhe": detalhe,
            }
        )

    def _auditar_por_status_e_valor(self, comissao, issues, issues_count):
        if comissao.status == "PAGA" and not comissao.data_pagamento:
            self._registrar_issue(
                issues,
                issues_count,
                kind="paga_sem_data_pagamento",
                comissao=comissao,
                detalhe="Comissão com status PAGA sem data_pagamento.",
            )
        if comissao.status in {"GERADA", "LIBERADA"} and comissao.data_pagamento:
            self._registrar_issue(
                issues,
                issues_count,
                kind="nao_paga_com_data_pagamento",
                comissao=comissao,
                detalhe="Comissão não paga com data_pagamento preenchida.",
            )
        if comissao.status == "PAGA" and comissao.tipo in {"SERVICO", "PECA"} and (comissao.valor_base or 0) <= 0:
            self._registrar_issue(
                issues,
                issues_count,
                kind="paga_base_zerada",
                comissao=comissao,
                detalhe="Comissão de serviço/peça paga com valor_base <= 0.",
            )
        if (comissao.valor_comissao or 0) < 0:
            self._registrar_issue(
                issues,
                issues_count,
                kind="valor_comissao_negativo",
                comissao=comissao,
                detalhe="Comissão com valor_comissao negativo.",
            )

    def _auditar_fonte(self, comissao, fontes_cache, issues, issues_count):
        if comissao.tipo not in TIPOS_COM_FONTE or comissao.status == "CANCELADA":
            return

        evento, tipo_da_chave, chave_ref = self._parse_chave_unica(comissao.chave_unica)
        if not chave_ref:
            self._registrar_issue(
                issues,
                issues_count,
                kind="chave_unica_invalida",
                comissao=comissao,
                detalhe="Não foi possível extrair a referência da chave_unica.",
            )
            return

        if tipo_da_chave and tipo_da_chave != comissao.tipo:
            self._registrar_issue(
                issues,
                issues_count,
                kind="tipo_chave_divergente",
                comissao=comissao,
                detalhe=f"Tipo na chave ({tipo_da_chave}) difere do campo tipo ({comissao.tipo}).",
            )

        if evento == "VENDA_MOSTRADOR" or chave_ref.startswith("venda:"):
            venda = self._venda_rapida_valida(chave_ref)
            if not venda:
                self._registrar_issue(
                    issues,
                    issues_count,
                    kind="sem_fonte_valida",
                    comissao=comissao,
                    detalhe=f"Referência '{chave_ref}' não encontrada nas vendas rápidas válidas.",
                )
            return

        if not comissao.ordem_servico_id:
            self._registrar_issue(
                issues,
                issues_count,
                kind="sem_ordem_servico",
                comissao=comissao,
                detalhe="Comissão sem ordem_servico vinculada.",
            )
            return

        ordem_id = comissao.ordem_servico_id
        if ordem_id not in fontes_cache:
            fontes_cache[ordem_id] = self._fontes_validas_por_ordem(comissao.ordem_servico)
        validas_tipo = fontes_cache[ordem_id].get(comissao.tipo, set())
        if chave_ref not in validas_tipo:
            self._registrar_issue(
                issues,
                issues_count,
                kind="sem_fonte_valida",
                comissao=comissao,
                detalhe=f"Referência '{chave_ref}' não encontrada nas fontes atuais da OS.",
            )

    def _mapear_assinatura_duplicidade(self, comissao, assinaturas):
        if comissao.tipo not in TIPOS_COM_FONTE or comissao.status == "CANCELADA":
            return
        _, _, chave_ref = self._parse_chave_unica(comissao.chave_unica)
        if not chave_ref:
            return
        assinatura = (comissao.tipo, chave_ref)
        assinaturas[assinatura].append(comissao)

    def _auditar_duplicidade_assinatura(self, assinaturas, issues, issues_count):
        for (tipo, chave_ref), grupo in assinaturas.items():
            if len(grupo) <= 1:
                continue
            for comissao in grupo:
                self._registrar_issue(
                    issues,
                    issues_count,
                    kind="duplicada_por_fonte",
                    comissao=comissao,
                    detalhe=f"Existe mais de uma comissão ativa para {tipo}:{chave_ref}.",
                )
