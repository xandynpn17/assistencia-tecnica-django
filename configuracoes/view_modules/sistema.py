from urllib.parse import urlencode
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from configuracoes.forms import ConfiguracaoOrdemServicoForm, ConfiguracaoSistemaForm
from configuracoes.models import ConfiguracaoOrdemServico, ConfiguracaoSistema, RegraSLAAlerta
from configuracoes.services.auditoria import registrar_evento_configuracao
from configuracoes.services.integracoes import emitir_evento_interno, garantir_modelos_operacionais_padrao
from configuracoes.services.tenant_guard import filtrar_queryset_empresa, obter_empresa_ativa


def configuracao_os_edit_impl(request):
    config = ConfiguracaoOrdemServico.get_configuracao()
    if request.method == "POST":
        form = ConfiguracaoOrdemServicoForm(request.POST, instance=config)
        if form.is_valid():
            obj = form.save()
            registrar_evento_configuracao(
                usuario=request.user,
                acao="config_os_editada",
                origem="ui",
                alvo="configuracao_os",
                depois={"prefixo_os": obj.prefixo_os, "inicio_id_ordem": obj.inicio_id_ordem},
            )
            emitir_evento_interno("configuracoes.alterada", {"escopo": "configuracao_os"})
            messages.success(request, "Configuracao da Ordem de Servico salva com sucesso!")
            return redirect("configuracoes:painel")
    else:
        form = ConfiguracaoOrdemServicoForm(instance=config)
    return render(
        request,
        "configuracoes/configuracao_os_form.html",
        {
            "form": form,
            "config_operacional_tab": "os",
            "config_operacional_title": "Ordem de servico",
            "config_operacional_subtitle": (
                "Padronize a abertura das OS com regras simples de numeracao, automacao e "
                "texto tecnico de apoio para relatorios e impressao."
            ),
        },
    )


def configuracao_sistema_edit_impl(request):
    garantir_modelos_operacionais_padrao(sobrescrever=False)
    config = ConfiguracaoSistema.get_configuracao()
    config_os = ConfiguracaoOrdemServico.get_configuracao()
    secoes_validas = {
        "geral",
        "atendimento",
        "estoque",
        "financeiro",
        "comunicacao",
        "documentos",
        "manutencao",
    }
    secao_ativa = (request.POST.get("secao") or request.GET.get("secao") or "geral").strip().lower()
    if secao_ativa not in secoes_validas:
        secao_ativa = "geral"
    pode_editar_termos_os = bool(request.user.is_superuser or getattr(request.user, "tipo_usuario", "") == "adm")
    if request.method == "POST":
        form = ConfiguracaoSistemaForm(request.POST, instance=config)
        form.fields["rodape_relatorio"].initial = config_os.rodape_relatorio
        if not pode_editar_termos_os and "termos_ordem_servico" in form.fields:
            form.fields["termos_ordem_servico"].disabled = True
        if form.is_valid():
            obj = form.save(commit=False)
            if not pode_editar_termos_os:
                obj.termos_ordem_servico = config.termos_ordem_servico
            obj.save()
            novo_rodape = (form.cleaned_data.get("rodape_relatorio") or "").strip()
            if (config_os.rodape_relatorio or "") != novo_rodape:
                config_os.rodape_relatorio = novo_rodape
                config_os.save(update_fields=["rodape_relatorio"])
            prazo_os_sem_mov = max(int(getattr(obj, "sla_dias_os_sem_movimentacao", 2) or 2), 1)
            regra, criada = RegraSLAAlerta.objects.get_or_create(
                codigo="os_sem_movimentacao",
                defaults={
                    "ativo": True,
                    "prazo_valor": prazo_os_sem_mov,
                    "prazo_unidade": "dias",
                    "severidade": "alta",
                    "responsavel_padrao": "Atendimento",
                    "acao_sugerida": "Atualizar linha de trabalho e validar proximo passo.",
                    "canal_notificacao": "painel",
                    "observacoes": "Monitora ordens sem evolucao tecnica recente.",
                },
            )
            if not criada:
                regra.prazo_valor = prazo_os_sem_mov
                regra.prazo_unidade = "dias"
                regra.save(update_fields=["prazo_valor", "prazo_unidade", "atualizado_em"])
            registrar_evento_configuracao(
                usuario=request.user,
                acao="config_sistema_editada",
                origem="ui",
                alvo="configuracao_sistema",
                depois={
                    "estado_padrao": obj.estado_padrao,
                    "ddd_padrao": obj.ddd_padrao,
                    "api_cep_provedor": obj.api_cep_provedor,
                },
            )
            emitir_evento_interno("configuracoes.alterada", {"escopo": "configuracao_sistema"})
            messages.success(request, "Configuracoes do sistema salvas com sucesso!")
            return redirect(f"{reverse('configuracoes:configuracao_sistema')}?secao={secao_ativa}")
    else:
        form = ConfiguracaoSistemaForm(instance=config)
        form.fields["rodape_relatorio"].initial = config_os.rodape_relatorio
        if not pode_editar_termos_os and "termos_ordem_servico" in form.fields:
            form.fields["termos_ordem_servico"].disabled = True

    context = {
        "form": form,
        "estados_brasil": ConfiguracaoSistema.ESTADOS_BRASIL,
        "ddd_brasil": ConfiguracaoSistema.DDD_BRASIL,
        "config_operacional_tab": "sistema",
        "config_secao": secao_ativa,
        "config_operacional_title": "Regras operacionais",
        "config_operacional_subtitle": (
            "Ajuste cada área separadamente: atendimento, estoque, financeiro, comunicação, "
            "documentos e manutenção."
        ),
    }
    return render(request, "configuracoes/configuracao_sistema_form.html", context)


def preview_documento_impl(request):
    tipo = (request.GET.get("tipo") or "os_impressao").strip().lower()
    ordem_id = (request.GET.get("ordem_id") or "").strip()
    orcamento_id = (request.GET.get("orcamento_id") or "").strip()
    preview_ativo = (request.GET.get("_preview") or "").strip().lower() in {"1", "true", "on", "yes", "sim"}
    preview_params = {}
    for key in (
        "layout_os_impressao",
        "layout_documentos_preset",
        "layout_documentos_cor",
        "modelo",
        "avaliacao",
        "layout_os_frente_espaco_assinaturas_cm",
        "layout_os_verso_espaco_assinatura_cm",
        "layout_os_data_fonte_pt",
        "layout_os_digital_exibir_validacao",
        "layout_os_exibir_etiqueta_corte",
        "pdf_os_exibir_documento_cliente",
        "pdf_os_exibir_nome_cliente",
        "pdf_os_exibir_telefone_cliente",
        "pdf_os_exibir_email_cliente",
        "pdf_os_exibir_endereco_cliente",
        "pdf_os_exibir_tipo_equipamento",
        "pdf_os_exibir_marca_equipamento",
        "pdf_os_exibir_modelo_equipamento",
        "pdf_os_exibir_numero_serie",
        "pdf_os_exibir_local_armazenamento",
        "pdf_os_exibir_defeito",
        "pdf_os_exibir_acessorios",
        "pdf_os_exibir_peritagem",
        "pdf_os_exibir_tipo_reparo",
        "pdf_os_exibir_data_compra",
        "pdf_os_exibir_numero_nota_fiscal",
        "pdf_os_exibir_referencia_parceiro",
        "pdf_os_exibir_origem_cliente",
        "pdf_os_exibir_os_origem_garantia",
        "pdf_os_exibir_classificacao_retorno",
        "pdf_os_exibir_manutencao_preventiva",
        "pdf_os_exibir_termos",
        "pdf_os_exibir_assinaturas",
        "pdf_relatorio_exibir_nome_cliente",
        "pdf_relatorio_exibir_telefone_cliente",
        "pdf_relatorio_exibir_documento_cliente",
        "pdf_relatorio_exibir_email_cliente",
        "pdf_relatorio_exibir_origem_cliente",
        "pdf_relatorio_exibir_tipo_equipamento",
        "pdf_relatorio_exibir_marca_equipamento",
        "pdf_relatorio_exibir_modelo_equipamento",
        "pdf_relatorio_exibir_numero_serie",
        "pdf_relatorio_exibir_local_armazenamento",
        "pdf_relatorio_exibir_defeito",
        "pdf_relatorio_exibir_peritagem",
        "pdf_relatorio_exibir_acessorios",
        "pdf_relatorio_exibir_tipo_reparo",
        "pdf_relatorio_exibir_tipo_reparacao",
        "pdf_relatorio_exibir_datas_movimento",
        "pdf_relatorio_exibir_responsaveis",
        "pdf_relatorio_exibir_servicos_pecas",
        "pdf_orcamento_exibir_nome_cliente",
        "pdf_orcamento_exibir_telefone_cliente",
        "pdf_orcamento_exibir_documento_cliente",
        "pdf_orcamento_exibir_email_cliente",
        "pdf_orcamento_exibir_origem_cliente",
        "pdf_orcamento_exibir_tipo_equipamento",
        "pdf_orcamento_exibir_marca_equipamento",
        "pdf_orcamento_exibir_modelo_equipamento",
        "pdf_orcamento_exibir_numero_serie",
        "pdf_orcamento_exibir_defeito",
        "pdf_orcamento_exibir_acessorios",
        "pdf_orcamento_exibir_peritagem",
        "pdf_orcamento_exibir_tipo_reparo",
        "pdf_orcamento_exibir_condicoes",
        "pdf_orcamento_exibir_aprovacao",
    ):
        value = (request.GET.get(key) or "").strip()
        if value != "":
            preview_params[key] = value
    if preview_ativo or preview_params:
        preview_params["_preview"] = "1"
    if tipo == "relatorio_google":
        preview_params["avaliacao"] = "1"

    def _build_url(route_name, kwargs):
        url = reverse(route_name, kwargs=kwargs)
        if preview_params:
            url = f"{url}?{urlencode(preview_params)}"
        return url

    from ordens.models import OrdemServico
    from orcamentos.models import Orcamento

    ordem = None
    orcamento = None
    empresa = obter_empresa_ativa(request, strict=False)

    if ordem_id.isdigit():
        ordem = filtrar_queryset_empresa(OrdemServico.objects.filter(id=int(ordem_id)), empresa).first()
    if orcamento_id.isdigit():
        orcamento = filtrar_queryset_empresa(
            Orcamento.objects.select_related("ordem_servico").filter(id=int(orcamento_id)),
            empresa,
        ).first()
        if orcamento and not ordem:
            ordem = orcamento.ordem_servico

    if not orcamento and ordem:
        orcamento = (
            filtrar_queryset_empresa(
                Orcamento.objects.select_related("ordem_servico").filter(ordem_servico=ordem),
                empresa,
            )
            .order_by("-id")
            .first()
        )

    if tipo == "os_digital":
        if not ordem:
            return _preview_documento_sample(request, tipo="os_digital", empresa=empresa)
        return redirect(_build_url("ordens:imprimir_ordem_servico", {"pk": ordem.pk}))
    if tipo in {"relatorio", "relatorio_google"}:
        if not ordem:
            return _preview_documento_sample(request, tipo=tipo, empresa=empresa)
        return redirect(_build_url("ordens:imprimir_relatorio_tecnico", {"pk": ordem.pk}))
    if tipo == "orcamento":
        if not orcamento:
            return _preview_documento_sample(request, tipo="orcamento", empresa=empresa)
        return redirect(_build_url("orcamentos:imprimir_orcamento", {"pk": orcamento.pk}))

    if not ordem:
        return _preview_documento_sample(request, tipo="os_impressao", empresa=empresa)
    return redirect(_build_url("ordens:imprimir_ordem_servico_impressao", {"pk": ordem.pk}))


def _preview_documento_sample(request, *, tipo, empresa):
    from clientes.models import Cliente
    from ordens.models import LinhaTrabalho, OrdemServico, ServicoPeca
    from orcamentos.models import ItemOrcamento, Orcamento
    from ordens.view_modules.impressao import (
        imprimir_ordem_servico,
        imprimir_ordem_servico_impressao,
        imprimir_relatorio_tecnico,
    )
    from orcamentos.views import imprimir_orcamento

    if tipo == "relatorio_google" and not (request.GET.get("avaliacao") or "").strip():
        request.GET = request.GET.copy()
        request.GET["avaliacao"] = "1"

    with transaction.atomic():
        cliente = Cliente.objects.create(
            empresa=empresa,
            nome="Cliente Exemplo Preview",
            documento="11144477735",
            telefone="11987654321",
            email="cliente.preview@abgest.local",
            origem_cliente="google",
            logradouro="Avenida Exemplo",
            numero="250",
            complemento="Sala 3",
            bairro="Centro",
            cidade="Sao Paulo",
            estado="SP",
            codigo_postal="01310930",
        )

        ordem = OrdemServico.objects.create(
            empresa=empresa,
            cliente=cliente,
            tipo_equipamento="notebook",
            marca_equipamento="Dell",
            modelo_equipamento="Inspiron 15",
            numero_serie_equipamento="ABG-2026-0001",
            local_armazenamento="Prateleira A / Coluna 2",
            defeito="Equipamento nao liga e apresenta falha intermitente na alimentacao.",
            acessorios="Carregador original e bolsa de transporte.",
            tipo_reparo="Fora de Garantia",
            status="pronto_contactado",
            peritagem="Sinais de desgaste no conector de carga e instabilidade no circuito primario.",
            data_compra=timezone.localdate().replace(year=max(timezone.localdate().year - 2, 2000)),
            numero_nota_fiscal="NF-45872",
            referencia_parceiro="Balcao principal",
            tipo_reparacao="substituicao",
            manutencao_preventiva_meses=6,
            relatorio_tecnico=(
                "Realizada substituicao do conector de carga, limpeza interna completa e testes "
                "de estresse por alimentacao e bateria."
            ),
        )

        LinhaTrabalho.objects.create(
            ordem=ordem,
            status="pronto_contactado",
            tipo_evento="manual",
            descricao="Preview gerada automaticamente para validar layout de documentos.",
            usuario=request.user if getattr(request.user, "is_authenticated", False) else None,
        )

        orcamento = Orcamento.objects.create(
            empresa=empresa,
            cliente=cliente,
            ordem_servico=ordem,
            descricao="Exemplo de orcamento para visualizacao de layout.",
            status="aprovado",
        )

        item_servico = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Reparo em placa principal",
            descricao="Recuperacao do circuito de entrada e testes eletricos.",
            valor_unitario=Decimal("220.00"),
            quantidade=1,
            tipo_item="servico",
            origem="manual",
            status="aprovado",
        )
        item_peca = ItemOrcamento.objects.create(
            orcamento=orcamento,
            nome="Conector de carga",
            descricao="Peca de reposicao homologada para o modelo.",
            valor_unitario=Decimal("48.00"),
            quantidade=1,
            tipo_item="peca",
            origem="manual",
            status="aprovado",
        )
        orcamento.atualizar_total()

        ServicoPeca.objects.create(
            ordem=ordem,
            item_orcamento=item_servico,
            tipo="servico",
            nome=item_servico.nome,
            descricao=item_servico.descricao,
            quantidade=item_servico.quantidade,
            valor_unitario=item_servico.valor_unitario,
            garantia_dias=90,
            tecnico_responsavel=request.user if getattr(request.user, "is_authenticated", False) else None,
        )
        ServicoPeca.objects.create(
            ordem=ordem,
            item_orcamento=item_peca,
            tipo="peca",
            nome=item_peca.nome,
            descricao=item_peca.descricao,
            quantidade=item_peca.quantidade,
            valor_unitario=item_peca.valor_unitario,
            garantia_dias=90,
            tecnico_responsavel=request.user if getattr(request.user, "is_authenticated", False) else None,
        )

        if tipo == "os_digital":
            response = imprimir_ordem_servico(request, ordem.pk)
        elif tipo in {"relatorio", "relatorio_google"}:
            response = imprimir_relatorio_tecnico(request, ordem.pk)
        elif tipo == "orcamento":
            response = imprimir_orcamento(request, orcamento.pk)
        else:
            response = imprimir_ordem_servico_impressao(request, ordem.pk)

        transaction.set_rollback(True)
        return response


def _preview_documento_mock(request, *, tipo):
    from reportlab.lib.styles import getSampleStyleSheet
    from ordens.view_modules.impressao import (
        _config_layout_para_request,
        _perfil_layout_documentos,
        _tema_layout_documentos,
        add_paragraph_styles,
        get_pdf_fonts,
    )

    config = _config_layout_para_request(request)
    layout_docs = _perfil_layout_documentos(config)
    tema_docs = _tema_layout_documentos(config)
    fonts = get_pdf_fonts()
    styles = getSampleStyleSheet()
    add_paragraph_styles(
        styles,
        fonts,
        {
            "PrevTitle": {"bold": True, "font_size": 16, "leading": 19, "text_color": tema_docs["title_color"]},
            "PrevMeta": {"bold": False, "font_size": 9, "leading": 12, "text_color": tema_docs["meta_color"]},
            "PrevSection": {"bold": True, "font_size": 10.5, "leading": 13, "text_color": tema_docs["section_text"]},
            "PrevText": {"bold": False, "font_size": 9.2, "leading": 13},
            "PrevValue": {"bold": True, "font_size": 11, "leading": 14, "text_color": tema_docs["hero_value"]},
        },
    )

    titulos = {
        "os_impressao": "Previa da OS impressa",
        "os_digital": "Previa da OS digital",
        "relatorio": "Previa do relatorio tecnico",
        "orcamento": "Previa do orcamento",
    }
    subtitulos = {
        "os_impressao": "Amostra gerada sem depender de ordens reais cadastradas.",
        "os_digital": "Valide hierarquia visual, identidade e espacamento do documento digital.",
        "relatorio": "Use esta amostra para ajustar legibilidade de secoes, texto tecnico e assinatura.",
        "orcamento": "Use esta amostra para ajustar apresentacao comercial, totais e destaque visual.",
    }
    amostras = {
        "os_impressao": [
            "Cliente: Maria Silva",
            "Equipamento: Notebook Dell Inspiron 15",
            "Defeito informado: nao liga / sem imagem",
            "Observacao: preview criado sem usar dados reais do banco.",
        ],
        "os_digital": [
            "Linha de trabalho: Diagnosticar",
            "Tecnico responsavel: A definir",
            "Assinatura digital: bloco ilustrativo",
            "Fluxo pronto para configuracao inicial da operacao.",
        ],
        "relatorio": [
            "Diagnostico: falha em circuito de alimentacao.",
            "Servico recomendado: reparo em placa e testes finais.",
            "Conclusao: documento tecnico com foco em clareza e assinatura.",
        ],
        "orcamento": [
            "Servico: reparo em placa principal - R$ 220,00",
            "Peca: conector de carga - R$ 48,00",
            "Validade: 7 dias",
            "Observacao: esta e uma amostra visual do layout comercial.",
        ],
    }

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="preview_{tipo}.pdf"'
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title=titulos.get(tipo, "Previa de documento"),
        author="ABGest",
        subject="Preview de layout",
        creator="Assistencia PDF Engine",
        pageCompression=1,
    )
    usable_w = A4[0] - (2.4 * cm)

    def _secao(titulo):
        table = Table([[Paragraph(titulo, styles["PrevSection"])]], colWidths=[usable_w])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), tema_docs["section_bg"]),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.35, tema_docs["section_line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    resumo = Table(
        [
            [
                Paragraph("Preset", styles["PrevMeta"]),
                Paragraph(config.layout_documentos_preset, styles["PrevValue"]),
                Paragraph("Cor", styles["PrevMeta"]),
                Paragraph(config.layout_documentos_cor, styles["PrevValue"]),
            ],
            [
                Paragraph("OS impressa", styles["PrevMeta"]),
                Paragraph(config.layout_os_impressao, styles["PrevValue"]),
                Paragraph("Validacao digital", styles["PrevMeta"]),
                Paragraph("Ativa" if config.layout_os_digital_exibir_validacao else "Oculta", styles["PrevValue"]),
            ],
        ],
        colWidths=[usable_w * 0.18, usable_w * 0.32, usable_w * 0.18, usable_w * 0.32],
    )
    resumo.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), tema_docs["hero_bg"]),
                ("BOX", (0, 0), (-1, -1), 0.4, tema_docs["section_line"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, tema_docs["section_line"]),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    story = [
        Paragraph(titulos.get(tipo, "Previa de documento"), styles["PrevTitle"]),
        Spacer(1, 0.15 * cm),
        Paragraph(subtitulos.get(tipo, ""), styles["PrevMeta"]),
        Spacer(1, 0.35 * cm),
        resumo,
        Spacer(1, 0.35 * cm),
        _secao("Amostra visual"),
        Spacer(1, 0.18 * cm),
    ]

    for linha in amostras.get(tipo, []):
        story.append(Paragraph(f"- {linha}", styles["PrevText"]))
        story.append(Spacer(1, 0.07 * cm))

    story.extend(
        [
            Spacer(1, 0.18 * cm),
            _secao("Observacoes"),
            Spacer(1, 0.18 * cm),
            Paragraph(
                "Quando a primeira OS real for cadastrada, a pre-visualizacao volta a usar os documentos reais automaticamente. "
                "Enquanto isso, esta amostra garante configuracao segura desde o primeiro uso.",
                styles["PrevText"],
            ),
            Spacer(1, 0.12 * cm),
            Paragraph(
                f"Escalas ativas: titulo {layout_docs.get('pdf_title_pt', 12)} pt / secao {layout_docs.get('pdf_section_pt', 10)} pt / texto {layout_docs.get('pdf_text_pt', 9)} pt.",
                styles["PrevMeta"],
            ),
        ]
    )
    doc.build(story)
    return response
