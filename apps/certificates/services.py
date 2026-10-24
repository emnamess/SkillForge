"""API du module certificats, à utiliser depuis les autres apps.

    from apps.certificates.services import delivrer_certificat, delivrer_si_eligible, est_eligible

    # Module cours : quand un apprenant termine un cours
    delivrer_si_eligible(inscription.apprenant, cours.titre, progression=inscription.progression,
                         score=moyenne_quiz, formateur=cours.formateur)

    # Délivrance directe (formateur ou administrateur)
    delivrer_certificat(apprenant, "Modélisation UML", formateur=karim, score=88,
                        competences=["Diagramme de classes", "Héritage"], delivre_par=karim)

Règle d'éligibilité : progression à 100 % et score final ≥ CERTIFICAT_SCORE_MINIMUM (70 par défaut,
modifiable dans les paramètres).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import notifier

from .models import Certificat


def score_minimum():
    return getattr(settings, "CERTIFICAT_SCORE_MINIMUM", 70)


def est_eligible(progression, score=None):
    """Vrai si l'apprenant a terminé le cours et (si un score est fourni) atteint le score minimum."""
    if progression is None or progression < 100:
        return False
    return score is None or score >= score_minimum()


def certificat_valide(apprenant, titre_cours):
    return Certificat.doublon_valide(apprenant, titre_cours)


@transaction.atomic
def delivrer_certificat(apprenant, titre_cours, *, formateur=None, score=None, duree_heures=None,
                        competences=(), delivre_par=None, notifier_apprenant=True):
    """Délivre un certificat et prévient l'apprenant. Lève ValidationError s'il en a déjà un valide."""
    titre_cours = titre_cours.strip()
    if not apprenant.est_apprenant:
        raise ValidationError("Seul un apprenant peut recevoir un certificat.")
    if certificat_valide(apprenant, titre_cours):
        raise ValidationError(f"{apprenant} possède déjà un certificat valide pour « {titre_cours} ».")
    if isinstance(competences, str):
        competences = competences.splitlines()

    certificat = Certificat.objects.create(
        apprenant=apprenant, titre_cours=titre_cours, formateur=formateur, score=score,
        duree_heures=duree_heures, competences="\n".join(c.strip() for c in competences if c.strip()),
        delivre_par=delivre_par,
    )
    if notifier_apprenant:
        transaction.on_commit(lambda: notifier(
            apprenant, "Certificat obtenu", f"Félicitations : votre certificat « {titre_cours} » est disponible.",
            type=Notification.Type.CERTIFICAT, lien=certificat.get_absolute_url(), email=True,
        ))
    return certificat


def delivrer_si_eligible(apprenant, titre_cours, *, progression, score=None, **kwargs):
    """Délivre le certificat seulement si l'apprenant est éligible et n'en a pas déjà un.

    Renvoie le certificat créé, ou None. Pratique à appeler à chaque mise à jour de la progression.
    """
    if not est_eligible(progression, score) or certificat_valide(apprenant, titre_cours):
        return None
    return delivrer_certificat(apprenant, titre_cours, score=score, **kwargs)


def notifier_modification(certificat):
    notifier(certificat.apprenant, "Certificat mis à jour",
             f"Votre certificat « {certificat.titre_cours} » a été corrigé. Le code de vérification reste le même.",
             type=Notification.Type.CERTIFICAT, lien=certificat.get_absolute_url())


@transaction.atomic
def revoquer_certificat(certificat, par, motif):
    if not certificat.est_valide:
        raise ValidationError("Ce certificat est déjà révoqué.")
    motif = motif.strip()
    if not motif:
        raise ValidationError("Indiquez le motif de la révocation.")
    certificat.statut = Certificat.Statut.REVOQUE
    certificat.motif_revocation = motif
    certificat.date_revocation = timezone.now()
    certificat.revoque_par = par
    certificat.save(update_fields=["statut", "motif_revocation", "date_revocation", "revoque_par"])
    transaction.on_commit(lambda: notifier(
        certificat.apprenant, "Certificat révoqué",
        f"Votre certificat « {certificat.titre_cours} » a été révoqué. Motif : {motif}",
        type=Notification.Type.CERTIFICAT, lien=certificat.get_absolute_url(), email=True,
    ))
    return certificat
