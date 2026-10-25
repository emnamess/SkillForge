"""Seul point de contact entre careers et le module notifications (couplage faible).

Chaque notification part après la validation de la transaction (on_commit), et un échec est
seulement journalisé : il ne bloque jamais une action de l'Espace Carrière.

Aucun type de notification « carrière » n'existe dans notifications : on utilise COMPTE pour la
décision sur l'entreprise et SYSTEME pour les candidatures.
"""

import logging

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import notifier

logger = logging.getLogger(__name__)


def _envoyer_apres_commit(destinataire, titre, message, *, type=Notification.Type.SYSTEME, lien="", email=False):
    def envoyer():
        try:
            notifier(destinataire, titre, message, type=type, lien=lien, email=email)
        except Exception:
            logger.exception("Notification Carrière non envoyée à %s : %s", destinataire, titre)

    transaction.on_commit(envoyer)


def nouvelle_candidature(candidature):
    offre = candidature.offre
    _envoyer_apres_commit(
        offre.entreprise.utilisateur, "Nouvelle candidature",
        f"{candidature.apprenant} a postulé à « {offre.titre} ».",
        lien=reverse("careers:fiche_candidat", args=[candidature.pk]),
    )


def statut_candidature_change(candidature, ancien_statut):
    Statut = candidature.Statut
    if candidature.statut == Statut.RETIREE:
        return  # l'apprenant est l'auteur du retrait : rien à lui notifier

    offre = candidature.offre
    if candidature.statut == Statut.ENTRETIEN:
        quand = timezone.localtime(candidature.date_entretien).strftime("%d/%m/%Y à %H:%M")
        titre = "Entretien déplacé" if ancien_statut == Statut.ENTRETIEN else "Entretien planifié"
        message = f"{offre.entreprise} · « {offre.titre} » : {quand}, {candidature.lieu_ou_lien_entretien}."
        email = True
    else:
        titre = f"Candidature {candidature.get_statut_display().lower()}"
        message = f"{offre.entreprise} · « {offre.titre} »."
        email = candidature.statut in (Statut.ACCEPTEE, Statut.REFUSEE)
    _envoyer_apres_commit(candidature.apprenant, titre, message, lien=candidature.get_absolute_url(), email=email)


def entreprise_decidee(entreprise):
    if entreprise.est_validee:
        titre = "Votre entreprise est validée"
        message = f"{entreprise} peut maintenant publier des offres sur SkillForge."
    else:
        titre = "Votre entreprise n'a pas été validée"
        message = f"Motif : {entreprise.motif_refus}"
    _envoyer_apres_commit(entreprise.utilisateur, titre, message, type=Notification.Type.COMPTE,
                          lien=reverse("careers:tableau_recruteur"), email=True)
