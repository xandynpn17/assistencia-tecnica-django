from django.urls import path
from . import views

app_name = "caixa"

urlpatterns = [
    path("", views.dashboard_caixa, name="dashboard_caixa"),
    path("meu-desempenho/", views.meu_desempenho, name="meu_desempenho"),
    path("pagamento/", views.registrar_pagamento, name="registrar_pagamento"),
    path("saida/", views.registrar_saida, name="registrar_saida"),
    path("abrir/", views.abrir_caixa, name="abrir_caixa"),
    path("fechar/", views.fechar_caixa, name="fechar_caixa"),
    path("contas-receber/", views.contas_receber, name="contas_receber"),
    path("contas-receber/nova/", views.criar_conta_receber, name="criar_conta_receber"),
    path("contas-receber/<int:conta_id>/", views.detalhe_conta_receber, name="detalhe_conta_receber"),
    path("contas-receber/aging/", views.aging_receber, name="aging_receber"),
    path("contas-pagar/", views.contas_pagar, name="contas_pagar"),
    path("contas-pagar/nova/", views.criar_conta_pagar, name="criar_conta_pagar"),
    path("contas-pagar/<int:conta_id>/", views.detalhe_conta_pagar, name="detalhe_conta_pagar"),
    path("categorias-financeiras/", views.categorias_financeiras, name="categorias_financeiras"),
    path("formas-pagamento/", views.formas_pagamento, name="formas_pagamento"),
    path("centros-custo/", views.centros_custo, name="centros_custo"),
    path("taloes/", views.taloes, name="taloes"),
    path("taloes/<int:pagamento_id>/imprimir/", views.imprimir_talao, name="imprimir_talao"),
    path("garantias-fabricante/", views.garantias_fabricante, name="garantias_fabricante"),
    path("comissoes/pagamentos/", views.comissoes_pagamento, name="comissoes_pagamento"),
    path("comissoes/pendencias/", views.comissoes_pendencias, name="comissoes_pendencias"),
    path("comissoes/", views.comissoes_tecnicos, name="comissoes_tecnicos"),
    path("premios/", views.premios_meta, name="premios_meta"),
    path("dre/", views.dre, name="dre"),
    path("auditoria-operacional/", views.auditoria_operacional, name="auditoria_operacional"),
    path("fluxo-projetado/", views.fluxo_projetado, name="fluxo_projetado"),
    path("relatorios/", views.relatorios, name="relatorios"),
]
