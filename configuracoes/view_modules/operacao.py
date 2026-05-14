from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.management import call_command
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from configuracoes.models import ConfiguracaoAuditoria
from configuracoes.services.auditoria import registrar_evento_configuracao
from configuracoes.services.integracoes import emitir_evento_interno
from configuracoes.view_modules.common import request_ip


def backup_banco_impl(request, logger):
    logger.info(
        "auditoria_operacional",
        extra={
            "acao": "backup_solicitado",
            "usuario": request.user.username,
            "ip": request_ip(request),
        },
    )
    backup_dir = Path(settings.BASE_DIR) / "backups"
    db_name = str(settings.DATABASES.get("default", {}).get("NAME", ""))
    if db_name.startswith("file:memorydb_") or db_name == ":memory:":
        backup_dir.mkdir(parents=True, exist_ok=True)
        messages.info(request, "Backup ignorado: banco em memória (ambiente de teste).")
        return redirect("configuracoes:painel")
    try:
        call_command("backup_db", output_dir=str(backup_dir), gzip=True)
        registrar_evento_configuracao(
            usuario=request.user,
            acao="backup_executado",
            origem="ui",
            alvo="database",
            depois={"diretorio": str(backup_dir)},
        )
        emitir_evento_interno("backup.executado", {"usuario": request.user.username, "status": "sucesso"})
        messages.success(request, f"Backup gerado com sucesso em: {backup_dir}")
    except Exception as exc:
        logger.exception("falha_backup_banco")
        registrar_evento_configuracao(
            usuario=request.user,
            acao="backup_falha",
            origem="ui",
            alvo="database",
            depois={"erro": str(exc)},
        )
        emitir_evento_interno("backup.executado", {"usuario": request.user.username, "status": "falha", "erro": str(exc)})
        messages.error(request, f"Falha ao gerar backup: {exc}")
    return redirect("configuracoes:painel")


def restore_banco_impl(request, logger):
    backup_dir = Path(settings.BASE_DIR) / "backups"
    if request.method != "POST":
        backups = sorted(
            [p for p in backup_dir.glob("*") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:30] if backup_dir.exists() else []
        return render(
            request,
            "configuracoes/restore.html",
            {"backups": backups, "backup_dir": backup_dir},
        )

    backup_path = (request.POST.get("arquivo") or "").strip()
    confirmar = (request.POST.get("confirmar") or "").strip().upper()
    if confirmar != "RESTAURAR":
        messages.error(request, "Confirmação inválida. Digite RESTAURAR para continuar.")
        return redirect("configuracoes:restore_banco")
    if not backup_path:
        messages.error(request, "Selecione um arquivo de backup.")
        return redirect("configuracoes:restore_banco")

    backup_absoluto = Path(backup_path).resolve()
    backup_dir_abs = backup_dir.resolve()
    if backup_dir_abs not in backup_absoluto.parents:
        messages.error(request, "Arquivo inválido: use apenas backups da pasta oficial.")
        return redirect("configuracoes:restore_banco")
    if backup_absoluto.suffix.lower() not in {".sqlite3", ".gz"}:
        messages.error(request, "Formato de arquivo inválido para restore.")
        return redirect("configuracoes:restore_banco")
    if not backup_absoluto.exists():
        messages.error(request, "Arquivo de backup não encontrado.")
        return redirect("configuracoes:restore_banco")

    try:
        registrar_evento_configuracao(
            usuario=request.user,
            acao="restore_solicitado",
            origem="ui",
            alvo="database",
            depois={"arquivo": str(backup_absoluto)},
        )
        call_command("restore_db", str(backup_absoluto), force=True)
        registrar_evento_configuracao(
            usuario=request.user,
            acao="restore_executado",
            origem="ui",
            alvo="database",
            depois={"arquivo": str(backup_absoluto)},
        )
        emitir_evento_interno(
            "restore.executado",
            {"usuario": request.user.username, "arquivo": str(backup_absoluto), "status": "sucesso"},
        )
        messages.success(request, "Restore executado com sucesso.")
    except Exception as exc:
        logger.exception("falha_restore_banco")
        registrar_evento_configuracao(
            usuario=request.user,
            acao="restore_falha",
            origem="ui",
            alvo="database",
            depois={"arquivo": str(backup_absoluto), "erro": str(exc)},
        )
        emitir_evento_interno(
            "restore.executado",
            {"usuario": request.user.username, "arquivo": str(backup_absoluto), "status": "falha", "erro": str(exc)},
        )
        messages.error(request, f"Falha no restore: {exc}")
    return redirect("configuracoes:painel")


def auditoria_configuracoes_impl(request):
    eventos_qs = ConfiguracaoAuditoria.objects.select_related("usuario").all()
    acao = (request.GET.get("acao") or "").strip()
    origem = (request.GET.get("origem") or "").strip()
    if acao:
        eventos_qs = eventos_qs.filter(acao__icontains=acao)
    if origem:
        eventos_qs = eventos_qs.filter(origem=origem)

    eventos_page = Paginator(eventos_qs, 40).get_page(request.GET.get("page"))
    return render(
        request,
        "configuracoes/auditoria_configuracoes.html",
        {
            "eventos": eventos_page,
            "acao": acao,
            "origem": origem,
            "origens": ConfiguracaoAuditoria.ORIGEM_CHOICES,
            "menu_app": "configuracoes",
            "menu_sub": "auditoria_configuracoes",
        },
    )
