from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.formats import date_format

from apps.notifications.models import Notification
from apps.notifications.services import annuler_rappels, notifier, planifier_rappels_seance

from .models import Disponibilite, SeanceMentorat


class CreneauIndisponible(Exception):
    """Le créneau n'est plus réservable ou entre en conflit avec une séance."""


def _quand(seance):
    return date_format(timezone.localtime(seance.debut), "l j F à H\\hi")


def _notifier_apres_commit(destinataires, titre, message, seance):
    """La notification ne part que si la séance est bien enregistrée."""
    transaction.on_commit(lambda: notifier(
        destinataires, titre, message, type=Notification.Type.SEANCE, lien=seance.get_absolute_url(), email=True,
    ))


def _notifier_changement(seance, statut, par):
    if statut == SeanceMentorat.Statut.CONFIRMEE:
        _notifier_apres_commit(
            seance.apprenant, "Séance de mentorat confirmée",
            f"{seance.formateur} a confirmé votre séance « {seance.sujet} » du {_quand(seance)}.", seance,
        )
    elif statut == SeanceMentorat.Statut.ANNULEE:
        # On prévient l'autre participant ; si un administrateur annule, les deux sont prévenus
        destinataires = [u for u in (seance.apprenant, seance.formateur) if par is None or u.pk != par.pk]
        auteur = f" par {par}" if par is not None else ""
        _notifier_apres_commit(
            destinataires, "Séance de mentorat annulée",
            f"La séance « {seance.sujet} » du {_quand(seance)} a été annulée{auteur}.", seance,
        )


def _est_formateur_valide(user):
    return user.is_active and user.est_formateur and not user.en_attente_validation


def _verifier_conflit(formateur, apprenant, debut, fin):
    conflit = SeanceMentorat.objects.filter(
        statut__in=(SeanceMentorat.Statut.EN_ATTENTE, SeanceMentorat.Statut.CONFIRMEE),
        debut__lt=fin,
        fin__gt=debut,
    ).filter(Q(formateur=formateur) | Q(apprenant=apprenant))
    if conflit.exists():
        raise CreneauIndisponible("Ce créneau chevauche une autre séance du formateur ou de l’apprenant.")


@transaction.atomic
def reserver_seance(disponibilite_id, apprenant, debut, sujet, description="", *, demandeur=None):
    """Réserve une unité du créneau et programme ses rappels atomiquement."""
    demandeur = demandeur or apprenant
    if not apprenant.is_active or not apprenant.est_apprenant:
        raise PermissionDenied("La séance doit être destinée à un apprenant actif.")
    try:
        disponibilite = Disponibilite.objects.select_for_update().select_related("formateur").get(
            pk=disponibilite_id, active=True,
        )
    except Disponibilite.DoesNotExist as exc:
        raise CreneauIndisponible("Cette disponibilité n’existe plus.") from exc

    formateur = disponibilite.formateur
    if not _est_formateur_valide(formateur):
        raise CreneauIndisponible("Ce formateur n’est pas disponible pour de nouvelles séances.")
    if demandeur.est_apprenant:
        if demandeur.pk != apprenant.pk:
            raise PermissionDenied("Un apprenant ne peut réserver une séance que pour lui-même.")
        statut_initial = SeanceMentorat.Statut.EN_ATTENTE
    elif demandeur.est_formateur:
        if not _est_formateur_valide(demandeur) or demandeur.pk != formateur.pk:
            raise PermissionDenied("Vous ne pouvez planifier une séance que sur vos disponibilités.")
        statut_initial = SeanceMentorat.Statut.CONFIRMEE
    else:
        raise PermissionDenied("Seuls les apprenants et leur formateur peuvent créer une séance.")
    fin = debut + timedelta(minutes=disponibilite.duree_seance)
    maintenant = timezone.now()
    if debut <= maintenant or debut < disponibilite.debut or fin > disponibilite.fin:
        raise CreneauIndisponible("L’horaire demandé est en dehors de la disponibilité.")
    if debut.minute % 15 or debut.second or debut.microsecond:
        raise CreneauIndisponible("L’heure de début doit être alignée sur un quart d’heure.")

    _verifier_conflit(formateur, apprenant, debut, fin)
    seance = SeanceMentorat(
        disponibilite=disponibilite,
        apprenant=apprenant,
        formateur=formateur,
        debut=debut,
        fin=fin,
        sujet=sujet,
        description=description,
        statut=statut_initial,
    )
    seance.full_clean()
    try:
        seance.save()
    except DatabaseError as exc:
        raise CreneauIndisponible("Ce créneau vient d’être réservé par un autre utilisateur.") from exc
    if statut_initial == SeanceMentorat.Statut.CONFIRMEE:
        planifier_rappels_seance(
            seance, [seance.apprenant, seance.formateur], seance.debut,
            titre=f"Séance de mentorat · {seance.sujet}", lien=seance.get_absolute_url(),
        )
        _notifier_apres_commit(
            apprenant, "Nouvelle séance de mentorat",
            f"{formateur} a planifié une séance « {sujet} » avec vous le {_quand(seance)}.", seance,
        )
    else:
        _notifier_apres_commit(
            formateur, "Nouvelle demande de séance",
            f"{apprenant} demande une séance « {sujet} » le {_quand(seance)}. Confirmez-la depuis la séance.", seance,
        )
    return seance


@transaction.atomic
def changer_statut(seance, statut, par=None):
    """`par` : utilisateur à l'origine du changement, pour ne pas le notifier de sa propre action."""
    if statut not in SeanceMentorat.Statut.values:
        raise ValidationError("Statut de séance invalide.")
    if seance.statut in (SeanceMentorat.Statut.ANNULEE, SeanceMentorat.Statut.TERMINEE):
        raise ValidationError("Cette séance est déjà terminée ou annulée.")
    if statut == SeanceMentorat.Statut.CONFIRMEE and seance.statut != SeanceMentorat.Statut.EN_ATTENTE:
        raise ValidationError("Seule une demande en attente peut être confirmée.")
    if statut == SeanceMentorat.Statut.TERMINEE and seance.debut > timezone.now():
        raise ValidationError("Une séance future ne peut pas être marquée comme terminée.")
    seance.statut = statut
    seance.save(update_fields=["statut", "date_modification"])
    if statut == SeanceMentorat.Statut.CONFIRMEE:
        planifier_rappels_seance(
            seance, [seance.apprenant, seance.formateur], seance.debut,
            titre=f"Séance de mentorat · {seance.sujet}", lien=seance.get_absolute_url(),
        )
    elif statut == SeanceMentorat.Statut.ANNULEE:
        annuler_rappels(seance)
    _notifier_changement(seance, statut, par)
    return seance


def creneaux_disponibles(disponibilite, *, maintenant=None):
    maintenant = maintenant or timezone.now()
    duree = timedelta(minutes=disponibilite.duree_seance)
    debut = disponibilite.debut
    if debut.second or debut.microsecond or debut.minute % 15:
        debut = debut.replace(second=0, microsecond=0)
        debut += timedelta(minutes=15 - debut.minute % 15)
    creneaux = []
    while debut + duree <= disponibilite.fin:
        fin = debut + duree
        if debut > maintenant:
            conflit = SeanceMentorat.objects.filter(
                statut__in=(SeanceMentorat.Statut.EN_ATTENTE, SeanceMentorat.Statut.CONFIRMEE),
                debut__lt=fin, fin__gt=debut,
            ).filter(Q(formateur=disponibilite.formateur) | Q(disponibilite=disponibilite)).exists()
            if not conflit:
                creneaux.append(debut)
        debut += timedelta(minutes=15)
    return creneaux


def peut_gerer_seance(user, seance):
    return user.est_administrateur or (_est_formateur_valide(user) and seance.formateur_id == user.pk)

