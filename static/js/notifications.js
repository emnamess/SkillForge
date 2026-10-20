/* SkillForge — cloche de notifications et messagerie */
(function () {
    "use strict";

    const INTERVALLE_COMPTEURS = 30000;
    const INTERVALLE_MESSAGES = 5000;

    function majPastille(element, valeur) {
        if (!element) return;
        element.textContent = valeur > 99 ? "99+" : valeur;
        element.hidden = valeur === 0;
    }

    // ---------- Cloche ----------
    const cloche = document.querySelector("[data-cloche]");
    if (cloche) {
        const bouton = cloche.querySelector("[data-cloche-bouton]");
        const menu = cloche.querySelector("[data-cloche-menu]");

        function fermer() {
            menu.hidden = true;
            bouton.setAttribute("aria-expanded", "false");
        }

        bouton.addEventListener("click", function (e) {
            e.stopPropagation();
            menu.hidden = !menu.hidden;
            bouton.setAttribute("aria-expanded", String(!menu.hidden));
        });
        document.addEventListener("click", function (e) {
            if (!cloche.contains(e.target)) fermer();
        });
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") fermer();
        });

        // Actualisation périodique des compteurs
        setInterval(function () {
            if (document.hidden) return;
            fetch(cloche.dataset.api, { headers: { "Accept": "application/json" } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    if (!data) return;
                    majPastille(document.querySelector("[data-compteur-notifications]"), data.notifications);
                    majPastille(document.querySelector("[data-compteur-messages]"), data.messages);
                })
                .catch(function () {});
        }, INTERVALLE_COMPTEURS);
    }

    // ---------- Conversation ----------
    const discussion = document.querySelector("[data-discussion]");
    if (discussion) {
        const defilerEnBas = function () { discussion.scrollTop = discussion.scrollHeight; };
        defilerEnBas();

        function creerBulle(m) {
            const ligne = document.createElement("div");
            ligne.className = "bulle-ligne" + (m.moi ? " moi" : "");

            const avatar = document.createElement("span");
            avatar.className = "avatar avatar-sm";
            avatar.textContent = m.initiales;

            const bloc = document.createElement("div");
            const meta = document.createElement("small");
            meta.className = "bulle-meta";
            meta.textContent = m.auteur + " " + m.heure;
            const bulle = document.createElement("div");
            bulle.className = "bulle";
            bulle.textContent = m.contenu;  // textContent : pas d'injection HTML

            bloc.append(meta, bulle);
            ligne.append(avatar, bloc);
            return ligne;
        }

        setInterval(function () {
            if (document.hidden) return;
            const url = discussion.dataset.api + "?apres=" + discussion.dataset.dernier;
            fetch(url, { headers: { "Accept": "application/json" } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    if (!data || !data.messages.length) return;
                    const enBas = discussion.scrollHeight - discussion.scrollTop - discussion.clientHeight < 80;
                    data.messages.forEach(function (m) {
                        discussion.appendChild(creerBulle(m));
                        discussion.dataset.dernier = m.id;
                    });
                    if (enBas) defilerEnBas();
                })
                .catch(function () {});
        }, INTERVALLE_MESSAGES);
    }

    // ---------- Zone de saisie ----------
    const saisie = document.querySelector("[data-saisie]");
    if (saisie) {
        const zone = saisie.querySelector("textarea");
        const ajuster = function () {
            zone.style.height = "auto";
            zone.style.height = Math.min(zone.scrollHeight, 160) + "px";
        };
        zone.addEventListener("input", ajuster);
        // Entrée envoie, Maj+Entrée va à la ligne
        zone.addEventListener("keydown", function (e) {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (zone.value.trim()) saisie.requestSubmit();
            }
        });
        zone.focus();
    }
})();
