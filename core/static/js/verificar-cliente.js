/**
 * Cadastro Cliente - Versão Profissional Equilibrada
 * Estável, expansível e sem hacks
 */

const CadastroCliente = (() => {
    'use strict';

    // ==============================
    // Helpers
    // ==============================
    const $ = (id) => document.getElementById(id);
    const apenasNumeros = (v) => v ? v.replace(/\D/g, '') : '';
    const group = (el) => el.closest('.form-group');

    // ==============================
    // FORMATAÇÕES
    // ==============================
    function formatarDocumento(input) {
        let v = apenasNumeros(input.value).substring(0, 14);

        if (v.length <= 11) {
            if (v.length > 9)
                v = v.replace(/(\d{3})(\d{3})(\d{3})(\d+)/, '$1.$2.$3-$4');
            else if (v.length > 6)
                v = v.replace(/(\d{3})(\d{3})(\d+)/, '$1.$2.$3');
            else if (v.length > 3)
                v = v.replace(/(\d{3})(\d+)/, '$1.$2');
        } else {
            if (v.length > 12)
                v = v.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d+)/, '$1.$2.$3/$4-$5');
            else if (v.length > 8)
                v = v.replace(/(\d{2})(\d{3})(\d{3})(\d+)/, '$1.$2.$3/$4');
        }

        input.value = v;
        input.dataset.clean = apenasNumeros(v);
    }

    function formatarTelefone(input) {
        let v = apenasNumeros(input.value).substring(0, 9);

        if (v.length > 4) {
            if (v.length <= 8)
                v = v.replace(/(\d{4})(\d+)/, '$1-$2');
            else
                v = v.replace(/(\d{5})(\d+)/, '$1-$2');
        }

        input.value = v;
        input.dataset.clean = apenasNumeros(v);
    }

    function formatarCEP(input) {
        let v = apenasNumeros(input.value).substring(0, 8);
        if (v.length > 5)
            v = v.replace(/(\d{5})(\d+)/, '$1-$2');

        input.value = v;
    }

    // ==============================
    // TELEFONE COMPLETO
    // ==============================
    function atualizarTelefoneCompleto() {
        const ddd = $('id_ddd');
        const numero = $('id_telefone_numero');
        if (!ddd || !numero) return;

        let hidden = $('telefone_completo');

        if (!hidden) {
            hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = 'telefone_completo';
            hidden.id = 'telefone_completo';
            numero.parentNode.appendChild(hidden);
        }

        const d = ddd.value;
        const n = numero.dataset.clean || apenasNumeros(numero.value);

        if (d && n.length >= 8) {
            hidden.value = d + n;
            mostrarTelefoneDisplay(d, n);
            numero.classList.add('is-valid');
            numero.classList.remove('is-invalid');
        } else {
            hidden.value = '';
            ocultarTelefoneDisplay();
        }
    }

    function mostrarTelefoneDisplay(ddd, numero) {
        const display = $('telefone-display');
        const formatado = $('telefone-formatado');
        const whatsapp = $('whatsapp-link');

        if (!display) return;

        let n = numero.length === 8
            ? numero.replace(/(\d{4})(\d{4})/, '$1-$2')
            : numero.replace(/(\d{5})(\d{4})/, '$1-$2');

        formatado.textContent = `(${ddd}) ${n}`;
        whatsapp.innerHTML =
            `<a href="https://wa.me/55${ddd}${numero}" target="_blank" class="text-success">
            wa.me/55${ddd}${numero}</a>`;

        display.style.display = 'block';
    }

    function ocultarTelefoneDisplay() {
        const display = $('telefone-display');
        if (display) display.style.display = 'none';
    }

    // ==============================
    // CEP
    // ==============================
    async function buscarCEP() {
        const cepInput = $('id_codigo_postal');
        const btn = $('btn-buscar-cep');
        const cep = apenasNumeros(cepInput.value);

        if (cep.length !== 8) {
            mostrarErroCEP('CEP deve ter 8 dígitos');
            return;
        }

        limparErroCEP();

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        try {
            const res = await fetch(`/configuracoes/buscar-cep/?cep=${cep}`);
            const data = await res.json();

            if (data.erro || data.error) {
                mostrarErroCEP('CEP não encontrado');
                limparEndereco();
            } else {
                preencherEndereco(data);
                cepInput.classList.add('is-valid');
            }

        } catch {
            mostrarErroCEP('Erro ao buscar CEP');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-search"></i>';
        }
    }

    function preencherEndereco(data) {
        $('id_logradouro').value = data.logradouro || '';
        $('id_bairro').value = data.bairro || '';
        $('id_cidade').value = data.cidade || '';
        $('id_complemento').value = data.complemento || '';

        const estado = $('id_estado');
        if (estado && data.estado)
            estado.value = data.estado.toUpperCase();
    }

    function limparEndereco() {
        ['id_logradouro','id_bairro','id_cidade','id_complemento']
            .forEach(id => $(id).value = '');
    }

    function mostrarErroCEP(msg) {
        const cepInput = $('id_codigo_postal');
        const g = group(cepInput);

        cepInput.classList.add('is-invalid');

        let fb = g.querySelector('.cep-error');
        if (!fb) {
            fb = document.createElement('div');
            fb.className = 'invalid-feedback d-block cep-error';
            g.appendChild(fb);
        }
        fb.textContent = msg;
    }

    function limparErroCEP() {
        const cepInput = $('id_codigo_postal');
        const g = group(cepInput);
        cepInput.classList.remove('is-invalid');

        const fb = g.querySelector('.cep-error');
        if (fb) fb.remove();
    }

    // ==============================
    // LIMPAR FORMULÁRIO
    // ==============================
    function limparFormulario() {
        const form = $('clienteForm');
        if (!form) return;

        form.reset();

        document.querySelectorAll('.is-valid, .is-invalid')
            .forEach(el => el.classList.remove('is-valid','is-invalid'));

        document.querySelectorAll('.cep-error')
            .forEach(el => el.remove());

        ocultarTelefoneDisplay();

        $('id_nome')?.focus();
    }

    // ==============================
    // INIT
    // ==============================
    function init() {
        const form = $('clienteForm');
        if (!form) return;

        const doc = $('id_documento');
        const tel = $('id_telefone_numero');
        const ddd = $('id_ddd');
        const cep = $('id_codigo_postal');
        const btnCep = $('btn-buscar-cep');
        const btnLimpar = $('btn-limpar-formulario');

        doc?.addEventListener('input', e => formatarDocumento(e.target));
        tel?.addEventListener('input', e => {
            formatarTelefone(e.target);
            atualizarTelefoneCompleto();
        });

        ddd?.addEventListener('change', atualizarTelefoneCompleto);

        cep?.addEventListener('input', e => formatarCEP(e.target));
        cep?.addEventListener('blur', () => {
            if (apenasNumeros(cep.value).length === 8)
                buscarCEP();
        });

        btnCep?.addEventListener('click', e => {
            e.preventDefault();
            buscarCEP();
        });

        btnLimpar?.addEventListener('click', e => {
            e.preventDefault();
            if (confirm('Deseja limpar o formulário?'))
                limparFormulario();
        });

        form.addEventListener('submit', () => {
            if (doc) doc.value = apenasNumeros(doc.value);
            if (cep) cep.value = apenasNumeros(cep.value);
        });
    }

    return { init };

})();

document.addEventListener('DOMContentLoaded', () => {
    CadastroCliente.init();
});
