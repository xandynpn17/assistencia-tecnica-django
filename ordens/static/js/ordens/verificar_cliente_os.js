// ============================================
// SISTEMA DE CADASTRO DE CLIENTE - COMPLETO
// ============================================

window._isPageLoading = true;

console.log('🚀 Sistema de cadastro carregado');

// ============================================
// CONFIGURAÇÕES
// ============================================
const CONFIG = {
    DDD_PADRAO: '11',
    DEBUG: true
};

// ============================================
// UTILITÁRIOS
// ============================================
const Utils = {
    log: function(...args) {
        if (CONFIG.DEBUG) console.log('📝', ...args);
    },

    apenasNumeros: function(str) {
        return str ? str.replace(/\D/g, '') : '';
    },

    mostrarFeedback: function(mensagem, tipo = 'success') {
        const feedback = document.createElement('div');
        feedback.className = `alert alert-${tipo} alert-dismissible fade show`;
        feedback.style.cssText = `
            position: fixed; top: 20px; right: 20px; z-index: 9999;
            min-width: 300px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        `;
        feedback.innerHTML = `
            <i class="fas fa-${tipo === 'success' ? 'check' : 'info'}-circle mr-2"></i>
            ${mensagem}
            <button type="button" class="close" data-dismiss="alert">&times;</button>
        `;
        document.body.appendChild(feedback);
        setTimeout(() => feedback.remove(), 3000);
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
// FUNÇÃO CEP
// ============================================
async function buscarCEP() {
    const cepInput = document.getElementById('id_codigo_postal');
    if (!cepInput) return;

    const cep = Utils.apenasNumeros(cepInput.value);
    if (cep.length !== 8) {
        alert('CEP deve ter 8 dígitos!');
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
        const response = await fetch(`/configuracoes/buscar-cep/?cep=${cep}`);
        const data = await response.json();

        if (data.erro || data.error) {
            alert('CEP não encontrado!');
            return;
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
        alert('Erro ao buscar CEP');
        cepInput.classList.add('is-invalid');
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
// Função para obter o DDD padrão das configurações

// Função principal de limpeza (sem mensagens)
function executarLimpeza() {
    const form = document.getElementById('clienteForm');
    if (!form) return false;

    console.log('🧹 Executando limpeza do formulário...');

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

    // Limpar TODAS as mensagens e validações
    document.querySelectorAll('.alert').forEach(el => el.remove());
    document.querySelectorAll('.invalid-feedback, .valid-feedback').forEach(el => el.remove());
    document.querySelectorAll('.text-danger').forEach(el => el.remove());

    return true;
}

// Função para limpeza MANUAL (com confirmação) - chamada pelo botão
function limparFormularioManual() {
    if (window._isPageLoading) {
        window._isPageLoading = false;
        return false;
    }

    if (!confirm('Tem certeza que deseja limpar todos os campos?')) return false;

    const resultado = executarLimpeza();
    if (resultado) {
        Utils.mostrarFeedback('✅ Formulário limpo!');
        document.getElementById('id_nome')?.focus();
    }
    return resultado;
}

// Função para limpeza SILENCIOSA (sem confirmação) - para uso automático
function limparFormularioSilencioso() {
    return executarLimpeza();
}

// ============================================
// INICIALIZAÇÃO
// ============================================
document.addEventListener('DOMContentLoaded', function() {
    console.log('✅ Inicializando sistema...');


    // DETECTAR F5/REFRESH
    const perfData = window.performance?.getEntriesByType?.('navigation')?.[0];
    const isReload = perfData && perfData.type === 'reload';

    if (isReload) {
        console.log('🔄 F5 detectado - limpando tudo');
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

            // Se NÃO veio da busca, limpar
            if (!veioDaBusca && !temMensagemErro && !temMensagemSucesso) {
                console.log('🔄 Limpando formulário no carregamento');
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
                console.log('🔍 Buscando CEP ao sair do campo');
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

    // ===== BOTÃO LIMPAR =====
    const btnLimpar = document.getElementById('btn-limpar-formulario');
    if (btnLimpar) {
        btnLimpar.addEventListener('click', e => {
            e.preventDefault();
            limparFormularioManual();  // ← MUDANÇA IMPORTANTE: agora chama limparFormularioManual()
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

    console.log('✅ Sistema pronto!');
});

// ============================================
// FUNÇÕES DE DEBUG
// ============================================
window.debugSistema = function() {
    console.log('\n=== DEBUG SISTEMA ===');
    console.log('📋 Form:', document.getElementById('clienteForm') ? '✅' : '❌');
    console.log('🧹 Botão Limpar:', document.getElementById('btn-limpar-formulario') ? '✅' : '❌');
    console.log('📍 Botão CEP:', document.getElementById('btn-buscar-cep') ? '✅' : '❌');
    console.log('📞 Telefone:', document.getElementById('id_telefone_numero')?.value || 'vazio');
    console.log('📮 CEP:', document.getElementById('id_codigo_postal')?.value || 'vazio');
};

window.testarCEP = function(cep = '01001000') {
    const input = document.getElementById('id_codigo_postal');
    if (input) {
        input.value = cep;
        buscarCEP();
    }
};

console.log('✅ Sistema 100% carregado!');
console.log('📝 Comandos: debugSistema(), testarCEP()');
