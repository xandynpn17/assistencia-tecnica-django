"""Leituras operacionais por empresa. Nenhuma consulta modifica OS ou pedidos."""
from decimal import Decimal

from django.db.models import OuterRef, Q, Subquery, Sum
from django.utils import timezone

from caixa.models import ContaReceber
from orcamentos.models import Orcamento
from ordens.models import ConfiguracaoOperacaoEmpresa, LinhaTrabalho, OrdemServico, PedidoCompra


def configuracao_operacao(empresa):
    return ConfiguracaoOperacaoEmpresa.objects.filter(empresa=empresa).first() or ConfiguracaoOperacaoEmpresa(empresa=empresa)


def pendencias_operacionais(empresa, *, hoje=None, mostrar_financeiro=False):
    hoje = hoje or timezone.localdate()
    config = configuracao_operacao(empresa)
    ultimo = LinhaTrabalho.objects.filter(ordem_id=OuterRef('pk')).order_by('-criado_em', '-pk').values('criado_em')[:1]
    abertas = OrdemServico.objects.filter(empresa=empresa, fechada=False).exclude(status='concluida').annotate(ultima_atividade=Subquery(ultimo))
    grupos = []

    def juntar(codigo, titulo, linhas):
        grupos.append({'codigo': codigo, 'titulo': titulo, 'linhas': linhas[:50], 'total': len(linhas)})

    paradas = []
    for ordem in abertas.exclude(status='pronto_contactado').select_related('tecnico_responsavel').order_by('data_abertura').iterator(chunk_size=500):
        referencia = timezone.localtime(ordem.ultima_atividade).date() if ordem.ultima_atividade else timezone.localtime(ordem.data_abertura).date()
        if (hoje - referencia).days >= config.dias_os_parada:
            paradas.append({'ordem': ordem, 'quando': referencia, 'responsavel': ordem.tecnico_responsavel, 'motivo': 'Sem linha de trabalho recente'})
    juntar('os', 'OS sem atividade recente', paradas)

    orcamentos = []
    for orcamento in Orcamento.objects.filter(empresa=empresa, status='pendente', ordem_servico__in=abertas, itens__isnull=False).distinct().select_related('ordem_servico', 'ordem_servico__tecnico_responsavel').order_by('data_atualizacao').iterator(chunk_size=500):
        data = timezone.localtime(orcamento.data_atualizacao).date()
        if (hoje - data).days >= config.dias_orcamento_sem_resposta:
            orcamentos.append({'ordem': orcamento.ordem_servico, 'quando': data, 'responsavel': orcamento.ordem_servico.tecnico_responsavel, 'motivo': f'Orçamento #{orcamento.numero} sem resposta'})
    juntar('orcamentos', 'Orçamentos sem resposta', orcamentos)

    prontos = []
    for ordem in abertas.filter(status='pronto_contactado').select_related('tecnico_responsavel').order_by('data_abertura').iterator(chunk_size=500):
        data = timezone.localtime(ordem.ultima_atividade).date() if ordem.ultima_atividade else timezone.localtime(ordem.data_abertura).date()
        if (hoje - data).days >= config.dias_pronto_aguardando:
            prontos.append({'ordem': ordem, 'quando': data, 'responsavel': ordem.tecnico_responsavel, 'motivo': 'Pronto, aguardando retirada'})
    juntar('prontos', 'Equipamentos prontos aguardando', prontos)

    compras = []
    compras_qs = PedidoCompra.objects.filter(empresa=empresa).exclude(status__in=PedidoCompra.STATUS_TERMINAIS).select_related('ordem', 'criado_por').annotate(
        recebido_ativo=Sum('recebimentos__quantidade', filter=Q(recebimentos__estornado_em__isnull=True))
    ).order_by('criado_em')
    for pedido in compras_qs.iterator(chunk_size=500):
        if pedido.ordem.empresa_id != empresa.pk:
            continue
        if Decimal(pedido.quantidade_solicitada or 0) - Decimal(pedido.recebido_ativo or 0) <= 0:
            continue
        data = pedido.data_prevista or timezone.localtime(pedido.criado_em).date()
        limite = 0 if pedido.data_prevista else config.dias_compra_pendente
        if (hoje - data).days >= limite:
            compras.append({'ordem': pedido.ordem, 'quando': data, 'responsavel': pedido.criado_por, 'motivo': f'{pedido.numero_oc or "Pedido"} · {pedido.get_status_display()}'})
    juntar('compras', 'Compras pendentes', compras)

    if mostrar_financeiro:
        fabricante = []
        cobrancas = ContaReceber.objects.filter(empresa=empresa, tipo_origem='garantia_fabricante', status__in=['aberta', 'parcial', 'vencida']).select_related('ordem_servico').order_by('vencimento').iterator(chunk_size=500)
        for conta in cobrancas:
            if (hoje - conta.vencimento).days >= config.dias_cobranca_fabricante and conta.valor_aberto > 0:
                fabricante.append({'ordem': conta.ordem_servico if conta.ordem_servico_id and conta.ordem_servico.empresa_id == empresa.pk else None, 'quando': conta.vencimento, 'responsavel': None, 'motivo': f'{conta.descricao} · R$ {conta.valor_aberto:.2f}'})
        juntar('fabricante', 'Fabricantes com cobrança vencida', fabricante)
    return {'grupos': grupos, 'total': sum(g['total'] for g in grupos), 'config': config, 'hoje': hoje}


def historico_equipamento(ordem, empresa):
    """Só mostra dados da mesma empresa e do mesmo cliente; terceiros ficam mascarados."""
    if ordem.empresa_id != getattr(empresa, 'pk', None):
        return {'ordens': [], 'terceiros': 0, 'criterio': 'fora do escopo'}
    base = OrdemServico.objects.filter(empresa=empresa, data_abertura__lt=ordem.data_abertura).exclude(pk=ordem.pk)
    ligados = list(base.filter(cliente=ordem.cliente, equipamento_grupo=ordem.equipamento_grupo).order_by('-data_abertura')[:20]) if ordem.equipamento_grupo else []
    serie = (ordem.numero_serie_equipamento or '').strip()
    if serie:
        base = base.filter(numero_serie_equipamento__iexact=serie, marca_equipamento__iexact=ordem.marca_equipamento, modelo_equipamento__iexact=ordem.modelo_equipamento)
        criterio = 'Série, marca e modelo iguais'
    else:
        base = base.filter(cliente=ordem.cliente, marca_equipamento__iexact=ordem.marca_equipamento, modelo_equipamento__iexact=ordem.modelo_equipamento, tipo_equipamento__iexact=ordem.tipo_equipamento)
        criterio = 'Sem série: apenas mesmo cliente, marca, modelo e tipo; confirme que é o mesmo equipamento'
    candidatos = list(base.filter(cliente=ordem.cliente).exclude(pk__in=[item.pk for item in ligados]).order_by('-data_abertura')[:20])
    return {'ordens': ligados, 'candidatos': candidatos, 'terceiros': base.exclude(cliente=ordem.cliente).count(), 'criterio': criterio}
