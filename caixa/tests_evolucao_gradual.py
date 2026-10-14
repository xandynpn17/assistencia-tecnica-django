from datetime import date, timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from caixa.models import (Caixa, ContaBancaria, ContaReceber, EstornoOrigemCheckout, LinhaExtratoBancario,
                          MovimentoBancario, MovimentoFinanceiro, Pagamento)
from caixa.services.consulta_bancaria import contexto_consulta_bancaria
from caixa.services.consulta_financeira import fluxo_financeiro_periodo
from caixa.services.historico_cliente import resumo_financeiro_cliente
from caixa.services.tesouraria import conciliar_linha
from caixa.view_modules.tesouraria import _url_retorno_tesouraria
from clientes.models import Cliente
from configuracoes.models import Empresa, User
from ordens.models import OrdemServico


class EvolucaoGradualTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nome='Empresa Evolução')
        cls.outra = Empresa.objects.create(nome='Outra Empresa')
        cls.gestor = User.objects.create_user(username='evolucao_gestor', tipo_usuario='gerente', empresa=cls.empresa)
        cls.tecnico = User.objects.create_user(username='evolucao_tecnico', tipo_usuario='tecnico', empresa=cls.empresa)
        cls.cliente = Cliente.objects.create(empresa=cls.empresa, nome='Cliente Evolução', documento='52998224725', telefone='11999998888', observacoes='Observação privada', logradouro='Rua Privada', estado='SP')
        cls.cliente_outra = Cliente.objects.create(empresa=cls.outra, nome='Outro Cliente', documento='11144477735', estado='SP')
        cls.ordem = OrdemServico.objects.create(empresa=cls.empresa, cliente=cls.cliente, tipo_equipamento='celular', marca_equipamento='Marca', modelo_equipamento='Modelo', defeito='Não liga', tipo_reparo='Fora de Garantia')
        cls.banco = ContaBancaria.objects.create(empresa=cls.empresa, nome='Principal', saldo_inicial=100, data_saldo_inicial=date(2026, 1, 1))
        cls.banco_outra = ContaBancaria.objects.create(empresa=cls.outra, nome='Outro Banco', data_saldo_inicial=date(2026, 1, 1))
        cls.caixa = Caixa.objects.create(empresa=cls.empresa, aberto=True)

    def consulta(self, **filtros):
        return contexto_consulta_bancaria(RequestFactory().get(reverse('caixa:tesouraria'), filtros), self.empresa)

    def movimento(self, banco=None, dia=date(2026, 8, 1), valor=10, tipo='entrada', chave='m1'):
        banco = banco or self.banco
        return MovimentoBancario.objects.create(empresa=banco.empresa, conta=banco, data_movimento=dia, valor=valor, tipo=tipo, origem_tipo='manual', descricao='Teste consulta', chave_idempotencia=chave)

    def pagamento(self, **kwargs):
        return Pagamento.objects.create(empresa=self.empresa, caixa=self.caixa, valor=100, metodo='pix', data_movimento=date(2026, 8, 1), **kwargs)

    def test_paginacao_totais_e_movimento_antigo(self):
        for n in range(105):
            self.movimento(dia=date(2026, 1, 1) + timedelta(days=n), chave=f'pg-{n}')
        consulta = self.consulta(pagina_movimentos=3, movimentos='todos')
        self.assertEqual(consulta['resumo_filtro']['banco_quantidade'], 105)
        self.assertEqual(consulta['resumo_filtro']['banco_entradas'], Decimal('1050'))
        self.assertEqual(len(consulta['movimentos']), 5)
        self.assertEqual(consulta['movimentos'][-1].data_movimento, date(2026, 1, 1))
        self.assertEqual(self.consulta(pagina_movimentos=1, movimentos='todos')['resumo_filtro'], consulta['resumo_filtro'])

    def test_filtro_data_e_saldo_periodo_nao_confunde_total(self):
        self.movimento(dia=date(2026, 1, 10), valor=40)
        self.movimento(dia=date(2026, 2, 10), valor=15, tipo='saida', chave='m2')
        consulta = self.consulta(conta=self.banco.pk, data_inicio='2026-02-01', data_fim='2026-02-28', movimentos='todos')
        self.assertEqual(consulta['resumo_filtro']['banco_entradas'], 0)
        self.assertEqual(consulta['resumo_filtro']['banco_saidas'], 15)
        self.assertEqual(consulta['saldo_fim_periodo'], 125)

    def test_natureza_sem_presumir_manual_antigo_e_contrapartida(self):
        manual = self.movimento(chave='natureza-manual')
        capital = MovimentoBancario.objects.create(empresa=self.empresa, conta=self.banco, tipo='entrada', origem_tipo='aporte_capital', valor=50, data_movimento=date(2026, 8, 1), descricao='Aporte', chave_idempotencia='natureza-capital')
        inverso = MovimentoBancario.objects.create(empresa=self.empresa, conta=self.banco, tipo='saida', origem_tipo='manual', valor=50, data_movimento=date(2026, 8, 2), descricao='Contrapartida', chave_idempotencia='natureza-inversa', neutralizacao_de=capital)
        conhecidos = self.consulta(natureza='capital', movimentos='todos')
        self.assertEqual({m.pk for m in conhecidos['movimentos']}, {capital.pk, inverso.pk})
        desconhecidos = self.consulta(natureza='nao_classificado', movimentos='todos')
        self.assertEqual({m.pk for m in desconhecidos['movimentos']}, {manual.pk})
        self.assertEqual(self.consulta(natureza='operacional', movimentos='todos')['resumo_filtro']['banco_quantidade'], 0)

    def test_natureza_filtra_extrato_so_com_vinculo_conhecido(self):
        p = self.pagamento()
        movimento = MovimentoBancario.objects.create(empresa=self.empresa, conta=self.banco, tipo='entrada', origem_tipo='pagamento', origem_id=p.pk, valor=100, data_movimento=date(2026, 8, 1), descricao='Pagamento', chave_idempotencia='natureza-pagamento')
        linha = LinhaExtratoBancario.objects.create(empresa=self.empresa, conta=self.banco, data_movimento=date(2026, 8, 1), descricao='Extrato pago', valor=100, identificador_externo='natureza-linha', movimento=movimento, status='conciliado')
        pendente = LinhaExtratoBancario.objects.create(empresa=self.empresa, conta=self.banco, data_movimento=date(2026, 8, 1), descricao='Ainda sem classificação', valor=10, identificador_externo='natureza-pendente')
        self.assertEqual({l.pk for l in self.consulta(natureza='operacional')['linhas_extrato']}, {linha.pk})
        self.assertEqual({l.pk for l in self.consulta(natureza='nao_classificado')['linhas_extrato']}, {pendente.pk})
        self.assertEqual(self.consulta(natureza='capital')['resumo_filtro']['extrato_quantidade'], 0)

    def test_intervalo_invertido_e_data_invalida(self):
        self.movimento()
        for filtros in [{'data_inicio': '2026-09-01', 'data_fim': '2026-08-01'}, {'data_inicio': 'inválida'}]:
            consulta = self.consulta(**filtros)
            self.assertTrue(consulta['filtro_bancario'].errors)
            self.assertEqual(consulta['resumo_filtro']['banco_quantidade'], 0)

    def test_tenant_e_conta_forjada(self):
        self.movimento(banco=self.banco_outra)
        self.assertEqual(self.consulta()['resumo_filtro']['banco_quantidade'], 0)
        self.assertFalse(self.consulta(conta=self.banco_outra.pk)['filtro_bancario'].is_valid())

    def test_conciliados_somente_no_historico(self):
        mov = self.movimento()
        linha = LinhaExtratoBancario.objects.create(empresa=self.empresa, conta=self.banco, data_movimento=mov.data_movimento, valor=10, descricao='Teste', identificador_externo='L1')
        conciliar_linha(linha=linha, movimento=mov, usuario=self.gestor)
        self.assertEqual(self.consulta()['resumo_filtro']['banco_quantidade'], 0)
        self.assertEqual(self.consulta(movimentos='todos')['resumo_filtro']['banco_quantidade'], 1)
        self.assertEqual(self.consulta(situacao='conciliado')['resumo_filtro']['extrato_quantidade'], 1)

    def test_retorno_preserva_filtros_sem_redirecionamento_externo(self):
        rf = RequestFactory()
        destino = reverse('caixa:tesouraria') + '?conta=1&data_inicio=2026-08-01&pagina_extrato=2'
        self.assertEqual(_url_retorno_tesouraria(rf.get('/acao/', {'next': destino})), destino)
        for retorno in ['https://example.com/', '//example.com/', 'http://[', '/outra/']:
            self.assertEqual(_url_retorno_tesouraria(rf.get('/acao/', {'next': retorno})), reverse('caixa:tesouraria'))

    def test_historico_inclui_venda_identificada_sem_adivinhar_nome(self):
        self.pagamento(cliente=self.cliente)
        self.pagamento(cliente_nome=self.cliente.nome)
        self.assertEqual(resumo_financeiro_cliente(self.cliente, self.empresa)['total_gasto'], 100)

    def test_cliente_inferido_e_mistura_tenant_bloqueada(self):
        p = self.pagamento(ordem_servico=self.ordem)
        self.assertEqual(p.cliente_id, self.cliente.pk)
        with self.assertRaises(ValidationError):
            self.pagamento(cliente=self.cliente_outra)

    def test_fabricante_nao_entra_no_gasto_cliente(self):
        self.pagamento(ordem_servico=self.ordem)
        Pagamento.objects.create(empresa=self.empresa, caixa=self.caixa, ordem_servico=self.ordem, valor=18, metodo='garantia_fabricante')
        for tipo, valor in [('cliente_os', 20), ('garantia_fabricante', 18)]:
            ContaReceber.objects.create(empresa=self.empresa, ordem_servico=self.ordem, tipo_origem=tipo, descricao='Cobrança', valor_original=valor, valor_aberto=valor, vencimento=date(2026, 8, 31))
        resumo = resumo_financeiro_cliente(self.cliente, self.empresa)
        self.assertEqual(resumo['total_gasto'], 100)
        self.assertEqual(resumo['total_em_aberto'], 20)

    def test_estorno_parcial_checkout_nao_duplica(self):
        p = self.pagamento(cliente=self.cliente, desconto=10, origens_compostas=[{'tipo': 'os', 'ordem_id': self.ordem.pk, 'valor_liquido': '60'}, {'tipo': 'produto', 'valor_liquido': '40', 'estornado': True}])
        EstornoOrigemCheckout.objects.create(pagamento=p, indice_origem=1, tipo_origem='produto', descricao='Devolução', valor_bruto=45, desconto=5, valor_estornado=40, motivo='Teste')
        resumo = resumo_financeiro_cliente(self.cliente, self.empresa)
        self.assertEqual(resumo['total_gasto'], 60)
        self.assertEqual(resumo['total_descontos'], 5)
        self.assertEqual(resumo['total_devolvido'], 40)
        self.assertEqual(resumo['totais_por_ordem'][self.ordem.pk], 60)

    def test_ficha_balao_permissoes_no_backend_e_tenant(self):
        self.client.force_login(self.tecnico)
        url = reverse('clientes:resumo_cliente', args=[self.cliente.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Observação privada')
        self.assertNotContains(r, 'Rua Privada')
        self.assertNotContains(r, 'cliente-financeiro')
        self.assertEqual(self.client.get(reverse('clientes:resumo_cliente', args=[self.cliente_outra.pk])).status_code, 404)
        self.tecnico.perm_cliente_ver_dados = True
        self.tecnico.save()
        self.assertContains(self.client.get(url), 'Observação privada')

    def test_edicao_cliente_sem_permissao_negada(self):
        atendente = User.objects.create_user(username='evolucao_atendente', tipo_usuario='atendente', empresa=self.empresa)
        self.client.force_login(atendente)
        self.assertEqual(self.client.get(reverse('clientes:editar_cliente', args=[self.cliente.pk])).status_code, 403)

    def test_devolucao_em_outro_mes_nao_altera_recebimento_anterior(self):
        p = self.pagamento(cliente=self.cliente, origens_compostas=[{'tipo': 'produto', 'valor_liquido': '100', 'estornado': True}])
        estorno = EstornoOrigemCheckout.objects.create(pagamento=p, indice_origem=0, tipo_origem='produto', descricao='Devolução', valor_bruto=20, valor_estornado=20, motivo='Teste datas')
        from django.utils import timezone
        evento = timezone.make_aware(timezone.datetime(2026, 9, 2, 10))
        EstornoOrigemCheckout.objects.filter(pk=estorno.pk).update(estornado_em=evento)
        agosto = resumo_financeiro_cliente(self.cliente, self.empresa, inicio=date(2026, 8, 1), fim=date(2026, 8, 31))
        setembro = resumo_financeiro_cliente(self.cliente, self.empresa, inicio=date(2026, 9, 1), fim=date(2026, 9, 30))
        self.assertEqual((agosto['total_gasto'], agosto['total_devolvido']), (100, 0))
        self.assertEqual((setembro['total_gasto'], setembro['total_devolvido']), (-20, 20))
        self.assertEqual(setembro['historico_pagamentos'][0]['data'], date(2026, 9, 2))

    def test_revisao_cliente_preserva_snapshot_e_financeiro(self):
        p = self.pagamento(cliente_nome='Nome do recibo original')
        self.client.force_login(self.gestor)
        resposta = self.client.post(reverse('caixa:revisar_identificacao_clientes'), {'pagamento': p.pk, 'cliente': self.cliente.pk, 'justificativa': 'Confirmado pelo recibo e atendimento'})
        self.assertEqual(resposta.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.cliente_id, self.cliente.pk)
        self.assertEqual(p.cliente_nome, 'Nome do recibo original')
        self.assertEqual(p.valor, 100)
        from caixa.models import AuditoriaFinanceira
        self.assertTrue(AuditoriaFinanceira.objects.filter(pagamento=p, evento='pagamento_cliente_identificado').exists())

    def test_revisao_cliente_recusa_outro_tenant(self):
        p = self.pagamento()
        self.client.force_login(self.gestor)
        resposta = self.client.post(reverse('caixa:revisar_identificacao_clientes'), {'pagamento': p.pk, 'cliente': self.cliente_outra.pk, 'justificativa': 'Tentativa de vincular empresa diferente'})
        self.assertEqual(resposta.status_code, 200)
        p.refresh_from_db()
        self.assertIsNone(p.cliente_id)

    def test_pagamento_antigo_sem_empresa_no_cadastro_nao_ganha_vinculo_forcado(self):
        Cliente.objects.filter(pk=self.cliente.pk).update(empresa=None)
        self.ordem.refresh_from_db()
        p = self.pagamento(ordem_servico=self.ordem)
        self.assertIsNone(p.cliente_id)

    def test_composicao_invalida_na_revisao_retorna_erro_de_formulario(self):
        p = self.pagamento()
        # Simular um snapshot legado inconsistente, sem passar pelo fluxo novo.
        Pagamento.objects.filter(pk=p.pk).update(origens_compostas=[{'tipo': 'os', 'ordem_id': 'antigo-invalido'}])
        self.client.force_login(self.gestor)
        resposta = self.client.post(reverse('caixa:revisar_identificacao_clientes'), {'pagamento': p.pk, 'cliente': self.cliente.pk, 'justificativa': 'Confirmando um registro antigo'})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'precisa de revisão')
        p.refresh_from_db()
        self.assertIsNone(p.cliente_id)

    def test_voltar_da_conciliacao_agrupada_preserva_filtro(self):
        self.client.force_login(self.gestor)
        retorno = reverse('caixa:tesouraria') + '?data_inicio=2026-08-01'
        resposta = self.client.get(reverse('caixa:conciliar_extrato_grupo'), {'next': retorno})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, retorno)

    def test_ficha_ampla_e_dashboard_renderizam(self):
        self.client.force_login(self.gestor)
        for nome, args in [('clientes:detalhes_cliente', [self.cliente.pk]), ('caixa:tesouraria', []), ('caixa:dashboard_financeiro', []), ('caixa:dashboard_caixa', [])]:
            self.assertEqual(self.client.get(reverse(nome, args=args)).status_code, 200, nome)

    def test_fluxo_retroativo_sem_sessao_sem_duplicar_ledger(self):
        p = self.pagamento(ordem_servico=self.ordem)
        from caixa.services.livro_financeiro import registrar_pagamento_no_livro
        registrar_pagamento_no_livro(p)
        MovimentoFinanceiro.objects.create(empresa=self.empresa, origem_tipo='conta_pagar', tipo='saida', valor=30, descricao='Despesa retroativa sem sessão', data_competencia=date(2026, 8, 1), data_movimento=date(2026, 8, 1), chave_idempotencia='fluxo-d')
        MovimentoFinanceiro.objects.create(empresa=self.empresa, origem_tipo='aporte_capital', tipo='entrada', natureza='capital', valor=500, descricao='Aporte', data_competencia=date(2026, 8, 1), data_movimento=date(2026, 8, 1), chave_idempotencia='fluxo-c')
        resumo = fluxo_financeiro_periodo(self.empresa, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual((resumo['entradas'], resumo['saidas'], resumo['fluxo_liquido']), (100, 30, 70))
        self.assertEqual(fluxo_financeiro_periodo(self.empresa, date(2026, 9, 1), date(2026, 9, 30))['entradas'], 0)
