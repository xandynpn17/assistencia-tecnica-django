/**
 * SISTEMA DE CADASTRO DE CLIENTE - VERSÃO PROFISSIONAL COMPLETA
 * @author Desenvolvedor
 * @version 3.0.0
 *
 * Funcionalidades:
 * ✅ CPF/CNPJ com formatação automática
 * ✅ Telefone com DDD e formatação
 * ✅ Busca de CEP com Tab, Enter e botão
 * ✅ Botão limpar funcionando
 * ✅ Limpeza ao recarregar página (F5)
 * ✅ Feedback visual com validações
 * ✅ Display do telefone com link WhatsApp
 */

// ============================================
// NAMESPACE ÚNICO - EVITA CONFLITOS
// ============================================
const CadastroCliente = (function() {
    'use strict';

    // ============================================
    // CONFIGURAÇÕES
    // ============================================
    const CONFIG = {
        DEBUG: true,
        TIMEOUTS: {
            INIT: 100,
            LIMPEZA: 150,
            CEP_BLUR: 200,
            FOCUS: 300,
            TAB: 50
        },
        DDD_PADRAO: '11',
        ESTADO_PADRAO: 'SP'
    };

    // ============================================
    // UTILITÁRIOS
    // ============================================
    const Utils = {
        log: function(...args) {
            if (CONFIG.DEBUG) {
                console.log('🏷️ [Cadastro]', ...args);
            }
        },

        error: function(...args) {
            console.error('❌ [Erro]', ...args);
        },

        apenasNumeros: function(str) {
            return str ? str.replace(/\D/g, '') : '';
        },

        delay: function(ms) {
            return new Promise(resolve => setTimeout(resolve, ms));
        },

        mostrarFeedback: function(mensagem, tipo = 'success') {
            const anterior = document.getElementById('feedback-rapido');
            if (anterior) anterior.remove();

            const feedback = document.createElement('div');
            feedback.id = 'feedback-rapido';
            feedback.className = `alert alert-${tipo} alert-dismissible fade show`;
            feedback.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 9999;
                min-width: 300px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                animation: slideIn 0.3s ease;
            `;
            feedback.innerHTML = `
                <i class="fas fa-${tipo === 'success' ? 'check' : 'info'}-circle mr-2"></i>
                ${mensagem}
                <button type="button" class="close" data-dismiss="alert">
                    <span>&times;</span>
                </button>
            `;

            document.body.appendChild(feedback);
            setTimeout(() => feedback.remove(), 3000);
        },

        focarPrimeiroCampo: function() {
            setTimeout(() => {
                const primeiroCampo = document.getElementById('id_nome');
                if (primeiroCampo) {
                    primeiroCampo.focus();
                    Utils.log('✅ Foco no campo nome');
                }
            }, 100);
        },

        limparValidacoesVisuais: function() {
            document.querySelectorAll('.is-valid, .is-invalid').forEach(el => {
                el.classList.remove('is-valid', 'is-invalid');
            });
            document.querySelectorAll('.invalid-feedback, .valid-feedback').forEach(el => {
                el.remove();
            });
        }
    };

    // ============================================
    // FORMATADORES
    // ============================================
    const Formatadores = {
        documento: function(input) {
            if (!input) return '';

            let valor = Utils.apenasNumeros(input.value);

            // Determina se é CPF (11) ou CNPJ (14)
            const maxDigits = valor.length > 11 ? 14 : 11;

            if (valor.length > maxDigits) {
                valor = valor.substring(0, maxDigits);
            }

            let formatado = valor;

            if (maxDigits === 11) { // CPF
                if (valor.length > 9) {
                    formatado = valor.replace(/(\d{3})(\d{3})(\d{3})(\d{0,2})/, '$1.$2.$3-$4');
                } else if (valor.length > 6) {
                    formatado = valor.replace(/(\d{3})(\d{3})(\d{0,3})/, '$1.$2.$3');
                } else if (valor.length > 3) {
                    formatado = valor.replace(/(\d{3})(\d{0,3})/, '$1.$2');
                }
            } else { // CNPJ
                if (valor.length > 12) {
                    formatado = valor.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{0,2})/, '$1.$2.$3/$4-$5');
                } else if (valor.length > 8) {
                    formatado = valor.replace(/(\d{2})(\d{3})(\d{3})(\d{0,4})/, '$1.$2.$3/$4');
                } else if (valor.length > 5) {
                    formatado = valor.replace(/(\d{2})(\d{3})(\d{0,3})/, '$1.$2.$3');
                } else if (valor.length > 2) {
                    formatado = valor.replace(/(\d{2})(\d{0,3})/, '$1.$2');
                }
            }

            input.value = formatado;
            input.dataset.valorLimpo = valor;
            return valor;
        },

        telefone: function(input) {
            if (!input) return '';

            let valor = Utils.apenasNumeros(input.value);

            if (valor.length > 9) {
                valor = valor.substring(0, 9);
            }

            let formatado = valor;
            if (valor.length > 4) {
                if (valor.length <= 8) {
                    formatado = valor.replace(/(\d{4})(\d{0,4})/, '$1-$2');
                } else {
                    formatado = valor.replace(/(\d{5})(\d{0,4})/, '$1-$2');
                }
            }

            input.value = formatado;
            input.dataset.valorLimpo = valor;
            return valor;
        },

        cep: function(input) {
            if (!input) return '';

            let valor = Utils.apenasNumeros(input.value);

            if (valor.length > 8) {
                valor = valor.substring(0, 8);
            }

            let formatado = valor;
            if (valor.length > 5) {
                formatado = valor.replace(/(\d{5})(\d{0,3})/, '$1-$2');
            }

            input.value = formatado;
            return valor;
        },

        validarCEPEmTempoReal: function(input) {
            const cepLimpo = Utils.apenasNumeros(input.value);

            // Remover mensagens temporárias
            const tempFeedback = input.parentNode.querySelector('.cep-temp-feedback');
            if (tempFeedback) tempFeedback.remove();

            if (cepLimpo.length === 0) {
                input.classList.remove('is-valid', 'is-invalid');
            } else if (cepLimpo.length === 8) {
                input.classList.remove('is-invalid');
                input.classList.add('is-valid');
            } else {
                input.classList.add('is-invalid');
                input.classList.remove('is-valid');

                if (cepLimpo.length > 0) {
                    const feedback = document.createElement('div');
                    feedback.className = 'invalid-feedback d-block cep-temp-feedback';

                    if (cepLimpo.length < 8) {
                        feedback.textContent = `Faltam ${8 - cepLimpo.length} dígitos!`;
                        feedback.style.color = '#ffc107';
                    } else {
                        feedback.textContent = 'CEP deve ter no máximo 8 dígitos!';
                    }

                    input.parentNode.appendChild(feedback);
                }
            }
        }
    };

    // ============================================
    // SERVIÇO DE CEP
    // ============================================
    const CepService = {
        tabPressed: false,

        async buscar(cep) {
            Utils.log('🔍 Buscando CEP:', cep);

            try {
                const response = await fetch(`/configuracoes/buscar-cep/?cep=${cep}`);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                Utils.log('📦 Resposta CEP:', data);

                return data;
            } catch (error) {
                Utils.error('Erro ao buscar CEP:', error);
                throw error;
            }
        },

        preencherCampos(data) {
            const campos = {
                'id_logradouro': data.logradouro,
                'id_bairro': data.bairro,
                'id_cidade': data.cidade,
                'id_complemento': data.complemento
            };

            Object.entries(campos).forEach(([id, valor]) => {
                if (valor) {
                    const campo = document.getElementById(id);
                    if (campo) {
                        campo.value = valor;
                        campo.classList.add('is-valid');
                        Utils.log(`✅ ${id} preenchido:`, valor);
                    }
                }
            });

            if (data.estado) {
                const estadoSelect = document.getElementById('id_estado');
                if (estadoSelect) {
                    const estadoUpper = data.estado.toUpperCase();
                    Array.from(estadoSelect.options).forEach(option => {
                        if (option.value === estadoUpper) {
                            estadoSelect.value = estadoUpper;
                            estadoSelect.classList.add('is-valid');
                            Utils.log('✅ Estado selecionado:', estadoUpper);
                        }
                    });
                }
            }
        },

        limparCampos() {
            ['id_logradouro', 'id_bairro', 'id_cidade', 'id_complemento'].forEach(id => {
                const campo = document.getElementById(id);
                if (campo) {
                    campo.value = '';
                    campo.classList.remove('is-valid');
                }
            });

            const estadoSelect = document.getElementById('id_estado');
            if (estadoSelect) {
                estadoSelect.value = '';
                estadoSelect.classList.remove('is-valid');
            }

            Utils.log('🧹 Campos de endereço limpos');
        }
    };

    // ============================================
    // MANIPULADORES DE EVENTOS
    // ============================================
    const Handlers = {
        // ========== DOCUMENTO ==========
        documento: {
            configurarEventos() {
                const input = document.getElementById('id_documento');
                if (!input) return;

                // Formatação ao digitar
                input.addEventListener('input', (e) => {
                    Formatadores.documento(e.target);
                });

                // Colagem
                input.addEventListener('paste', (e) => {
                    e.preventDefault();
                    const pasted = (e.clipboardData || window.clipboardData).getData('text');
                    const cleaned = Utils.apenasNumeros(pasted).substring(0, 14);
                    e.target.value = cleaned;
                    Formatadores.documento(e.target);
                });

                // Formatar valor existente
                if (input.value) {
                    Formatadores.documento(input);
                }

                // Preencher da busca
                const termoBusca = document.querySelector('input[name="cpf_telefone_busca"]')?.value || '';
                if (termoBusca && !input.value) {
                    const termoLimpo = Utils.apenasNumeros(termoBusca);
                    if (termoLimpo.length === 11 || termoLimpo.length === 14) {
                        input.value = termoLimpo;
                        Formatadores.documento(input);
                    }
                }

                Utils.log('✅ Documento configurado');
            }
        },

        // ========== TELEFONE ==========
        telefone: {
            atualizarCompleto() {
                const dddSelect = document.getElementById('id_ddd');
                const telefoneInput = document.getElementById('id_telefone_numero');
                let telefoneCompletoInput = document.getElementById('telefone_completo');

                if (!dddSelect || !telefoneInput) return;

                // Criar campo oculto se não existir
                if (!telefoneCompletoInput) {
                    telefoneCompletoInput = document.createElement('input');
                    telefoneCompletoInput.type = 'hidden';
                    telefoneCompletoInput.name = 'telefone_completo';
                    telefoneCompletoInput.id = 'telefone_completo';
                    telefoneInput.parentNode.appendChild(telefoneCompletoInput);
                    Utils.log('➕ Campo oculto telefone_completo criado');
                }

                const ddd = dddSelect.value || '';
                const numero = telefoneInput.dataset.valorLimpo || Utils.apenasNumeros(telefoneInput.value);

                if (ddd && numero && (numero.length === 8 || numero.length === 9)) {
                    const telefoneCompleto = ddd + numero;
                    telefoneCompletoInput.value = telefoneCompleto;
                    Utils.log('📱 Telefone completo:', telefoneCompleto);

                    this.mostrarDisplay(ddd, numero);

                    telefoneInput.classList.add('is-valid');
                    telefoneInput.classList.remove('is-invalid');
                } else {
                    telefoneCompletoInput.value = '';
                    this.ocultarDisplay();

                    if (numero && numero.length > 0) {
                        telefoneInput.classList.add('is-invalid');
                        telefoneInput.classList.remove('is-valid');
                    } else {
                        telefoneInput.classList.remove('is-valid', 'is-invalid');
                    }
                }
            },

            mostrarDisplay(ddd, numero) {
                const display = document.getElementById('telefone-display');
                const formatado = document.getElementById('telefone-formatado');
                const whatsapp = document.getElementById('whatsapp-link');

                if (!display || !formatado || !whatsapp) return;

                let numeroFormatado = numero;
                if (numero.length === 8) {
                    numeroFormatado = numero.replace(/(\d{4})(\d{4})/, '$1-$2');
                } else if (numero.length === 9) {
                    numeroFormatado = numero.replace(/(\d{5})(\d{4})/, '$1-$2');
                }

                formatado.textContent = `(${ddd}) ${numeroFormatado}`;

                const whatsappNumero = '55' + ddd + numero;
                whatsapp.innerHTML = `<a href="https://wa.me/${whatsappNumero}" target="_blank" class="text-success">wa.me/${whatsappNumero}</a>`;

                display.style.display = 'block';
                Utils.log('📞 Display telefone atualizado');
            },

            ocultarDisplay() {
                const display = document.getElementById('telefone-display');
                if (display) {
                    display.style.display = 'none';
                }
            },

            configurarEventos() {
                const telefoneInput = document.getElementById('id_telefone_numero');
                const dddSelect = document.getElementById('id_ddd');

                if (!telefoneInput || !dddSelect) return;

                // Formatação ao digitar
                telefoneInput.addEventListener('input', (e) => {
                    Formatadores.telefone(e.target);
                    this.atualizarCompleto();
                });

                // DDD mudou
                dddSelect.addEventListener('change', () => {
                    Utils.log('🔄 DDD alterado:', dddSelect.value);
                    this.atualizarCompleto();
                });

                // Formatar valor existente
                if (telefoneInput.value) {
                    Formatadores.telefone(telefoneInput);
                    this.atualizarCompleto();
                }

                // Preencher da busca
                const termoBusca = document.querySelector('input[name="cpf_telefone_busca"]')?.value || '';
                if (termoBusca && (!telefoneInput.value || Utils.apenasNumeros(telefoneInput.value).length < 8)) {
                    const termoLimpo = Utils.apenasNumeros(termoBusca);

                    if (termoLimpo.length === 9) {
                        const dddPadrao = document.querySelector('meta[name="ddd-padrao"]')?.content || CONFIG.DDD_PADRAO;
                        dddSelect.value = dddPadrao;
                        telefoneInput.value = termoLimpo;
                        Formatadores.telefone(telefoneInput);
                        this.atualizarCompleto();
                    } else if (termoLimpo.length === 10 || termoLimpo.length === 11) {
                        const ddd = termoLimpo.substring(0, 2);
                        const numero = termoLimpo.substring(2);

                        Array.from(dddSelect.options).some(option => {
                            if (option.value === ddd) {
                                dddSelect.value = ddd;
                                return true;
                            }
                            return false;
                        });

                        telefoneInput.value = numero;
                        Formatadores.telefone(telefoneInput);
                        this.atualizarCompleto();
                    }
                }

                Utils.log('✅ Telefone configurado');
            }
        },

        // ========== CEP ==========
        cep: {
            async buscar() {
                const cepInput = document.getElementById('id_codigo_postal');
                if (!cepInput) {
                    Utils.error('Campo CEP não encontrado');
                    return;
                }

                const cep = Utils.apenasNumeros(cepInput.value);

                if (cep.length !== 8) {
                    Handlers.cep.mostrarErro('CEP deve ter 8 dígitos!');
                    cepInput.focus();
                    cepInput.select();
                    return;
                }

                // Limpar validações anteriores
                cepInput.classList.remove('is-valid', 'is-invalid');

                // Loading state no botão
                const btnCep = document.getElementById('btn-buscar-cep');
                const originalHtml = btnCep?.innerHTML || '';
                if (btnCep) {
                    btnCep.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
                    btnCep.disabled = true;
                }

                try {
                    const data = await CepService.buscar(cep);

                    if (data.erro || data.error) {
                        Handlers.cep.mostrarErro('CEP não encontrado!');
                        CepService.limparCampos();
                    } else {
                        Handlers.cep.mostrarSucesso();
                        CepService.preencherCampos(data);

                        setTimeout(() => {
                            const numeroInput = document.getElementById('id_numero');
                            if (numeroInput) numeroInput.focus();
                        }, 100);
                    }
                } catch (error) {
                    Handlers.cep.mostrarErro('Erro na conexão. Tente novamente.');
                    CepService.limparCampos();
                } finally {
                    if (btnCep) {
                        btnCep.innerHTML = originalHtml;
                        btnCep.disabled = false;
                    }
                }
            },

            mostrarErro(mensagem) {
                const cepInput = document.getElementById('id_codigo_postal');
                if (!cepInput) return;

                cepInput.classList.add('is-invalid');
                cepInput.classList.remove('is-valid');

                let feedback = cepInput.parentNode.querySelector('.cep-error-feedback');
                if (!feedback) {
                    feedback = document.createElement('div');
                    feedback.className = 'invalid-feedback d-block cep-error-feedback';
                    cepInput.parentNode.appendChild(feedback);
                }
                feedback.textContent = mensagem;
            },

            mostrarSucesso() {
                const cepInput = document.getElementById('id_codigo_postal');
                if (!cepInput) return;

                cepInput.classList.add('is-valid');
                cepInput.classList.remove('is-invalid');

                const errorFeedback = cepInput.parentNode.querySelector('.cep-error-feedback');
                if (errorFeedback) errorFeedback.remove();
            },

            configurarEventos() {
                Utils.log('⚙️ Configurando eventos do CEP...');

                const cepInput = document.getElementById('id_codigo_postal');
                const btnCep = document.getElementById('btn-buscar-cep');

                if (!cepInput) {
                    Utils.error('Campo CEP não encontrado');
                    return;
                }

                // Input com formatação e validação em tempo real
                cepInput.addEventListener('input', (e) => {
                    Formatadores.cep(e.target);
                    Formatadores.validarCEPEmTempoReal(e.target);
                });

                // Evento Tab
                let tabPressed = false;
                cepInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Tab') {
                        tabPressed = true;
                    }
                });

                cepInput.addEventListener('blur', (e) => {
                    const cepLimpo = Utils.apenasNumeros(e.target.value);

                    if (cepLimpo.length > 0 && cepLimpo.length < 8) {
                        Handlers.cep.mostrarErro(`CEP incompleto! Faltam ${8 - cepLimpo.length} dígitos.`);
                        return;
                    }

                    if (cepLimpo.length === 8) {
                        if (tabPressed) {
                            tabPressed = false;
                            setTimeout(() => this.buscar(), CONFIG.TIMEOUTS.TAB);
                        } else {
                            setTimeout(() => this.buscar(), CONFIG.TIMEOUTS.CEP_BLUR);
                        }
                    }
                });

                // Enter
                cepInput.addEventListener('keypress', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        this.buscar();
                    }
                });

                // Botão buscar
                if (btnCep) {
                    btnCep.addEventListener('click', (e) => {
                        e.preventDefault();
                        this.buscar();
                    });
                    Utils.log('✅ Botão CEP configurado');
                }

                // Atualizar texto de ajuda
                setTimeout(() => {
                    const helpText = cepInput.parentNode.querySelector('.form-text');
                    if (helpText) {
                        helpText.textContent = 'Digite o CEP e pressione Tab ou clique na lupa';
                    }
                }, 100);

                // Formatar e validar valor existente
                if (cepInput.value) {
                    Formatadores.cep(cepInput);
                    Formatadores.validarCEPEmTempoReal(cepInput);
                }

                Utils.log('✅ Eventos CEP configurados');
            }
        },

        // ========== BOTÃO LIMPAR ==========
        limpar: {
            executar() {
                Utils.log('🧹 Iniciando limpeza completa...');

                const form = document.getElementById('clienteForm');
                if (!form) {
                    Utils.error('❌ Formulário não encontrado');
                    return;
                }

                // 1. Reset do formulário
                form.reset();
                Utils.log('✅ Form.reset() executado');

                // 2. Limpar campos manualmente
                const campos = [
                    'id_nome', 'id_documento', 'id_telefone_numero',
                    'id_codigo_postal', 'id_email', 'id_logradouro',
                    'id_numero', 'id_complemento', 'id_bairro',
                    'id_cidade', 'id_observacoes'
                ];

                campos.forEach(id => {
                    const campo = document.getElementById(id);
                    if (campo) {
                        campo.value = '';
                        campo.classList.remove('is-valid', 'is-invalid');
                        delete campo.dataset.valorLimpo;
                    }
                });

                // 3. Limpar selects
                const dddSelect = document.getElementById('id_ddd');
                if (dddSelect) {
                    const dddPadrao = dddSelect.querySelector('option[value="11"]');
                    dddSelect.value = dddPadrao ? '11' : dddSelect.options[0]?.value || '';
                }

                const estadoSelect = document.getElementById('id_estado');
                if (estadoSelect) {
                    estadoSelect.selectedIndex = 0;
                }

                // 4. Limpar campo oculto do telefone
                const telCompleto = document.getElementById('telefone_completo');
                if (telCompleto) {
                    telCompleto.value = '';
                }

                // 5. Limpar display do telefone
                Handlers.telefone.ocultarDisplay();

                // 6. Limpar validações visuais
                Utils.limparValidacoesVisuais();

                // 7. Limpar feedback do CEP
                const cepError = document.querySelector('.cep-error-feedback');
                if (cepError) cepError.remove();

                // 8. Feedback visual
                Utils.mostrarFeedback('✅ Formulário limpo com sucesso!');

                // 9. Focar no primeiro campo
                Utils.focarPrimeiroCampo();

                Utils.log('🎉 Limpeza concluída!');
            },

            configurar() {
                Utils.log('🔧 Configurando botão limpar...');

                const btnLimpar = document.getElementById('btn-limpar-formulario');

                if (!btnLimpar) {
                    Utils.error('❌ Botão limpar não encontrado!');
                    Utils.log('Botões disponíveis:', document.querySelectorAll('button'));
                    return;
                }

                Utils.log('🎯 Botão limpar encontrado:', btnLimpar);

                // Remover listeners antigos (clone seguro)
                const novoBotao = btnLimpar.cloneNode(true);
                btnLimpar.parentNode.replaceChild(novoBotao, btnLimpar);

                // Adicionar novo listener
                novoBotao.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();

                    if (confirm('Tem certeza que deseja limpar todos os campos do formulário?')) {
                        this.executar();
                    }
                });

                Utils.log('✅ Botão limpar configurado com sucesso!');
            }
        },

        // ========== SUBMIT ==========
        submit: {
            preparar(e) {
                Utils.log('📤 Preparando envio do formulário...');

                // 1. Documento - remover formatação
                const docInput = document.getElementById('id_documento');
                if (docInput?.dataset.valorLimpo) {
                    docInput.value = docInput.dataset.valorLimpo;
                    Utils.log('📄 Documento limpo:', docInput.value);
                }

                // 2. CEP - remover formatação
                const cepInput = document.getElementById('id_codigo_postal');
                if (cepInput) {
                    cepInput.value = Utils.apenasNumeros(cepInput.value);
                    Utils.log('📍 CEP limpo:', cepInput.value);
                }

                // 3. Telefone - garantir campo oculto
                Handlers.telefone.atualizarCompleto();

                Utils.log('✅ Formulário pronto para envio');
                return true;
            },

            configurar() {
                const form = document.getElementById('clienteForm');
                if (!form) return;

                form.addEventListener('submit', (e) => this.preparar(e));
                Utils.log('✅ Handler de submit configurado');
            }
        },

        // ========== LIMPEZA AO RECARREGAR ==========
        refresh: {
            verificarELimpar() {
                const campos = ['id_nome', 'id_documento', 'id_telefone_numero', 'id_codigo_postal'];
                const temDados = campos.some(id => {
                    const campo = document.getElementById(id);
                    return campo && campo.value && campo.value.trim() !== '';
                });

                const temMensagens = document.querySelector('.alert-success, .alert-danger');
                const veioDaBusca = document.querySelector('input[name="cpf_telefone_busca"]')?.value;

                if (!temDados && !temMensagens && !veioDaBusca) {
                    Utils.log('🔄 Página recarregada - limpando formulário...');
                    Handlers.limpar.executar();
                } else if (veioDaBusca) {
                    Utils.log('🔍 Veio da busca, mantendo dados');
                } else {
                    Utils.log('📋 Formulário já tem dados, mantendo');
                }
            },

            configurar() {
                setTimeout(() => this.verificarELimpar(), 200);
            }
        },

        // ========== AUTOCOMPLETE ==========
        autocomplete: {
            configurar() {
                const fields = ['id_documento', 'id_telefone_numero', 'id_codigo_postal'];

                fields.forEach(id => {
                    const field = document.getElementById(id);
                    if (field) {
                        field.setAttribute('autocomplete', 'off');
                        field.setAttribute('autocapitalize', 'off');
                        field.setAttribute('autocorrect', 'off');
                        field.setAttribute('spellcheck', 'false');
                    }
                });

                Utils.log('✅ Autocomplete prevenido');
            }
        },

        // ========== FOCO ==========
        focus: {
            configurar() {
                // Campo de busca
                const campoBusca = document.getElementById('campoBusca');
                if (campoBusca && !campoBusca.value) {
                    setTimeout(() => campoBusca.focus(), CONFIG.TIMEOUTS.FOCUS);
                }

                // Primeiro campo do formulário
                const form = document.getElementById('clienteForm');
                if (form) {
                    const primeiroCampo = form.querySelector('input:not([type="hidden"]):not([readonly]), select, textarea');
                    if (primeiroCampo && !primeiroCampo.value) {
                        setTimeout(() => primeiroCampo.focus(), CONFIG.TIMEOUTS.FOCUS + 200);
                    }
                }

                Utils.log('✅ Gerenciamento de foco configurado');
            }
        }
    };

    // ============================================
    // INICIALIZAÇÃO
    // ============================================
    function init() {
        Utils.log('🚀 Inicializando sistema de cadastro...');

        // Verificar se é página de cadastro
        if (!document.getElementById('clienteForm') && !document.getElementById('campoBusca')) {
            Utils.log('⚠️ Não é página de cadastro');
            return;
        }

        // Aguardar DOM
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', iniciarModulos);
        } else {
            iniciarModulos();
        }
    }

    function iniciarModulos() {
        Utils.log('✅ Página de cadastro detectada');

        // Configurar módulos com delays estratégicos
        const timers = [
            { delay: 50, handler: () => Handlers.documento.configurarEventos() },
            { delay: 80, handler: () => Handlers.telefone.configurarEventos() },
            { delay: 100, handler: () => Handlers.cep.configurarEventos() },
            { delay: 120, handler: () => Handlers.autocomplete.configurar() },
            { delay: 140, handler: () => Handlers.submit.configurar() },
            { delay: 160, handler: () => Handlers.limpar.configurar() },
            { delay: 200, handler: () => Handlers.refresh.configurar() },
            { delay: 300, handler: () => Handlers.focus.configurar() }
        ];

        timers.forEach(timer => {
            setTimeout(timer.handler, timer.delay);
        });

        Utils.log('✅ Todos os módulos inicializados');
    }

    // ============================================
    // API PÚBLICA (para console)
    // ============================================
    return {
        init,

        // Debug completo
        debug: function() {
            console.log('\n=== 🔍 DEBUG COMPLETO DO SISTEMA ===\n');

            const elementos = {
                '📋 Formulário': document.getElementById('clienteForm'),
                '🧹 Botão Limpar': document.getElementById('btn-limpar-formulario'),
                '📍 Botão CEP': document.getElementById('btn-buscar-cep'),
                '👤 Campo Nome': document.getElementById('id_nome'),
                '🆔 Campo Documento': document.getElementById('id_documento'),
                '📞 Campo Telefone': document.getElementById('id_telefone_numero'),
                '📮 Campo CEP': document.getElementById('id_codigo_postal'),
                '🔍 Campo Busca': document.getElementById('campoBusca')
            };

            console.log('📌 ELEMENTOS ENCONTRADOS:');
            Object.entries(elementos).forEach(([nome, elem]) => {
                console.log(`   ${nome}: ${elem ? '✅' : '❌'} ${elem ? `(valor: "${elem.value}")` : ''}`);
            });

            console.log('\n📌 FUNÇÕES DISPONÍVEIS:');
            console.log('   📍 testarCEP() - Buscar CEP 01001000');
            console.log('   🧹 limpar() - Limpar formulário');
            console.log('   📞 verificarTelefone() - Ver estado do telefone');
            console.log('   🔄 forcarLimpeza() - Forçar limpeza');
            console.log('   🎯 testarBotao() - Disparar clique no botão limpar\n');
        },

        // Utilitários
        limpar: () => Handlers.limpar.executar(),
        forcarLimpeza: () => Handlers.limpar.executar(),

        testarCEP: function(cep = '01001000') {
            const cepInput = document.getElementById('id_codigo_postal');
            if (cepInput) {
                cepInput.value = cep;
                Formatadores.cep(cepInput);
                Handlers.cep.buscar();
            }
        },

        testarBotao: function() {
            const botao = document.getElementById('btn-limpar-formulario');
            if (botao) {
                Utils.log('🎯 Disparando clique no botão...');
                botao.click();
            }
        },

        verificarTelefone: function() {
            console.log('\n📞 ESTADO DO TELEFONE:');
            console.log('   DDD:', document.getElementById('id_ddd')?.value);
            console.log('   Número:', document.getElementById('id_telefone_numero')?.value);
            console.log('   Número limpo:', document.getElementById('id_telefone_numero')?.dataset.valorLimpo);
            console.log('   Telefone completo:', document.getElementById('telefone_completo')?.value);
            console.log('   Display:', document.getElementById('telefone-display')?.style.display);
        },

        verificarCEP: function() {
            const cepInput = document.getElementById('id_codigo_postal');
            console.log('\n📍 ESTADO DO CEP:');
            console.log('   Valor:', cepInput?.value);
            console.log('   Limpo:', Utils.apenasNumeros(cepInput?.value || ''));
            console.log('   Válido:', Utils.apenasNumeros(cepInput?.value || '').length === 8 ? '✅' : '❌');
        }
    };

})();

// ============================================
// INICIAR SISTEMA
// ============================================
// Expor global para console
window.CadastroCliente = CadastroCliente;
window.debugFormulario = () => CadastroCliente.debug();
window.forcarLimpeza = () => CadastroCliente.limpar();
window.testarCEP = (cep) => CadastroCliente.testarCEP(cep);
window.verificarTelefone = () => CadastroCliente.verificarTelefone();

console.log('✅ Sistema de cadastro profissional carregado!');