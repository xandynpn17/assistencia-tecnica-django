"""Ensaio de recuperação: nunca aceita um banco ou pasta de destino em uso."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4
import zipfile

import psycopg
from psycopg import sql
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from configuracoes.management.commands.backup_db import Command as BackupCommand


def preparar_pacote(origem, temporario):
    """Lê apenas arquivos esperados; verifica CRC, tamanho e hash do manifesto."""
    with zipfile.ZipFile(origem) as pacote:
        manifestos = [n for n in pacote.namelist() if n.endswith('/manifest.json') or n == 'manifest.json']
        if len(manifestos) != 1 or pacote.testzip():
            raise CommandError('Pacote inválido ou sem manifesto único.')
        manifesto = json.loads(pacote.read(manifestos[0]))
        prefixo = manifestos[0][:-len('manifest.json')]
        nomes = [manifesto.get('database_file'), manifesto.get('media_file')]
        if nomes != ['database.dump', 'media.zip']:
            raise CommandError('Este ensaio exige pacote PostgreSQL completo, incluindo anexos.')
        for nome in nomes:
            sha, tamanho = hashlib.sha256(), 0
            with pacote.open(prefixo + nome) as entrada, (temporario / nome).open('xb') as saida:
                for bloco in iter(lambda: entrada.read(1024 * 1024), b''):
                    sha.update(bloco)
                    tamanho += len(bloco)
                    saida.write(bloco)
            esperado = manifesto.get('files', {}).get(nome)
            if esperado and (sha.hexdigest() != esperado.get('sha256') or tamanho != esperado.get('size')):
                raise CommandError('O pacote não corresponde ao hash/tamanho do manifesto.')
    media = temporario / 'anexos_recuperados'
    media.mkdir()
    with zipfile.ZipFile(temporario / 'media.zip') as anexos:
        if anexos.testzip():
            raise CommandError('Um anexo falhou na verificação de integridade.')
        for info in anexos.infolist():
            destino = (media / info.filename).resolve()
            if destino != media.resolve() and media.resolve() not in destino.parents:
                raise CommandError('Caminho inseguro dentro dos anexos.')
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise CommandError('Link simbólico não é permitido no pacote.')
        anexos.extractall(media)
    return manifesto, sum(1 for p in media.rglob('*') if p.is_file())


class Command(BaseCommand):
    help = 'Testa um backup próprio num PostgreSQL temporário e recupera anexos numa pasta temporária. Não altera o banco ativo.'

    def add_arguments(self, parser):
        parser.add_argument('pacote')

    def handle(self, *args, **options):
        db = settings.DATABASES['default']
        if db['ENGINE'] != 'django.db.backends.postgresql':
            raise CommandError('Ensaio disponível para PostgreSQL.')
        pg_restore = BackupCommand()._resolve_pg_tool('pg_restore')
        nome = 'abgest_validacao_' + uuid4().hex
        conexao = dict(host=db.get('HOST') or None, port=db.get('PORT') or None,
                       user=db.get('USER') or None, password=db.get('PASSWORD') or None,
                       dbname='postgres')
        if (db.get('OPTIONS') or {}).get('sslmode'):
            conexao['sslmode'] = db['OPTIONS']['sslmode']
        criado = False
        try:
            with tempfile.TemporaryDirectory(prefix='abgest_recuperacao_') as pasta:
                manifesto, anexos = preparar_pacote(Path(options['pacote']), Path(pasta))
                with psycopg.connect(**conexao, autocommit=True) as admin:
                    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(nome)))
                    criado = True
                    env = os.environ.copy()
                    if db.get('PASSWORD'):
                        env['PGPASSWORD'] = str(db['PASSWORD'])
                    if conexao.get('sslmode'):
                        env['PGSSLMODE'] = conexao['sslmode']
                    comando = [str(pg_restore), '--exit-on-error', '--single-transaction', '--no-owner', '--no-privileges', '--dbname', nome]
                    for chave, parametro in [('HOST', '--host'), ('PORT', '--port'), ('USER', '--username')]:
                        if db.get(chave):
                            comando += [parametro, str(db[chave])]
                    subprocess.run(comando + [str(Path(pasta) / 'database.dump')], check=True, capture_output=True, env=env)
                    with psycopg.connect(**{**conexao, 'dbname': nome}) as recuperado:
                        migrations = recuperado.execute('SELECT count(*) FROM django_migrations').fetchone()[0]
                        tabelas = recuperado.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
                        if manifesto.get('migrations') and migrations != len(manifesto['migrations']):
                            raise CommandError('O esquema recuperado difere do manifesto.')
                    self.stdout.write(self.style.SUCCESS(f'Recuperação isolada confirmada: {tabelas} tabelas, {migrations} migrations e {anexos} anexos recuperados. Banco ativo preservado.'))
                    self.stdout.write('Isto verifica recuperação e integridade; não substitui conferir vínculos de anexos ou testar a operação da loja.')
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError('Ensaio falhou. Verifique pacote, acesso ao PostgreSQL e permissão para criar banco temporário. O banco ativo não foi restaurado.') from exc
        finally:
            if criado:
                with psycopg.connect(**conexao, autocommit=True) as admin:
                    admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(nome)))
