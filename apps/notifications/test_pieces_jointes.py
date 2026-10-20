import shutil
import tempfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from . import services
from .models import Message

MDP = "MotDePasse!2026"
DOSSIER_TEST = tempfile.mkdtemp()


def creer(email, role=User.Role.APPRENANT, **extra):
    return User.objects.create_user(username=User.generer_username(email), email=email, password=MDP,
                                    role=role, first_name=email.split("@")[0].capitalize(), **extra)


def pdf(nom="cours.pdf", taille=100):
    return SimpleUploadedFile(nom, b"%PDF" + b"0" * taille, content_type="application/pdf")


@override_settings(PRIVATE_MEDIA_ROOT=DOSSIER_TEST)
class PiecesJointesTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.formateur = creer("karim@test.tn", role=User.Role.FORMATEUR)
        self.intrus = creer("amine@test.tn")
        self.conv = services.obtenir_conversation(self.apprenant, self.formateur)

    def test_envoyer_un_fichier_seul(self):
        m = services.envoyer_message(self.conv, self.apprenant, fichier=pdf())
        self.assertEqual((m.nom_fichier, m.taille_fichier, m.contenu), ("cours.pdf", 104, ""))
        self.assertTrue(m.fichier.name.startswith(f"messagerie/{self.conv.pk}/"))
        self.assertNotIn("cours", m.fichier.name)  # nom stocké aléatoire

    def test_extension_refusee(self):
        with self.assertRaises(ValidationError):
            services.envoyer_message(self.conv, self.apprenant,
                                     fichier=SimpleUploadedFile("virus.exe", b"MZ"))
        self.assertFalse(Message.objects.exists())

    @override_settings(PIECE_JOINTE_TAILLE_MAX=50)
    def test_fichier_trop_gros_refuse(self):
        with self.assertRaises(ValidationError):
            services.envoyer_message(self.conv, self.apprenant, fichier=pdf(taille=100))

    def test_envoi_ajax_avec_fichier(self):
        self.client.force_login(self.apprenant)
        r = self.client.post(self.conv.get_absolute_url(), {"contenu": "Voici le TP", "fichier": pdf()},
                             HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"]["fichier"]["nom"], "cours.pdf")
        self.assertEqual(data["message"]["contenu"], "Voici le TP")

    def test_telechargement_reserve_aux_participants(self):
        m = services.envoyer_message(self.conv, self.apprenant, fichier=pdf())
        url = reverse("notifications:piece_jointe", args=[m.pk])

        self.client.force_login(self.formateur)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertIn("inline", r["Content-Disposition"])  # un PDF s'ouvre dans le navigateur
        self.assertEqual(b"".join(r.streaming_content)[:4], b"%PDF")

        r = self.client.get(url, {"telecharger": 1})
        self.assertIn("attachment", r["Content-Disposition"])

        self.client.force_login(self.intrus)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_apercu_dans_la_liste_des_conversations(self):
        services.envoyer_message(self.conv, self.apprenant, fichier=pdf())
        self.client.force_login(self.formateur)
        r = self.client.get(reverse("notifications:messagerie"))
        self.assertContains(r, "📎 cours.pdf")


class RechercheTests(TestCase):
    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.formateur = creer("karim@test.tn", role=User.Role.FORMATEUR)
        self.autre = creer("amine@test.tn")
        conv = services.obtenir_conversation(self.apprenant, self.formateur)
        self.m1 = services.envoyer_message(conv, self.apprenant, "Question sur les jointures SQL")
        services.envoyer_message(conv, self.formateur, "Regarde le module 3")
        conv2 = services.obtenir_conversation(self.autre, self.formateur)
        services.envoyer_message(conv2, self.autre, "Moi aussi les jointures <b>SQL</b>")

    def test_trouve_uniquement_dans_ses_conversations(self):
        self.client.force_login(self.apprenant)
        r = self.client.get(reverse("notifications:recherche"), {"q": "jointures"})
        self.assertEqual(list(r.context["resultats"]), [self.m1])
        self.assertContains(r, "<mark>jointures</mark>")

    def test_surlignage_echappe_le_html(self):
        self.client.force_login(self.formateur)
        r = self.client.get(reverse("notifications:recherche"), {"q": "sql"})
        self.assertEqual(len(r.context["resultats"]), 2)
        self.assertContains(r, "&lt;b&gt;<mark>SQL</mark>&lt;/b&gt;")
        self.assertNotContains(r, "<b>SQL</b>")

    def test_terme_trop_court(self):
        self.client.force_login(self.apprenant)
        r = self.client.get(reverse("notifications:recherche"), {"q": "s"})
        self.assertEqual(r.context["resultats"], [])
