import json
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from clientes.models import Cliente
from ordens.models import OrdemServico

from .models import AgendaDisponibilidade, Agendamento


class AgendaPublicoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.tecnico = user_model.objects.create_user(
            username="tecnico_agenda",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        self.data_base = timezone.localdate() + timedelta(days=3)
        AgendaDisponibilidade.objects.create(
            tecnico=self.tecnico,
            dia_semana=self.data_base.weekday(),
            hora_inicio=time(10, 0),
            hora_fim=time(12, 0),
            duracao_minutos=60,
            ativo=True,
        )

    def _dt_aware(self, hora, minuto=0):
        dt = datetime.combine(self.data_base, time(hora, minuto))
        return timezone.make_aware(dt, timezone.get_current_timezone())

    def test_api_slots_disponiveis_retorna_horarios_livres(self):
        response = self.client.get(
            reverse("agenda:api_slots_disponiveis"),
            {"tecnico_id": self.tecnico.id, "data": self.data_base.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("10:00", payload.get("slots", []))
        self.assertIn("11:00", payload.get("slots", []))

    def test_api_slots_disponiveis_ignora_horario_ja_ocupado(self):
        Agendamento.objects.create(
            titulo="Atendimento ocupado",
            tecnico=self.tecnico,
            data_inicio=self._dt_aware(10),
            data_fim=self._dt_aware(11),
            status="agendado",
        )

        response = self.client.get(
            reverse("agenda:api_slots_disponiveis"),
            {"tecnico_id": self.tecnico.id, "data": self.data_base.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("10:00", payload.get("slots", []))
        self.assertIn("11:00", payload.get("slots", []))

    def test_agendamento_publico_cria_solicitacao(self):
        response = self.client.post(
            reverse("agenda:agendar_publico"),
            {
                "nome_cliente": "Cliente Agenda",
                "telefone": "11999999999",
                "email": "cliente@agenda.com",
                "tecnico": self.tecnico.id,
                "data": self.data_base.isoformat(),
                "slot": "10:00",
                "descricao": "Teste de agendamento online",
            },
        )
        self.assertEqual(response.status_code, 200)
        agendamento = Agendamento.objects.get()
        self.assertEqual(agendamento.origem, "publico")
        self.assertEqual(agendamento.status, "solicitado")
        self.assertEqual(agendamento.tecnico_id, self.tecnico.id)
        self.assertContains(response, "Protocolo")


class AgendaCalendarioTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.atendente = user_model.objects.create_user(
            username="atendente_agenda",
            password="senha-forte-123",
            tipo_usuario="atendente",
        )
        self.tecnico = user_model.objects.create_user(
            username="tecnico_calendario",
            password="senha-forte-123",
            tipo_usuario="tecnico",
        )
        inicio = timezone.now() + timedelta(days=1)
        self.agendamento = Agendamento.objects.create(
            titulo="Reparo microondas",
            tecnico=self.tecnico,
            data_inicio=inicio,
            data_fim=inicio + timedelta(hours=1),
            status="agendado",
            origem="interno",
        )
        self.cliente = Cliente.objects.create(
            nome="Cliente Agenda",
            documento="39053344705",
            telefone="11990001122",
            estado="SP",
        )
        self.ordem = OrdemServico.objects.create(
            cliente=self.cliente,
            tipo_equipamento="celular",
            marca_equipamento="Marca X",
            modelo_equipamento="Modelo Y",
            defeito="Nao liga",
            tipo_reparo="Fora de Garantia",
            status="em_andamento",
        )

    def test_calendario_renderiza_para_usuario_logado(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("agenda:calendario_agenda"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "agenda-calendar")

    @override_settings(TIME_ZONE="Europe/Lisbon")
    def test_calendario_usa_timezone_do_settings(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("agenda:calendario_agenda"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'timeZone: "Europe/Lisbon"')

    def test_api_eventos_retorna_evento(self):
        self.client.force_login(self.atendente)
        inicio = (timezone.localdate() - timedelta(days=1)).isoformat()
        fim = (timezone.localdate() + timedelta(days=7)).isoformat()
        response = self.client.get(reverse("agenda:api_eventos_agenda"), {"start": inicio, "end": fim})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(len(payload.get("eventos", [])), 1)
        self.assertEqual(payload["eventos"][0]["id"], self.agendamento.id)
        evento = payload["eventos"][0]
        self.assertNotIn("+", evento.get("start", ""))
        self.assertNotIn("Z", evento.get("start", ""))

    def test_api_mover_agendamento_atualiza_datas(self):
        self.client.force_login(self.atendente)
        novo_inicio = timezone.now() + timedelta(days=2)
        novo_fim = novo_inicio + timedelta(hours=2)
        response = self.client.post(
            reverse("agenda:api_mover_agendamento", args=[self.agendamento.id]),
            data=json.dumps(
                {
                    "start": novo_inicio.isoformat(),
                    "end": novo_fim.isoformat(),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.agendamento.refresh_from_db()
        self.assertEqual(self.agendamento.data_inicio.date(), novo_inicio.date())
        self.assertEqual(self.agendamento.data_fim.date(), novo_fim.date())

    def test_api_modal_novo_retorna_formulario(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("agenda:api_modal_agendamento_novo"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("data-agenda-modal-form", payload.get("html", ""))

    def test_criar_agendamento_prefill_por_query_da_os(self):
        self.client.force_login(self.atendente)
        inicio = timezone.localtime(timezone.now() + timedelta(days=1))
        fim = inicio + timedelta(hours=1)
        response = self.client.get(
            reverse("agenda:criar_agendamento"),
            {
                "ordem": self.ordem.id,
                "cliente": self.cliente.id,
                "tecnico": self.tecnico.id,
                "titulo": f"Reparo OS {self.ordem.numero_os}",
                "descricao": "Teste prefill",
                "inicio": inicio.isoformat(),
                "fim": fim.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial.get("ordem_servico"), self.ordem.id)
        self.assertEqual(form.initial.get("cliente"), self.cliente.id)
        self.assertEqual(form.initial.get("tecnico"), self.tecnico.id)
        self.assertIn("Reparo OS", form.initial.get("titulo", ""))

    def test_criar_agendamento_post_com_data_invalida_nao_retorna_500(self):
        self.client.force_login(self.atendente)
        response = self.client.post(
            reverse("agenda:criar_agendamento"),
            {
                "titulo": "Teste invalido",
                "status": "agendado",
                "tecnico": self.tecnico.id,
                "data_inicio": "data-invalida",
                "data_fim": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-invalida")

    def test_api_modal_editar_retorna_acoes_rapidas(self):
        self.client.force_login(self.atendente)
        response = self.client.get(reverse("agenda:api_modal_agendamento_editar", args=[self.agendamento.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("data-agenda-quick-action=\"cancelar\"", payload.get("html", ""))

    def test_api_modal_novo_cria_agendamento(self):
        self.client.force_login(self.atendente)
        inicio = timezone.localtime(timezone.now() + timedelta(days=3))
        fim = inicio + timedelta(hours=1)
        response = self.client.post(
            reverse("agenda:api_modal_agendamento_novo"),
            {
                "titulo": "Agendamento via modal",
                "status": "agendado",
                "tecnico": self.tecnico.id,
                "data_inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
                "data_fim": fim.strftime("%Y-%m-%dT%H:%M"),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(Agendamento.objects.filter(titulo="Agendamento via modal").exists())

    def test_api_modal_editar_atualiza_agendamento(self):
        self.client.force_login(self.atendente)
        inicio = timezone.localtime(self.agendamento.data_inicio + timedelta(days=1))
        fim = inicio + timedelta(hours=1)
        response = self.client.post(
            reverse("agenda:api_modal_agendamento_editar", args=[self.agendamento.id]),
            {
                "titulo": "Reparo atualizado",
                "status": "confirmado",
                "tecnico": self.tecnico.id,
                "data_inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
                "data_fim": fim.strftime("%Y-%m-%dT%H:%M"),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.agendamento.refresh_from_db()
        self.assertEqual(self.agendamento.titulo, "Reparo atualizado")
        self.assertEqual(self.agendamento.status, "confirmado")

    def test_api_acao_cancelar_agendamento(self):
        self.client.force_login(self.atendente)
        response = self.client.post(
            reverse("agenda:api_acao_agendamento", args=[self.agendamento.id]),
            {"acao": "cancelar"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.agendamento.refresh_from_db()
        self.assertEqual(self.agendamento.status, "cancelado")

    def test_api_acao_concluir_agendamento(self):
        self.client.force_login(self.atendente)
        response = self.client.post(
            reverse("agenda:api_acao_agendamento", args=[self.agendamento.id]),
            {"acao": "concluir"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.agendamento.refresh_from_db()
        self.assertEqual(self.agendamento.status, "concluido")

    def test_api_acao_duplicar_agendamento(self):
        self.client.force_login(self.atendente)
        response = self.client.post(
            reverse("agenda:api_acao_agendamento", args=[self.agendamento.id]),
            {"acao": "duplicar"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(Agendamento.objects.count(), 2)
        novo = Agendamento.objects.exclude(id=self.agendamento.id).first()
        self.assertIsNotNone(novo)
        self.assertEqual(novo.status, "agendado")
        self.assertEqual((novo.data_inicio.date() - self.agendamento.data_inicio.date()).days, 7)
