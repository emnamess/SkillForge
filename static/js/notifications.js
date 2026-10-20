/* SkillForge — notifications et messagerie en temps réel (WebSockets)
 *
 * Si le WebSocket n'est pas disponible, la page se rabat sur une actualisation
 * périodique (polling) et sur l'envoi classique du formulaire.
 */
(function () {
    "use strict";

    const INTERVALLE_COMPTEURS = 30000;
    const INTERVALLE_MESSAGES = 5000;
    const DELAI_ECRIT = 2000;

    // ---------- Outils ----------

    function cookie(nom) {
        const m = document.cookie.match("(^|;)\\s*" + nom + "=([^;]+)");
        return m ? decodeURIComponent(m[2]) : "";
    }

    function el(tag, classe, texte) {
        const e = document.createElement(tag);
        if (classe) e.className = classe;
        if (texte !== undefined) e.textContent = texte;  // textContent : jamais d'injection HTML
        return e;
    }

    function tailleLisible(octets) {
        if (octets < 1024) return octets + " octets";
        if (octets < 1024 * 1024) return (octets / 1024).toFixed(1).replace(".", ",") + " Ko";
        return (octets / 1024 / 1024).toFixed(1).replace(".", ",") + " Mo";
    }

    function majPastille(element, valeur) {
        if (!element) return;
        element.textContent = valeur > 99 ? "99+" : valeur;
        element.hidden = valeur === 0;
    }

    function majCompteurs(c) {
        if (!c) return;
        majPastille(document.querySelector("[data-compteur-notifications]"), c.notifications);
        majPastille(document.querySelector("[data-compteur-messages]"), c.messages);
    }

    /** WebSocket qui se reconnecte tout seul (1 s, 2 s, 4 s… jusqu'à 30 s). */
    function SocketAuto(chemin, gestionnaires) {
        const self = this;
        let delai = 1000;
        let arret = false;
        this.connecte = false;

        function ouvrir() {
            const protocole = location.protocol === "https:" ? "wss://" : "ws://";
            let ws;
            try {
                ws = new WebSocket(protocole + location.host + chemin);
            } catch (e) {
                return;
            }
            self.ws = ws;
            ws.onopen = function () {
                self.connecte = true;
                delai = 1000;
                if (gestionnaires.ouvert) gestionnaires.ouvert();
            };
            ws.onmessage = function (e) {
                try { gestionnaires.message(JSON.parse(e.data)); } catch (err) { console.error(err); }
            };
            ws.onclose = function (e) {
                self.connecte = false;
                if (gestionnaires.ferme) gestionnaires.ferme();
                if (arret || e.code === 4403) return;  // 4403 : accès refusé, inutile de réessayer
                setTimeout(ouvrir, delai);
                delai = Math.min(delai * 2, 30000);
            };
        }

        this.envoyer = function (donnees) {
            if (!self.connecte) return false;
            self.ws.send(JSON.stringify(donnees));
            return true;
        };
        window.addEventListener("beforeunload", function () { arret = true; });
        ouvrir();
    }

    // ---------- Toasts ----------

    const zoneToasts = document.querySelector("[data-toasts]");

    function toast(titre, texte, lien) {
        if (!zoneToasts) return;
        const t = el(lien ? "a" : "div", "toast");
        if (lien) t.href = lien;
        t.append(el("strong", "", titre));
        if (texte) t.append(el("span", "", texte.length > 100 ? texte.slice(0, 100) + "…" : texte));
        zoneToasts.append(t);
        setTimeout(function () { t.classList.add("sortie"); }, 5000);
        setTimeout(function () { t.remove(); }, 5600);
    }

    // ---------- Cloche ----------

    const cloche = document.querySelector("[data-cloche]");
    if (cloche) {
        const bouton = cloche.querySelector("[data-cloche-bouton]");
        const menu = cloche.querySelector("[data-cloche-menu]");
        const liste = cloche.querySelector("[data-cloche-liste]");

        const fermer = function () {
            menu.hidden = true;
            bouton.setAttribute("aria-expanded", "false");
        };
        bouton.addEventListener("click", function (e) {
            e.stopPropagation();
            menu.hidden = !menu.hidden;
            bouton.setAttribute("aria-expanded", String(!menu.hidden));
        });
        document.addEventListener("click", function (e) { if (!cloche.contains(e.target)) fermer(); });
        document.addEventListener("keydown", function (e) { if (e.key === "Escape") fermer(); });

        function ajouterALaCloche(n) {
            const vide = liste.querySelector("[data-cloche-vide]");
            if (vide) vide.remove();
            const item = el("a", "notif-item non-lue");
            item.href = n.url;
            const icone = el("span", "notif-icone notif-" + n.type);
            icone.append(el("span", "notif-point"));
            const texte = el("span", "notif-texte");
            texte.append(el("strong", "", n.titre));
            if (n.message) texte.append(el("span", "", n.message.slice(0, 80)));
            texte.append(el("small", "", "à l'instant"));
            item.append(icone, texte);
            liste.prepend(item);
            while (liste.children.length > 5) liste.lastElementChild.remove();
        }

        const socket = new SocketAuto(cloche.dataset.ws, {
            message: function (d) {
                if (d.type === "notification") {
                    majCompteurs(d.compteurs);
                    ajouterALaCloche(d.notification);
                    // Pas de toast pour un message de la conversation déjà ouverte
                    if (d.notification.lien !== location.pathname) {
                        toast(d.notification.titre, d.notification.message, d.notification.url);
                    }
                } else if (d.type === "compteurs") {
                    majCompteurs(d.compteurs);
                }
            },
        });

        // Repli : actualisation périodique si le WebSocket est coupé
        setInterval(function () {
            if (socket.connecte || document.hidden) return;
            fetch(cloche.dataset.api, { headers: { "Accept": "application/json" } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(majCompteurs)
                .catch(function () {});
        }, INTERVALLE_COMPTEURS);
    }

    // ---------- Conversation ----------

    const discussion = document.querySelector("[data-discussion]");
    if (!discussion) return;

    const form = document.querySelector("[data-saisie]");
    const zone = form.querySelector("textarea");
    const boutonEnvoyer = form.querySelector("[data-envoyer]");
    const champFichier = form.querySelector("[data-fichier]");
    const alerte = document.querySelector("[data-alerte-envoi]");
    const ecrit = document.querySelector("[data-ecrit]");
    const affiches = new Set(
        Array.from(discussion.querySelectorAll("[data-message-id]")).map(function (e) { return Number(e.dataset.messageId); })
    );
    let refEnCours = null;

    const defilerEnBas = function () { discussion.scrollTop = discussion.scrollHeight; };
    const estEnBas = function () {
        return discussion.scrollHeight - discussion.scrollTop - discussion.clientHeight < 80;
    };

    // Arrivée depuis une recherche : on se place sur le message trouvé
    const cible = location.hash && document.querySelector(location.hash);
    if (cible) {
        cible.scrollIntoView({ block: "center" });
        cible.classList.add("surbrillance");
    } else {
        defilerEnBas();
    }

    function creerBulle(m) {
        const ligne = el("div", "bulle-ligne" + (m.moi ? " moi" : ""));
        ligne.id = "message-" + m.id;
        ligne.dataset.messageId = m.id;

        const bloc = el("div");
        bloc.append(el("small", "bulle-meta", (m.moi ? "Vous" : m.auteur) + " " + m.heure));
        const bulle = el("div", "bulle");

        if (m.fichier) {
            if (m.fichier.image) {
                const a = el("a", "piece-image");
                a.href = m.fichier.url;
                a.target = "_blank";
                a.rel = "noopener";
                const img = el("img");
                img.src = m.fichier.url;
                img.alt = m.fichier.nom;
                img.addEventListener("load", function () { if (estEnBas()) defilerEnBas(); });
                a.append(img);
                bulle.append(a);
            } else {
                const a = el("a", "piece-fichier");
                a.href = m.fichier.url + "?telecharger=1";
                const ext = (m.fichier.nom.split(".").pop() || "?").toUpperCase();
                const texte = el("span", "piece-texte");
                texte.append(el("strong", "", m.fichier.nom), el("small", "", tailleLisible(m.fichier.taille)));
                a.append(el("span", "piece-icone", ext), texte);
                bulle.append(a);
            }
        }
        if (m.contenu) bulle.append(el("div", "bulle-texte", m.contenu));

        bloc.append(bulle);
        ligne.append(el("span", "avatar avatar-sm", m.initiales), bloc);
        return ligne;
    }

    function afficherMessage(m) {
        if (affiches.has(m.id)) return;
        affiches.add(m.id);
        const enBas = estEnBas() || m.moi;
        discussion.append(creerBulle(m));
        discussion.dataset.dernier = Math.max(Number(discussion.dataset.dernier), m.id);
        if (enBas) defilerEnBas();
        if (!m.moi) ecrit.hidden = true;
    }

    function montrerAlerte(texte) {
        alerte.querySelector("[data-alerte-texte]").textContent = texte;
        alerte.hidden = false;
    }
    alerte.querySelector("[data-alerte-fermer]").addEventListener("click", function () { alerte.hidden = true; });

    function attente(active) {
        form.classList.toggle("en-analyse", active);
        boutonEnvoyer.disabled = active;
    }

    // Indicateur « en train d'écrire »
    let minuteurEcrit = null;
    function montrerEcrit(nom) {
        ecrit.querySelector("[data-ecrit-texte]").textContent = nom + " est en train d'écrire…";
        ecrit.hidden = false;
        clearTimeout(minuteurEcrit);
        minuteurEcrit = setTimeout(function () { ecrit.hidden = true; }, 3000);
    }

    function majPresence(enLigne) {
        document.querySelector("[data-point-statut]").classList.toggle("en-ligne", enLigne);
        document.querySelector("[data-statut]").textContent = enLigne ? "En ligne" : "Hors ligne";
    }

    const socket = new SocketAuto(discussion.dataset.ws, {
        message: function (d) {
            if (d.type === "message") {
                afficherMessage(d.message);
            } else if (d.type === "envoye" && d.ref === refEnCours) {
                refEnCours = null;
                zone.value = "";
                zone.dispatchEvent(new Event("input"));
                attente(false);
            } else if (d.type === "erreur" && d.ref === refEnCours) {
                refEnCours = null;
                attente(false);
                montrerAlerte(d.message);  // le texte reste dans la zone de saisie pour être corrigé
            } else if (d.type === "ecrit") {
                montrerEcrit(d.nom);
            } else if (d.type === "presence") {
                majPresence(d.en_ligne);
            }
        },
        ferme: function () {
            if (refEnCours) {
                refEnCours = null;
                attente(false);
            }
        },
    });

    // Repli : actualisation périodique si le WebSocket est coupé
    setInterval(function () {
        if (socket.connecte || document.hidden) return;
        fetch(discussion.dataset.api + "?apres=" + discussion.dataset.dernier, { headers: { "Accept": "application/json" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) { if (data) data.messages.forEach(afficherMessage); })
            .catch(function () {});
    }, INTERVALLE_MESSAGES);

    // ---------- Pièce jointe ----------

    const apercu = document.querySelector("[data-piece-selectionnee]");
    const tailleMax = Number(form.dataset.tailleMax);
    const extensions = champFichier.accept.split(",");

    function retirerFichier() {
        champFichier.value = "";
        apercu.hidden = true;
    }
    apercu.querySelector("[data-piece-retirer]").addEventListener("click", retirerFichier);

    champFichier.addEventListener("change", function () {
        const f = champFichier.files[0];
        if (!f) return retirerFichier();
        const ext = "." + f.name.split(".").pop().toLowerCase();
        if (extensions.indexOf(ext) === -1) {
            retirerFichier();
            return montrerAlerte("Le format " + ext + " n'est pas accepté.");
        }
        if (f.size > tailleMax) {
            retirerFichier();
            return montrerAlerte("Le fichier dépasse la taille maximale (" + tailleLisible(tailleMax) + ").");
        }
        alerte.hidden = true;
        apercu.querySelector("[data-piece-ext]").textContent = ext.slice(1).toUpperCase();
        apercu.querySelector("[data-piece-nom]").textContent = f.name;
        apercu.querySelector("[data-piece-taille]").textContent = tailleLisible(f.size);
        apercu.hidden = false;
        zone.focus();
    });

    function envoyerAvecFichier() {
        attente(true);
        fetch(form.action || location.pathname, {
            method: "POST",
            body: new FormData(form),
            headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": cookie("csrftoken") },
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                attente(false);
                if (!data.ok) return montrerAlerte(data.erreur);
                zone.value = "";
                zone.dispatchEvent(new Event("input"));
                retirerFichier();
                afficherMessage(Object.assign({}, data.message, { moi: true }));
            })
            .catch(function () {
                attente(false);
                montrerAlerte("L'envoi a échoué. Vérifiez votre connexion.");
            });
    }

    // ---------- Envoi ----------

    form.addEventListener("submit", function (e) {
        if (refEnCours) return e.preventDefault();
        const texte = zone.value.trim();
        const fichier = champFichier.files[0];
        if (!texte && !fichier) return e.preventDefault();
        alerte.hidden = true;

        if (fichier) {
            e.preventDefault();
            return envoyerAvecFichier();
        }
        if (socket.connecte) {
            e.preventDefault();
            refEnCours = String(Date.now());
            attente(true);
            socket.envoyer({ action: "envoyer", contenu: texte, ref: refEnCours });
        }
        // Sinon : envoi classique du formulaire (rechargement de la page)
    });

    // ---------- Zone de saisie ----------

    let dernierEcrit = 0;
    zone.addEventListener("input", function () {
        zone.style.height = "auto";
        zone.style.height = Math.min(zone.scrollHeight, 160) + "px";
        if (zone.value && Date.now() - dernierEcrit > DELAI_ECRIT) {
            dernierEcrit = Date.now();
            socket.envoyer({ action: "ecrit" });
        }
    });
    // Entrée envoie, Maj+Entrée va à la ligne
    zone.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            form.requestSubmit();
        }
    });
    zone.focus();
})();
