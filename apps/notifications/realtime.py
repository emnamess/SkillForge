"""Diffusion en temps réel vers les navigateurs (groupes Django Channels).

Groupes :
- `utilisateur_<id>`   : cloche, compteurs et statut en ligne d'un utilisateur (toutes ses pages)
- `conversation_<id>`  : messages, « en train d'écrire » et présence dans une conversation
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.db import transaction
from django.utils.formats import date_format
from django.utils.timezone import localtime

logger = logging.getLogger(__name__)


def groupe_utilisateur(user_id):
    return f"utilisateur_{user_id}"


def groupe_conversation(conversation_id):
    return f"conversation_{conversation_id}"


def envoyer_au_groupe(groupe, evenement):
    """Envoie un événement après la validation de la transaction en cours."""
    layer = get_channel_layer()
    if layer is None:
        return

    def envoyer():
        try:
            async_to_sync(layer.group_send)(groupe, evenement)
        except Exception:  # le temps réel ne doit jamais faire échouer l'action
            logger.exception("Diffusion temps réel impossible vers %s", groupe)

    transaction.on_commit(envoyer)


# ---------- Format des données envoyées au navigateur ----------

def message_en_dict(message):
    return {
        "id": message.pk,
        "conversation": message.conversation_id,
        "expediteur_id": message.expediteur_id,
        "auteur": str(message.expediteur),
        "initiales": message.expediteur.initiales,
        "contenu": message.contenu,
        "heure": date_format(localtime(message.date_envoi), "H:i"),
        "signale": message.signale,
        "modifie": bool(message.modifie_le),
        "fichier": {
            "url": message.url_fichier(),
            "nom": message.nom_fichier,
            "taille": message.taille_fichier,
            "image": message.est_image,
        } if message.fichier else None,
    }


def notification_en_dict(notification):
    return {
        "id": notification.pk,
        "type": notification.type,
        "titre": notification.titre,
        "message": notification.message,
        "lien": notification.lien,
        "url": notification.get_absolute_url(),
    }


# ---------- Événements ----------

def compteurs(user):
    from .services import messages_non_lus

    return {
        "notifications": user.notifications.filter(lue=False).count(),
        "messages": messages_non_lus(user),
    }


def pousser_compteurs(user):
    envoyer_au_groupe(groupe_utilisateur(user.pk), {"type": "compteurs.maj", "compteurs": compteurs(user)})


def pousser_compteurs_id(user_id):
    from apps.accounts.models import User

    user = User.objects.filter(pk=user_id).first()
    if user:
        pousser_compteurs(user)


def pousser_notification(notification):
    envoyer_au_groupe(groupe_utilisateur(notification.destinataire_id), {
        "type": "notification.nouvelle",
        "notification": notification_en_dict(notification),
        "compteurs": compteurs(notification.destinataire),
    })


def diffuser_message(message):
    envoyer_au_groupe(groupe_conversation(message.conversation_id), {
        "type": "chat.message",
        "message": message_en_dict(message),
    })


def diffuser_modification(message):
    envoyer_au_groupe(groupe_conversation(message.conversation_id), {
        "type": "chat.modifie",
        "message": message_en_dict(message),
    })


def diffuser_suppression(message, par_auteur=False):
    """Retire un message des conversations ouvertes (par son auteur ou par la modération)."""
    envoyer_au_groupe(groupe_conversation(message.conversation_id), {
        "type": "chat.supprime", "id": message.pk, "par_auteur": par_auteur,
    })


# ---------- Présence (en ligne / hors ligne) ----------
# Compteur de connexions par utilisateur : plusieurs onglets ouverts = toujours en ligne.

def _cle_presence(user_id):
    return f"presence:{user_id}"


def connexion_ouverte(user_id):
    cle = _cle_presence(user_id)
    cache.add(cle, 0, timeout=None)
    return cache.incr(cle)


def connexion_fermee(user_id):
    cle = _cle_presence(user_id)
    try:
        restant = cache.decr(cle)
    except ValueError:
        return 0
    if restant <= 0:
        cache.delete(cle)
        return 0
    return restant


def est_en_ligne(user_id):
    return (cache.get(_cle_presence(user_id)) or 0) > 0
