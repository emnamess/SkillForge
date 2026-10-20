"""API du module notifications, à utiliser depuis les autres apps.

    from apps.notifications.services import notifier, planifier_rappels_seance, annuler_rappels
    from apps.notifications.models import Notification

    notifier(apprenant, "Quiz corrigé", "Vous avez obtenu 16/20.",
             type=Notification.Type.QUIZ, lien=quiz.get_absolute_url())

    planifier_rappels_seance(seance, [seance.apprenant, seance.formateur], seance.date_heure,
                             titre="Séance de mentorat · Modélisation UML", lien=seance.get_absolute_url())

    annuler_rappels(seance)  # si la séance est annulée ou déplacée
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format

from .models import Conversation, Message, Notification, Rappel

logger = logging.getLogger(__name__)

DELAIS_RAPPEL_SEANCE = (timedelta(hours=24), timedelta(minutes=15))


# ---------- Notifications ----------

def notifier(destinataires, titre, message="", *, type=Notification.Type.SYSTEME, lien="", email=False):
    """Crée une notification pour un ou plusieurs utilisateurs. Renvoie la liste créée."""
    if not isinstance(destinataires, (list, tuple, set)) and not hasattr(destinataires, "model"):
        destinataires = [destinataires]

    notifications = Notification.objects.bulk_create([
        Notification(destinataire=u, type=type, titre=titre, message=message, lien=lien)
        for u in destinataires if u.is_active
    ])
    if email:
        for n in notifications:
            envoyer_email(n.destinataire, titre, message, lien)
    return notifications


def envoyer_email(user, sujet, message, lien=""):
    if not user.email:
        return
    corps = f"Bonjour {user.first_name or user.username},\n\n{message}\n"
    if lien:
        corps += f"\n{getattr(settings, 'SITE_URL', '').rstrip('/')}{lien}\n"
    corps += "\nL'équipe SkillForge"
    try:
        send_mail(f"SkillForge · {sujet}", corps, None, [user.email])
    except Exception:  # un e-mail en échec ne doit pas bloquer l'action de l'utilisateur
        logger.exception("Échec de l'envoi de l'e-mail à %s", user.email)


def marquer_toutes_lues(user):
    return user.notifications.filter(lue=False).update(lue=True)


# ---------- Messagerie ----------

def peut_ecrire_a(expediteur, destinataire):
    """Un apprenant écrit aux formateurs et aux administrateurs ; les autres écrivent à tous."""
    if expediteur == destinataire or not destinataire.is_active:
        return False
    if expediteur.est_apprenant:
        return destinataire.est_formateur or destinataire.est_administrateur
    return True


def destinataires_possibles(user):
    from apps.accounts.models import User

    qs = User.objects.filter(is_active=True).exclude(pk=user.pk)
    if user.est_apprenant:
        qs = qs.filter(role__in=[User.Role.FORMATEUR, User.Role.ADMINISTRATEUR])
    return qs.order_by("first_name", "last_name")


def obtenir_conversation(user_a, user_b):
    """Renvoie la conversation entre deux utilisateurs, en la créant si besoin."""
    conversation = Conversation.objects.entre(user_a, user_b).first()
    if conversation is None:
        conversation = Conversation.objects.create()
        conversation.participants.add(user_a, user_b)
    return conversation


@transaction.atomic
def envoyer_message(conversation, expediteur, contenu):
    if not conversation.participants.filter(pk=expediteur.pk).exists():
        raise PermissionDenied("Vous ne participez pas à cette conversation.")

    message = Message.objects.create(conversation=conversation, expediteur=expediteur, contenu=contenu)
    conversation.save(update_fields=["date_maj"])

    # Une seule notification non lue par conversation, pour ne pas inonder la cloche
    destinataire = conversation.interlocuteur(expediteur)
    lien = conversation.get_absolute_url()
    if destinataire and not destinataire.notifications.filter(lue=False, type=Notification.Type.MESSAGE,
                                                              lien=lien).exists():
        notifier(destinataire, f"Nouveau message de {expediteur}", contenu[:120],
                 type=Notification.Type.MESSAGE, lien=lien)
    return message


def messages_non_lus(user):
    return Message.objects.filter(conversation__participants=user, lu=False).exclude(expediteur=user).count()


# ---------- Rappels ----------

def planifier_rappel(destinataire, date_envoi, titre, message="", *, lien="", objet=None, par_email=True):
    rappel = Rappel(destinataire=destinataire, date_envoi=date_envoi, titre=titre, message=message,
                    lien=lien, par_email=par_email)
    if objet is not None:
        rappel.objet = objet
    rappel.save()
    return rappel


def planifier_rappels_seance(seance, participants, date_seance, *, titre, lien="",
                             delais=DELAIS_RAPPEL_SEANCE):
    """Programme un rappel par participant et par délai (par défaut 24 h et 15 min avant).

    Les rappels déjà existants pour cette séance sont remplacés : on peut donc rappeler
    cette fonction quand la séance est déplacée.
    """
    annuler_rappels(seance)
    maintenant = timezone.now()
    quand = date_format(timezone.localtime(date_seance), "l j F à H\\hi")
    rappels = []
    for delai in delais:
        date_envoi = date_seance - delai
        if date_envoi <= maintenant:
            continue
        for participant in participants:
            rappels.append(planifier_rappel(
                participant, date_envoi, f"Rappel · {titre}",
                f"Votre séance commence {quand}.", lien=lien, objet=seance,
            ))
    return rappels


def annuler_rappels(objet):
    """Supprime les rappels non encore envoyés liés à un objet (ex. une séance annulée)."""
    ct = ContentType.objects.get_for_model(objet)
    return Rappel.objects.filter(content_type=ct, object_id=objet.pk, envoye=False).delete()[0]


def envoyer_rappels_dus(maintenant=None):
    """Transforme en notifications les rappels arrivés à échéance. Renvoie le nombre envoyé."""
    maintenant = maintenant or timezone.now()
    envoyes = 0
    rappels = Rappel.objects.filter(envoye=False, date_envoi__lte=maintenant).select_related("destinataire")
    for rappel in rappels:
        with transaction.atomic():
            # Verrouille la ligne : deux exécutions simultanées n'envoient pas deux fois
            if not Rappel.objects.filter(pk=rappel.pk, envoye=False).update(envoye=True):
                continue
            notifier(rappel.destinataire, rappel.titre, rappel.message, type=Notification.Type.RAPPEL,
                     lien=rappel.lien, email=rappel.par_email)
            envoyes += 1
    return envoyes
