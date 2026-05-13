from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from caixa.services.comissoes import cancelar_comissoes_por_item, processar_evento_servico_finalizado
from ordens.models import LinhaTrabalho, ServicoPeca

from ..models import ItemOrcamento


@dataclass
class AtualizacaoOrcamentoResultado:
    itens_processados: int
    status_orcamento: str
    status_ordem_anterior: str
    status_ordem_atual: str


@dataclass
class MigracaoOrcamentoResultado:
    total_migrados: int
    itens_selecionados: int
    itens_aprovados: int
    itens_nao_aprovados: int
    itens_ja_migrados: int


class FluxoOrcamentoService:
    @staticmethod
    def aceitar_itens(orcamento, itens_ids, usuario=None):
        ordem = orcamento.ordem_servico
        with transaction.atomic():
            itens = list(orcamento.itens.filter(id__in=itens_ids))
            for item in itens:
                item.status = "aprovado"
                item.save()

            processar_evento_servico_finalizado(ordem, evento="SERVICO_FINALIZADO")

            status_orcamento = orcamento.status
            status_ordem_anterior = ordem.status
            status_ordem_atual = ordem.status
            if ordem.status not in {"pronto_contactado", "concluida", "autorizado"}:
                ordem.status = "orcamentado"
                ordem.save(update_fields=["status"])
                status_ordem_atual = ordem.status
            if not orcamento.itens.filter(status="pendente").exists():
                orcamento.status = "aprovado"
                orcamento.save(update_fields=["status"])
                status_orcamento = orcamento.status
                if ordem.status not in {"pronto_contactado", "concluida"}:
                    ordem.status = "autorizado"
                    ordem.save(update_fields=["status"])
                status_ordem_atual = ordem.status
                LinhaTrabalho.objects.create(
                    ordem=ordem,
                    status=ordem.status,
                    descricao=(
                        f"Todos os itens do orcamento aprovados pelo cliente "
                        f"(status: {status_ordem_anterior} -> {ordem.status})."
                    ),
                    usuario=usuario,
                )

        return AtualizacaoOrcamentoResultado(
            itens_processados=len(itens),
            status_orcamento=status_orcamento,
            status_ordem_anterior=status_ordem_anterior,
            status_ordem_atual=status_ordem_atual,
        )

    @staticmethod
    def recusar_itens(orcamento, itens_ids, usuario=None):
        ordem = orcamento.ordem_servico
        with transaction.atomic():
            itens = list(orcamento.itens.filter(id__in=itens_ids))
            for item in itens:
                item.status = "recusado"
                item.save()
                cancelar_comissoes_por_item(
                    item,
                    motivo="Item de orcamento recusado.",
                    evento="CANCELAMENTO_ITEM",
                )

            status_orcamento = orcamento.status
            status_ordem_anterior = ordem.status
            status_ordem_atual = ordem.status
            if not orcamento.itens.filter(status="pendente").exists():
                orcamento.status = "recusado"
                orcamento.save(update_fields=["status"])
                status_orcamento = orcamento.status
                ordem.status = "pendente_cliente"
                ordem.save(update_fields=["status"])
                status_ordem_atual = ordem.status
                LinhaTrabalho.objects.create(
                    ordem=ordem,
                    status="pendente_cliente",
                    descricao="Todos os itens do orcamento recusados pelo cliente.",
                    usuario=usuario,
                )

        return AtualizacaoOrcamentoResultado(
            itens_processados=len(itens),
            status_orcamento=status_orcamento,
            status_ordem_anterior=status_ordem_anterior,
            status_ordem_atual=status_ordem_atual,
        )

    @classmethod
    def migrar_itens_selecionados(
        cls,
        orcamento,
        itens_ids,
        usuario=None,
        *,
        criar_historico=True,
        status_historico="orcamentado",
        descricao_historico="{total} item(s) migrado(s) para Servicos & Pecas.",
        usar_valor_liquido=True,
        copiar_comissionavel=True,
    ):
        itens = orcamento.itens.filter(id__in=itens_ids)
        return cls._migrar_itens(
            ordem=orcamento.ordem_servico,
            itens=itens,
            usuario=usuario,
            criar_historico=criar_historico,
            status_historico=status_historico,
            descricao_historico=descricao_historico,
            apenas_aprovados=True,
            usar_valor_liquido=usar_valor_liquido,
            copiar_comissionavel=copiar_comissionavel,
        )

    @classmethod
    def migrar_itens_aprovados_da_ordem(
        cls,
        ordem,
        usuario=None,
        *,
        criar_historico=True,
        status_historico=None,
        descricao_historico="Itens aprovados migrados para Servicos & Pecas ({total}).",
        usar_valor_liquido=False,
        copiar_comissionavel=False,
    ):
        itens = ItemOrcamento.objects.select_related("tecnico_responsavel").filter(
            orcamento__ordem_servico=ordem,
            status="aprovado",
        )
        return cls._migrar_itens(
            ordem=ordem,
            itens=itens,
            usuario=usuario,
            criar_historico=criar_historico,
            status_historico=status_historico or ordem.status,
            descricao_historico=descricao_historico,
            apenas_aprovados=False,
            usar_valor_liquido=usar_valor_liquido,
            copiar_comissionavel=copiar_comissionavel,
        )

    @classmethod
    def _migrar_itens(
        cls,
        *,
        ordem,
        itens,
        usuario=None,
        criar_historico=True,
        status_historico="orcamentado",
        descricao_historico="{total} item(s) migrado(s) para Servicos & Pecas.",
        apenas_aprovados=True,
        usar_valor_liquido=True,
        copiar_comissionavel=True,
    ):
        itens = list(itens.select_related("tecnico_responsavel"))
        itens_selecionados = len(itens)
        itens_aprovados = 0
        itens_nao_aprovados = 0
        itens_ja_migrados = 0
        total_migrados = 0

        with transaction.atomic():
            for item in itens:
                if apenas_aprovados and item.status != "aprovado":
                    itens_nao_aprovados += 1
                    continue
                itens_aprovados += 1
                defaults = {
                    "nome": item.nome,
                    "descricao": item.descricao,
                    "valor_unitario": cls._valor_unitario_migrado(item, usar_valor_liquido=usar_valor_liquido),
                    "quantidade": int(item.quantidade or 1) or 1,
                    "tipo": cls._tipo_item_resolvido(item),
                    "tecnico_responsavel": item.tecnico_responsavel or ordem.tecnico_responsavel,
                }
                if copiar_comissionavel:
                    defaults["comissionavel"] = item.comissionavel
                _, created = ServicoPeca.objects.get_or_create(
                    ordem=ordem,
                    item_orcamento=item,
                    defaults=defaults,
                )
                if created:
                    total_migrados += 1
                else:
                    itens_ja_migrados += 1

            if criar_historico and total_migrados:
                LinhaTrabalho.objects.create(
                    ordem=ordem,
                    status=status_historico,
                    descricao=descricao_historico.format(total=total_migrados),
                    usuario=usuario,
                    tipo_evento="sistema" if status_historico == ordem.status else "manual",
                )

        return MigracaoOrcamentoResultado(
            total_migrados=total_migrados,
            itens_selecionados=itens_selecionados,
            itens_aprovados=itens_aprovados,
            itens_nao_aprovados=itens_nao_aprovados,
            itens_ja_migrados=itens_ja_migrados,
        )

    @staticmethod
    def _tipo_item_resolvido(item):
        tipo_item = (item.tipo_item or "").strip()
        if tipo_item in {"servico", "peca"}:
            return tipo_item
        return "peca" if item.origem == "estoque" else "servico"

    @staticmethod
    def _valor_unitario_migrado(item, *, usar_valor_liquido):
        quantidade_item = int(item.quantidade or 1) or 1
        if not usar_valor_liquido:
            return item.valor_unitario
        return (Decimal(item.total() or 0) / Decimal(quantidade_item)).quantize(Decimal("0.01"))
