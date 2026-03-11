from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from caixa.models import Comissao, ContaReceber, Pagamento
from clientes.models import Cliente
from configuracoes.models import FornecedorGarantia, MarcaGarantia
from estoque.models import CategoriaProduto, PontoOperacional, Produto, SaldoEstoquePonto
from orcamentos.models import ItemOrcamento, Orcamento
from ordens.models import LinhaTrabalho, OrdemServico, ServicoPeca


def _somente_digitos(valor: str) -> str:
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def _digito_cpf(base: str, peso_inicial: int) -> str:
    soma = sum(int(base[i]) * (peso_inicial - i) for i in range(len(base)))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def _gerar_cpf(indice: int) -> str:
    base = f"{(indice % 999999999):09d}"
    d1 = _digito_cpf(base, 10)
    d2 = _digito_cpf(base + d1, 11)
    return f"{base}{d1}{d2}"


def _digito_cnpj(base: str, pesos: list[int]) -> str:
    soma = sum(int(base[i]) * pesos[i] for i in range(len(pesos)))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def _gerar_cnpj(indice: int) -> str:
    raiz = f"{(indice % 99999999):08d}0001"
    d1 = _digito_cnpj(raiz, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _digito_cnpj(raiz + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return f"{raiz}{d1}{d2}"


@dataclass(frozen=True)
class ProdutoSeed:
    nome: str
    tipo_item: str
    categoria: str
    custo_unitario: Decimal
    margem: Decimal
    quantidade: int
    estoque_minimo: int
    fornecedor: str
    permite_comissao_peca: bool = False
    percentual_comissao_peca: Decimal = Decimal("0")
    bonus_venda: Decimal = Decimal("0")


class Command(BaseCommand):
    help = "Gera base de testes com clientes, produtos, técnicos e ordens para validação funcional."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prefixo",
            type=str,
            default="SEED",
            help="Prefixo para identificar dados de teste. Ex.: SEED",
        )
        parser.add_argument(
            "--clientes",
            type=int,
            default=20,
            help="Quantidade de clientes de teste a criar/atualizar (padrao: 20).",
        )
        parser.add_argument(
            "--produtos",
            type=int,
            default=20,
            help="Quantidade de produtos de teste a criar/atualizar (padrao: 20).",
        )
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Remove dados anteriores do mesmo prefixo antes de gerar novos.",
        )
        parser.add_argument(
            "--ordens",
            type=int,
            default=0,
            help="Quantidade de ordens de serviço de teste a criar/atualizar (padrão: 0).",
        )
        parser.add_argument(
            "--tecnicos",
            type=int,
            default=3,
            help="Quantidade de técnicos de teste (usado quando --ordens > 0).",
        )

    def handle(self, *args, **options):
        prefixo = (options["prefixo"] or "").strip()
        qtd_clientes = int(options["clientes"] or 0)
        qtd_produtos = int(options["produtos"] or 0)
        qtd_ordens = int(options["ordens"] or 0)
        qtd_tecnicos = int(options["tecnicos"] or 0)
        limpar = bool(options["limpar"])

        if not prefixo or len(prefixo) < 2:
            raise CommandError("Informe --prefixo com pelo menos 2 caracteres para segurança.")

        if qtd_clientes < 0 or qtd_produtos < 0 or qtd_ordens < 0 or qtd_tecnicos < 0:
            raise CommandError("Use valores zero ou positivos para --clientes, --produtos, --ordens e --tecnicos.")

        if limpar:
            self._limpar_dados(prefixo=prefixo)

        if qtd_clientes == 0 and qtd_produtos == 0 and qtd_ordens == 0:
            self.stdout.write(self.style.SUCCESS("Somente limpeza executada."))
            return

        categorias = self._criar_categorias(prefixo=prefixo)
        fornecedor_map, marca_map = self._criar_fornecedores_marcas(prefixo=prefixo)
        resumo_clientes = self._criar_clientes(prefixo=prefixo, quantidade=qtd_clientes)
        resumo_produtos = self._criar_produtos(
            prefixo=prefixo,
            quantidade=qtd_produtos,
            categorias=categorias,
            fornecedores=fornecedor_map,
            marcas=marca_map,
        )
        resumo_tecnicos = {"criados": 0, "atualizados": 0}
        resumo_ordens = {"criadas": 0, "atualizadas": 0}
        if qtd_ordens > 0:
            resumo_tecnicos, tecnicos = self._criar_tecnicos(prefixo=prefixo, quantidade=max(1, qtd_tecnicos))
            resumo_ordens = self._criar_ordens(
                prefixo=prefixo,
                quantidade=qtd_ordens,
                tecnicos=tecnicos,
            )

        self.stdout.write(self.style.SUCCESS("Base de teste gerada com sucesso."))
        self.stdout.write(
            f"Clientes -> criados: {resumo_clientes['criados']} | atualizados: {resumo_clientes['atualizados']}"
        )
        self.stdout.write(
            f"Produtos -> criados: {resumo_produtos['criados']} | atualizados: {resumo_produtos['atualizados']}"
        )
        if qtd_ordens > 0:
            self.stdout.write(
                f"Tecnicos -> criados: {resumo_tecnicos['criados']} | atualizados: {resumo_tecnicos['atualizados']}"
            )
            self.stdout.write(
                f"Ordens -> criadas: {resumo_ordens['criadas']} | atualizadas: {resumo_ordens['atualizadas']}"
            )
        self.stdout.write(f"Prefixo utilizado: {prefixo}")

    def _limpar_dados(self, *, prefixo: str):
        produtos = Produto.objects.filter(nome__startswith=f"{prefixo} - ")
        clientes = Cliente.objects.filter(nome__startswith=f"{prefixo} - ")
        marcas = MarcaGarantia.objects.filter(nome__startswith=f"{prefixo} - ")
        fornecedores = FornecedorGarantia.objects.filter(nome__startswith=f"{prefixo} - ")
        categorias = CategoriaProduto.objects.filter(nome__startswith=f"{prefixo} - ")
        tecnicos = get_user_model().objects.filter(username__startswith=f"{prefixo.lower()}_tec_")
        ordens = OrdemServico.objects.filter(notas_internas__icontains=f"[SEED:{prefixo}:")
        pagamentos_prefixo = Pagamento.objects.filter(referencia__startswith=f"{prefixo}-")
        contas_ordens = ContaReceber.objects.filter(ordem_servico__in=ordens)
        comissoes_ordens = Comissao.objects.filter(ordem_servico__in=ordens)

        total_produtos = produtos.count()
        total_clientes = clientes.count()
        total_marcas = marcas.count()
        total_fornecedores = fornecedores.count()
        total_categorias = categorias.count()
        total_tecnicos = tecnicos.count()
        total_ordens = ordens.count()
        total_pagamentos = pagamentos_prefixo.count()
        total_contas = contas_ordens.count()
        total_comissoes = comissoes_ordens.count()

        comissoes_ordens.delete()
        contas_ordens.delete()
        pagamentos_prefixo.delete()
        ordens.delete()
        tecnicos.delete()
        produtos.delete()
        clientes.delete()
        marcas.delete()
        fornecedores.delete()
        categorias.delete()

        self.stdout.write(
            self.style.WARNING(
                "Limpeza concluída: "
                f"{total_clientes} clientes, {total_produtos} produtos, "
                f"{total_marcas} marcas, {total_fornecedores} fornecedores, {total_categorias} categorias, "
                f"{total_tecnicos} técnicos, {total_ordens} ordens, {total_pagamentos} pagamentos, "
                f"{total_contas} contas e {total_comissoes} comissões."
            )
        )

    def _criar_clientes(self, *, prefixo: str, quantidade: int) -> dict:
        nomes_base = [
            "Joao Silva",
            "Maria Oliveira",
            "Carlos Souza",
            "Ana Pereira",
            "Rafael Costa",
            "Luciana Mendes",
            "Fernanda Rocha",
            "Bruno Almeida",
            "Camila Nunes",
            "Ricardo Lima",
            "Patricia Teixeira",
            "Eduardo Martins",
            "Roberta Dias",
            "Paulo Barbosa",
            "Juliana Araujo",
            "Oficina Alfa Ltda",
            "Mercado Bom Preco",
            "Clinica Sao Lucas",
            "Tecno Info Comercio",
            "Condominio Primavera",
            "Auto Eletrica Centro",
            "Loja do Eletro",
            "Assist Tech Solutions",
            "Padaria Nova Era",
        ]
        criados = 0
        atualizados = 0
        cpf_cursor = 100000001
        cnpj_cursor = 10000000

        for i in range(quantidade):
            base_nome = nomes_base[i % len(nomes_base)]
            nome = f"{prefixo} - {base_nome} {i + 1:03d}"
            telefone = f"1199{(1000000 + i):07d}"[:11]

            cliente = Cliente.objects.filter(nome=nome).first()
            if cliente:
                alterou = False
                if cliente.telefone != telefone:
                    cliente.telefone = telefone
                    alterou = True
                if cliente.estado != "SP":
                    cliente.estado = "SP"
                    alterou = True
                if alterou:
                    cliente.save(update_fields=["telefone", "estado"])
                    atualizados += 1
                continue

            documento = None
            if i % 5 == 0:
                while True:
                    candidato = _gerar_cnpj(cnpj_cursor)
                    cnpj_cursor += 1
                    if not Cliente.objects.filter(documento=candidato).exists():
                        documento = candidato
                        break
            else:
                while True:
                    candidato = _gerar_cpf(cpf_cursor)
                    cpf_cursor += 1
                    if not Cliente.objects.filter(documento=candidato).exists():
                        documento = candidato
                        break

            Cliente.objects.create(
                nome=nome,
                documento=_somente_digitos(documento),
                telefone=telefone,
                estado="SP",
                cidade="Sao Paulo",
                bairro="Centro",
                endereco="Rua de Teste, 100",
            )
            criados += 1

        return {"criados": criados, "atualizados": atualizados}

    def _criar_categorias(self, *, prefixo: str) -> dict[str, CategoriaProduto]:
        categorias_seed = [
            ("Motores e Ventilacao", Decimal("45.00"), 10),
            ("Resistencias e Aquecimento", Decimal("42.00"), 20),
            ("Placas e Eletronica", Decimal("50.00"), 30),
            ("Mecanica e Estrutura", Decimal("38.00"), 40),
            ("Consumiveis", Decimal("35.00"), 50),
            ("Servicos Tecnicos", Decimal("60.00"), 60),
        ]
        categorias: dict[str, CategoriaProduto] = {}
        for nome, margem, ordem in categorias_seed:
            nome_final = f"{prefixo} - {nome}"
            categoria, _ = CategoriaProduto.objects.update_or_create(
                nome=nome_final,
                defaults={"margem_padrao": margem, "ordem": ordem, "ativo": True},
            )
            categorias[nome] = categoria
        return categorias

    def _criar_fornecedores_marcas(self, *, prefixo: str):
        fornecedores_seed = [
            "Fornecedor Eletro Sul",
            "Distribuidora Tech Parts",
            "Componentes Brasil",
        ]
        fornecedor_map = {}
        marca_map = {}

        for idx, nome in enumerate(fornecedores_seed):
            nome_final = f"{prefixo} - {nome}"
            fornecedor, _ = FornecedorGarantia.objects.update_or_create(
                nome=nome_final,
                defaults={
                    "modalidade_pagamento": "pix",
                    "prazo_pagamento_dias": 28 + idx,
                    "ativo": True,
                },
            )
            fornecedor_map[nome] = fornecedor

        marcas_seed = [
            ("Marca ProLine", "Fornecedor Eletro Sul"),
            ("Marca UltraHeat", "Distribuidora Tech Parts"),
            ("Marca Electra", "Componentes Brasil"),
        ]
        for nome_marca, nome_fornecedor in marcas_seed:
            nome_marca_final = f"{prefixo} - {nome_marca}"
            marca, _ = MarcaGarantia.objects.update_or_create(
                nome=nome_marca_final,
                defaults={
                    "fornecedor": fornecedor_map[nome_fornecedor],
                    "parceira_garantia": True,
                    "valor_mao_obra_garantia": Decimal("35.00"),
                    "ativo": True,
                },
            )
            marca_map[nome_marca] = marca
        return fornecedor_map, marca_map

    def _produto_seeds(self) -> list[ProdutoSeed]:
        return [
            ProdutoSeed("Motor Universal 127V", "peca", "Motores e Ventilacao", Decimal("95"), Decimal("45"), 8, 2, "Fornecedor Eletro Sul", True, Decimal("4"), Decimal("3")),
            ProdutoSeed("Motor Universal 220V", "peca", "Motores e Ventilacao", Decimal("98"), Decimal("45"), 8, 2, "Fornecedor Eletro Sul", True, Decimal("4"), Decimal("3")),
            ProdutoSeed("Micro Motor Ventoinha", "peca", "Motores e Ventilacao", Decimal("52"), Decimal("45"), 12, 3, "Fornecedor Eletro Sul", True, Decimal("3"), Decimal("2")),
            ProdutoSeed("Resistencia Secadora 127V", "peca", "Resistencias e Aquecimento", Decimal("38"), Decimal("42"), 18, 4, "Distribuidora Tech Parts", True, Decimal("3"), Decimal("1")),
            ProdutoSeed("Resistencia Secadora 220V", "peca", "Resistencias e Aquecimento", Decimal("39"), Decimal("42"), 18, 4, "Distribuidora Tech Parts", True, Decimal("3"), Decimal("1")),
            ProdutoSeed("Resistencia Ferro 1200W", "peca", "Resistencias e Aquecimento", Decimal("25"), Decimal("42"), 20, 5, "Distribuidora Tech Parts", True, Decimal("2.5"), Decimal("1")),
            ProdutoSeed("Placa Eletronica Controle", "peca", "Placas e Eletronica", Decimal("145"), Decimal("50"), 6, 2, "Componentes Brasil", True, Decimal("5"), Decimal("6")),
            ProdutoSeed("Placa Fonte Bivolt", "peca", "Placas e Eletronica", Decimal("110"), Decimal("50"), 7, 2, "Componentes Brasil", True, Decimal("5"), Decimal("4")),
            ProdutoSeed("Sensor Temperatura NTC", "peca", "Placas e Eletronica", Decimal("18"), Decimal("50"), 22, 5, "Componentes Brasil", True, Decimal("2"), Decimal("1")),
            ProdutoSeed("Capacitor 12uF", "peca", "Placas e Eletronica", Decimal("9"), Decimal("50"), 35, 10, "Componentes Brasil", True, Decimal("2"), Decimal("0.5")),
            ProdutoSeed("Fusivel Termico 192C", "peca", "Placas e Eletronica", Decimal("6"), Decimal("50"), 40, 12, "Componentes Brasil", True, Decimal("2"), Decimal("0.5")),
            ProdutoSeed("Termostato Bimetalico", "peca", "Resistencias e Aquecimento", Decimal("13"), Decimal("42"), 30, 8, "Distribuidora Tech Parts", True, Decimal("2"), Decimal("0.5")),
            ProdutoSeed("Correia Dentada", "peca", "Mecanica e Estrutura", Decimal("17"), Decimal("38"), 24, 6, "Fornecedor Eletro Sul", True, Decimal("2"), Decimal("0.5")),
            ProdutoSeed("Rolamento 6202", "peca", "Mecanica e Estrutura", Decimal("8"), Decimal("38"), 35, 10, "Fornecedor Eletro Sul", True, Decimal("2"), Decimal("0.5")),
            ProdutoSeed("Escova de Carvao Par", "peca", "Mecanica e Estrutura", Decimal("12"), Decimal("38"), 25, 7, "Fornecedor Eletro Sul", True, Decimal("2"), Decimal("0.5")),
            ProdutoSeed("Microchave Tampa", "peca", "Mecanica e Estrutura", Decimal("11"), Decimal("38"), 28, 8, "Fornecedor Eletro Sul", True, Decimal("2"), Decimal("0.5")),
            ProdutoSeed("Pasta Termica 10g", "consumivel", "Consumiveis", Decimal("4"), Decimal("35"), 60, 15, "Componentes Brasil", False, Decimal("0"), Decimal("0")),
            ProdutoSeed("Alcool Isopropilico 250ml", "consumivel", "Consumiveis", Decimal("14"), Decimal("35"), 20, 6, "Componentes Brasil", False, Decimal("0"), Decimal("0")),
            ProdutoSeed("Spray Limpa Contato", "consumivel", "Consumiveis", Decimal("16"), Decimal("35"), 18, 5, "Componentes Brasil", False, Decimal("0"), Decimal("0")),
            ProdutoSeed("Mao de Obra Troca de Motor", "servico", "Servicos Tecnicos", Decimal("40"), Decimal("60"), 0, 0, "Fornecedor Eletro Sul", False, Decimal("0"), Decimal("0")),
            ProdutoSeed("Mao de Obra Troca Resistencia", "servico", "Servicos Tecnicos", Decimal("32"), Decimal("60"), 0, 0, "Distribuidora Tech Parts", False, Decimal("0"), Decimal("0")),
            ProdutoSeed("Diagnostico Eletrico Completo", "servico", "Servicos Tecnicos", Decimal("25"), Decimal("60"), 0, 0, "Componentes Brasil", False, Decimal("0"), Decimal("0")),
            ProdutoSeed("Limpeza Tecnica Interna", "servico", "Servicos Tecnicos", Decimal("18"), Decimal("60"), 0, 0, "Componentes Brasil", False, Decimal("0"), Decimal("0")),
            ProdutoSeed("Atualizacao de Firmware", "servico", "Servicos Tecnicos", Decimal("22"), Decimal("60"), 0, 0, "Componentes Brasil", False, Decimal("0"), Decimal("0")),
        ]

    def _criar_produtos(self, *, prefixo: str, quantidade: int, categorias, fornecedores, marcas) -> dict:
        seeds = self._produto_seeds()
        if quantidade > len(seeds):
            raise CommandError(f"Quantidade maxima de produtos para este seed: {len(seeds)}")

        criados = 0
        atualizados = 0
        for seed in seeds[:quantidade]:
            nome_final = f"{prefixo} - {seed.nome}"
            categoria_obj = categorias[seed.categoria]
            fornecedor_obj = fornecedores[seed.fornecedor]
            marca_obj = marcas["Marca Electra"]
            if seed.fornecedor == "Fornecedor Eletro Sul":
                marca_obj = marcas["Marca ProLine"]
            elif seed.fornecedor == "Distribuidora Tech Parts":
                marca_obj = marcas["Marca UltraHeat"]

            defaults = {
                "tipo_item": seed.tipo_item,
                "categoria_config": categoria_obj,
                "fornecedor_config": fornecedor_obj,
                "marca": marca_obj,
                "descricao": f"Item de teste para validacao do sistema ({prefixo}).",
                "custo_unitario": seed.custo_unitario,
                "margem_lucro": seed.margem,
                "margem_minima": Decimal("10"),
                "quantidade": seed.quantidade,
                "estoque_minimo": seed.estoque_minimo,
                "modo_preco": "simples",
                "permite_os": True,
                "permite_comissao_peca": seed.permite_comissao_peca,
                "percentual_comissao_peca": seed.percentual_comissao_peca,
                "bonus_venda": seed.bonus_venda,
                "ativo": True,
            }

            produto = Produto.objects.filter(nome=nome_final).first()
            if not produto:
                Produto.objects.create(nome=nome_final, **defaults)
                criados += 1
                continue

            for campo, valor in defaults.items():
                setattr(produto, campo, valor)
            produto.save()
            atualizados += 1

        return {"criados": criados, "atualizados": atualizados}

    def _criar_tecnicos(self, *, prefixo: str, quantidade: int):
        nomes_base = [
            "Tecnico Motor",
            "Tecnico Eletronica",
            "Tecnico Campo",
            "Tecnico Garantia",
            "Tecnico Banco",
            "Tecnico Freelance",
        ]
        user_model = get_user_model()
        criados = 0
        atualizados = 0
        tecnicos = []
        for i in range(quantidade):
            username = f"{prefixo.lower()}_tec_{i + 1:02d}"
            defaults = {
                "first_name": nomes_base[i % len(nomes_base)],
                "tipo_usuario": "tecnico",
                "is_active": True,
                "tipo_vinculo": "FUNCIONARIO" if i % 3 == 0 else ("PJ" if i % 3 == 1 else "FREELANCER"),
                "percentual_comissao_servico": Decimal("12.00") + Decimal(i % 4),
                "percentual_comissao_peca": Decimal("4.00") + Decimal(i % 3),
            }
            tecnico = user_model.objects.filter(username=username).first()
            if tecnico:
                for campo, valor in defaults.items():
                    setattr(tecnico, campo, valor)
                tecnico.save()
                atualizados += 1
            else:
                tecnico = user_model.objects.create_user(
                    username=username,
                    password="SenhaForte@123",
                    **defaults,
                )
                criados += 1
            tecnicos.append(tecnico)
        return {"criados": criados, "atualizados": atualizados}, tecnicos

    def _criar_ordens(self, *, prefixo: str, quantidade: int, tecnicos):
        clientes = list(Cliente.objects.filter(nome__startswith=f"{prefixo} - ").order_by("id"))
        if not clientes:
            raise CommandError("Não há clientes seed suficientes para criar ordens.")
        produtos_servico = list(
            Produto.objects.filter(nome__startswith=f"{prefixo} - ", tipo_item="servico", ativo=True).order_by("id")
        )
        produtos_peca = list(
            Produto.objects.filter(
                nome__startswith=f"{prefixo} - ",
                tipo_item__in=["peca", "produto", "consumivel"],
                ativo=True,
            ).order_by("id")
        )
        if not produtos_peca:
            raise CommandError("Não há produtos seed suficientes para criar ordens.")

        po2, _ = PontoOperacional.objects.get_or_create(codigo="PO2", defaults={"nome": "Armazem", "ativo": True})
        po3, _ = PontoOperacional.objects.get_or_create(codigo="PO3", defaults={"nome": "Loja", "ativo": True})

        status_ciclo = [
            "diagnosticar",
            "pendente_orcamento",
            "orcamentado",
            "autorizado",
            "pronto_contactar",
            "pronto_contactado",
            "concluida",
            "pendente_pecas",
            "reparo",
            "em_andamento",
        ]
        criadas = 0
        atualizadas = 0
        agora = timezone.now()

        for idx in range(quantidade):
            marcador = f"[SEED:{prefixo}:OS:{idx + 1:03d}]"
            cliente = clientes[idx % len(clientes)]
            tecnico = tecnicos[idx % len(tecnicos)]
            status = status_ciclo[idx % len(status_ciclo)]
            dias = 2 + (idx % 40)
            data_abertura = agora - timedelta(days=dias)
            data_conclusao = (data_abertura + timedelta(days=1)) if status == "concluida" else None

            ordem = OrdemServico.objects.filter(notas_internas__icontains=marcador).first()
            relatorio = (
                f"Relatorio tecnico seed para ordem {idx + 1:03d}. Troca de componentes e testes executados."
                if status in {"autorizado", "pronto_contactar", "pronto_contactado", "concluida"}
                else ""
            )
            defaults = {
                "cliente": cliente,
                "tipo_equipamento": "secador" if idx % 2 == 0 else "ventilador",
                "marca_equipamento": f"{prefixo} Marca {idx % 5 + 1}",
                "modelo_equipamento": f"Modelo Seed {idx % 9 + 1}",
                "numero_serie_equipamento": f"{prefixo}-SERIE-{idx + 1:05d}",
                "defeito": "Nao liga e apresenta ruido ao iniciar.",
                "acessorios": "Cabo de energia e adaptador.",
                "tipo_reparo": "Fora de Garantia",
                "status": status,
                "relatorio_tecnico": relatorio,
                "tipo_reparacao": "substituicao" if relatorio else "",
                "tecnico_responsavel": tecnico,
                "peritagem": "Peritagem inicial registrada para testes de homologacao.",
                "fechada": status == "concluida",
                "notas_internas": marcador,
            }
            if ordem:
                for campo, valor in defaults.items():
                    setattr(ordem, campo, valor)
                ordem.save()
                atualizadas += 1
            else:
                ordem = OrdemServico.objects.create(**defaults)
                criadas += 1

            OrdemServico.objects.filter(id=ordem.id).update(
                data_abertura=data_abertura,
                data_conclusao=data_conclusao,
            )
            ordem.refresh_from_db(fields=["data_abertura", "data_conclusao", "status"])

            linha = LinhaTrabalho.objects.filter(ordem=ordem, descricao__icontains=marcador).first()
            if not linha:
                linha = LinhaTrabalho.objects.create(
                    ordem=ordem,
                    status="concluida" if status == "concluida" else "diagnosticar",
                    descricao=f"Evento seed {marcador}",
                    tipo_evento="sistema",
                    usuario=tecnico,
                )
            LinhaTrabalho.objects.filter(id=linha.id).update(criado_em=data_abertura)

            orcamento = Orcamento.objects.filter(ordem_servico=ordem, numero=1).first()
            if not orcamento:
                orcamento = Orcamento.objects.create(
                    cliente=cliente,
                    ordem_servico=ordem,
                    numero=1,
                    tipo="1",
                    descricao=f"Orcamento seed {marcador}",
                    status="pendente",
                )
            else:
                orcamento.cliente = cliente
                orcamento.descricao = f"Orcamento seed {marcador}"
                orcamento.status = "pendente"
                orcamento.save(update_fields=["cliente", "descricao", "status", "data_atualizacao"])

            produto_peca = produtos_peca[idx % len(produtos_peca)]
            produto_servico = produtos_servico[idx % len(produtos_servico)] if produtos_servico else None
            item_aprovado = status in {"autorizado", "pronto_contactar", "pronto_contactado", "concluida"}
            status_item = "aprovado" if item_aprovado else ("recusado" if idx % 5 == 0 else "pendente")

            item_servico = ItemOrcamento.objects.filter(orcamento=orcamento, nome__icontains="Mao de obra seed").first()
            if not item_servico:
                item_servico = ItemOrcamento.objects.create(
                    orcamento=orcamento,
                    nome=f"Mao de obra seed {idx + 1:03d}",
                    descricao="Servico tecnico de diagnostico e reparacao.",
                    valor_unitario=(produto_servico.preco_final if produto_servico else Decimal("80.00")),
                    quantidade=1,
                    tipo_item="servico",
                    origem="manual",
                    status=status_item,
                    tecnico_responsavel=tecnico if status_item == "aprovado" else None,
                )
            else:
                item_servico.descricao = "Servico tecnico de diagnostico e reparacao."
                item_servico.valor_unitario = produto_servico.preco_final if produto_servico else Decimal("80.00")
                item_servico.quantidade = 1
                item_servico.tipo_item = "servico"
                item_servico.origem = "manual"
                item_servico.status = status_item
                item_servico.tecnico_responsavel = tecnico if status_item == "aprovado" else None
                item_servico.save()

            item_peca = ItemOrcamento.objects.filter(orcamento=orcamento, nome__icontains="Peca seed").first()
            if not item_peca:
                item_peca = ItemOrcamento.objects.create(
                    orcamento=orcamento,
                    nome=f"Peca seed {idx + 1:03d} - {produto_peca.nome}",
                    ean=produto_peca.ean,
                    descricao="Peca de reposicao para homologacao.",
                    valor_unitario=produto_peca.preco_final,
                    quantidade=1 + (idx % 2),
                    tipo_item="peca",
                    origem="estoque",
                    status=status_item,
                    tecnico_responsavel=tecnico if status_item == "aprovado" else None,
                )
            else:
                item_peca.nome = f"Peca seed {idx + 1:03d} - {produto_peca.nome}"
                item_peca.ean = produto_peca.ean
                item_peca.descricao = "Peca de reposicao para homologacao."
                item_peca.valor_unitario = produto_peca.preco_final
                item_peca.quantidade = 1 + (idx % 2)
                item_peca.tipo_item = "peca"
                item_peca.origem = "estoque"
                item_peca.status = status_item
                item_peca.tecnico_responsavel = tecnico if status_item == "aprovado" else None
                item_peca.save()

            if status_item == "aprovado":
                ServicoPeca.objects.update_or_create(
                    ordem=ordem,
                    item_orcamento=item_servico,
                    defaults={
                        "tipo": "servico",
                        "nome": item_servico.nome,
                        "descricao": item_servico.descricao,
                        "quantidade": item_servico.quantidade,
                        "valor_unitario": item_servico.valor_unitario,
                        "tecnico_responsavel": tecnico,
                    },
                )
                ServicoPeca.objects.update_or_create(
                    ordem=ordem,
                    item_orcamento=item_peca,
                    defaults={
                        "tipo": "peca",
                        "nome": produto_peca.nome,
                        "descricao": item_peca.descricao,
                        "quantidade": item_peca.quantidade,
                        "valor_unitario": item_peca.valor_unitario,
                        "tecnico_responsavel": tecnico,
                    },
                )
            else:
                ServicoPeca.objects.filter(ordem=ordem, item_orcamento__in=[item_servico, item_peca]).delete()

            self._garantir_saldo_produto(produto_peca, po2=po2, po3=po3)
            orcamento.status = "aprovado" if status_item == "aprovado" else "pendente"
            orcamento.save(update_fields=["status", "data_atualizacao"])
            orcamento.atualizar_total()

        return {"criadas": criadas, "atualizadas": atualizadas}

    def _garantir_saldo_produto(self, produto: Produto, *, po2: PontoOperacional, po3: PontoOperacional):
        total = int(produto.quantidade or 0)
        if total <= 0:
            SaldoEstoquePonto.objects.update_or_create(
                produto=produto,
                ponto_operacional=po2,
                defaults={"quantidade": 0},
            )
            SaldoEstoquePonto.objects.update_or_create(
                produto=produto,
                ponto_operacional=po3,
                defaults={"quantidade": 0},
            )
            return

        qtd_loja = max(1, int(total * 0.6))
        qtd_armazem = max(0, total - qtd_loja)
        SaldoEstoquePonto.objects.update_or_create(
            produto=produto,
            ponto_operacional=po3,
            defaults={"quantidade": qtd_loja},
        )
        SaldoEstoquePonto.objects.update_or_create(
            produto=produto,
            ponto_operacional=po2,
            defaults={"quantidade": qtd_armazem},
        )
