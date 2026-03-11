(function (window, document) {
    "use strict";

    function ensureContainer(target) {
        if (target && target.nodeType === 1) return target;
        if (typeof target === "string") {
            var el = document.querySelector(target);
            if (el) return el;
        }

        var container = document.getElementById("app-system-messages");
        if (container) return container;

        var contentRoot = document.querySelector(".content .container-fluid") || document.querySelector(".content-wrapper");
        container = document.createElement("div");
        container.id = "app-system-messages";
        container.className = "mb-3";
        if (contentRoot && contentRoot.firstChild) {
            contentRoot.insertBefore(container, contentRoot.firstChild);
        } else if (contentRoot) {
            contentRoot.appendChild(container);
        } else {
            document.body.prepend(container);
        }
        return container;
    }

    function iconFor(type) {
        if (type === "success") return "check-circle";
        if (type === "danger" || type === "error") return "exclamation-triangle";
        if (type === "warning") return "exclamation-circle";
        return "info-circle";
    }

    function normalizeType(type) {
        return type === "error" ? "danger" : (type || "info");
    }

    var AppMessages = {
        show: function (message, options) {
            var opts = options || {};
            var type = normalizeType(opts.type);
            var container = ensureContainer(opts.target);
            if (!container) return;

            var wrapper = document.createElement("div");
            wrapper.className = "alert alert-" + type + " alert-dismissible fade show";
            wrapper.setAttribute("role", "alert");
            wrapper.innerHTML =
                "<i class=\"fas fa-" + iconFor(type) + " mr-2\"></i>" +
                "<span class=\"app-message-text\"></span>" +
                "<button type=\"button\" class=\"close\" data-dismiss=\"alert\" aria-label=\"Fechar\">" +
                "<span aria-hidden=\"true\">&times;</span>" +
                "</button>";
            wrapper.querySelector(".app-message-text").textContent = String(message || "");

            if (opts.append) {
                container.appendChild(wrapper);
            } else {
                container.innerHTML = "";
                container.appendChild(wrapper);
            }

            if (opts.timeout && Number(opts.timeout) > 0) {
                window.setTimeout(function () {
                    if (wrapper && wrapper.parentNode) wrapper.parentNode.removeChild(wrapper);
                }, Number(opts.timeout));
            }
        },

        clear: function (target) {
            var container = ensureContainer(target);
            if (container) container.innerHTML = "";
        },

        confirmSync: function (message) {
            return window.confirm(String(message || "Confirmar esta acao?"));
        },

        confirm: function (message, options) {
            var opts = options || {};
            return Promise.resolve(this.confirmSync(message || opts.message || "Confirmar esta acao?"));
        },
    };

    window.AppMessages = AppMessages;
})(window, document);
