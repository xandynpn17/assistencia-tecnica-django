from django.urls import path
from . import views
from . import views as orc_views  # para manter consistência, usar orc_views

app_name = 'orcamentos'

urlpatterns = [
    # Listagem geral
    path('', orc_views.lista_orcamentos, name='lista_orcamentos'),

    # Criar orçamento vinculado a uma ordem
    path('ordem/<int:ordem_id>/novo/', orc_views.criar_orcamento, name='criar_orcamento'),

    # Orcamento (editar/excluir)
    path('orcamento/<int:orcamento_id>/editar/', orc_views.editar_orcamento, name='editar_orcamento'),
    path('orcamento/<int:orcamento_id>/excluir/', orc_views.excluir_orcamento, name='excluir_orcamento'),

    # Acoes por itens selecionados
    path('orcamento/<int:orcamento_id>/aceitar/', orc_views.aceitar_itens_orcamento, name='aceitar_orcamento'),
    path('orcamento/<int:orcamento_id>/recusar/', orc_views.recusar_itens_orcamento, name='recusar_orcamento'),
    path('orcamento/<int:orcamento_id>/migrar/', orc_views.migrar_para_servicos, name='migrar_para_servicos'),

    # Itens do orçamento
    path('item/<int:item_id>/editar/', orc_views.editar_item, name='editar_item'),
    path('item/<int:item_id>/excluir/', orc_views.excluir_item, name='excluir_item'),
    path('orcamento/<int:orcamento_id>/adicionar-item/', orc_views.adicionar_item, name='adicionar_item'),

    # PDF
    path('<int:pk>/imprimir/', orc_views.imprimir_orcamento, name='imprimir_orcamento'),
]

