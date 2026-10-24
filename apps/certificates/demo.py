"""Certificats de démonstration, créés par `python run.py demo`.

En plus des certificats des comptes de démo, la commande crée des **apprenants simulés**
(e-mails en @sim.skillforge.tn) qui suivent des parcours réalistes (data, conception, web).
Ils donnent au moteur de recommandation assez de données pour apprendre et être évalué.
Ces données sont générées (graine fixe, donc toujours identiques) : ce ne sont pas de vrais apprenants.
"""

import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Certificat

DOMAINE_SIMULES = "sim.skillforge.tn"
NB_APPRENANTS_SIMULES = 40
GRAINE = 2026

# Catalogue : cours -> compétences. Certaines compétences sont partagées entre parcours (liens de contenu).
CATALOGUE = {
    "Bases de données relationnelles": ["Modèle relationnel", "Normalisation", "SQL de base"],
    "SQL avancé": ["Jointures et sous-requêtes", "Index et performances", "Transactions"],
    "Python pour la data": ["Pandas", "Nettoyage des données", "Visualisation"],
    "Pipelines ETL": ["Extraction des données", "Transformation des données", "Orchestration"],
    "Machine learning": ["Régression", "Classification", "Évaluation des modèles"],
    "Modélisation UML": ["Diagramme de classes", "Héritage et associations", "Cas d'utilisation"],
    "Design patterns": ["Patrons de conception", "Héritage et associations", "Architecture logicielle"],
    "Méthodes agiles": ["Scrum", "User stories", "Rétrospectives"],
    "Développement web avec Django": ["Architecture MVT", "ORM Django", "Formulaires web"],
    "API REST": ["Architecture REST", "Authentification", "Sérialisation JSON"],
    "JavaScript moderne": ["ES6", "Manipulation du DOM", "Programmation asynchrone"],
}

# Parcours typiques (ordre de progression), formateur et centres d'intérêt écrits dans la présentation
PARCOURS = {
    "data": (["Bases de données relationnelles", "SQL avancé", "Python pour la data", "Pipelines ETL",
              "Machine learning"], "leila",
             "Je m'intéresse à la data : bases de données, analyse avec Python et machine learning."),
    "conception": (["Modélisation UML", "Design patterns", "Méthodes agiles", "Bases de données relationnelles"],
                   "karim", "Passionné par la conception logicielle, l'architecture et les méthodes agiles."),
    "web": (["JavaScript moderne", "Développement web avec Django", "API REST", "Bases de données relationnelles"],
            "karim", "Je veux devenir développeur web full stack : JavaScript, Django et API REST."),
}

PRENOMS = ["Ahmed", "Ines", "Youssef", "Mariem", "Omar", "Rania", "Skander", "Nour", "Hamza", "Eya",
           "Aziz", "Salma", "Bilel", "Chaima", "Fares", "Hela", "Walid", "Lina", "Mehdi", "Asma"]
NOMS = ["Ben Salah", "Trabelsi", "Gharbi", "Jlassi", "Mansouri", "Ayari", "Hammami", "Chebbi", "Sassi", "Baccar"]

# Certificats des comptes de démo : (apprenant, cours, formateur, score, heures, il y a N jours)
CERTIFICATS = [
    ("yasmine", "SQL avancé", "leila", 92, 18, 3),
    ("yasmine", "Modélisation UML", "karim", 85, 24, 48),
    ("sarra", "Modélisation UML", "karim", 78, 24, 75),
    ("amine", "Bases de données relationnelles", "leila", 71, 20, 110),
    ("sarra", "Bases de données relationnelles", "leila", 88, 20, 140),
]


def creer_certificats_demo(comptes):
    maintenant = timezone.now()
    for apprenant, cours, formateur, score, heures, jours in CERTIFICATS:
        Certificat.objects.create(
            apprenant=comptes[apprenant], titre_cours=cours, formateur=comptes[formateur], score=score,
            duree_heures=heures, competences="\n".join(CATALOGUE[cours]), delivre_par=comptes[formateur],
            date_delivrance=maintenant - timedelta(days=jours),
        )

    # Un certificat révoqué, pour la page de vérification et les statistiques
    revoque = Certificat.objects.create(
        apprenant=comptes["amine"], titre_cours="Modélisation UML", formateur=comptes["karim"], score=74,
        duree_heures=24, competences="\n".join(CATALOGUE["Modélisation UML"]), delivre_par=comptes["karim"],
        date_delivrance=maintenant - timedelta(days=20),
    )
    revoque.statut = Certificat.Statut.REVOQUE
    revoque.motif_revocation = "Quiz final passé par une autre personne (démo)."
    revoque.date_revocation = maintenant - timedelta(days=2)
    revoque.revoque_par = comptes["admin"]
    revoque.save()

    creer_apprenants_simules(comptes)


def creer_apprenants_simules(comptes, nombre=NB_APPRENANTS_SIMULES, graine=GRAINE):
    """Apprenants simulés avec des parcours réalistes (et un peu de hasard), pour le moteur de recommandation."""
    User = get_user_model()
    User.objects.filter(email__endswith=f"@{DOMAINE_SIMULES}").delete()
    hasard = random.Random(graine)
    maintenant = timezone.now()

    for n in range(1, nombre + 1):
        principal = hasard.choice(list(PARCOURS))
        cours_parcours, formateur, interets = PARCOURS[principal]
        # Progression dans le parcours principal : 1 à tous les cours, dans l'ordre
        suivis = cours_parcours[:hasard.randint(1, len(cours_parcours))]
        # Un apprenant sur trois picore aussi dans un autre parcours
        if hasard.random() < 0.33:
            autre = hasard.choice([p for p in PARCOURS if p != principal])
            suivis += PARCOURS[autre][0][:hasard.randint(1, 2)]
        # Un peu de bruit : parfois un cours au hasard
        if hasard.random() < 0.15:
            suivis.append(hasard.choice(list(CATALOGUE)))

        prenom, nom = hasard.choice(PRENOMS), hasard.choice(NOMS)
        apprenant = User.objects.create_user(
            username=f"sim_{n:02d}", email=f"sim{n:02d}@{DOMAINE_SIMULES}", password=None,
            first_name=prenom, last_name=nom, role=User.Role.APPRENANT,
            bio=interets if hasard.random() < 0.7 else "",  # 30 % n'ont pas rempli leur présentation
        )
        jours = hasard.randint(30, 200)
        for cours in dict.fromkeys(suivis):  # sans doublon, dans l'ordre du parcours
            prof = comptes[formateur if cours in cours_parcours else hasard.choice(["karim", "leila"])]
            Certificat.objects.create(
                apprenant=apprenant, titre_cours=cours, formateur=prof, delivre_par=prof,
                score=hasard.randint(65, 98), duree_heures=hasard.choice([12, 18, 20, 24, 30]),
                competences="\n".join(CATALOGUE[cours]), date_delivrance=maintenant - timedelta(days=jours),
            )
            jours = max(1, jours - hasard.randint(10, 40))
