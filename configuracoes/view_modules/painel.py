from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from configuracoes.forms import ModeloMensagemForm, SetupInicialSistemaForm, TipoEquipamentoConfigForm
from configuracoes.models import (
    ConfiguracaoOrdemServico,
    ConfiguracaoSistema,
    Empresa,
    LinhaAtuacaoCatalogo,
    ModeloMensagem,
    SetupInicialSistema,
    TipoEquipamentoConfig,
)
from configuracoes.services.setup_inicial import (
    garantir_catalogo_padrao,
    setup_inicial_concluido,
    sincronizar_tipos_ativos_por_linhas,
)
from configuracoes.services.tenant_guard import obter_empresa_ativa
from estoque.services_estrutura import garantir_estrutura_estoque_padrao
from configuracoes.services.integracoes import (
    garantir_modelos_operacionais_padrao,
    listar_eventos_comunicacao,
)
from configuracoes.view_modules.operacao import resumo_saude_operacional


LINHAS_ATUACAO_AJUDA = {
    "eletrodomesticos": {
        "descricao": "Linha focada em produtos maiores de uso residencial e bancada pesada.",
        "exemplos": ["Geladeira", "Lavadora", "Micro-ondas", "Forno"],
    },
    "eletroportateis": {
        "descricao": "Itens menores de casa e cozinha com alto giro de entrada e saida.",
        "exemplos": ["Liquidificador", "Air fryer", "Aspirador", "Cafeteira"],
    },
    "celulares_tablets": {
        "descricao": "Atendimentos moveis com triagem rapida, acessorios e alta recorrencia.",
        "exemplos": ["Smartphone", "Tablet", "Smartwatch", "Fone bluetooth"],
    },
    "informatica": {
        "descricao": "Equipamentos de TI e produtividade com diagnostico mais detalhado.",
        "exemplos": ["Notebook", "Desktop", "Impressora", "Monitor"],
    },
    "carros_utilitarios": {
        "descricao": "Fluxo de oficina para veiculos leves e utilitarios de uso diario.",
        "exemplos": ["Carro", "SUV", "Van", "Pickup"],
    },
    "motos": {
        "descricao": "Operacao focada em motocicletas, motonetas e servicos rapidos.",
        "exemplos": ["Moto", "Scooter", "Ciclomotor", "Quadriciclo"],
    },
}


def painel_impl(request):
    saude_operacional = resumo_saude_operacional()
    atalhos_operacionais = [
        {
            "titulo": "Gerar backup",
            "descricao": "Criar uma copia oficial antes de mudancas importantes.",
            "url": "configuracoes:backup_banco",
            "icone": "fas fa-download",
            "cor": "success",
        },
        {
            "titulo": "Restaurar backup",
            "descricao": "Recuperar base e arquivos com checklist visual.",
            "url": "configuracoes:restore_banco",
            "icone": "fas fa-upload",
            "cor": "danger",
        },
        {
            "titulo": "Ver auditoria",
            "descricao": "Rastrear restores, falhas e alteracoes sensiveis.",
            "url": "configuracoes:auditoria_configuracoes",
            "icone": "fas fa-clipboard-list",
            "cor": "dark",
        },
        {
            "titulo": "Monitorar integracoes",
            "descricao": "Conferir logs de webhook, e-mail, WhatsApp e sistema.",
            "url": "configuracoes:logs_integracoes",
            "icone": "fas fa-plug",
            "cor": "info",
        },
    ]
    if getattr(settings, "LOCAL_RECOVERY_KEY", ""):
        atalhos_operacionais.append(
            {
                "titulo": "Recuperacao local",
                "descricao": "Abrir o fluxo emergencial de restore sem login para ambiente local.",
                "url": "configuracoes:restore_banco_publico",
                "icone": "fas fa-life-ring",
                "cor": "warning",
            }
        )

    proximos_passos = [
        {
            "titulo": "Revisar empresa e identidade",
            "descricao": "Confirme dados fiscais, contatos e logos antes de comecar a operar.",
            "url": "configuracoes:empresa",
            "cta": "Abrir empresa",
        },
        {
            "titulo": "Validar ordem de servico",
            "descricao": "Ajuste numeracao, PDFs, termos e campos padrao da OS.",
            "url": "configuracoes:configuracao_os",
            "cta": "Configurar OS",
        },
        {
            "titulo": "Conferir catalogo operacional",
            "descricao": "Revise tipos de equipamento, marcas, fornecedores e mensagens.",
            "url": "configuracoes:tipos_equipamento",
            "cta": "Revisar catalogo",
        },
        {
            "titulo": "Gerar primeiro backup",
            "descricao": "Crie um ponto de recuperacao assim que a base estiver pronta para uso.",
            "url": "configuracoes:backup_banco",
            "cta": "Gerar backup",
        },
    ]
    if not saude_operacional.get("setup_concluido"):
        proximos_passos.insert(
            0,
            {
                "titulo": "Concluir setup inicial",
                "descricao": "Defina empresa, prefixo da OS e linhas de atuacao para liberar o restante.",
                "url": "configuracoes:setup_inicial",
                "cta": "Finalizar setup",
                "destaque": True,
            },
        )
    else:
        proximos_passos.insert(
            0,
            {
                "titulo": "Revisar assistente inicial",
                "descricao": "Reabra o setup para conferir dados da empresa, numeracao e linhas de atuacao.",
                "url": "configuracoes:setup_inicial",
                "cta": "Revisar setup",
                "destaque": True,
            },
        )

    secoes = [
        {
            "titulo": "Base da operacao",
            "icone": "fas fa-briefcase",
            "cor": "primary",
            "itens": [
                {
                    "titulo": "Dados da empresa",
                    "icone": "fas fa-building",
                    "descricao": "Cadastro principal, logo e dados fiscais basicos.",
                    "url": "configuracoes:empresa",
                    "cta": "Abrir",
                },
                {
                    "titulo": "Ordem de servico",
                    "icone": "fas fa-tools",
                    "descricao": "Prefixo, numeracao e padroes de impressao da OS.",
                    "url": "configuracoes:configuracao_os",
                    "cta": "Configurar",
                },
                {
                    "titulo": "Sistema",
                    "icone": "fas fa-sliders-h",
                    "descricao": "CEP, obrigatoriedades, busca, SLA base e parametros locais.",
                    "url": "configuracoes:configuracao_sistema",
                    "cta": "Configurar",
                },
            ],
        },
        {
            "titulo": "Catalogo e atendimento",
            "icone": "fas fa-layer-group",
            "cor": "secondary",
            "itens": [
                {
                    "titulo": "Tipos de equipamento",
                    "icone": "fas fa-mobile-alt",
                    "descricao": "Base dos tipos exibidos na abertura da OS.",
                    "url": "configuracoes:tipos_equipamento",
                    "cta": "Gerir",
                },
                {
                    "titulo": "Marcas e fornecedores",
                    "icone": "fas fa-industry",
                    "descricao": "Parceiros, marcas e regras de garantia.",
                    "url": "configuracoes:marcas_fornecedores",
                    "cta": "Gerir",
                },
                {
                    "titulo": "Modelos de mensagem",
                    "icone": "fas fa-comment-dots",
                    "descricao": "Mensagens operacionais para e-mail e WhatsApp.",
                    "url": "configuracoes:modelos_mensagem",
                    "cta": "Gerir",
                },
                {
                    "titulo": "Alquotas",
                    "icone": "fas fa-percentage",
                    "descricao": "Cadastro fiscal complementar para cenarios comerciais.",
                    "url": "configuracoes:lista_aliquotas",
                    "cta": "Gerir",
                },
            ],
        },
        {
            "titulo": "Equipe e seguranca",
            "icone": "fas fa-user-shield",
            "cor": "dark",
            "itens": [
                {
                    "titulo": "Usuarios e permissoes",
                    "icone": "fas fa-users-cog",
                    "descricao": "Perfis operacionais, acessos e permissoes sensiveis.",
                    "url": "configuracoes:lista_usuarios" if request.user.is_superuser or request.user.tipo_usuario == "adm" else "configuracoes:adicionar_usuario",
                    "cta": "Gerir" if request.user.is_superuser or request.user.tipo_usuario == "adm" else "Novo usuario",
                },
                {
                    "titulo": "Auditoria",
                    "icone": "fas fa-clipboard-list",
                    "descricao": "Alteracoes criticas, backups, restores e rastreabilidade.",
                    "url": "configuracoes:auditoria_configuracoes",
                    "cta": "Visualizar",
                },
            ],
        },
        {
            "titulo": "Monitoramento e recuperacao",
            "icone": "fas fa-heartbeat",
            "cor": "info",
            "itens": [
                {
                    "titulo": "SLA e alertas",
                    "icone": "fas fa-stopwatch",
                    "descricao": "Prazos operacionais e pendencias criticas.",
                    "url": "configuracoes:regras_sla",
                    "cta": "Configurar",
                },
                {
                    "titulo": "Garantia e reincidencias",
                    "icone": "fas fa-shield-alt",
                    "descricao": "Indicadores de retorno por tecnico, marca e equipamento.",
                    "url": "configuracoes:painel_reincidencias",
                    "cta": "Visualizar",
                },
                {
                    "titulo": "Backup e restauracao",
                    "icone": "fas fa-database",
                    "descricao": "Backup local, restore administrativo e recuperacao emergencial.",
                    "url": "configuracoes:backup_banco",
                    "cta": "Abrir",
                },
                {
                    "titulo": "Logs de integracoes",
                    "icone": "fas fa-plug",
                    "descricao": "Eventos de e-mail, WhatsApp, webhooks e falhas.",
                    "url": "configuracoes:logs_integracoes",
                    "cta": "Visualizar",
                },
            ],
        },
    ]
    return render(
        request,
        "configuracoes/painel.html",
        {
            "atalhos_operacionais": atalhos_operacionais,
            "proximos_passos": proximos_passos,
            "secoes_config": secoes,
            "saude_operacional": saude_operacional,
            "operacao_tab": "painel",
            "operacao_title": "Painel geral da operacao",
            "operacao_subtitle": "Acompanhe a saude do ambiente, setup, rotinas criticas e atalhos de administracao.",
            "menu_app": "configuracoes",
            "menu_sub": "painel",
        },
    )


def setup_inicial_impl(request):
    garantir_catalogo_padrao()
    setup = SetupInicialSistema.get_setup()
    empresa = obter_empresa_ativa(request, strict=False)
    config_os = ConfiguracaoOrdemServico.get_configuracao()

    tipo_empresa_query = (request.GET.get("tipo_empresa") or "").strip()
    tipo_empresa_post = (request.POST.get("tipo_empresa") or "").strip() if request.method == "POST" else ""
    tipo_empresa_inicial = tipo_empresa_post or tipo_empresa_query or setup.tipo_empresa or "assistencia_tecnica"

    def _ddd_por_telefone(valor):
        digitos = "".join(ch for ch in str(valor or "") if ch.isdigit())
        return digitos[:2] if len(digitos) >= 10 else ""

    if request.method == "POST":
        form = SetupInicialSistemaForm(request.POST, tipo_empresa=tipo_empresa_inicial)
        if form.is_valid():
            linhas = form.cleaned_data["linhas_atuacao"]
            if not linhas:
                form.add_error("linhas_atuacao", "Selecione pelo menos uma linha de atuacao.")
            else:
                if not empresa:
                    empresa = Empresa.objects.create(nome=form.cleaned_data["nome_empresa"])
                empresa.nome = form.cleaned_data["nome_empresa"]
                empresa.nome_fantasia = form.cleaned_data["nome_empresa"]
                empresa.razao_social = form.cleaned_data["razao_social"]
                empresa.cnpj = form.cleaned_data["cnpj"]
                empresa.inscricao_estadual = form.cleaned_data["inscricao_estadual"]
                empresa.inscricao_municipal = form.cleaned_data["inscricao_municipal"]
                empresa.cep = form.cleaned_data["cep"]
                empresa.logradouro = form.cleaned_data["logradouro"]
                empresa.numero = form.cleaned_data["numero"]
                empresa.complemento = form.cleaned_data["complemento"]
                empresa.bairro = form.cleaned_data["bairro"]
                empresa.cidade = form.cleaned_data["cidade"]
                empresa.estado = form.cleaned_data["estado"]
                empresa.telefone = form.cleaned_data["telefone"]
                empresa.celular_whatsapp = form.cleaned_data["celular_whatsapp"]
                empresa.email = form.cleaned_data["email"]
                empresa.endereco = empresa.montar_endereco_compacto()
                empresa.save()

                config_os.prefixo_os = form.cleaned_data["prefixo_os"]
                config_os.inicio_id_ordem = form.cleaned_data["inicio_id_ordem"]
                config_os.gerar_numero_automatico = True
                config_os.save(update_fields=["prefixo_os", "inicio_id_ordem", "gerar_numero_automatico"])

                config_sistema = ConfiguracaoSistema.get_configuracao()
                if empresa.estado:
                    config_sistema.estado_padrao = empresa.estado
                ddd_sugerido = _ddd_por_telefone(empresa.celular_whatsapp or empresa.telefone)
                if ddd_sugerido and any(codigo == ddd_sugerido for codigo, _ in ConfiguracaoSistema.DDD_BRASIL):
                    config_sistema.ddd_padrao = ddd_sugerido
                config_sistema.save()

                setup.empresa = empresa
                setup.tipo_empresa = form.cleaned_data["tipo_empresa"]
                setup.concluido = True
                setup.save()
                setup.linhas_atuacao.set(linhas)
                sincronizar_tipos_ativos_por_linhas(linhas)
                garantir_estrutura_estoque_padrao()

                messages.success(request, "Setup inicial concluido com sucesso.")
                return redirect("core:dashboard")
    else:
        linhas_iniciais = list(setup.linhas_atuacao.values_list("id", flat=True))
        initial = {
            "nome_empresa": (empresa.nome if empresa else ""),
            "razao_social": (empresa.razao_social if empresa else ""),
            "cnpj": (empresa.cnpj if empresa else ""),
            "inscricao_estadual": (empresa.inscricao_estadual if empresa else ""),
            "inscricao_municipal": (empresa.inscricao_municipal if empresa else ""),
            "telefone": (empresa.telefone if empresa else ""),
            "celular_whatsapp": (empresa.celular_whatsapp if empresa else ""),
            "email": (empresa.email if empresa else ""),
            "cep": (empresa.cep if empresa else ""),
            "logradouro": (empresa.logradouro if empresa else ""),
            "numero": (empresa.numero if empresa else ""),
            "complemento": (empresa.complemento if empresa else ""),
            "bairro": (empresa.bairro if empresa else ""),
            "cidade": (empresa.cidade if empresa else ""),
            "estado": (empresa.estado if empresa else ""),
            "prefixo_os": config_os.prefixo_os,
            "inicio_id_ordem": config_os.inicio_id_ordem,
            "tipo_empresa": tipo_empresa_inicial,
            "linhas_atuacao": linhas_iniciais,
        }
        form = SetupInicialSistemaForm(initial=initial, tipo_empresa=initial["tipo_empresa"])

    linhas_disponiveis = (
        LinhaAtuacaoCatalogo.objects.filter(ativo=True, segmento__codigo=tipo_empresa_inicial)
        .select_related("segmento")
        .prefetch_related("tipos_equipamento")
        .order_by("segmento__ordem", "ordem", "nome")
    )
    linhas_selecionadas = [str(valor) for valor in (form["linhas_atuacao"].value() or [])]
    linhas_cards = []
    for linha in linhas_disponiveis:
        meta = LINHAS_ATUACAO_AJUDA.get(linha.codigo, {})
        tipos_relacionados = list(linha.tipos_equipamento.all()[:4])
        tipos_exemplo = [tipo.nome for tipo in tipos_relacionados]
        if not tipos_exemplo:
            tipos_exemplo = list(meta.get("exemplos") or [])
        linhas_cards.append(
            {
                "id": linha.id,
                "codigo": linha.codigo,
                "nome": linha.nome,
                "descricao": meta.get("descricao") or "Ativa tipos de equipamento e atalhos operacionais relacionados a esta linha.",
                "tipos_exemplo": tipos_exemplo,
            }
        )
    backup_dir = Path(settings.BASE_DIR) / "backups"
    backups_disponiveis = bool(backup_dir.exists() and any(backup_dir.iterdir()))
    return render(
        request,
        "configuracoes/setup_inicial.html",
        {
            "form": form,
            "linhas_disponiveis": linhas_disponiveis,
            "linhas_cards": linhas_cards,
            "linhas_selecionadas": linhas_selecionadas,
            "tipo_empresa_ativo": tipo_empresa_inicial,
            "setup_concluido": setup_inicial_concluido(),
            "backups_disponiveis": backups_disponiveis,
            "backup_dir": backup_dir,
            "menu_app": "configuracoes",
            "menu_sub": "setup_inicial",
        },
    )


def modelos_mensagem_impl(request):
    editar_id = request.GET.get("edit")
    instancia = None
    if editar_id and editar_id.isdigit():
        instancia = ModeloMensagem.objects.filter(id=int(editar_id)).first()

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "popular_eventos":
            sobrescrever = request.POST.get("sobrescrever") == "1"
            total = garantir_modelos_operacionais_padrao(sobrescrever=sobrescrever)
            if total:
                messages.success(request, f"{total} modelos operacionais criados/atualizados.")
            else:
                messages.info(request, "Nenhum novo modelo foi criado. Os modelos por evento ja existem.")
            return redirect("configuracoes:modelos_mensagem")
        if form_type == "delete":
            modelo = get_object_or_404(ModeloMensagem, id=request.POST.get("modelo_id"))
            modelo.delete()
            messages.success(request, "Modelo removido com sucesso.")
            return redirect("configuracoes:modelos_mensagem")

        if form_type == "toggle":
            modelo = get_object_or_404(ModeloMensagem, id=request.POST.get("modelo_id"))
            modelo.ativo = not modelo.ativo
            modelo.save(update_fields=["ativo"])
            messages.success(request, "Modelo atualizado.")
            return redirect("configuracoes:modelos_mensagem")

        model_id = request.POST.get("modelo_id")
        if model_id:
            instancia = get_object_or_404(ModeloMensagem, id=model_id)
        form = ModeloMensagemForm(request.POST, instance=instancia)
        if form.is_valid():
            form.save()
            messages.success(request, "Modelo salvo com sucesso.")
            return redirect("configuracoes:modelos_mensagem")
    else:
        form = ModeloMensagemForm(instance=instancia)

    busca_modelo = (request.GET.get("q") or "").strip()
    filtro_tipo = (request.GET.get("tipo") or "").strip()
    filtro_ativo = (request.GET.get("ativo") or "").strip()

    modelos = ModeloMensagem.objects.all()
    if busca_modelo:
        modelos = modelos.filter(nome__icontains=busca_modelo)
    if filtro_tipo:
        modelos = modelos.filter(tipo=filtro_tipo)
    if filtro_ativo == "1":
        modelos = modelos.filter(ativo=True)
    elif filtro_ativo == "0":
        modelos = modelos.filter(ativo=False)
    modelos = modelos.order_by("nome")
    eventos_catalogo = listar_eventos_comunicacao()
    eventos_com_modelo = set(
        ModeloMensagem.objects.exclude(evento_chave="").values_list("evento_chave", flat=True)
    )
    resumo_modelos = {
        "total": ModeloMensagem.objects.count(),
        "ativos": ModeloMensagem.objects.filter(ativo=True).count(),
        "por_evento": ModeloMensagem.objects.exclude(evento_chave="").count(),
        "eventos_catalogo": len(eventos_catalogo),
        "eventos_sem_modelo": sum(1 for evento in eventos_catalogo if evento["codigo"] not in eventos_com_modelo),
    }
    return render(
        request,
        "configuracoes/modelos_mensagem.html",
        {
            "form": form,
            "modelos": modelos,
            "eventos_catalogo": eventos_catalogo,
            "resumo_modelos": resumo_modelos,
            "busca_modelo": busca_modelo,
            "filtro_tipo": filtro_tipo,
            "filtro_ativo": filtro_ativo,
            "tipos_modelo": ModeloMensagem.TIPO_CHOICES,
            "edit_modelo_id": instancia.id if instancia else None,
            "catalogo_tab": "mensagens",
            "catalogo_title": "Modelos e comunicao de atendimento",
            "catalogo_subtitle": (
                "Mantenha a biblioteca operacional de mensagens manuais e os eventos de comunicao "
                "disponveis para atendimento e relacionamento com o cliente."
            ),
            "menu_app": "configuracoes",
            "menu_sub": "modelos_mensagem",
        },
    )


def tipos_equipamento_impl(request):
    editar_id = (request.GET.get("edit") or "").strip()
    instancia = None
    if editar_id.isdigit():
        instancia = TipoEquipamentoConfig.objects.filter(id=int(editar_id)).first()

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "delete":
            item = get_object_or_404(TipoEquipamentoConfig, id=request.POST.get("item_id"))
            item.delete()
            messages.success(request, "Tipo de equipamento removido.")
            return redirect("configuracoes:tipos_equipamento")
        if form_type == "toggle":
            item = get_object_or_404(TipoEquipamentoConfig, id=request.POST.get("item_id"))
            item.ativo = not item.ativo
            item.save(update_fields=["ativo"])
            messages.success(request, "Tipo de equipamento atualizado.")
            return redirect("configuracoes:tipos_equipamento")

        item_id = request.POST.get("item_id")
        if item_id:
            instancia = get_object_or_404(TipoEquipamentoConfig, id=item_id)
        form = TipoEquipamentoConfigForm(request.POST, instance=instancia)
        if form.is_valid():
            form.save()
            messages.success(request, "Tipo de equipamento salvo.")
            return redirect("configuracoes:tipos_equipamento")
        messages.error(request, "Nao foi possivel salvar. Verifique os campos informados.")
    else:
        form = TipoEquipamentoConfigForm(instance=instancia)

    return render(
        request,
        "configuracoes/tipos_equipamento.html",
        {
            "form": form,
            "itens": TipoEquipamentoConfig.objects.order_by("nome"),
            "edit_item_id": instancia.id if instancia else None,
            "catalogo_tab": "tipos",
            "catalogo_title": "Tipos de equipamento",
            "catalogo_subtitle": (
                "Padronize os equipamentos disponveis no cadastro para melhorar busca, abertura de OS "
                "e organizao do atendimento."
            ),
            "menu_app": "configuracoes",
            "menu_sub": "tipos_equipamento",
        },
    )



