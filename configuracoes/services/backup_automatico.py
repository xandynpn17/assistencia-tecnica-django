"""Backups locais com lock de processo e cópia cifrada para pasta de nuvem."""
import base64
from contextlib import contextmanager
import hashlib
from io import StringIO
import logging
import os
from pathlib import Path
import re
import tempfile
import zipfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from configuracoes.models import ConfiguracaoSistema, ExecucaoBackup, PoliticaBackup

logger = logging.getLogger(__name__)
CABECALHO = b"ABGEST-BACKUP\x01"
BLOCO = 1024 * 1024


def chave_backup():
    try:
        chave = base64.urlsafe_b64decode(os.environ.get("ABGEST_BACKUP_KEY", "").encode("ascii"))
        if len(chave) != 32:
            raise ValueError()
        return chave
    except (ValueError, UnicodeError):
        raise ValidationError("Configure ABGEST_BACKUP_KEY com uma chave de 32 bytes em base64 e guarde-a fora do servidor.") from None


def hash_arquivo(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(BLOCO), b""):
            sha.update(bloco)
    return sha.hexdigest()


@contextmanager
def trava_backup(diretorio):
    diretorio = Path(diretorio)
    diretorio.mkdir(parents=True, exist_ok=True)
    with (diretorio / ".rotina_backup.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValidationError("Já existe uma rotina de backup em execução.") from None
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def cifrar_pacote(origem, destino):
    chave = chave_backup()
    nonce = os.urandom(12)
    cifrador = Cipher(algorithms.AES(chave), modes.GCM(nonce)).encryptor()
    cifrador.authenticate_additional_data(CABECALHO)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(dir=destino.parent, suffix=".partial", delete=False) as saida:
            temporario = Path(saida.name)
            saida.write(CABECALHO + nonce)
            with Path(origem).open("rb") as entrada:
                for bloco in iter(lambda: entrada.read(BLOCO), b""):
                    saida.write(cifrador.update(bloco))
            saida.write(cifrador.finalize())
            saida.write(cifrador.tag)
            saida.flush()
            os.fsync(saida.fileno())
        os.replace(temporario, destino)
    finally:
        if temporario and temporario.exists():
            temporario.unlink()


def decifrar_pacote(origem, destino):
    from cryptography.exceptions import InvalidTag
    destino = Path(destino)
    if destino.exists():
        raise ValidationError("O destino já existe. Escolha um novo ficheiro para não sobrescrever dados.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    try:
        with Path(origem).open("rb") as entrada:
            tamanho = entrada.seek(0, os.SEEK_END)
            if tamanho < len(CABECALHO) + 12 + 16:
                raise ValidationError("Pacote cifrado inválido.")
            entrada.seek(0)
            if entrada.read(len(CABECALHO)) != CABECALHO:
                raise ValidationError("Formato de backup cifrado não reconhecido.")
            nonce = entrada.read(12)
            entrada.seek(-16, os.SEEK_END)
            tag = entrada.read(16)
            decifrador = Cipher(algorithms.AES(chave_backup()), modes.GCM(nonce, tag)).decryptor()
            decifrador.authenticate_additional_data(CABECALHO)
            entrada.seek(len(CABECALHO) + 12)
            restante = tamanho - len(CABECALHO) - 12 - 16
            with tempfile.NamedTemporaryFile(dir=destino.parent, suffix=".partial", delete=False) as saida:
                temporario = Path(saida.name)
                while restante:
                    bloco = entrada.read(min(BLOCO, restante))
                    if not bloco:
                        raise ValidationError("Pacote cifrado incompleto.")
                    restante -= len(bloco)
                    saida.write(decifrador.update(bloco))
                saida.write(decifrador.finalize())
        with zipfile.ZipFile(temporario) as pacote:
            if pacote.testzip():
                raise ValidationError("O pacote recuperado falhou na verificação de integridade.")
        # Publicar sem sobrescrever um destino criado por outra operação.
        with temporario.open("rb") as entrada, destino.open("xb") as saida:
            import shutil
            try:
                shutil.copyfileobj(entrada, saida)
            except Exception:
                saida.close()
                destino.unlink(missing_ok=True)
                raise
    except InvalidTag:
        raise ValidationError("Chave incorreta ou backup alterado. Nenhum pacote foi recuperado.") from None
    finally:
        if temporario and temporario.exists():
            temporario.unlink()


def _copiar_nuvem(execucao, politica, diretorio, agora):
    try:
        pacote = Path(execucao.pacote)
        if not pacote.is_file() or hash_arquivo(pacote) != execucao.sha256:
            raise ValidationError("A cópia local não corresponde à execução verificada.")
        nuvem = Path(politica.pasta_nuvem).resolve()
        if nuvem == diretorio or nuvem in diretorio.parents or diretorio in nuvem.parents:
            raise ValidationError("As pastas local e de nuvem devem ser independentes.")
        cifrar_pacote(pacote, nuvem / (pacote.name + ".abenc"))
        execucao.nuvem_status, execucao.erro = "aguarda_sync", ""
        corte = agora.timestamp() - politica.retencao_nuvem_dias * 86400
        for antigo in nuvem.iterdir():
            if antigo.is_file() and re.fullmatch(r"backup_\d{8}_\d{6}\.zip\.abenc", antigo.name) and antigo.stat().st_mtime < corte:
                antigo.unlink()
    except Exception:
        execucao.nuvem_status = "falha"
        execucao.erro = "Backup local concluído; cópia cifrada para nuvem falhou. Verifique pasta, chave e espaço."
        logger.exception("falha_copia_backup_nuvem")


def executar_rotina_backup(*, agendado=False):
    politica = PoliticaBackup.objects.filter(pk=1).first()
    if not politica:
        return None
    agora = timezone.localtime()
    if agendado and (not politica.ativo or agora.time().replace(tzinfo=None) < politica.horario):
        return None
    diretorio = Path(ConfiguracaoSistema.resolver_diretorio_backup()).resolve()
    with trava_backup(diretorio):
        # Repetição da tarefa não produz outra cópia automática no mesmo dia.
        anterior = ExecucaoBackup.objects.filter(agendado=True, status="sucesso", iniciado_em__date=agora.date()).first() if agendado else None
        if anterior:
            if anterior.nuvem_status == "falha" and politica.destino_nuvem == "pasta":
                _copiar_nuvem(anterior, politica, diretorio, agora)
                anterior.terminado_em = timezone.now()
                anterior.save()
                return anterior
            return None
        execucao = ExecucaoBackup.objects.create(agendado=agendado)
        try:
            anteriores = {p.name for p in diretorio.glob("backup_*.zip")}
            call_command("backup_db", output_dir=str(diretorio), include_media=True, skip_lock=True, stdout=StringIO())
            novos = [p for p in diretorio.glob("backup_*.zip") if p.name not in anteriores]
            if len(novos) != 1:
                raise ValidationError("Não foi possível identificar o novo pacote de backup.")
            pacote = novos[0]
            with zipfile.ZipFile(pacote) as zipf:
                if zipf.testzip():
                    raise ValidationError("Backup inválido. A última cópia válida foi preservada.")
            execucao.pacote = str(pacote)
            execucao.tamanho_bytes = pacote.stat().st_size
            execucao.sha256 = hash_arquivo(pacote)
            execucao.status = "sucesso"
            if politica.destino_nuvem == "pasta":
                _copiar_nuvem(execucao, politica, diretorio, agora)
        except Exception:
            execucao.status = "falha"
            execucao.erro = "Falha no backup local. Verifique acesso ao PostgreSQL, pasta, anexos e espaço disponível."
            logger.exception("falha_rotina_backup")
        finally:
            execucao.terminado_em = timezone.now()
            execucao.save()
        return execucao
