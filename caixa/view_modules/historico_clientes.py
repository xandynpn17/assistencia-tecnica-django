from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from caixa.models import AuditoriaFinanceira, Pagamento
from caixa.services.consulta_bancaria import pagina_consulta
from clientes.models import Cliente
from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, require_sensitive_permission, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa
from ordens.models import OrdemServico


def pagamentos_sem_identificacao(empresa):
    return (Pagamento.objects.filter(empresa=empresa, cliente__isnull=True, ordem_servico__isnull=True)
            .exclude(recebimentoconta__conta__ordem_servico__isnull=False)
            .exclude(Q(metodo__in=['garantia_fabricante', 'custo_loja']) | Q(forma_pagamento__codigo__in=['garantia_fabricante', 'custo_loja'])).distinct())


class IdentificarClientePagamentoForm(forms.Form):
    pagamento = forms.ModelChoiceField(queryset=Pagamento.objects.none())
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.none())
    justificativa = forms.CharField(min_length=12, max_length=180, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields['pagamento'].queryset = pagamentos_sem_identificacao(empresa).order_by('-data_movimento', '-id')
        self.fields['pagamento'].label_from_instance = lambda p: f'{p.numero_talao} · {p.data_movimento:%d/%m/%Y} · R$ {p.valor:.2f} · {p.cliente_nome or "Não identificado"}'
        self.fields['cliente'].queryset = Cliente.objects.filter(empresa=empresa).order_by('nome')
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control form-control-sm'

    def clean(self):
        dados = super().clean()
        pagamento, cliente = dados.get('pagamento'), dados.get('cliente')
        if pagamento and cliente:
            try:
                ids = [int(o['ordem_id']) for o in pagamento.origens_compostas if o.get('tipo') == 'os']
            except (TypeError, ValueError, KeyError, AttributeError):
                self.add_error('pagamento', 'A composição antiga deste pagamento precisa de revisão antes de identificar o cliente.')
                return dados
            if ids and OrdemServico.objects.filter(empresa=self.empresa, cliente=cliente, pk__in=ids).count() != len(set(ids)):
                self.add_error('cliente', 'O cliente não corresponde às OS da composição. Reveja os dados antes de vincular.')
        return dados


@role_required(CAIXA_FINANCIAL_ROLES)
def revisar_identificacao_clientes(request):
    require_sensitive_permission(request.user, 'perm_cliente_ver_financeiro')
    require_sensitive_permission(request.user, 'perm_caixa_corrigir_lancamentos')
    empresa = obter_empresa_ativa(request, strict=True)
    form = IdentificarClientePagamentoForm(request.POST if request.method == 'POST' else None, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            pagamento = Pagamento.objects.select_for_update().filter(pk=form.cleaned_data['pagamento'].pk, empresa=empresa).first()
            if not pagamento or not pagamentos_sem_identificacao(empresa).filter(pk=pagamento.pk).exists():
                form.add_error('pagamento', 'Este pagamento já foi identificado por outra operação. Atualize a página.')
            else:
                cliente = form.cleaned_data['cliente']
                # Apenas o vínculo: valores, datas e snapshots dos recibos não mudam.
                Pagamento.objects.filter(pk=pagamento.pk).update(cliente=cliente)
                AuditoriaFinanceira.objects.create(pagamento=pagamento, usuario=request.user, evento='pagamento_cliente_identificado', descricao=f'Cliente #{cliente.pk}: {form.cleaned_data["justificativa"]}')
                messages.success(request, 'Cliente vinculado ao histórico. Recibo e movimentos financeiros preservados.')
                return redirect('caixa:revisar_identificacao_clientes')
    lista = pagamentos_sem_identificacao(empresa).order_by('-data_movimento', '-id')
    q = (request.GET.get('q') or '').strip()[:150]
    if q:
        lista = lista.filter(Q(numero_talao__icontains=q) | Q(cliente_nome__icontains=q) | Q(referencia__icontains=q))
    pagina, nav = pagina_consulta(lista, request, 'pagina', tamanho=25)
    return render(request, 'caixa/revisar_identificacao_clientes.html', {'form': form, 'pagina': pagina, 'nav': nav, 'q': q, 'menu_app': 'caixa'})
