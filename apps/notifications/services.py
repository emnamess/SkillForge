"""API du module notifications, à utiliser depuis les autres apps.

Les notifications créées ici arrivent instantanément dans le navigateur (WebSockets).

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
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from . import realtime
from .moderation import moderer
from .models import Conversation, Message, Notification, Rappel, Signalement

logger = logging.getLogger(__name__)


class MessageBloque(Exception):
    """Levée quand la modération refuse un message. `resultat` contient la raison."""

    def __init__(self, resultat):
        super().__init__(resultat.raison)
        self.resultat = resultat

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
    for n in notifications:
        realtime.pousser_notification(n)
        if email:
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
    n = user.notifications.filter(lue=False).update(lue=True)
    realtime.pousser_compteurs(user)
    return n


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


def valider_piece_jointe(fichier):
    extension = Path(fichier.name).suffix.lower().lstrip(".")
    if extension not in settings.PIECE_JOINTE_EXTENSIONS:
        raise ValidationError(f"Le format .{extension or '?'} n'est pas accepté.")
    if fichier.size > settings.PIECE_JOINTE_TAILLE_MAX:
        raise ValidationError(f"Le fichier dépasse la taille maximale "
                              f"({filesizeformat(settings.PIECE_JOINTE_TAILLE_MAX)}).")


def _notifier_moderateurs(signalement):
    from apps.accounts.models import User

    admins = User.objects.filter(role=User.Role.ADMINISTRATEUR, is_active=True)
    action = "bloqué" if signalement.decision == Signalement.Decision.BLOQUE else "signalé"
    notifier(admins, f"Message {action} par la modération IA",
             f"{signalement.auteur} · {signalement.raison}", type=Notification.Type.SYSTEME,
             lien=reverse("notifications:moderation"))


def envoyer_message(conversation, expediteur, contenu="", fichier=None, resultat_moderation=None):
    """Envoie un message après modération. Lève `MessageBloque` si l'IA le refuse.

    `resultat_moderation` permet de fournir une analyse déjà faite (le consumer WebSocket
    interroge l'IA dans un thread séparé pour ne pas bloquer les autres connexions).
    """
    contenu = (contenu or "").strip()
    if not conversation.participants.filter(pk=expediteur.pk).exists():
        raise PermissionDenied("Vous ne participez pas à cette conversation.")
    if not contenu and not fichier:
        raise ValidationError("Le message est vide.")
    if fichier:
        valider_piece_jointe(fichier)

    # L'appel à l'IA se fait hors transaction : la base n'est pas verrouillée pendant l'attente
    resultat = resultat_moderation or moderer(contenu)

    with transaction.atomic():
        if resultat.bloque:
            signalement = Signalement.objects.create(
                conversation=conversation, auteur=expediteur, contenu=contenu,
                decision=Signalement.Decision.BLOQUE, categorie=resultat.categorie,
                raison=resultat.raison, source=resultat.source,
            )
            _notifier_moderateurs(signalement)
        else:
            message = Message(conversation=conversation, expediteur=expediteur, contenu=contenu,
                              signale=not resultat.autorise)
            if fichier:
                message.nom_fichier = Path(fichier.name).name[:255]
                message.taille_fichier = fichier.size
                message.fichier = fichier
            message.save()
            conversation.save(update_fields=["date_maj"])

            if message.signale:
                signalement = Signalement.objects.create(
                    message=message, conversation=conversation, auteur=expediteur, contenu=contenu,
                    decision=Signalement.Decision.SIGNALE, categorie=resultat.categorie,
                    raison=resultat.raison, source=resultat.source,
                )
                _notifier_moderateurs(signalement)

            realtime.diffuser_message(message)
            _notifier_destinataire(conversation, expediteur, message)

    if resultat.bloque:
        # Hors du bloc atomique : le signalement reste enregistré
        raise MessageBloque(resultat)
    return message


def _notifier_destinataire(conversation, expediteur, message):
    """Une seule notification non lue par conversation, pour ne pas inonder la cloche."""
    destinataire = conversation.interlocuteur(expediteur)
    if destinataire is None:
        return
    lien = conversation.get_absolute_url()
    if destinataire.notifications.filter(lue=False, type=Notification.Type.MESSAGE, lien=lien).exists():
        realtime.pousser_compteurs(destinataire)
    else:
        notifier(destinataire, f"Nouveau message de {expediteur}", message.apercu()[:120],
                 type=Notification.Type.MESSAGE, lien=lien)


def messages_non_lus(user):
    return Message.objects.filter(conversation__participants=user, lu=False).exclude(expediteur=user).count()


def rechercher_messages(user, terme, limite=50):
    """Messages des conversations de l'utilisateur contenant le terme (texte ou nom de fichier)."""
    from django.db.models import Q

    return (
        Message.objects.filter(conversation__participants=user)
        .filter(Q(contenu__icontains=terme) | Q(nom_fichier__icontains=terme))
        .select_related("expediteur", "conversation")
        .order_by("-date_envoi")[:limite]
    )


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
