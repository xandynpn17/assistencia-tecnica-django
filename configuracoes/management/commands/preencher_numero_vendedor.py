import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import OperationalError, transaction
from django.db.models import Q


class Command(BaseCommand):
    help = "Preenche numero_vendedor para usuarios que estao sem esse campo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula a atualizacao sem persistir alteracoes no banco.",
        )
        parser.add_argument(
            "--listar",
            action="store_true",
            help="Exibe usuario e numero_vendedor gerado para cada registro atualizado.",
        )

    @staticmethod
    def _is_database_locked(exc):
        mensagem = str(exc).lower()
        return "database is locked" in mensagem or "database table is locked" in mensagem

    def _salvar_com_retry(self, usuario, tentativas=30, espera=0.2):
        ultima_excecao = None
        for tentativa in range(1, tentativas + 1):
            try:
                usuario.save()
                return
            except OperationalError as exc:
                if not self._is_database_locked(exc):
                    raise
                ultima_excecao = exc
                if tentativa >= tentativas:
                    break
                time.sleep(espera)
        if ultima_excecao:
            raise ultima_excecao

    def _preencher_usuarios(self, usuarios, *, listar=False):
        atualizados = []
        for usuario in usuarios:
            usuario.numero_vendedor = None
            self._salvar_com_retry(usuario)
            atualizados.append((usuario.username, usuario.numero_vendedor))
            if listar:
                self.stdout.write(f"- {usuario.username}: {usuario.numero_vendedor}")
        return atualizados

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        listar = bool(options.get("listar"))
        user_model = get_user_model()

        usuarios_sem_numero = user_model.objects.filter(
            Q(numero_vendedor__isnull=True) | Q(numero_vendedor="")
        ).order_by("id")
        total_alvo = usuarios_sem_numero.count()

        if total_alvo == 0:
            self.stdout.write(self.style.SUCCESS("Nenhum usuario sem numero_vendedor encontrado."))
            return

        if dry_run:
            with transaction.atomic():
                atualizados = self._preencher_usuarios(usuarios_sem_numero, listar=listar)
                transaction.set_rollback(True)
        else:
            atualizados = self._preencher_usuarios(usuarios_sem_numero, listar=listar)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY-RUN concluido. Usuarios analisados: {total_alvo}. Nenhuma alteracao persistida."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Atualizacao concluida. Usuarios com numero_vendedor preenchido: {len(atualizados)}."
            )
        )
