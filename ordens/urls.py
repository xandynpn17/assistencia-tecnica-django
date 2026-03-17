from django.urls import path
from . import views
from .views import OrdemServicoCreateView, OrdemServicoListView, OrdemServicoUpdateView, DetalhesOrdemView, OrdemServicoResumoView
from orcamentos import views as orc_views



app_name = 'ordens'

urlpatterns = [
    # =======================
    # Seleção e criação de ordens
    # =======================
    path('selecionar-cliente/', views.selecionar_cliente_os, name='selecionar_cliente_os'),
    path('novo/<int:cliente_id>/', OrdemServicoCreateView.as_view(), name='nova_ordem_cliente'),
    path('novo/', OrdemServicoCreateView.as_view(), name='nova_ordem'),

    # =======================
    # Listagem, edição e detalhes
    # =======================
    path('', OrdemServicoListView.as_view(), name='lista_ordens'),
    path('<int:pk>/editar/', OrdemServicoUpdateView.as_view(), name='editar_ordem'),
    path('<int:pk>/detalhes/', DetalhesOrdemView.as_view(), name='detalhes_ordem'),
    path('<int:pk>/agendar/', views.agendar_ordem, name='agendar_ordem'),
    path('<int:pk>/resumo/', OrdemServicoResumoView.as_view(), name='resumo_ordem'),
    path('<int:pk>/confirmar-manual-resumo/', views.confirmar_manual_resumo, name='confirmar_manual_resumo'),
    path('<int:pk>/toggle-fechamento/', views.toggle_fechamento_os, name='toggle_fechamento_os'),
    path('<int:pk>/imprimir-confirmacao/', views.imprimir_confirmacao_os, name='imprimir_confirmacao_os'),
    path('<int:pk>/reenviar-confirmacao-whatsapp/', views.reenviar_confirmacao_whatsapp, name='reenviar_confirmacao_whatsapp'),
    path('<int:pk>/notificar/<str:tipo>/', views.notificar_cliente_ordem, name='notificar_cliente_ordem'),
    path("buscar-ordens/", views.buscar_ordens, name="buscar_ordens"),
    path("pedidos/dashboard/", views.dashboard_pedidos_compra, name="dashboard_pedidos"),
    path("pedidos/<int:pedido_id>/toggle-fechamento/", views.toggle_fechamento_pedido_compra, name="toggle_fechamento_pedido"),
    path("portal/", views.portal_cliente, name="portal_cliente"),
    path("confirmar/<uuid:token>/", views.confirmar_ordem_token_publico, name="confirmar_ordem_token_publico"),


    # =======================
    # Verificação de cliente antes de abrir ordem
    # =======================
    path('verificar-cliente/', views.verificar_cliente_os, name='verificar_cliente_os'),

    # =======================
    # Orcamentos
    #path('orcamentos/', orc_views.lista_orcamentos, name='lista_orcamentos'),
    path('orcamentos/novo/<int:ordem_id>/', orc_views.criar_orcamento, name='criar_orcamento'),
    path('orcamentos/<int:orcamento_id>/aceitar/', orc_views.aceitar_itens_orcamento, name='aceitar_orcamento'),
    path('orcamentos/<int:orcamento_id>/recusar/', orc_views.recusar_itens_orcamento, name='recusar_orcamento'),
    path('orcamentos/<int:orcamento_id>/migrar/', orc_views.migrar_para_servicos, name='migrar_para_servicos'),

    # Itens de orçamento
    path('orcamentos/item/adicionar/<int:orcamento_id>/', orc_views.adicionar_item, name='adicionar_item_orcamento'),
    path('orcamentos/item/editar/<int:item_id>/', orc_views.editar_item, name='editar_item_orcamento'),
    path('orcamentos/item/excluir/<int:item_id>/', orc_views.excluir_item, name='excluir_item_orcamento'),
    path('<int:pk>/migrar-orcamento/', views.migrar_orcamento, name='migrar_orcamento'),

    #ajax
    path('<int:os_id>/atualizar_local/', views.atualizar_local, name='atualizar_local'),
    path('<int:os_id>/adicionar_linha/', views.adicionar_linha, name='adicionar_linha'),
    path('<int:os_id>/atualizar_observacoes/', views.atualizar_observacoes, name='atualizar_observacoes'),
    path('<int:os_id>/atualizar_tecnico/', views.atualizar_tecnico, name='atualizar_tecnico'),
    path('<int:os_id>/atualizar_numero_serie/', views.atualizar_numero_serie, name='atualizar_numero_serie'),




    #PDF
    path("<int:pk>/imprimir/", views.imprimir_ordem_servico, name="imprimir_ordem_servico"),
    path("<int:pk>/imprimir-fisico/", views.imprimir_ordem_servico_impressao, name="imprimir_ordem_servico_impressao"),
    path('imprimir_relatorio/<int:pk>/', views.imprimir_relatorio_tecnico, name='imprimir_relatorio_tecnico'),
]
