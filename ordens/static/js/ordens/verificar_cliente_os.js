// ============================================
// SISTEMA DE CADASTRO DE CLIENTE - COMPLETO
// ============================================

window._isPageLoading = true;


// ============================================
// ============================================
const CONFIG = {
    DDD_PADRAO: '11',
    DEBUG: true
};

// ============================================
// ============================================
const Utils = {
    log: function(...args) {
    },

    apenasNumeros: function(str) {
        return str ? str.replace(/\D/g, '') : '';
    },

    obterContainerMensagem: function() {
        let container = document.getElementById('js-system-messages');
        if (container) return container;
        const form = document.getElementById('clienteForm');
        if (!form) return null;
        container = document.createElement('div');
        container.id = 'js-system-messages';
        container.className = 'mb-3';
        form.prepend(container);
        return container;
    },

    limparMensagens: function() {
        const container = this.obterContainerMensagem();
        if (container) container.innerHTML = '';
    },

    mostrarFeedback: function(mensagem, tipo = 'success') {
        const container = this.obterContainerMensagem();
        if (!container) return;
        const nivel = tipo === 'error' ? 'danger' : tipo;
        const icone = nivel === 'success'
            ? 'check-circle'
            : nivel === 'warning'
                ? 'exclamation-triangle'
                : nivel === 'danger'
                    ? 'times-circle'
                    : 'info-circle';
        container.innerHTML = `
            <div class="alert alert-${nivel} alert-dismissible fade show js-system-alert" role="alert">
                <i class="fas fa-${icone} mr-2"></i>${mensagem}
                <button type="button" class="close" data-dismiss="alert" aria-label="Close">
                    <span aria-hidden="true">&times;</span>
                </button>
            </div>
        `;
    }
};

// ============================================
// FORMATADORES
// ============================================
const Formatadores = {
    documento: function(input) {
        let valor = Utils.apenasNumeros(input.value);
        const maxDigits = valor.length > 11 ? 14 : 11;

        if (valor.length > maxDigits) valor = valor.substring(0, maxDigits);

        if (maxDigits === 11) { // CPF
            if (valor.length > 9) {
                input.value = valor.replace(/(\d{3})(\d{3})(\d{3})(\d{0,2})/, '$1.$2.$3-$4');
            } else if (valor.length > 6) {
                input.value = valor.replace(/(\d{3})(\d{3})(\d{0,3})/, '$1.$2.$3');
            } else if (valor.length > 3) {
                input.value = valor.replace(/(\d{3})(\d{0,3})/, '$1.$2');
            }
        } else { // CNPJ
            if (valor.length > 12) {
                input.value = valor.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{0,2})/, '$1.$2.$3/$4-$5');
            } else if (valor.length > 8) {
                input.value = valor.replace(/(\d{2})(\d{3})(\d{3})(\d{0,4})/, '$1.$2.$3/$4');
            } else if (valor.length > 5) {
                input.value = valor.replace(/(\d{2})(\d{3})(\d{0,3})/, '$1.$2.$3');
            } else if (valor.length > 2) {
                input.value = valor.replace(/(\d{2})(\d{0,3})/, '$1.$2');
            }
        }
        input.dataset.valorLimpo = valor;
    },

    telefone: function(input) {
        let valor = Utils.apenasNumeros(input.value);
        if (valor.length > 9) valor = valor.substring(0, 9);

        if (valor.length > 4) {
            if (valor.length <= 8) {
                input.value = valor.replace(/(\d{4})(\d{0,4})/, '$1-$2');
            } else {
                input.value = valor.replace(/(\d{5})(\d{0,4})/, '$1-$2');
            }
        }
        input.dataset.valorLimpo = valor;
    },

    cep: function(input) {
        let valor = Utils.apenasNumeros(input.value);
        if (valor.length > 8) valor = valor.substring(0, 8);
        if (valor.length > 5) {
            input.value = valor.replace(/(\d{5})(\d{0,3})/, '$1-$2');
        }
    }
};

// ============================================
// ============================================
async function buscarCEP() {
    const cepInput = document.getElementById('id_codigo_postal');
    if (!cepInput) return;

    const cep = Utils.apenasNumeros(cepInput.value);
    if (cep.length !== 8) {
        Utils.mostrarFeedback('CEP deve ter 8 digitos.', 'warning');
        cepInput.focus();
        return;
    }

    const btnCep = document.getElementById('btn-buscar-cep');
    const originalHtml = btnCep?.innerHTML;
    if (btnCep) {
        btnCep.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        btnCep.disabled = true;
    }

    try {
        const response = await fetch(`/configuracoes/buscar-cep/?cep=${cep}`, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const contentType = (response.headers.get('content-type') || '').toLowerCase();
        const data = contentType.includes('application/json') ? await response.json() : {};

        if (!response.ok) {
            let mensagem = data.erro || data.error || 'Falha ao consultar CEP.';
            if (response.status === 400) mensagem = data.erro || 'CEP inválido.';
            if (response.status === 403) mensagem = 'Este perfil não possui permissão para buscar CEP.';
            if (response.status === 404) mensagem = data.erro || 'CEP não encontrado.';
            if (response.status === 502) mensagem = data.erro || 'Serviço de CEP indisponível no momento.';
            if (response.status >= 500) mensagem = data.erro || 'Erro interno ao consultar CEP.';
            throw new Error(mensagem);
        }

        if (data.erro || data.error) {
            throw new Error(data.erro || data.error);
        }

        if (data.logradouro) document.getElementById('id_logradouro').value = data.logradouro;
        if (data.bairro) document.getElementById('id_bairro').value = data.bairro;
        if (data.cidade) document.getElementById('id_cidade').value = data.cidade;
        if (data.complemento) document.getElementById('id_complemento').value = data.complemento;
        if (data.estado) {
            const estado = document.getElementById('id_estado');
            if (estado) estado.value = data.estado.toUpperCase();
        }

        cepInput.classList.add('is-valid');
        cepInput.classList.remove('is-invalid');

        setTimeout(() => {
            document.getElementById('id_numero')?.focus();
        }, 100);

    } catch (error) {
        Utils.mostrarFeedback(error?.message || 'Erro ao buscar CEP.', 'danger');
        cepInput.classList.add('is-invalid');
        cepInput.classList.remove('is-valid');
    } finally {
        if (btnCep) {
            btnCep.innerHTML = originalHtml;
            btnCep.disabled = false;
        }
    }
}

// ============================================
// TELEFONE COMPLETO
// ============================================
function atualizarTelefoneCompleto() {
    const ddd = document.getElementById('id_ddd')?.value || '';
    const telefone = document.getElementById('id_telefone_numero');
    if (!telefone) return;

    const numero = telefone.dataset.valorLimpo || Utils.apenasNumeros(telefone.value);

    if (ddd && numero && (numero.length === 8 || numero.length === 9)) {
        const completo = ddd + numero;

        // Criar campo oculto
        let hidden = document.getElementById('telefone_completo');
        if (!hidden) {
            hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = 'telefone_completo';
            hidden.id = 'telefone_completo';
            telefone.parentNode.appendChild(hidden);
        }
        hidden.value = completo;

        // Mostrar display
        const display = document.getElementById('telefone-display');
        const formatado = document.getElementById('telefone-formatado');
        const whatsapp = document.getElementById('whatsapp-link');

        if (display && formatado && whatsapp) {
            let numFormat = numero;
            if (numero.length === 8) numFormat = numero.replace(/(\d{4})(\d{4})/, '$1-$2');
            else numFormat = numero.replace(/(\d{5})(\d{4})/, '$1-$2');

            formatado.textContent = `(${ddd}) ${numFormat}`;
            whatsapp.innerHTML = `<a href="https://wa.me/55${completo}" target="_blank">wa.me/55${completo}</a>`;
            display.style.display = 'block';
        }

        telefone.classList.add('is-valid');
        telefone.classList.remove('is-invalid');
    }
}

// ============================================
// LIMPEZA COMPLETA
// ============================================

function executarLimpeza() {
    const form = document.getElementById('clienteForm');
    if (!form) return false;


    form.reset();

    const campos = [
        'id_nome', 'id_documento', 'id_telefone_numero', 'id_codigo_postal',
        'id_email', 'id_logradouro', 'id_numero', 'id_complemento',
        'id_bairro', 'id_cidade', 'id_observacoes'
    ];

    campos.forEach(id => {
        const campo = document.getElementById(id);
        if (campo) {
            campo.value = '';
            campo.classList.remove('is-valid', 'is-invalid');
            delete campo.dataset.valorLimpo;
        }
    });



    const estado = document.getElementById('id_estado');
    if (estado) estado.selectedIndex = 0;

    // Limpar campo oculto
    const hidden = document.getElementById('telefone_completo');
    if (hidden) hidden.value = '';

    // Esconder display
    const display = document.getElementById('telefone-display');
    if (display) display.style.display = 'none';

    Utils.limparMensagens();
    document.querySelectorAll('.invalid-feedback, .valid-feedback').forEach(el => el.remove());
    document.querySelectorAll('.text-danger').forEach(el => el.remove());

    return true;
}

function limparFormularioManual() {
    if (window._isPageLoading) {
        window._isPageLoading = false;
        return false;
    }

    if (!window.AppMessages.confirmSync('Tem certeza que deseja limpar todos os campos?')) return false;

    const resultado = executarLimpeza();
    if (resultado) {
        Utils.mostrarFeedback('Formulário limpo!');
        document.getElementById('id_nome')?.focus();
    }
    return resultado;
}

function limparFormularioSilencioso() {
    return executarLimpeza();
}

// ============================================
// ============================================
document.addEventListener('DOMContentLoaded', function() {


    // DETECTAR F5/REFRESH
    const perfData = window.performance?.getEntriesByType?.('navigation')?.[0];
    const isReload = perfData && perfData.type === 'reload';

    if (isReload) {
        setTimeout(() => {
            executarLimpeza();
            window._isPageLoading = false;
        }, 50);
    } else {
        setTimeout(() => {
            // Verificar se veio de uma busca
            const veioDaBusca = document.querySelector('input[name="cpf_telefone_busca"]')?.value;
            const temMensagemErro = document.querySelector('.alert-danger') !== null;
            const temMensagemSucesso = document.querySelector('.alert-success') !== null;

            if (!veioDaBusca && !temMensagemErro && !temMensagemSucesso) {
                window._isAutoClean = true;
                limparFormularioSilencioso();
                window._isAutoClean = false;
            }

            window._isPageLoading = false;
        }, 200);
    }

    // ===== DOCUMENTO =====
    const docInput = document.getElementById('id_documento');
    if (docInput) {
        docInput.addEventListener('input', e => Formatadores.documento(e.target));
        docInput.addEventListener('paste', e => {
            e.preventDefault();
            const pasted = (e.clipboardData || window.clipboardData).getData('text');
            const cleaned = Utils.apenasNumeros(pasted).substring(0, 14);
            e.target.value = cleaned;
            Formatadores.documento(e.target);
        });
    }

    // ===== TELEFONE =====
    const telInput = document.getElementById('id_telefone_numero');
    const dddSelect = document.getElementById('id_ddd');
    if (telInput && dddSelect) {
        telInput.addEventListener('input', e => {
            Formatadores.telefone(e.target);
            atualizarTelefoneCompleto();
        });
        dddSelect.addEventListener('change', atualizarTelefoneCompleto);
    }

    // ===== CEP =====
    const cepInput = document.getElementById('id_codigo_postal');
    const btnCep = document.getElementById('btn-buscar-cep');

    if (cepInput) {
        cepInput.addEventListener('input', e => Formatadores.cep(e.target));
        cepInput.addEventListener('blur', function() {
            const cepLimpo = Utils.apenasNumeros(this.value);
            if (cepLimpo.length === 8) {
                buscarCEP();
            }
        });
        cepInput.addEventListener('keypress', e => {
            if (e.key === 'Enter') {
                e.preventDefault();
                buscarCEP();
            }
        });
    }

    if (btnCep) {
        btnCep.addEventListener('click', e => {
            e.preventDefault();
            buscarCEP();
        });
    }

    const btnLimpar = document.getElementById('btn-limpar-formulario');
    if (btnLimpar) {
        btnLimpar.addEventListener('click', e => {
            e.preventDefault();
        });
    }

    // ===== SUBMIT =====
    const form = document.getElementById('clienteForm');
    if (form) {
        form.addEventListener('submit', function(e) {
            const doc = document.getElementById('id_documento');
            if (doc?.dataset.valorLimpo) doc.value = doc.dataset.valorLimpo;

            const cep = document.getElementById('id_codigo_postal');
            if (cep) cep.value = Utils.apenasNumeros(cep.value);

            atualizarTelefoneCompleto();
        });
    }

    // ===== AUTOCOMPLETE =====
    ['id_documento', 'id_telefone_numero', 'id_codigo_postal'].forEach(id => {
        const campo = document.getElementById(id);
        if (campo) campo.setAttribute('autocomplete', 'off');
    });

});

// ============================================
// ============================================
window.debugSistema = function() {
    console.log('\n=== DEBUG SISTEMA ===');
};

window.testarCEP = function(cep = '01001000') {
    const input = document.getElementById('id_codigo_postal');
    if (input) {
        input.value = cep;
        buscarCEP();
    }
};



