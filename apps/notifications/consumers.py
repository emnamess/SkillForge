"""Consumers WebSocket : l'équivalent des vues pour les connexions temps réel."""

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.exceptions import PermissionDenied, ValidationError

from . import realtime
from .models import Conversation
from .moderation import moderer
from .services import MessageBloque, envoyer_message

FERMETURE_NON_AUTORISE = 4403


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """Ouvert sur toutes les pages de l'espace connecté : cloche, compteurs et présence."""

    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close(code=FERMETURE_NON_AUTORISE)
            return
        self.groupe = realtime.groupe_utilisateur(self.user.pk)
        await self.channel_layer.group_add(self.groupe, self.channel_name)
        await self.accept()

        if await database_sync_to_async(realtime.connexion_ouverte)(self.user.pk) == 1:
            await self.annoncer_presence(True)

    async def disconnect(self, code):
        if not getattr(self, "groupe", None):
            return
        await self.channel_layer.group_discard(self.groupe, self.channel_name)
        if await database_sync_to_async(realtime.connexion_fermee)(self.user.pk) == 0:
            await self.annoncer_presence(False)

    async def annoncer_presence(self, en_ligne):
        """Prévient les conversations de l'utilisateur qu'il vient d'arriver ou de partir."""
        ids = await database_sync_to_async(
            lambda: list(Conversation.objects.pour(self.user).values_list("pk", flat=True)))()
        for conversation_id in ids:
            await self.channel_layer.group_send(realtime.groupe_conversation(conversation_id), {
                "type": "presence.maj", "user_id": self.user.pk, "en_ligne": en_ligne,
            })

    # Événements reçus du groupe et transmis au navigateur

    async def notification_nouvelle(self, event):
        await self.send_json({"type": "notification", "notification": event["notification"],
                              "compteurs": event["compteurs"]})

    async def compteurs_maj(self, event):
        await self.send_json({"type": "compteurs", "compteurs": event["compteurs"]})


class ConversationConsumer(AsyncJsonWebsocketConsumer):
    """Une conversation ouverte : envoi des messages, « en train d'écrire » et présence."""

    async def connect(self):
        self.user = self.scope["user"]
        self.conversation_id = int(self.scope["url_route"]["kwargs"]["pk"])
        self.groupe = None

        self.interlocuteur_id = await self.verifier_acces()
        if self.interlocuteur_id is None:
            await self.close(code=FERMETURE_NON_AUTORISE)
            return

        self.groupe = realtime.groupe_conversation(self.conversation_id)
        await self.channel_layer.group_add(self.groupe, self.channel_name)
        await self.accept()
        await self.send_json({
            "type": "presence",
            "user_id": self.interlocuteur_id,
            "en_ligne": await database_sync_to_async(realtime.est_en_ligne)(self.interlocuteur_id),
        })

    async def disconnect(self, code):
        if self.groupe:
            await self.channel_layer.group_discard(self.groupe, self.channel_name)

    @database_sync_to_async
    def verifier_acces(self):
        """Renvoie l'id de l'interlocuteur, ou None si l'utilisateur n'a pas accès."""
        if not self.user.is_authenticated:
            return None
        conversation = Conversation.objects.pour(self.user).filter(pk=self.conversation_id).first()
        if conversation is None:
            return None
        autre = conversation.interlocuteur(self.user)
        return autre.pk if autre else 0

    async def receive_json(self, contenu, **kwargs):
        action = contenu.get("action")
        if action == "envoyer":
            await self.envoyer(str(contenu.get("contenu", ""))[:2000], contenu.get("ref"))
        elif action == "ecrit":
            await self.channel_layer.group_send(self.groupe, {
                "type": "chat.ecrit", "user_id": self.user.pk, "nom": self.user.first_name or str(self.user),
            })

    async def envoyer(self, texte, ref):
        try:
            # L'appel à l'IA (réseau, ~1 s) tourne dans un thread à part
            resultat = await sync_to_async(moderer, thread_sensitive=False)(texte)
            await database_sync_to_async(self._envoyer)(texte, resultat)
        except MessageBloque as e:
            await self.send_json({"type": "erreur", "ref": ref, "bloque": True,
                                  "categorie": e.resultat.libelle_categorie,
                                  "source": e.resultat.libelle_source,
                                  "message": e.resultat.raison or "Message refusé par la modération."})
        except (ValidationError, PermissionDenied) as e:
            message = e.messages[0] if isinstance(e, ValidationError) else str(e)
            await self.send_json({"type": "erreur", "ref": ref, "message": message})
        else:
            await self.send_json({"type": "envoye", "ref": ref})

    def _envoyer(self, texte, resultat):
        conversation = Conversation.objects.get(pk=self.conversation_id)
        envoyer_message(conversation, self.user, texte, resultat_moderation=resultat)

    @database_sync_to_async
    def marquer_lue(self):
        conversation = Conversation.objects.get(pk=self.conversation_id)
        if conversation.marquer_lue(self.user):
            realtime.pousser_compteurs(self.user)

    # Événements reçus du groupe et transmis au navigateur

    async def chat_message(self, event):
        message = event["message"]
        moi = message["expediteur_id"] == self.user.pk
        await self.send_json({"type": "message", "message": {**message, "moi": moi}})
        if not moi:
            # Le destinataire a la conversation sous les yeux : le message est lu
            await self.marquer_lue()

    async def chat_ecrit(self, event):
        if event["user_id"] != self.user.pk:
            await self.send_json({"type": "ecrit", "nom": event["nom"]})

    async def presence_maj(self, event):
        if event["user_id"] != self.user.pk:
            await self.send_json({"type": "presence", "user_id": event["user_id"], "en_ligne": event["en_ligne"]})
