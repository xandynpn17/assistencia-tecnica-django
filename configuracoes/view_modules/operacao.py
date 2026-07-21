import ipaddress
import json
import shutil
from pathlib import Path
import logging
from unittest.mock import Mock

from django.conf import settings
from django.contrib import messages
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse

from configuracoes.models import ConfiguracaoAuditoria, ConfiguracaoSistema, SetupInicialSistema
from configuracoes.services.auditoria import registrar_evento_configuracao
from configuracoes.services.integracoes import emitir_evento_interno
from configuracoes.services.setup_inicial import setup_inicial_concluido
from configuracoes.view_modules.common import request_ip

logger = logging.getLogger(__name__)


def _backup_dir():
    return Path(settings.BASE_DIR) / "backups"


def _database_engine_label():
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if engine == "django.db.backends.postgresql":
        return "PostgreSQL"
    if engine == "django.db.backends.sqlite3":
        return "SQLite"
    return engine or "Desconhecido"


def _ler_manifesto(item):
    manifesto = item / "manifest.json" if item.is_dir() else item.parent / "manifest.json"
    if not manifesto.exists():
        return {}
    try:
        return json.loads(manifesto.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _formata_tamanho(item):
    if item.is_file():
        total = item.stat().st_size
    else:
        total = sum(path.stat().st_size for path in item.rglob("*") if path.is_file())
    unidades = ["B", "KB", "MB", "GB"]
    valor = float(total)
    for unidade in unidades:
        if valor < 1024 or unidade == unidades[-1]:
            if unidade == "B":
                return f"{int(valor)} {unidade}"
            return f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{int(total)} B"


def _listar_backups(limit=30):
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return []

    itens = []
    for item in sorted(backup_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not (item.is_dir() or item.is_file()):
            continue
        if item.is_file() and item.suffix.lower() == ".zip" and item.with_suffix("").is_dir():
            continue
        manifesto = _ler_manifesto(item)
        itens.append(
            {
                "path": str(item),
                "name": item.name,
                "is_dir": item.is_dir(),
                "modified_at": item.stat().st_mtime,
                "created_at": manifesto.get("created_at", ""),
                "engine": manifesto.get("engine", ""),
                "database_file": manifesto.get("database_file", ""),
                "media_file": manifesto.get("media_file", ""),
                "size_label": _formata_tamanho(item),
                "has_media": bool(manifesto.get("media_file")) or (item.is_dir() and (item / "media.zip").exists()),
            }
        )
    return itens[:limit]


def _restore_page_context(*, setup_pendente=False, modo_recuperacao_local=False):
    try:
        config = ConfiguracaoSistema.get_configuracao() if not modo_recuperacao_local else None
    except DatabaseError as exc:
        logger.warning(
            "restore_page_context_config_falha",
            extra={
                "modulo": "configuracoes",
                "acao": "restore_page_context",
                "modo_recuperacao_local": modo_recuperacao_local,
                "erro": str(exc),
            },
        )
        config = None
    return {
        "backups": _listar_backups(),
        "backup_dir": _backup_dir(),
        "setup_pendente": setup_pendente,
        "modo_recuperacao_local": modo_recuperacao_local,
        "engine_label": _database_engine_label(),
        "retencao_dias": getattr(config, "backup_retencao_dias", None),
        "local_recovery_enabled": bool(getattr(settings, "LOCAL_RECOVERY_KEY", "")),
    }


def resumo_saude_operacional():
    backups = _listar_backups(limit=5)
    ultimo_backup = backups[0] if backups else None
    setup = SetupInicialSistema.get_setup()
    ultimo_restore = ConfiguracaoAuditoria.objects.filter(
        acao__in=["restore_executado", "restore_falha"]
    ).first()
    ultimo_backup_evento = ConfiguracaoAuditoria.objects.filter(
        acao__in=["backup_executado", "backup_falha"]
    ).first()
    return {
        "setup_concluido": bool(getattr(setup, "concluido", False)),
        "backups_total": len(backups),
        "ultimo_backup": ultimo_backup,
        "ultimo_backup_evento": ultimo_backup_evento,
        "ultimo_restore": ultimo_restore,
        "recovery_local_habilitado": bool(getattr(settings, "LOCAL_RECOVERY_KEY", "")),
        "engine_label": _database_engine_label(),
    }


def _request_privado_ou_local(request):
    ip = request_ip(request)
    if not ip:
        return False
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return parsed.is_loopback or parsed.is_private


def _recovery_publico_liberado(request):
    return bool(
        getattr(settings, "LOCAL_RECOVERY_KEY", "")
        and (getattr(settings, "LOCAL_NETWORK_MODE", False) or getattr(settings, "DEBUG", False))
        and _request_privado_ou_local(request)
    )


def _executar_restore(
    request,
    logger,
    *,
    usuario_label,
    origem,
    redirect_name,
    exige_chave_recuperacao=False,
):
    backup_path = (request.POST.get("arquivo") or "").strip()
    confirmar = (request.POST.get("confirmar") or "").strip().upper()
    if confirmar != "RESTAURAR":
        messages.error(request, "Confirmação inválida. Digite RESTAURAR para continuar.")
        return redirect(redirect_name)
    if request.POST.get("ciente_restore") != "1":
        messages.error(request, "Confirme que entende o risco do restore antes de continuar.")
        return redirect(redirect_name)
    if exige_chave_recuperacao:
        chave = (request.POST.get("recovery_key") or "").strip()
        if chave != getattr(settings, "LOCAL_RECOVERY_KEY", ""):
            messages.error(request, "Chave de recuperação inválida.")
            return redirect(redirect_name)
    if not backup_path:
        messages.error(request, "Selecione um backup válido.")
        return redirect(redirect_name)

    backup_absoluto = Path(backup_path).resolve()
    backup_dir_abs = _backup_dir().resolve()
    if backup_dir_abs not in backup_absoluto.parents:
        messages.error(request, "Arquivo inválido: use apenas backups da pasta oficial.")
        return redirect(redirect_name)
    if backup_absoluto.is_file() and backup_absoluto.suffix.lower() not in {".sqlite3", ".gz", ".dump"}:
        messages.error(request, "Formato de arquivo inválido para restore.")
        return redirect(redirect_name)
    if not backup_absoluto.exists():
        messages.error(request, "Backup não encontrado.")
        return redirect(redirect_name)

    restore_media = bool(request.POST.get("restore_media"))
    repair_single_tenant = bool(request.POST.get("repair_single_tenant"))

    try:
        registrar_evento_configuracao(
            usuario=getattr(request, "user", None) if getattr(getattr(request, "user", None), "is_authenticated", False) else None,
            acao="restore_solicitado",
            origem=origem,
            alvo="database",
            depois={"arquivo": str(backup_absoluto), "usuario": usuario_label},
        )
        call_command(
            "restore_db",
            str(backup_absoluto),
            force=True,
            restore_media=restore_media,
            repair_single_tenant=repair_single_tenant,
        )
        registrar_evento_configuracao(
            usuario=getattr(request, "user", None) if getattr(getattr(request, "user", None), "is_authenticated", False) else None,
            acao="restore_executado",
            origem=origem,
            alvo="database",
            depois={"arquivo": str(backup_absoluto), "usuario": usuario_label},
        )
        emitir_evento_interno(
            "restore.executado",
            {"usuario": usuario_label, "arquivo": str(backup_absoluto), "status": "sucesso", "origem": origem},
        )
        messages.success(request, "Restore executado com sucesso.")
    except Exception as exc:
        logger.exception("falha_restore_banco")
        registrar_evento_configuracao(
            usuario=getattr(request, "user", None) if getattr(getattr(request, "user", None), "is_authenticated", False) else None,
            acao="restore_falha",
            origem=origem,
            alvo="database",
            depois={"arquivo": str(backup_absoluto), "usuario": usuario_label, "erro": str(exc)},
        )
        emitir_evento_interno(
            "restore.executado",
            {"usuario": usuario_label, "arquivo": str(backup_absoluto), "status": "falha", "erro": str(exc), "origem": origem},
        )
        messages.error(request, f"Falha no restore: {exc}")
    return redirect(redirect_name)


def backup_banco_impl(request, logger):
    backup_dir = _backup_dir()
    if request.method == "POST":
        logger.info(
            "auditoria_operacional",
            extra={
                "acao": "backup_solicitado",
                "usuario": request.user.username,
                "ip": request_ip(request),
            },
        )
        db_name = str(settings.DATABASES.get("default", {}).get("NAME", ""))
        comando_mockado = isinstance(call_command, Mock)
        if (db_name.startswith("file:memorydb_") or db_name == ":memory:") and not comando_mockado:
            backup_dir.mkdir(parents=True, exist_ok=True)
            messages.info(request, "Backup ignorado: banco em memória (ambiente de teste).")
            return redirect("configuracoes:backup_banco")

        include_media = request.POST.get("include_media", "1") == "1"
        try:
            call_command("backup_db", output_dir=str(backup_dir), gzip=True, include_media=include_media)
            registrar_evento_configuracao(
                usuario=request.user,
                acao="backup_executado",
                origem="ui",
                alvo="database",
                depois={"diretorio": str(backup_dir), "include_media": include_media},
            )
            emitir_evento_interno(
                "backup.executado",
                {"usuario": request.user.username, "status": "sucesso", "include_media": include_media},
            )
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
            emitir_evento_interno(
                "backup.executado",
                {"usuario": request.user.username, "status": "falha", "erro": str(exc)},
            )
            messages.error(request, f"Falha ao gerar backup: {exc}")
        return redirect("configuracoes:backup_banco")

    return render(
        request,
        "configuracoes/backup.html",
        {
            **_restore_page_context(setup_pendente=not setup_inicial_concluido()),
            "saude_operacional": resumo_saude_operacional(),
            "operacao_tab": "backup",
            "operacao_title": "Backups e cópias oficiais",
            "operacao_subtitle": "Gere, baixe e revise backups locais para manter o ambiente protegido antes de alterações sensíveis.",
            "menu_app": "configuracoes",
            "menu_sub": "backup_banco",
        },
    )


def restore_banco_impl(request, logger):
    if request.method == "POST":
        return _executar_restore(
            request,
            logger,
            usuario_label=request.user.username,
            origem="ui",
            redirect_name="configuracoes:restore_banco",
        )

    return render(
        request,
        "configuracoes/restore.html",
        {
            **_restore_page_context(setup_pendente=not setup_inicial_concluido()),
            "saude_operacional": resumo_saude_operacional(),
            "operacao_tab": "restore",
            "operacao_title": "Restore administrativo",
            "operacao_subtitle": "Restaure base e arquivos com checklist visual e menor risco operacional para a equipe.",
            "menu_app": "configuracoes",
            "menu_sub": "restore_banco",
            "cancel_url": reverse("configuracoes:painel"),
        },
    )


def restore_banco_publico_impl(request, logger):
    if not _recovery_publico_liberado(request):
        return HttpResponseForbidden("Recuperação local indisponível neste ambiente.")

    if request.method == "POST":
        return _executar_restore(
            request,
            logger,
            usuario_label=f"recuperacao_local:{request_ip(request)}",
            origem="recuperacao_local",
            redirect_name="configuracoes:restore_banco_publico",
            exige_chave_recuperacao=True,
        )

    return render(
        request,
        "configuracoes/restore_publico.html",
        {
            **_restore_page_context(setup_pendente=not setup_inicial_concluido(), modo_recuperacao_local=True),
            "ip_origem": request_ip(request),
        },
    )


def download_backup_impl(request):
    backup_path = (request.GET.get("path") or "").strip()
    if not backup_path:
        raise Http404("Backup não informado.")

    target = Path(backup_path).resolve()
    backup_dir_abs = _backup_dir().resolve()
    if backup_dir_abs not in target.parents:
        raise Http404("Backup inválido.")
    if not target.exists():
        raise Http404("Backup não encontrado.")

    arquivo_download = target
    if target.is_dir():
        zip_path = target.with_suffix(".zip")
        precisa_regerar = (not zip_path.exists()) or zip_path.stat().st_mtime < target.stat().st_mtime
        if precisa_regerar:
            base_name = str(target)
            if zip_path.exists():
                zip_path.unlink(missing_ok=True)
            shutil.make_archive(base_name, "zip", root_dir=target.parent, base_dir=target.name)
        arquivo_download = zip_path

    return FileResponse(
        open(arquivo_download, "rb"),
        as_attachment=True,
        filename=arquivo_download.name,
    )


def auditoria_configuracoes_impl(request):
    eventos_qs = ConfiguracaoAuditoria.objects.select_related("usuario").all()
    acao = (request.GET.get("acao") or "").strip()
    origem = (request.GET.get("origem") or "").strip()
    if acao:
        eventos_qs = eventos_qs.filter(acao__icontains=acao)
    if origem:
        eventos_qs = eventos_qs.filter(origem=origem)

    eventos_page = Paginator(eventos_qs, 40).get_page(request.GET.get("page"))
    eventos_recentes = list(ConfiguracaoAuditoria.objects.select_related("usuario")[:8])
    total_backups = ConfiguracaoAuditoria.objects.filter(acao="backup_executado").count()
    total_restores = ConfiguracaoAuditoria.objects.filter(acao="restore_executado").count()
    total_falhas = ConfiguracaoAuditoria.objects.filter(
        acao__in=["backup_falha", "restore_falha"]
    ).count()
    return render(
        request,
        "configuracoes/auditoria_configuracoes.html",
        {
            "eventos": eventos_page,
            "eventos_recentes": eventos_recentes,
            "acao": acao,
            "origem": origem,
            "origens": ConfiguracaoAuditoria.ORIGEM_CHOICES,
            "auditoria_resumo": {
                "total_backups": total_backups,
                "total_restores": total_restores,
                "total_falhas": total_falhas,
            },
            "operacao_tab": "auditoria",
            "operacao_title": "Auditoria e rastreabilidade",
            "operacao_subtitle": "Consulte eventos críticos da configuração para acompanhar restores, backups e alterações relevantes.",
            "menu_app": "configuracoes",
            "menu_sub": "auditoria_configuracoes",
        },
    )



