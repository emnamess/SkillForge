/* Espace Carrière : glisser-déposer du Kanban des candidatures (HTML5 natif + fetch).
 *
 * Sans JavaScript, chaque carte garde son menu « Changer le statut » (formulaire POST classique).
 * Avec JavaScript, ce même menu et le glisser-déposer envoient la demande en fetch : le serveur
 * valide la transition et répond en JSON ; en cas de refus, la carte revient à sa place.
 */
(function () {
    "use strict";

    const kanban = document.querySelector("[data-kanban]");
    if (!kanban) return;

    const zoneMessage = document.querySelector("[data-kanban-message]");
    let carteDeplacee = null;

    function jetonCsrf(carte) {
        const champ = carte.querySelector("input[name=csrfmiddlewaretoken]");
        return champ ? champ.value : "";
    }

    function afficherMessage(texte, type, lien) {
        zoneMessage.innerHTML = "";
        const alerte = document.createElement("div");
        alerte.className = "alert alert-" + type;
        alerte.textContent = texte;
        if (lien) {
            const a = document.createElement("a");
            a.href = lien;
            a.textContent = " Ouvrir la fiche du candidat";
            alerte.appendChild(a);
        }
        zoneMessage.appendChild(alerte);
        clearTimeout(afficherMessage.minuteur);
        afficherMessage.minuteur = setTimeout(() => { zoneMessage.innerHTML = ""; }, 6000);
    }

    function majColonnes() {
        kanban.querySelectorAll(".kanban-colonne").forEach(colonne => {
            const n = colonne.querySelectorAll("[data-carte]").length;
            colonne.querySelector("[data-compteur]").textContent = n;
            let vide = colonne.querySelector("[data-vide]");
            if (n === 0 && !vide) {
                vide = document.createElement("p");
                vide.className = "kanban-vide";
                vide.dataset.vide = "";
                vide.textContent = "Aucun candidat";
                colonne.appendChild(vide);
            } else if (n > 0 && vide) {
                vide.remove();
            }
        });
    }

    function majMenu(carte, statutsPossibles) {
        const form = carte.querySelector("[data-form-statut]");
        const select = form.querySelector("select");
        select.innerHTML = "";
        statutsPossibles.forEach(s => select.add(new Option(s.libelle, s.valeur)));
        form.hidden = statutsPossibles.length === 0;
    }

    /* Envoie le changement ; la carte est déplacée tout de suite et revient si le serveur refuse. */
    function changerStatut(carte, nouveauStatut) {
        if (carte.dataset.statut === nouveauStatut) return;
        const origine = carte.parentElement;
        const suivante = carte.nextElementSibling;
        const destination = kanban.querySelector(`.kanban-colonne[data-statut="${nouveauStatut}"]`);
        destination.appendChild(carte);
        majColonnes();

        const donnees = new FormData();
        donnees.append("statut", nouveauStatut);
        fetch(carte.dataset.url, {
            method: "POST",
            body: donnees,
            headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": jetonCsrf(carte) },
            credentials: "same-origin",
        })
            .then(r => r.json().catch(() => ({ ok: false, erreur: "Réponse inattendue du serveur." })))
            .then(reponse => {
                if (!reponse.ok) throw reponse;
                carte.dataset.statut = reponse.statut;
                majMenu(carte, reponse.statuts_possibles);
                afficherMessage("Candidature passée en « " + reponse.libelle + " ».", "success");
            })
            .catch(reponse => {
                origine.insertBefore(carte, suivante && suivante.parentElement === origine ? suivante : null);
                majColonnes();
                carte.classList.add("refusee-anim");
                setTimeout(() => carte.classList.remove("refusee-anim"), 500);
                const erreur = (reponse && reponse.erreur) || "Le changement de statut a échoué. Réessayez.";
                afficherMessage(erreur, "error", nouveauStatut === "entretien" ? carte.dataset.fiche : null);
            });
    }

    kanban.querySelectorAll("[data-carte]").forEach(carte => {
        carte.draggable = true;
        carte.addEventListener("dragstart", e => {
            carteDeplacee = carte;
            carte.classList.add("deplacement");
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", carte.dataset.url);
        });
        carte.addEventListener("dragend", () => {
            carte.classList.remove("deplacement");
            carteDeplacee = null;
        });
        // Le menu accessible passe aussi par fetch (le formulaire classique reste le repli sans JS)
        carte.querySelector("[data-form-statut]").addEventListener("submit", e => {
            e.preventDefault();
            changerStatut(carte, e.target.querySelector("select").value);
        });
    });

    kanban.querySelectorAll(".kanban-colonne").forEach(colonne => {
        colonne.addEventListener("dragover", e => {
            if (!carteDeplacee) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            colonne.classList.add("survol");
        });
        colonne.addEventListener("dragleave", e => {
            if (!colonne.contains(e.relatedTarget)) colonne.classList.remove("survol");
        });
        colonne.addEventListener("drop", e => {
            e.preventDefault();
            colonne.classList.remove("survol");
            if (carteDeplacee) changerStatut(carteDeplacee, colonne.dataset.statut);
        });
    });
})();
