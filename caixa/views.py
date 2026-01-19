from django.shortcuts import render, redirect
from .models import Caixa, Pagamento, LancamentoCaixa
from .forms import PagamentoForm, LancamentoCaixaForm
from ordens.models import OrdemServico

# -------------------------------
# Função auxiliar
# -------------------------------
def caixa_atual():
    """ Retorna o caixa aberto ou None """
    return Caixa.objects.filter(aberto=True).last()

# -------------------------------
# Dashboard Caixa
# -------------------------------
def dashboard_caixa(request):
    caixa = caixa_atual()

    if caixa:
        pagamentos = caixa.pagamentos.all()
        lancamentos = caixa.lancamentos.all()
        total_entradas = sum(l.valor for l in lancamentos if l.tipo == "entrada")
        total_saidas = sum(l.valor for l in lancamentos if l.tipo == "saida")
        saldo = caixa.saldo_inicial + total_entradas - total_saidas
    else:
        pagamentos = []
        lancamentos = []
        total_entradas = total_saidas = saldo = 0

    return render(request, "caixa/dashboard_caixa.html", {
        "caixa": caixa,
        "pagamentos": pagamentos,
        "lancamentos": lancamentos,
        "total_entradas": total_entradas,
        "total_saidas": total_saidas,
        "saldo": saldo,
        "menu_app": "caixa",
        "menu_sub": "dashboard_caixa",
    })

# -------------------------------
# Abrir Caixa
# -------------------------------
def abrir_caixa(request):
    caixa = caixa_atual()
    if caixa:
        msg = "O caixa já está aberto."
        return render(request, "caixa/abrir_caixa.html", {
            "caixa": caixa,
            "mensagem": msg,
            "menu_app": "caixa",
            "menu_sub": "abrir_caixa",
        })

    if request.method == "POST":
        saldo_inicial = float(request.POST.get("saldo_inicial", 0))
        caixa = Caixa.objects.create(saldo_inicial=saldo_inicial, aberto=True)
        return redirect("caixa:dashboard_caixa")

    return render(request, "caixa/abrir_caixa.html", {
        "caixa": None,
        "mensagem": "",
        "menu_app": "caixa",
        "menu_sub": "abrir_caixa",
    })

# -------------------------------
# Fechar Caixa
# -------------------------------
def fechar_caixa(request):
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:dashboard_caixa")

    total_entradas = sum(l.valor for l in caixa.lancamentos.all() if l.tipo=="entrada")
    total_saidas = sum(l.valor for l in caixa.lancamentos.all() if l.tipo=="saida")
    saldo_atual = caixa.saldo_inicial + total_entradas - total_saidas

    if request.method == "POST":
        caixa.aberto = False
        caixa.saldo_final = saldo_atual
        caixa.save()
        return redirect("caixa:dashboard_caixa")

    return render(request, "caixa/fechar_caixa.html", {
        "caixa": caixa,
        "total_entradas": total_entradas,
        "total_saidas": total_saidas,
        "saldo": saldo_atual,
        "menu_app": "caixa",
        "menu_sub": "fechar_caixa",
    })

# -------------------------------
# Registrar Pagamento
# -------------------------------
# caixa/views.py


def registrar_pagamento(request):
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")

    os_id = request.GET.get("os")
    stock_id = request.GET.get("stock")

    ordem = OrdemServico.objects.filter(id=os_id).first() if os_id else None
    item = None
    if stock_id:
        from stock.models import ItemVenda
        item = ItemVenda.objects.filter(id=stock_id).first()

    if request.method == "POST":
        form = PagamentoForm(request.POST)
        if form.is_valid():
            pagamento = form.save(commit=False)
            pagamento.caixa = caixa
            pagamento.ordem_servico = ordem if ordem else pagamento.ordem_servico
            pagamento.stock_item = item if item else pagamento.stock_item
            pagamento.save()

            descricao = (
                f"Pagamento OS {pagamento.ordem_servico.numero_os}"
                if pagamento.ordem_servico else
                f"Pagamento Stock {pagamento.stock_item.id}"
                if pagamento.stock_item else
                "Pagamento Avulso"
            )

            LancamentoCaixa.objects.create(
                caixa=caixa,
                descricao=descricao,
                valor=pagamento.valor,
                tipo="entrada",
                usuario=request.user
            )

            messages.success(request, f"Pagamento de {pagamento.valor:.2f}€ registrado com sucesso!")
            return redirect("caixa:dashboard_caixa")
    else:
        form = PagamentoForm()

    return render(request, "caixa/registrar_pagamento.html", {
        "form": form,
        "ordem": ordem,
        "item": item,
        "caixa": caixa,
        "menu_app": "caixa",
        "menu_sub": "registrar_pagamento",
    })


# -------------------------------
# Registrar Saída
# -------------------------------
def registrar_saida(request):
    caixa = caixa_atual()
    if not caixa:
        return redirect("caixa:abrir_caixa")

    if request.method == "POST":
        form = LancamentoCaixaForm(request.POST)
        if form.is_valid():
            saida = form.save(commit=False)
            saida.caixa = caixa
            saida.tipo = "saida"
            saida.usuario = request.user
            saida.save()
            return redirect("caixa:dashboard_caixa")
    else:
        form = LancamentoCaixaForm()

    return render(request, "caixa/registrar_saida.html", {
        "form": form,
        "menu_app": "caixa",
        "menu_sub": "registrar_saida",
        "caixa": caixa,
    })

# -------------------------------
# Relatórios
# -------------------------------
def relatorios(request):
    caixa = caixa_atual()
    if caixa:
        pagamentos = caixa.pagamentos.all()
        lancamentos = caixa.lancamentos.all()
    else:
        pagamentos = []
        lancamentos = []

    return render(request, "caixa/relatorios.html", {
        "caixa": caixa,
        "pagamentos": pagamentos,
        "lancamentos": lancamentos,
        "menu_app": "caixa",
        "menu_sub": "relatorios",
    })