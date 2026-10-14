import logging
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.core.exceptions import PermissionDenied, ValidationError
from configuracoes.forms_backup import PoliticaBackupForm
from configuracoes.models import Empresa, ExecucaoBackup, PoliticaBackup
from configuracoes.permissions import ADM_ROLES, role_required
from configuracoes.services.auditoria import registrar_evento_configuracao
from configuracoes.services.backup_automatico import executar_rotina_backup

logger = logging.getLogger(__name__)


@role_required(ADM_ROLES)
def rotina_backup(request):
    # O pacote contém todas as empresas: um administrador de tenant não o administra.
    if not request.user.is_superuser and Empresa.objects.exclude(pk=request.user.empresa_id).exists():
        raise PermissionDenied("A rotina da instalação inteira exige o administrador da instalação.")
    politica = PoliticaBackup.objects.filter(pk=1).first() or PoliticaBackup(pk=1)
    acao = request.POST.get("acao") if request.method == "POST" else ""
    form = PoliticaBackupForm(request.POST if acao == "configurar" else None, instance=politica)
    if acao == "configurar" and form.is_valid():
        form.save()
        registrar_evento_configuracao(usuario=request.user, acao="backup_politica", origem="ui", alvo="instalacao", depois={"ativo": politica.ativo, "destino_nuvem": politica.destino_nuvem})
        messages.success(request, "Configuração guardada. Para execução automática, instale a tarefa de backup no servidor.")
        return redirect("configuracoes:rotina_backup")
    if acao == "executar":
        PoliticaBackup.objects.get_or_create(pk=1)
        try:
            execucao = executar_rotina_backup()
            if execucao.status == "sucesso":
                messages.success(request, "Backup local concluído e verificado.")
            if execucao.status == "falha" or execucao.nuvem_status == "falha":
                messages.error(request, execucao.erro)
            registrar_evento_configuracao(usuario=request.user, acao="backup_rotina_executada", origem="ui", alvo="instalacao", depois={"status": execucao.status, "nuvem_status": execucao.nuvem_status})
        except ValidationError as exc:
            messages.warning(request, "; ".join(exc.messages))
        return redirect("configuracoes:rotina_backup")
    if acao == "confirmar_teste" and request.POST.get("teste_confirmado") == "1":
        politica.ultimo_teste_recuperacao = timezone.now()
        politica.save()
        registrar_evento_configuracao(usuario=request.user, acao="backup_teste_declarado", origem="ui", alvo="instalacao", depois={"declarado_pelo_administrador": True})
        messages.success(request, "Teste de recuperação declarado pelo administrador e registado na auditoria.")
        return redirect("configuracoes:rotina_backup")
    ultimo_sucesso = ExecucaoBackup.objects.filter(status="sucesso").first()
    atrasado = bool(politica.ativo and (not ultimo_sucesso or timezone.now() - ultimo_sucesso.iniciado_em > timezone.timedelta(hours=36)))
    return render(request, "configuracoes/rotina_backup.html", {"form": form, "politica": politica, "execucoes": ExecucaoBackup.objects.all()[:30], "ultimo_sucesso": ultimo_sucesso, "backup_atrasado": atrasado, "menu_app": "configuracoes", "menu_sub": "backup_banco"})
