"""Ferramentas internas de acompanhamento, sem efeitos no fechamento da OS."""
import uuid

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from configuracoes.permissions import CAIXA_FINANCIAL_ROLES, MANAGER_ROLES, ORDER_ROLES, has_role, role_required
from configuracoes.services.tenant_guard import obter_empresa_ativa
from ordens.models import ChecklistEntregaOS, ConfiguracaoOperacaoEmpresa, LogOS, OrdemServico
from ordens.services.evolucao_operacional import configuracao_operacao, historico_equipamento, pendencias_operacionais


class ConfiguracaoOperacaoForm(forms.ModelForm):
    itens = forms.CharField(label="Itens de conferência (um por linha)", required=False, widget=forms.Textarea(attrs={"rows": 6}))
    itens_tipo = forms.CharField(label="Itens por tipo de equipamento (tipo | item)", required=False, widget=forms.Textarea(attrs={"rows": 5}))

    class Meta:
        model = ConfiguracaoOperacaoEmpresa
        fields = ["dias_os_parada", "dias_orcamento_sem_resposta", "dias_pronto_aguardando", "dias_compra_pendente", "dias_cobranca_fabricante", "checklist_obrigatorio"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
        if not self.is_bound:
            self.fields["itens"].initial = "\n".join(self.instance.checklist_itens or [])
            self.fields["itens_tipo"].initial = "\n".join(f"{tipo} | {item}" for tipo, itens in (self.instance.checklist_por_tipo or {}).items() for item in itens)

    def clean_itens(self):
        itens = list(dict.fromkeys(line.strip() for line in self.cleaned_data["itens"].splitlines() if line.strip()))
        if len(itens) > 20 or any(len(item) > 100 for item in itens):
            raise forms.ValidationError("Use até 20 itens, com no máximo 100 caracteres cada.")
        return itens

    def clean_itens_tipo(self):
        por_tipo = {}
        for linha in self.cleaned_data["itens_tipo"].splitlines():
            if not linha.strip():
                continue
            tipo, separador, item = linha.partition("|")
            tipo, item = tipo.strip().casefold(), item.strip()
            if not separador or not tipo or not item or len(tipo) > 40 or len(item) > 100:
                raise forms.ValidationError("Use uma linha por item no formato tipo | item (até 40 e 100 caracteres).")
            itens = por_tipo.setdefault(tipo, [])
            if item not in itens:
                itens.append(item)
            if len(itens) > 20:
                raise forms.ValidationError("Cada tipo aceita até 20 itens.")
        return por_tipo

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.checklist_itens = self.cleaned_data["itens"]
        obj.checklist_por_tipo = self.cleaned_data["itens_tipo"]
        if commit:
            obj.full_clean()
            obj.save()
        return obj


@role_required(ORDER_ROLES)
def central_pendencias(request):
    empresa = obter_empresa_ativa(request)
    return render(request, "ordens/central_pendencias.html", {**pendencias_operacionais(empresa, mostrar_financeiro=has_role(request.user, CAIXA_FINANCIAL_ROLES)), "menu_app": "ordens", "menu_sub": "central_pendencias"})


@role_required(MANAGER_ROLES)
def configurar_operacao(request):
    empresa = obter_empresa_ativa(request)
    config = configuracao_operacao(empresa)
    form = ConfiguracaoOperacaoForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Prazos e checklist atualizados para esta empresa.")
        return redirect("ordens:configurar_operacao")
    return render(request, "ordens/configurar_operacao.html", {"form": form, "menu_app": "ordens"})


@role_required(ORDER_ROLES)
def historico_por_equipamento(request, pk):
    empresa = obter_empresa_ativa(request)
    ordem = get_object_or_404(OrdemServico.objects.select_related("cliente"), pk=pk, empresa=empresa)
    if request.method == "POST":
        if not has_role(request.user, MANAGER_ROLES):
            raise PermissionDenied
        if request.POST.get("acao") == "desvincular":
            OrdemServico.objects.filter(pk=ordem.pk, empresa=empresa).update(equipamento_grupo=None)
            LogOS.objects.create(ordem_servico=ordem, tipo_evento="edicao_critica", descricao="Desvinculou a OS do histórico do equipamento.", usuario_responsavel=request.user)
            messages.success(request, "Vínculo removido desta OS.")
            return redirect("ordens:historico_equipamento", pk=pk)
        alvo_id = request.POST.get("ordem_anterior")
        with transaction.atomic():
            alvo = get_object_or_404(OrdemServico.objects.select_for_update(), pk=alvo_id, empresa=empresa, cliente=ordem.cliente)
            if alvo.pk == ordem.pk or alvo.data_abertura >= ordem.data_abertura:
                messages.error(request, "Escolha uma OS anterior do mesmo cliente.")
            elif any((getattr(alvo, campo) or "").strip().casefold() != (getattr(ordem, campo) or "").strip().casefold() for campo in ("tipo_equipamento", "marca_equipamento", "modelo_equipamento")):
                messages.error(request, "Tipo, marca e modelo não coincidem. Verifique as OS antes de vincular.")
            elif ordem.equipamento_grupo and alvo.equipamento_grupo and ordem.equipamento_grupo != alvo.equipamento_grupo:
                messages.error(request, "As OS já pertencem a históricos distintos. Desvincule primeiro, se necessário.")
            else:
                grupo = ordem.equipamento_grupo or alvo.equipamento_grupo or uuid.uuid4()
                OrdemServico.objects.filter(pk__in=[ordem.pk, alvo.pk], empresa=empresa).update(equipamento_grupo=grupo)
                LogOS.objects.create(ordem_servico=ordem, tipo_evento="edicao_critica", descricao=f"Vinculou histórico do equipamento à OS {alvo.numero_os}.", usuario_responsavel=request.user)
                messages.success(request, "Histórico vinculado após revisão.")
        return redirect("ordens:historico_equipamento", pk=pk)
    return render(request, "ordens/historico_equipamento.html", {"ordem": ordem, **historico_equipamento(ordem, empresa), "pode_vincular": has_role(request.user, MANAGER_ROLES), "menu_app": "ordens"})


@role_required(ORDER_ROLES)
def checklist_entrega(request, pk):
    empresa = obter_empresa_ativa(request)
    ordem = get_object_or_404(OrdemServico, pk=pk, empresa=empresa)
    config = configuracao_operacao(empresa)
    checklist = ChecklistEntregaOS.objects.filter(ordem=ordem, empresa=empresa).first()
    itens_configurados = list(dict.fromkeys((config.checklist_itens or []) + (config.checklist_por_tipo or {}).get((ordem.tipo_equipamento or "").strip().casefold(), [])))
    itens = checklist.itens_snapshot if checklist else itens_configurados
    if request.method == "POST":
        with transaction.atomic():
            checklist, _ = ChecklistEntregaOS.objects.select_for_update().get_or_create(
                ordem=ordem, defaults={"empresa": empresa, "itens_snapshot": itens_configurados}
            )
            itens = checklist.itens_snapshot
            marcados = request.POST.getlist("item")
            if any(item not in itens for item in marcados):
                messages.error(request, "O checklist foi alterado. Reabra a página antes de salvar.")
                return redirect("ordens:checklist_entrega", pk=pk)
            checklist.marcados = list(dict.fromkeys(marcados))
            checklist.acessorios_conferidos = request.POST.get("acessorios") == "on"
            checklist.testes_finais_conferidos = request.POST.get("testes") == "on"
            checklist.observacao = request.POST.get("observacao", "")[:2000]
            completo = all(item in checklist.marcados for item in itens) and checklist.acessorios_conferidos and checklist.testes_finais_conferidos
            if request.POST.get("concluir") and config.checklist_obrigatorio and not completo:
                messages.error(request, "Confira todos os itens, acessórios e testes antes de concluir.")
            else:
                checklist.concluido_em = timezone.now() if request.POST.get("concluir") else None
                checklist.registrado_por = request.user
                checklist.full_clean()
                checklist.save()
                messages.success(request, "Conferência de entrega registrada.")
                return redirect("ordens:checklist_entrega", pk=pk)
    return render(request, "ordens/checklist_entrega.html", {"ordem": ordem, "checklist": checklist, "itens": [(item, item in (checklist.marcados if checklist else [])) for item in itens], "obrigatorio": config.checklist_obrigatorio, "menu_app": "ordens"})
