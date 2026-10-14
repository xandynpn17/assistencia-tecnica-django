import base64
from datetime import time
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from configuracoes.forms_backup import PoliticaBackupForm
from configuracoes.management.commands.validar_recuperacao_backup import preparar_pacote
from configuracoes.models import Empresa, ExecucaoBackup, PoliticaBackup, User
from configuracoes.services.backup_automatico import (chave_backup, cifrar_pacote, decifrar_pacote,
                                                     executar_rotina_backup, hash_arquivo, trava_backup)

CHAVE = base64.urlsafe_b64encode(b'a' * 32).decode()


class BackupAutomaticoTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.local = self.raiz / 'local'
        self.nuvem = self.raiz / 'nuvem'
        self.local.mkdir()
        self.env = patch.dict(os.environ, {'ABGEST_BACKUP_KEY': CHAVE})
        self.env.start()
        self.addCleanup(self.env.stop)

    def pacote(self, pasta=None):
        pacote = (pasta or self.local) / 'backup_20260916_235959.zip'
        with zipfile.ZipFile(pacote, 'w') as zipf:
            zipf.writestr('teste.txt', 'conteúdo privado')
        return pacote

    def test_cifra_recupera_hash_identico_sem_sobrescrever(self):
        original = self.pacote()
        cifrado = self.nuvem / 'backup.abenc'
        destino = self.raiz / 'recuperado.zip'
        cifrar_pacote(original, cifrado)
        self.assertNotIn(b'conte', cifrado.read_bytes())
        decifrar_pacote(cifrado, destino)
        self.assertEqual(hash_arquivo(original), hash_arquivo(destino))
        with self.assertRaises(ValidationError):
            decifrar_pacote(cifrado, destino)
        self.assertEqual(hash_arquivo(original), hash_arquivo(destino))

    def test_chave_errada_ou_pacote_alterado_nao_publica_destino(self):
        original = self.pacote()
        cifrado = self.raiz / 'backup.abenc'
        cifrar_pacote(original, cifrado)
        destino = self.raiz / 'recuperado.zip'
        with patch.dict(os.environ, {'ABGEST_BACKUP_KEY': base64.urlsafe_b64encode(b'b' * 32).decode()}):
            with self.assertRaises(ValidationError):
                decifrar_pacote(cifrado, destino)
        self.assertFalse(destino.exists())
        dados = bytearray(cifrado.read_bytes())
        dados[-1] ^= 1
        cifrado.write_bytes(dados)
        with self.assertRaises(ValidationError):
            decifrar_pacote(cifrado, destino)
        self.assertFalse(destino.exists())
        self.assertEqual(list(self.raiz.glob('*.partial')), [])

    def test_chave_obrigatoria(self):
        with patch.dict(os.environ, {'ABGEST_BACKUP_KEY': ''}):
            with self.assertRaises(ValidationError):
                chave_backup()

    def test_lock_impede_duas_rotinas(self):
        with trava_backup(self.local):
            with self.assertRaises(ValidationError):
                with trava_backup(self.local):
                    self.fail('Não deveria obter a segunda trava')
        with trava_backup(self.local):
            pass

    def test_desativado_e_horario_futuro_nao_executam(self):
        p = PoliticaBackup.objects.create(pk=1, ativo=False, horario=time(0, 0))
        self.assertIsNone(executar_rotina_backup(agendado=True))
        p.ativo, p.horario = True, time(23, 59, 59)
        p.save()
        self.assertIsNone(executar_rotina_backup(agendado=True))
        self.assertFalse(ExecucaoBackup.objects.exists())

    @patch('configuracoes.services.backup_automatico.call_command')
    @patch('configuracoes.models.ConfiguracaoSistema.resolver_diretorio_backup')
    def test_execucao_agendada_idempotente_e_copia_nao_afirma_upload(self, resolver, comando):
        resolver.return_value = self.local
        comando.side_effect = lambda *args, **kwargs: self.pacote()
        PoliticaBackup.objects.create(pk=1, ativo=True, horario=time(0, 0), destino_nuvem='pasta', pasta_nuvem=str(self.nuvem))
        resultado = executar_rotina_backup(agendado=True)
        self.assertEqual(resultado.status, 'sucesso')
        self.assertEqual(resultado.nuvem_status, 'aguarda_sync')
        self.assertEqual(len(resultado.sha256), 64)
        self.assertEqual(len(list(self.nuvem.glob('*.abenc'))), 1)
        self.assertIsNone(executar_rotina_backup(agendado=True))
        self.assertEqual(comando.call_count, 1)
        self.assertEqual(ExecucaoBackup.objects.count(), 1)

    @patch('configuracoes.services.backup_automatico.call_command')
    @patch('configuracoes.models.ConfiguracaoSistema.resolver_diretorio_backup')
    def test_falha_local_preserva_ultimo_pacote(self, resolver, comando):
        resolver.return_value = self.local
        antigo = self.pacote()
        sha = hash_arquivo(antigo)
        comando.side_effect = CommandError('dump indisponível')
        PoliticaBackup.objects.create(pk=1)
        with self.assertLogs('configuracoes.services.backup_automatico', level='ERROR'):
            resultado = executar_rotina_backup()
        self.assertEqual(resultado.status, 'falha')
        self.assertEqual(hash_arquivo(antigo), sha)

    @patch('configuracoes.services.backup_automatico.call_command')
    @patch('configuracoes.models.ConfiguracaoSistema.resolver_diretorio_backup')
    def test_falha_nuvem_nao_elimina_copia_local(self, resolver, comando):
        resolver.return_value = self.local
        comando.side_effect = lambda *args, **kwargs: self.pacote()
        PoliticaBackup.objects.create(pk=1, destino_nuvem='pasta', pasta_nuvem=str(self.nuvem))
        with patch.dict(os.environ, {'ABGEST_BACKUP_KEY': ''}), self.assertLogs('configuracoes.services.backup_automatico', level='ERROR'):
            resultado = executar_rotina_backup()
        self.assertEqual((resultado.status, resultado.nuvem_status), ('sucesso', 'falha'))
        self.assertTrue(Path(resultado.pacote).exists())

    @patch('configuracoes.models.ConfiguracaoSistema.resolver_diretorio_backup')
    def test_formulario_rejeita_destino_local_e_sem_chave(self, resolver):
        resolver.return_value = self.local
        dados = {'ativo': 'on', 'horario': '23:00', 'destino_nuvem': 'pasta', 'pasta_nuvem': str(self.local), 'retencao_nuvem_dias': 30}
        form = PoliticaBackupForm(dados, instance=PoliticaBackup(pk=1))
        self.assertFalse(form.is_valid())
        self.assertIn('pasta_nuvem', form.errors)
        dados['pasta_nuvem'] = str(self.nuvem)
        with patch.dict(os.environ, {'ABGEST_BACKUP_KEY': ''}):
            self.assertFalse(PoliticaBackupForm(dados, instance=PoliticaBackup(pk=1)).is_valid())

    @patch('configuracoes.services.backup_automatico.call_command')
    @patch('configuracoes.models.ConfiguracaoSistema.resolver_diretorio_backup')
    def test_repeticao_recupera_copia_nuvem_sem_duplicar_backup_local(self, resolver, comando):
        resolver.return_value = self.local
        comando.side_effect = lambda *args, **kwargs: self.pacote()
        PoliticaBackup.objects.create(pk=1, ativo=True, horario=time(0, 0), destino_nuvem='pasta', pasta_nuvem=str(self.nuvem))
        with patch.dict(os.environ, {'ABGEST_BACKUP_KEY': ''}), self.assertLogs('configuracoes.services.backup_automatico', level='ERROR'):
            resultado = executar_rotina_backup(agendado=True)
        self.assertEqual(resultado.nuvem_status, 'falha')
        repetido = executar_rotina_backup(agendado=True)
        self.assertEqual(repetido.pk, resultado.pk)
        self.assertEqual(repetido.nuvem_status, 'aguarda_sync')
        self.assertEqual(comando.call_count, 1)

    @patch('configuracoes.services.backup_automatico.call_command')
    @patch('configuracoes.models.ConfiguracaoSistema.resolver_diretorio_backup')
    def test_retencao_nuvem_nao_apaga_arquivos_alheios(self, resolver, comando):
        resolver.return_value = self.local
        comando.side_effect = lambda *args, **kwargs: self.pacote()
        self.nuvem.mkdir()
        proprio = self.nuvem / 'backup_20260101_230000.zip.abenc'
        alheio = self.nuvem / 'backup_documentos_importantes.zip'
        for arquivo in [proprio, alheio]:
            arquivo.write_bytes(b'copia anterior')
            os.utime(arquivo, (100, 100))
        PoliticaBackup.objects.create(pk=1, destino_nuvem='pasta', pasta_nuvem=str(self.nuvem), retencao_nuvem_dias=30)
        executar_rotina_backup()
        self.assertFalse(proprio.exists())
        self.assertTrue(alheio.exists())

    def test_tela_e_configuracao_global_nao_disponiveis_a_gerente_ou_admin_de_tenant(self):
        empresa = Empresa.objects.create(nome='Empresa backup')
        user = User.objects.create_user(username='gestor_backup', tipo_usuario='gerente', empresa=empresa)
        self.client.force_login(user)
        url = reverse('configuracoes:rotina_backup')
        self.assertEqual(self.client.get(url).status_code, 403)
        user.tipo_usuario = 'adm'
        user.save()
        self.assertEqual(self.client.get(url).status_code, 200)
        Empresa.objects.create(nome='Outra empresa backup')
        self.assertEqual(self.client.get(url).status_code, 403)
        user.is_superuser = True
        user.save()
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_backup_manual_download_restore_negam_admin_de_outra_empresa(self):
        empresa = Empresa.objects.create(nome='Empresa do administrador')
        Empresa.objects.create(nome='Empresa não autorizada')
        user = User.objects.create_user(username='admin_backup_manual', tipo_usuario='adm', empresa=empresa)
        self.client.force_login(user)
        for nome in ['backup_banco', 'download_backup', 'restore_banco']:
            self.assertEqual(self.client.get(reverse('configuracoes:' + nome)).status_code, 403)
            self.assertEqual(self.client.post(reverse('configuracoes:' + nome)).status_code, 403)

    def test_ensaio_rejeita_hash_incorreto_antes_de_criar_banco(self):
        pacote = self.raiz / 'invalido.zip'
        with zipfile.ZipFile(pacote, 'w') as z:
            z.writestr('backup/manifest.json', json.dumps({'database_file': 'database.dump', 'media_file': 'media.zip', 'files': {'database.dump': {'sha256': 'errado', 'size': 4}}}))
            z.writestr('backup/database.dump', b'dump')
        destino = self.raiz / 'ensaio'
        destino.mkdir()
        with self.assertRaises(CommandError):
            preparar_pacote(pacote, destino)
