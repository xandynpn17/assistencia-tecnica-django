from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from clientes.models import Cliente
from configuracoes.models import User
from ordens.models import OrdemServico

PENDING_STOPPED_STATUSES = {
    "pendente_cliente",
    "pendente_tecnico",
    "pendente_pecas",
    "pendente_marca",
}


class Command(BaseCommand):
    help = (
        "Gera ordens de servico de teste com datas antigas/novas para validar indicadores, "
        "incluindo o card de 'Paradas ha 15+ dias'."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--quantidade",
            type=int,
            default=24,
            help="Quantidade de OS de teste a criar (padrao: 24).",
        )
        parser.add_argument(
            "--prefixo",
            type=str,
            default="ZZ_TESTE_AUTO_OS",
            help="Prefixo para identificar clientes/OS de teste.",
        )
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Remove clientes e OS de teste existentes com o prefixo informado antes de gerar novos.",
        )
        parser.add_argument(
            "--tecnico",
            type=str,
            default="tecnico_teste_auto",
            help="Username do tecnico de teste (padrao: tecnico_teste_auto).",
        )
        parser.add_argument(
            "--senha-tecnico",
            type=str,
            default="Teste@123",
            help="Senha para o tecnico criado automaticamente.",
        )

    def handle(self, *args, **options):
        quantidade = options["quantidade"]
        prefixo = (options["prefixo"] or "").strip() or "ZZ_TESTE_AUTO_OS"
        username_tecnico = (options["tecnico"] or "").strip() or "tecnico_teste_auto"
        senha_tecnico = options["senha_tecnico"] or "Teste@123"

        limpou_registros = False
        if options["limpar"]:
            clientes_teste = Cliente.objects.filter(nome__startswith=prefixo)
            total_clientes = clientes_teste.count()
            total_ordens = OrdemServico.objects.filter(cliente__in=clientes_teste).count()
            clientes_teste.delete()
            limpou_registros = True
            self.stdout.write(
                self.style.WARNING(
                    f"Registros removidos: {total_clientes} cliente(s) e {total_ordens} OS de teste."
                )
            )

        if quantidade <= 0:
            if limpou_registros and quantidade == 0:
                self.stdout.write(self.style.SUCCESS("Somente limpeza executada com sucesso."))
                return
            raise CommandError("Use --quantidade com valor maior que zero.")

        tecnico = self._obter_ou_criar_tecnico(username_tecnico=username_tecnico, senha=senha_tecnico)
        cliente = self._criar_cliente_teste(prefixo=prefixo)
        resumo = self._gerar_ordens(cliente=cliente, tecnico=tecnico, quantidade=quantidade)

        self.stdout.write(self.style.SUCCESS("Dados de teste gerados com sucesso."))
        self.stdout.write(f"Cliente teste: {cliente.nome} (id={cliente.id})")
        self.stdout.write(f"Tecnico teste: {tecnico.username}")
        self.stdout.write(f"OS criadas: {resumo['total_os']}")
        self.stdout.write(f"OS pendentes totais: {resumo['pendentes_total']}")
        self.stdout.write(f"OS pendentes com 15+ dias: {resumo['pendentes_15_mais']}")
        self.stdout.write(
            "Validacao rapida: acesse o Dashboard gerencial e confira o card 'Paradas ha 15+ dias'."
        )

    def _obter_ou_criar_tecnico(self, *, username_tecnico: str, senha: str) -> User:
        tecnico, created = User.objects.get_or_create(
            username=username_tecnico,
            defaults={
                "tipo_usuario": "tecnico",
                "is_active": True,
                "nome_completo": "Tecnico Teste Automatico",
            },
        )
        if created:
            tecnico.set_password(senha)
            tecnico.save(update_fields=["password"])
        elif tecnico.tipo_usuario != "tecnico":
            tecnico.tipo_usuario = "tecnico"
            tecnico.save(update_fields=["tipo_usuario"])
        return tecnico

    def _criar_cliente_teste(self, *, prefixo: str) -> Cliente:
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        return Cliente.objects.create(
            nome=f"{prefixo} {timestamp}",
            telefone="11999990000",
            estado="SP",
        )

    def _gerar_ordens(self, *, cliente: Cliente, tecnico: User, quantidade: int) -> dict:
        status_rotacao = [
            "pendente_cliente",
            "pendente_tecnico",
            "pendente_pecas",
            "pendente_marca",
            "diagnosticar",
            "bancada",
            "reparo",
            "autorizado",
        ]
        agora = timezone.now()
        ids_criados = []

        for indice in range(quantidade):
            status = status_rotacao[indice % len(status_rotacao)]
            ordem = OrdemServico.objects.create(
                cliente=cliente,
                tipo_equipamento="celular",
                marca_equipamento="Marca Teste",
                modelo_equipamento=f"Modelo {indice + 1}",
                defeito="Gerado automaticamente para teste de dashboard",
                tipo_reparo="Fora de Garantia",
                status=status,
                tecnico_responsavel=tecnico if indice % 2 == 0 else None,
            )
            dias = self._dias_abertura_para_status(status=status, indice=indice)
            OrdemServico.objects.filter(pk=ordem.pk).update(data_abertura=agora - timedelta(days=dias))
            ids_criados.append(ordem.pk)

        limite_15 = agora - timedelta(days=15)
        base_qs = OrdemServico.objects.filter(id__in=ids_criados, fechada=False)
        pendentes_total = base_qs.filter(status__in=PENDING_STOPPED_STATUSES).count()
        pendentes_15_mais = base_qs.filter(
            status__in=PENDING_STOPPED_STATUSES,
            data_abertura__lte=limite_15,
        ).count()
        return {
            "total_os": len(ids_criados),
            "pendentes_total": pendentes_total,
            "pendentes_15_mais": pendentes_15_mais,
        }

    @staticmethod
    def _dias_abertura_para_status(*, status: str, indice: int) -> int:
        if status in PENDING_STOPPED_STATUSES:
            # Gera metade das OS pendentes acima de 15 dias e metade abaixo.
            return 16 + (indice % 20) if indice % 2 == 0 else 2 + (indice % 10)
        return indice % 14
