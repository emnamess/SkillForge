from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.notifications.models import Conversation, Signalement

from .models import User


@override_settings(GEMINI_API_KEY="")
class CommandeDemoTests(TestCase):
    def lancer(self, *args):
        call_command("creer_demo", "--force", *args, stdout=StringIO())

    def test_cree_les_comptes_et_les_donnees(self):
        self.lancer()
        demo = User.objects.filter(email__endswith="@demo.skillforge.tn")
        self.assertEqual(demo.count(), 7)
        self.assertTrue(User.objects.get(username="demo_admin").est_administrateur)
        self.assertTrue(User.objects.get(username="demo_sami").en_attente_validation)
        self.assertTrue(User.objects.get(username="demo_yasmine").check_password("SkillForge2026!"))
        self.assertEqual(Conversation.objects.count(), 3)
        self.assertEqual(Signalement.objects.count(), 1)

    def test_relancer_ne_cree_pas_de_doublons(self):
        self.lancer()
        self.lancer()
        self.assertEqual(User.objects.filter(email__endswith="@demo.skillforge.tn").count(), 7)
        self.assertEqual(Conversation.objects.count(), 3)

    def test_reinitialiser(self):
        self.lancer()
        self.lancer("--reinitialiser")
        self.assertEqual(User.objects.filter(email__endswith="@demo.skillforge.tn").count(), 7)
        self.assertEqual(Conversation.objects.count(), 3)

    def test_refusee_hors_developpement(self):
        # Les tests tournent avec DEBUG=False : sans --force, la commande refuse
        with self.assertRaises(CommandError):
            call_command("creer_demo", stdout=StringIO())
