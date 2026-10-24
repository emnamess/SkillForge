// Module certificats : chargement des recommandations de l'IA sur la page « Mes certificats ».
// Le contenu est inséré avec textContent (jamais innerHTML) : aucun risque d'injection.

(function () {
    const zone = document.querySelector("[data-recommandations]");
    if (!zone) return;

    const liste = zone.querySelector("[data-reco-liste]");
    const erreur = zone.querySelector("[data-reco-erreur]");
    const texteErreur = zone.querySelector("[data-reco-erreur-texte]");
    const note = zone.querySelector("[data-reco-note]");
    const squelettes = liste.innerHTML;

    function element(balise, classe, texte) {
        const el = document.createElement(balise);
        if (classe) el.className = classe;
        if (texte !== undefined) el.textContent = texte;
        return el;
    }

    function carte(reco, rang) {
        const article = element("article", "card reco-card");
        const tete = element("div", "reco-tete");
        tete.append(element("span", "reco-rang", String(rang)));
        const badge = reco.niveau === "Très pertinent" ? "badge-green" : reco.niveau === "Populaire" ? "badge-orange" : "badge-indigo";
        tete.append(element("span", "badge " + badge, reco.niveau));
        article.append(tete);
        article.append(element("h3", "", reco.titre));

        const jauge = element("span", "progress reco-jauge");
        jauge.setAttribute("role", "img");
        jauge.setAttribute("aria-label", "Indice de pertinence : " + Math.round(reco.score * 100) + " sur 100");
        const rempli = element("span");
        rempli.style.width = Math.max(4, Math.round(reco.score * 100)) + "%";
        jauge.append(rempli);
        article.append(jauge);

        const raisons = element("ul", "reco-raisons");
        reco.raisons.forEach((r) => raisons.append(element("li", "", r)));
        article.append(raisons);

        if (reco.competences_nouvelles.length) {
            article.append(element("p", "reco-sous-titre", "Compétences à acquérir"));
            const puces = element("div", "reco-competences");
            reco.competences_nouvelles.forEach((c) => puces.append(element("span", "badge badge-competence", c)));
            article.append(puces);
        }
        return article;
    }

    function afficher(donnees) {
        liste.replaceChildren();
        const recos = donnees.recommandations;
        if (!recos.length) {
            liste.append(element("p", "muted", "Pas encore de recommandation : revenez après votre premier certificat."));
        } else {
            recos.forEach((r, i) => liste.append(carte(r, i + 1)));
        }
        note.textContent = (donnees.source === "populaires"
            ? "Vous n'avez encore ni certificat ni présentation : voici les certifications les plus obtenues. "
            : "Calculées par le moteur de recommandation SkillForge à partir de vos certificats, de votre présentation et des parcours des autres apprenants. ")
            + "Réponse en " + donnees.duree_ms.toLocaleString("fr-FR") + " ms.";
        note.hidden = false;
    }

    async function charger() {
        erreur.hidden = true;
        note.hidden = true;
        liste.innerHTML = squelettes;
        liste.setAttribute("aria-busy", "true");
        const controleur = new AbortController();
        const delai = setTimeout(() => controleur.abort(), 10000);
        try {
            const reponse = await fetch(zone.dataset.recommandations, {
                headers: { Accept: "application/json" }, signal: controleur.signal, credentials: "same-origin",
            });
            const donnees = await reponse.json().catch(() => ({}));
            if (!reponse.ok) throw new Error(donnees.erreur || "Erreur " + reponse.status);
            afficher(donnees);
        } catch (e) {
            liste.replaceChildren();
            texteErreur.textContent = e.name === "AbortError"
                ? "Le calcul des recommandations a pris trop de temps."
                : (e.message.startsWith("Erreur") || e.message === "Failed to fetch"
                    ? "Les recommandations n'ont pas pu être chargées (connexion au serveur impossible)."
                    : e.message);
            erreur.hidden = false;
        } finally {
            clearTimeout(delai);
            liste.setAttribute("aria-busy", "false");
        }
    }

    zone.querySelector("[data-reco-reessayer]").addEventListener("click", charger);
    charger();
})();
