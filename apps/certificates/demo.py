"""Certificats de démonstration, créés par `python run.py demo`."""

from datetime import timedelta

from django.utils import timezone

from .models import Certificat

# (apprenant, cours, formateur, score, heures, il y a N jours, compétences)
CERTIFICATS = [
    ("yasmine", "SQL avancé", "leila", 92, 18, 3,
     ["Jointures et sous-requêtes", "Index et performances", "Transactions"]),
    ("yasmine", "Modélisation UML", "karim", 85, 24, 48,
     ["Diagramme de classes", "Héritage et associations", "Cas d'utilisation"]),
    ("sarra", "Modélisation UML", "karim", 78, 24, 75, ["Diagramme de classes", "Cas d'utilisation"]),
    ("amine", "Bases de données relationnelles", "leila", 71, 20, 110, ["Modèle relationnel", "Normalisation"]),
    ("sarra", "Bases de données relationnelles", "leila", 88, 20, 140, ["Modèle relationnel", "Normalisation"]),
]


def creer_certificats_demo(comptes):
    maintenant = timezone.now()
    for apprenant, cours, formateur, score, heures, jours, competences in CERTIFICATS:
        Certificat.objects.create(
            apprenant=comptes[apprenant], titre_cours=cours, formateur=comptes[formateur], score=score,
            duree_heures=heures, competences="\n".join(competences), delivre_par=comptes[formateur],
            date_delivrance=maintenant - timedelta(days=jours),
        )

    # Un certificat révoqué, pour la page de vérification et les statistiques
    revoque = Certificat.objects.create(
        apprenant=comptes["amine"], titre_cours="Modélisation UML", formateur=comptes["karim"], score=74,
        duree_heures=24, delivre_par=comptes["karim"], date_delivrance=maintenant - timedelta(days=20),
    )
    revoque.statut = Certificat.Statut.REVOQUE
    revoque.motif_revocation = "Quiz final passé par une autre personne (démo)."
    revoque.date_revocation = maintenant - timedelta(days=2)
    revoque.revoque_par = comptes["admin"]
    revoque.save()
