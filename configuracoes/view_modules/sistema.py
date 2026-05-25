from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from configuracoes.forms import ConfiguracaoOrdemServicoForm, ConfiguracaoSistemaForm
from configuracoes.models import ConfiguracaoOrdemServico, ConfiguracaoSistema, RegraSLAAlerta
from configuracoes.services.auditoria import registrar_evento_configuracao
from configuracoes.services.integracoes import emitir_evento_interno


def configuracao_os_edit_impl(request):
    config = ConfiguracaoOrdemServico.objects.first()
    if request.method == "POST":
        form = ConfiguracaoOrdemServicoForm(request.POST, instance=config)
        if form.is_valid():
            obj = form.save()
            registrar_evento_configuracao(
                usuario=request.user,
                acao="config_os_editada",
                origem="ui",
                alvo="configuracao_os",
                depois={"prefixo_os": obj.prefixo_os, "inicio_id_ordem": obj.inicio_id_ordem},
            )
            emitir_evento_interno("configuracoes.alterada", {"escopo": "configuracao_os"})
            messages.success(request, "Configuração da Ordem de Serviço salva com sucesso!")
            return redirect("configuracoes:painel")
    else:
        form = ConfiguracaoOrdemServicoForm(instance=config)
    return render(request, "configuracoes/configuracao_os_form.html", {"form": form})


def configuracao_sistema_edit_impl(request):
    config = ConfiguracaoSistema.get_configuracao()
    pode_editar_termos_os = bool(request.user.is_superuser or getattr(request.user, "tipo_usuario", "") == "adm")
    if request.method == "POST":
        form = ConfiguracaoSistemaForm(request.POST, instance=config)
        if not pode_editar_termos_os and "termos_ordem_servico" in form.fields:
            form.fields["termos_ordem_servico"].disabled = True
        if form.is_valid():
            obj = form.save(commit=False)
            if not pode_editar_termos_os:
                obj.termos_ordem_servico = config.termos_ordem_servico
            obj.save()
            prazo_os_sem_mov = max(int(getattr(obj, "sla_dias_os_sem_movimentacao", 2) or 2), 1)
            regra, criada = RegraSLAAlerta.objects.get_or_create(
                codigo="os_sem_movimentacao",
                defaults={
                    "ativo": True,
                    "prazo_valor": prazo_os_sem_mov,
                    "prazo_unidade": "dias",
                    "severidade": "alta",
                    "responsavel_padrao": "Atendimento",
                    "acao_sugerida": "Atualizar linha de trabalho e validar próximo passo.",
                    "canal_notificacao": "painel",
                    "observacoes": "Monitora ordens sem evolução técnica recente.",
                },
            )
            if not criada:
                regra.prazo_valor = prazo_os_sem_mov
                regra.prazo_unidade = "dias"
                regra.save(update_fields=["prazo_valor", "prazo_unidade", "atualizado_em"])
            registrar_evento_configuracao(
                usuario=request.user,
                acao="config_sistema_editada",
                origem="ui",
                alvo="configuracao_sistema",
                depois={
                    "estado_padrao": obj.estado_padrao,
                    "ddd_padrao": obj.ddd_padrao,
                    "api_cep_provedor": obj.api_cep_provedor,
                },
            )
            emitir_evento_interno("configuracoes.alterada", {"escopo": "configuracao_sistema"})
            messages.success(request, "Configurações do sistema salvas com sucesso!")
            return redirect("configuracoes:painel")
    else:
        form = ConfiguracaoSistemaForm(instance=config)
        if not pode_editar_termos_os and "termos_ordem_servico" in form.fields:
            form.fields["termos_ordem_servico"].disabled = True

    context = {
        "form": form,
        "estados_brasil": ConfiguracaoSistema.ESTADOS_BRASIL,
        "ddd_brasil": ConfiguracaoSistema.DDD_BRASIL,
    }
    return render(request, "configuracoes/configuracao_sistema_form.html", context)


def preview_documento_impl(request):
    tipo = (request.GET.get("tipo") or "os_impressao").strip().lower()
    ordem_id = (request.GET.get("ordem_id") or "").strip()
    orcamento_id = (request.GET.get("orcamento_id") or "").strip()
    preview_ativo = (request.GET.get("_preview") or "").strip().lower() in {"1", "true", "on", "yes", "sim"}
    preview_params = {}
    for key in (
        "layout_os_impressao",
        "layout_documentos_preset",
        "layout_documentos_cor",
        "layout_os_frente_espaco_assinaturas_cm",
        "layout_os_verso_espaco_assinatura_cm",
        "layout_os_data_fonte_pt",
        "layout_os_digital_exibir_validacao",
        "layout_os_exibir_etiqueta_corte",
    ):
        value = (request.GET.get(key) or "").strip()
        if value != "":
            preview_params[key] = value
    if preview_ativo or preview_params:
        preview_params["_preview"] = "1"

    def _build_url(route_name, kwargs):
        url = reverse(route_name, kwargs=kwargs)
        if preview_params:
            url = f"{url}?{urlencode(preview_params)}"
        return url

    from ordens.models import OrdemServico
    from orcamentos.models import Orcamento

    ordem = None
    orcamento = None

    if ordem_id.isdigit():
        ordem = OrdemServico.objects.filter(id=int(ordem_id)).first()
    if orcamento_id.isdigit():
        orcamento = Orcamento.objects.select_related("ordem_servico").filter(id=int(orcamento_id)).first()
        if orcamento and not ordem:
            ordem = orcamento.ordem_servico

    if not ordem:
        ordem = OrdemServico.objects.order_by("-id").first()
    if not orcamento:
        if ordem:
            orcamento = (
                Orcamento.objects.select_related("ordem_servico")
                .filter(ordem_servico=ordem)
                .order_by("-id")
                .first()
            )
        if not orcamento:
            orcamento = Orcamento.objects.select_related("ordem_servico").order_by("-id").first()
            if orcamento and not ordem:
                ordem = orcamento.ordem_servico

    if tipo == "os_digital":
        if not ordem:
            return HttpResponse("Sem OS cadastrada para pré-visualização.", content_type="text/plain", status=404)
        return redirect(_build_url("ordens:imprimir_ordem_servico", {"pk": ordem.pk}))
    if tipo == "relatorio":
        if not ordem:
            return HttpResponse("Sem OS cadastrada para pré-visualização.", content_type="text/plain", status=404)
        return redirect(_build_url("ordens:imprimir_relatorio_tecnico", {"pk": ordem.pk}))
    if tipo == "orcamento":
        if not orcamento:
            return HttpResponse("Sem orçamento cadastrado para pré-visualização.", content_type="text/plain", status=404)
        return redirect(_build_url("orcamentos:imprimir_orcamento", {"pk": orcamento.pk}))

    if not ordem:
        return HttpResponse("Sem OS cadastrada para pré-visualização.", content_type="text/plain", status=404)
    return redirect(_build_url("ordens:imprimir_ordem_servico_impressao", {"pk": ordem.pk}))
