"""Tests des WebSockets (Django Channels)."""

from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import TransactionTestCase, override_settings

from apps.accounts.models import User

from . import services
from .models import Message
from .routing import websocket_urlpatterns

application = URLRouter(websocket_urlpatterns)
MDP = "MotDePasse!2026"


def creer(email, role=User.Role.APPRENANT):
    return User.objects.create_user(username=User.generer_username(email), email=email, password=MDP,
                                    role=role, first_name=email.split("@")[0].capitalize())


async def connecter(chemin, user):
    """Ouvre un WebSocket en tant qu'utilisateur (le middleware d'auth est remplacé par le scope)."""
    communicator = WebsocketCommunicator(application, chemin)
    communicator.scope["user"] = user
    connecte, code = await communicator.connect()
    return communicator, connecte, code


async def recevoir_type(communicator, type_attendu, essais=5):
    """Lit les messages jusqu'à trouver celui du type demandé."""
    return (await recevoir_types(communicator, {type_attendu}, essais))[type_attendu]


async def recevoir_types(communicator, types_attendus, essais=6):
    """Lit les messages jusqu'à avoir reçu un message de chaque type demandé (dans n'importe quel ordre)."""
    recus = {}
    for _ in range(essais):
        donnees = await communicator.receive_json_from(timeout=3)
        if donnees["type"] in types_attendus:
            recus.setdefault(donnees["type"], donnees)
        if recus.keys() == types_attendus:
            return recus
    raise AssertionError(f"Types manquants : {types_attendus - recus.keys()}")


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class TempsReelTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.apprenant = creer("yasmine@test.tn")
        self.formateur = creer("karim@test.tn", role=User.Role.FORMATEUR)
        self.intrus = creer("amine@test.tn")
        self.conv = services.obtenir_conversation(self.apprenant, self.formateur)
        self.chemin = f"/ws/messagerie/{self.conv.pk}/"

    async def test_anonyme_refuse(self):
        _, connecte, code = await connecter("/ws/notifications/", AnonymousUser())
        self.assertFalse(connecte)
        self.assertEqual(code, 4403)

    async def test_non_participant_refuse(self):
        _, connecte, code = await connecter(self.chemin, self.intrus)
        self.assertFalse(connecte)
        self.assertEqual(code, 4403)

    async def test_message_livre_instantanement(self):
        ws_apprenant, ok1, _ = await connecter(self.chemin, self.apprenant)
        ws_formateur, ok2, _ = await connecter(self.chemin, self.formateur)
        self.assertTrue(ok1 and ok2)

        await ws_apprenant.send_json_to({"action": "envoyer", "contenu": "Bonjour Karim !", "ref": "1"})

        recu = await recevoir_type(ws_formateur, "message")
        self.assertEqual(recu["message"]["contenu"], "Bonjour Karim !")
        self.assertFalse(recu["message"]["moi"])

        recus = await recevoir_types(ws_apprenant, {"message", "envoye"})
        self.assertTrue(recus["message"]["message"]["moi"])
        self.assertEqual(recus["envoye"]["ref"], "1")

        # Le formateur avait la conversation ouverte : le message est marqué lu
        await ws_formateur.receive_nothing(timeout=0.5)
        lu = await database_sync_to_async(lambda: Message.objects.get().lu)()
        self.assertTrue(lu)

        await ws_apprenant.disconnect()
        await ws_formateur.disconnect()

    async def test_indicateur_en_train_d_ecrire(self):
        ws_apprenant, _, _ = await connecter(self.chemin, self.apprenant)
        ws_formateur, _, _ = await connecter(self.chemin, self.formateur)
        await ws_apprenant.send_json_to({"action": "ecrit"})
        ecrit = await recevoir_type(ws_formateur, "ecrit")
        self.assertEqual(ecrit["nom"], "Yasmine")
        await ws_apprenant.disconnect()
        await ws_formateur.disconnect()

    async def test_presence_en_ligne(self):
        ws_conv, _, _ = await connecter(self.chemin, self.apprenant)
        statut = await recevoir_type(ws_conv, "presence")
        self.assertFalse(statut["en_ligne"])

        # Le formateur ouvre une page de l'espace connecté
        ws_notif, ok, _ = await connecter("/ws/notifications/", self.formateur)
        self.assertTrue(ok)
        statut = await recevoir_type(ws_conv, "presence")
        self.assertTrue(statut["en_ligne"])

        await ws_notif.disconnect()
        statut = await recevoir_type(ws_conv, "presence")
        self.assertFalse(statut["en_ligne"])
        await ws_conv.disconnect()

    async def test_notification_poussee_dans_la_cloche(self):
        ws, ok, _ = await connecter("/ws/notifications/", self.apprenant)
        self.assertTrue(ok)
        await database_sync_to_async(services.notifier)(self.apprenant, "Quiz corrigé", "16/20")
        donnees = await recevoir_type(ws, "notification")
        self.assertEqual(donnees["notification"]["titre"], "Quiz corrigé")
        self.assertGreaterEqual(donnees["compteurs"]["notifications"], 1)
        await ws.disconnect()
