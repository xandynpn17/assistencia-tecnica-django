from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from configuracoes.models import Empresa, FornecedorGarantia, MarcaGarantia, SetupInicialSistema
from estoque.models import (
    CategoriaProduto,
    PontoOperacional,
    Produto,
    ReservaEstoque,
    UbicacaoEstoque,
    VendaRapidaEstoque,
)
from estoque.services import criar_item_cesto_venda_rapida, criar_reserva_estoque, registrar_movimentacao_estoque
from estoque.services_estrutura import garantir_estrutura_estoque_padrao


@dataclass(frozen=True)
class ProdutoSeed:
    nome: str
    tipo_item: str
    categoria: str
    fornecedor: str
    marca: str
    custo_unitario: Decimal
    margem: Decimal
    estoque_minimo: int
    qtd_po2: int = 0
    qtd_po3: int = 0
    ubicacao_po3: str = "A1"
    permite_comissao_peca: bool = False
    percentual_comissao_peca: Decimal = Decimal("0")
    bonus_venda: Decimal = Decimal("0")

    @property
    def eh_servico(self) -> bool:
        return self.tipo_item == "servico"


class Command(BaseCommand):
    help = "Gera uma base de estoque enxuta para testes manuais, com saldos, reservas e pre-reservas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prefixo",
            default="MANUAL",
            help="Prefixo dos dados gerados para facilitar busca e limpeza.",
        )
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Remove os dados do mesmo prefixo antes de recriar a base.",
        )

    def handle(self, *args, **options):
        prefixo = " ".join(str(options["prefixo"] or "").strip().split()).upper()
        if len(prefixo) < 2:
            self.stderr.write(self.style.ERROR("Use um prefixo com pelo menos 2 caracteres."))
            return

        if options["limpar"]:
            self._limpar_prefixo(prefixo)

        with transaction.atomic():
            empresa = self._obter_empresa_ativa()
            pontos, ubicacoes = self._garantir_estrutura()
            categorias = self._garantir_categorias(prefixo)
            fornecedores, marcas = self._garantir_fornecedores_marcas(prefixo)
            produtos = self._garantir_produtos(
                prefixo=prefixo,
                empresa=empresa,
                categorias=categorias,
                fornecedores=fornecedores,
                marcas=marcas,
                pontos=pontos,
                ubicacoes=ubicacoes,
            )
            reservas = self._garantir_reservas(prefixo, produtos, pontos, ubicacoes)
            vendedor, cesto, qtd_pre_reservas = self._garantir_pre_reservas(prefixo, produtos, pontos)

        fisicos = sum(1 for produto in produtos if not produto.eh_servico)
        servicos = sum(1 for produto in produtos if produto.eh_servico)
        self.stdout.write(self.style.SUCCESS("Base de estoque para testes criada com sucesso."))
        self.stdout.write(f"Empresa ativa: {empresa.nome if empresa else 'sem empresa'}")
        self.stdout.write(f"Produtos fisicos: {fisicos} | Servicos: {servicos}")
        self.stdout.write(f"Reservas ativas: {len(reservas)}")
        self.stdout.write(f"Pre-reservas em aberto: {qtd_pre_reservas} | Cesto: {cesto or '-'}")
        if vendedor:
            self.stdout.write(f"Usuario vendedor reutilizado: {vendedor.username} / n. {vendedor.numero_vendedor}")
        else:
            self.stdout.write("Usuario vendedor: nao encontrado, pre-reservas nao foram criadas.")
        self.stdout.write(f"Prefixo utilizado: {prefixo}")

    def _obter_empresa_ativa(self) -> Empresa | None:
        try:
            setup = SetupInicialSistema.get_setup()
            if setup.empresa_id:
                return setup.empresa
        except Exception:
            pass
        return Empresa.objects.order_by("id").first()

    def _garantir_estrutura(self):
        garantir_estrutura_estoque_padrao()
        po2 = PontoOperacional.objects.get(codigo="PO2")
        po3 = PontoOperacional.objects.get(codigo="PO3")
        estrutura_extra = {
            "PO2": [
                ("A2", "Prateleira secundaria"),
                ("B1", "Recebimento"),
            ],
            "PO3": [
                ("A2", "Balcao tecnico"),
                ("V1", "Vitrine"),
            ],
        }
        for codigo_ponto, items in estrutura_extra.items():
            ponto = po2 if codigo_ponto == "PO2" else po3
            for codigo, descricao in items:
                UbicacaoEstoque.objects.get_or_create(
                    ponto_operacional=ponto,
                    codigo=codigo,
                    defaults={"descricao": descricao, "ativo": True},
                )
        ubicacoes = {
            "PO2:A1": UbicacaoEstoque.objects.get(ponto_operacional=po2, codigo="A1"),
            "PO2:A2": UbicacaoEstoque.objects.get(ponto_operacional=po2, codigo="A2"),
            "PO2:B1": UbicacaoEstoque.objects.get(ponto_operacional=po2, codigo="B1"),
            "PO3:A1": UbicacaoEstoque.objects.get(ponto_operacional=po3, codigo="A1"),
            "PO3:A2": UbicacaoEstoque.objects.get(ponto_operacional=po3, codigo="A2"),
            "PO3:V1": UbicacaoEstoque.objects.get(ponto_operacional=po3, codigo="V1"),
        }
        return {"PO2": po2, "PO3": po3}, ubicacoes

    def _garantir_categorias(self, prefixo: str):
        definicoes = [
            ("Acessorios", Decimal("35.00"), 10),
            ("Componentes", Decimal("42.00"), 20),
            ("Consumiveis", Decimal("30.00"), 30),
            ("Servicos", Decimal("55.00"), 40),
        ]
        categorias = {}
        for nome, margem, ordem in definicoes:
            categoria, _ = CategoriaProduto.objects.update_or_create(
                nome=f"{prefixo} - {nome}",
                defaults={"margem_padrao": margem, "ativo": True, "ordem": ordem},
            )
            categorias[nome] = categoria
        return categorias

    def _garantir_fornecedores_marcas(self, prefixo: str):
        definicoes = {
            "Distribuicao": {
                "fornecedor": f"{prefixo} - Distribuicao Tecnica",
                "marca": f"{prefixo} - Northwind",
            },
            "Componentes": {
                "fornecedor": f"{prefixo} - Componentes Express",
                "marca": f"{prefixo} - Thermix",
            },
        }
        fornecedores = {}
        marcas = {}
        for chave, item in definicoes.items():
            fornecedor, _ = FornecedorGarantia.objects.update_or_create(
                nome=item["fornecedor"],
                defaults={
                    "modalidade_pagamento": "pix",
                    "prazo_pagamento_dias": 28,
                    "ativo": True,
                },
            )
            marca, _ = MarcaGarantia.objects.update_or_create(
                nome=item["marca"],
                defaults={
                    "fornecedor": fornecedor,
                    "parceira_garantia": True,
                    "valor_mao_obra_garantia": Decimal("35.00"),
                    "ativo": True,
                },
            )
            fornecedores[chave] = fornecedor
            marcas[chave] = marca
        return fornecedores, marcas

    def _produto_seeds(self):
        return [
            ProdutoSeed("Mouse USB Preto", "produto", "Acessorios", "Distribuicao", "Distribuicao", Decimal("22.00"), Decimal("38.00"), 3, 8, 4, "V1"),
            ProdutoSeed("Teclado ABNT2 USB", "produto", "Acessorios", "Distribuicao", "Distribuicao", Decimal("48.00"), Decimal("35.00"), 2, 6, 3, "V1"),
            ProdutoSeed("SSD 480GB SATA", "produto", "Componentes", "Componentes", "Componentes", Decimal("145.00"), Decimal("28.00"), 2, 4, 3, "A1"),
            ProdutoSeed("Memoria DDR4 8GB", "produto", "Componentes", "Componentes", "Componentes", Decimal("110.00"), Decimal("30.00"), 2, 5, 2, "A1"),
            ProdutoSeed("Fonte Notebook 19V 3.42A", "peca", "Componentes", "Componentes", "Componentes", Decimal("55.00"), Decimal("42.00"), 2, 7, 3, "A2", True, Decimal("3.50"), Decimal("2.00")),
            ProdutoSeed("Cooler 120mm", "peca", "Componentes", "Componentes", "Componentes", Decimal("18.00"), Decimal("45.00"), 4, 12, 5, "A2", True, Decimal("2.50"), Decimal("1.00")),
            ProdutoSeed("Resistencia Secadora 127V", "peca", "Componentes", "Componentes", "Componentes", Decimal("34.00"), Decimal("45.00"), 3, 10, 4, "A2", True, Decimal("3.00"), Decimal("1.00")),
            ProdutoSeed("Motor Ventilador Universal", "peca", "Componentes", "Distribuicao", "Distribuicao", Decimal("79.00"), Decimal("50.00"), 2, 5, 2, "A2", True, Decimal("4.00"), Decimal("2.00")),
            ProdutoSeed("Capacitor 12uF", "peca", "Componentes", "Componentes", "Componentes", Decimal("8.00"), Decimal("48.00"), 8, 15, 5, "A1", True, Decimal("2.00"), Decimal("0.50")),
            ProdutoSeed("Alcool Isopropilico 250ml", "consumivel", "Consumiveis", "Distribuicao", "Distribuicao", Decimal("12.00"), Decimal("30.00"), 6, 10, 6, "A2"),
            ProdutoSeed("Pasta Termica 10g", "consumivel", "Consumiveis", "Componentes", "Componentes", Decimal("5.00"), Decimal("35.00"), 8, 20, 8, "A2"),
            ProdutoSeed("Bateria CR2032 Cartela", "consumivel", "Consumiveis", "Distribuicao", "Distribuicao", Decimal("6.00"), Decimal("35.00"), 6, 12, 6, "V1"),
            ProdutoSeed("Diagnostico Avancado", "servico", "Servicos", "Distribuicao", "Distribuicao", Decimal("35.00"), Decimal("55.00"), 0),
            ProdutoSeed("Limpeza Tecnica Interna", "servico", "Servicos", "Distribuicao", "Distribuicao", Decimal("22.00"), Decimal("55.00"), 0),
            ProdutoSeed("Instalacao de SSD", "servico", "Servicos", "Componentes", "Componentes", Decimal("40.00"), Decimal("55.00"), 0),
            ProdutoSeed("Troca de Fonte DC", "servico", "Servicos", "Componentes", "Componentes", Decimal("32.00"), Decimal("55.00"), 0),
        ]

    def _garantir_produtos(self, *, prefixo, empresa, categorias, fornecedores, marcas, pontos, ubicacoes):
        marcador = f"[SEED-ESTOQUE:{prefixo}]"
        produtos = []
        for seed in self._produto_seeds():
            nome = f"{prefixo} - {seed.nome}"
            defaults = {
                "empresa": empresa,
                "tipo_item": seed.tipo_item,
                "categoria_config": categorias[seed.categoria],
                "fornecedor_config": fornecedores[seed.fornecedor],
                "marca": marcas[seed.marca],
                "descricao": f"Produto seed para testes manuais de estoque. {marcador}",
                "observacao_interna": marcador,
                "permite_os": True,
                "modo_preco": "simples",
                "custo_unitario": seed.custo_unitario,
                "margem_lucro": seed.margem,
                "margem_minima": Decimal("10.00"),
                "estoque_minimo": seed.estoque_minimo,
                "permite_comissao_peca": seed.permite_comissao_peca,
                "percentual_comissao_peca": seed.percentual_comissao_peca,
                "bonus_venda": seed.bonus_venda,
                "ativo": True,
                "ponto_operacional": pontos["PO3"] if not seed.eh_servico else pontos["PO3"],
                "ubicacao_padrao": ubicacoes.get(f"PO3:{seed.ubicacao_po3}", ubicacoes["PO3:A1"]) if not seed.eh_servico else None,
                "quantidade": 0 if not seed.eh_servico else 0,
            }
            produto, _ = Produto.objects.update_or_create(
                nome=nome,
                defaults=defaults,
            )
            produtos.append(produto)
            if seed.eh_servico:
                continue
            if produto.movimentacoes.filter(observacao__icontains=marcador).exists():
                continue
            self._registrar_estoque_inicial(
                produto=produto,
                seed=seed,
                pontos=pontos,
                ubicacoes=ubicacoes,
                marcador=marcador,
            )
        return produtos

    def _registrar_estoque_inicial(self, *, produto, seed, pontos, ubicacoes, marcador):
        total = int(seed.qtd_po2 or 0) + int(seed.qtd_po3 or 0)
        if total <= 0:
            return
        registrar_movimentacao_estoque(
            produto=produto,
            tipo="entrada",
            quantidade=total,
            destino=pontos["PO2"],
            destino_ubicacao_ref=ubicacoes["PO2:A1"],
            destino_ubicacao="A1",
            valor_unitario_custo=seed.custo_unitario,
            observacao=f"{marcador} Entrada inicial",
        )
        if int(seed.qtd_po3 or 0) > 0:
            registrar_movimentacao_estoque(
                produto=produto,
                tipo="transferencia",
                quantidade=int(seed.qtd_po3),
                origem=pontos["PO2"],
                destino=pontos["PO3"],
                origem_ubicacao=ubicacoes["PO2:A1"],
                destino_ubicacao_ref=ubicacoes[f"PO3:{seed.ubicacao_po3}"],
                destino_ubicacao=seed.ubicacao_po3,
                observacao=f"{marcador} Transferencia inicial para loja",
            )

    def _garantir_reservas(self, prefixo, produtos, pontos, ubicacoes):
        reservas = []
        fisicos = [produto for produto in produtos if not produto.eh_servico]
        nomes_reserva = [
            (f"{prefixo} Cliente Reserva 01", "910000001", fisicos[0], 1, "PO3:V1", 2),
            (f"{prefixo} Cliente Reserva 02", "910000002", fisicos[2], 1, "PO3:A1", 3),
            (f"{prefixo} Cliente Reserva 03", "910000003", fisicos[10], 2, "PO3:A2", 1),
        ]
        for nome, telefone, produto, quantidade, chave_ubicacao, dias in nomes_reserva:
            reserva = ReservaEstoque.objects.filter(
                produto=produto,
                nome_contato=nome,
                telefone_contato=telefone,
                status="ativa",
            ).first()
            if reserva:
                reservas.append(reserva)
                continue
            reservas.append(
                criar_reserva_estoque(
                    produto=produto,
                    ponto_operacional=pontos["PO3"],
                    ubicacao=ubicacoes[chave_ubicacao],
                    quantidade=quantidade,
                    nome_contato=nome,
                    telefone_contato=telefone,
                    valido_ate=timezone.localdate() + timedelta(days=dias),
                )
            )
        return reservas

    def _garantir_pre_reservas(self, prefixo, produtos, pontos):
        vendedor = self._obter_vendedor_existente(prefixo)
        if not vendedor:
            return None, "", 0
        existentes = VendaRapidaEstoque.objects.filter(
            usuario=vendedor,
            status="pre_reserva",
            produto__nome__startswith=f"{prefixo} - ",
        ).order_by("id")
        if existentes.count() >= 2:
            return vendedor, existentes.first().cesto_codigo, existentes.count()

        cesto_codigo = ""
        for produto, quantidade in ((produtos[0], 1), (produtos[1], 1)):
            resultado = criar_item_cesto_venda_rapida(
                produto=produto,
                ponto_operacional=pontos["PO3"],
                quantidade=quantidade,
                funcionario_numero=vendedor.numero_vendedor,
                cesto_codigo=cesto_codigo,
                usuario=vendedor,
            )
            cesto_codigo = resultado["cesto_codigo"]
        total = VendaRapidaEstoque.objects.filter(
            usuario=vendedor,
            status="pre_reserva",
            produto__nome__startswith=f"{prefixo} - ",
        ).count()
        return vendedor, cesto_codigo, total

    def _obter_vendedor_existente(self, prefixo):
        user_model = get_user_model()
        username = f"{slugify(prefixo).replace('-', '_')}_estoque_seed"
        vendedor = (
            user_model.objects.filter(username=username, is_active=True)
            .exclude(numero_vendedor__isnull=True)
            .exclude(numero_vendedor="")
            .first()
        )
        if vendedor:
            return vendedor
        return (
            user_model.objects.filter(is_active=True)
            .exclude(numero_vendedor__isnull=True)
            .exclude(numero_vendedor="")
            .order_by("id")
            .first()
        )

    def _limpar_prefixo(self, prefixo):
        produtos = Produto.objects.filter(nome__startswith=f"{prefixo} - ")
        VendaRapidaEstoque.objects.filter(produto__in=produtos).delete()
        ReservaEstoque.objects.filter(produto__in=produtos).delete()
        produtos.delete()
        CategoriaProduto.objects.filter(nome__startswith=f"{prefixo} - ").delete()
        MarcaGarantia.objects.filter(nome__startswith=f"{prefixo} - ").delete()
        FornecedorGarantia.objects.filter(nome__startswith=f"{prefixo} - ").delete()
        self.stdout.write(self.style.WARNING(f"Dados anteriores removidos para o prefixo {prefixo}."))
