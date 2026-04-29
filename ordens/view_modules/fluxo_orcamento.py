from orcamentos.services import FluxoOrcamentoService

from . import fluxo_support as _support

# Reexporta nomes compartilhados, incluindo helpers internos.
globals().update({name: getattr(_support, name) for name in dir(_support) if not name.startswith("__")})


@role_required(ORDER_ROLES)
def migrar_orcamento(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    orcamento = getattr(ordem, "orcamento", None)
    if ordem.fechada:
        messages.error(request, "A OS estÃ¡ fechada. Reabra para alterar o orÃ§amento.")
        return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

    if request.method == "POST":
        if not orcamento or not orcamento.itens.exists():
            messages.warning(request, "Nenhum item encontrado no orÃ§amento.")
            return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

        resultado = FluxoOrcamentoService.migrar_itens_aprovados_da_ordem(
            ordem,
            usuario=request.user,
            criar_historico=False,
            usar_valor_liquido=False,
            copiar_comissionavel=False,
        )
        count = resultado.total_migrados
        if not resultado.itens_aprovados:
            messages.warning(request, "Somente itens aprovados podem ser migrados para ServiÃ§os & PeÃ§as.")
            return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")

        if count:
            LinhaTrabalho.objects.create(
                ordem=ordem,
                descricao=f"Itens do orÃ§amento migrados ({count} itens)",
                status=ordem.status,
                usuario=request.user,
                tipo_evento="sistema",
            )
        registrar_auditoria(
            logger,
            request,
            "orcamento_migrado_para_servicos",
            ordem=ordem,
            extra={"itens": count},
        )
        _log_os(
            ordem,
            "edicao_critica",
            f"OrÃ§amento migrado para serviÃ§os/peÃ§as ({count} itens).",
            usuario=request.user,
            dados_extras={"itens": count},
        )

        if not count:
            messages.info(request, "Os itens aprovados jÃ¡ estavam migrados para ServiÃ§os & PeÃ§as.")
            return redirect(f"{ordem.get_absolute_url()}?tab=servicos")

        messages.success(request, f"{count} itens migrados para ServiÃ§os & PeÃ§as com sucesso.")
        return redirect(f"{ordem.get_absolute_url()}?tab=servicos")

    return redirect(f"{ordem.get_absolute_url()}?tab=orcamentos")
