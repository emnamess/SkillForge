from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User

from . import services
from .models import Conversation, Message, Notification, Rappel

MDP = "MotDePasse!2026"


def creer(email, role=User.Role.APPRENANT, **extra):
    return User.objects.create_user(username=User.generer_username(email), email=email, password=MDP,
                                    role=role, first_name=email.split("@")[0].capitalize(), **extra)


class NotifierTests(TestCase):
    def setUp(self):
        self.user = creer("yasmine@test.tn")
        Notification.objects.all().delete()  # ignore la notification de bienvenue

    def test_notifier_un_utilisateur(self):
        services.notifier(self.user, "Quiz corrigé", "16/20", type=Notification.Type.QUIZ, lien="/quiz/1/")
        n = self.user.notifications.get()
        self.assertEqual((n.titre, n.type, n.lue), ("Quiz corrigé", "quiz", False))

    def test_notifier_plusieurs_et_ignorer_inactifs(self):
        inactif = creer("omar@test.tn", is_active=False)
        Notification.objects.all().delete()
        services.notifier([self.user, inactif], "Annonce")
        self.assertEqual(Notification.objects.count(), 1)

    def test_notifier_par_email(self):
        services.notifier(self.user, "Séance confirmée", "Jeudi 14h", lien="/mentorat/1/", email=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Séance confirmée", mail.outbox[0].subject)
        self.assertIn("http://127.0.0.1:8000/mentorat/1/", mail.outbox[0].body)


class SignauxTests(TestCase):
    def test_bienvenue_a_l_inscription(self):
        u = creer("yasmine@test.tn")
        self.assertTrue(u.notifications.filter(titre__startswith="Bienvenue").exists())

    def test_admins_alertes_pour_formateur_en_attente(self):
        admin = creer("admin@test.tn", role=User.Role.ADMINISTRATEUR)
        creer("karim@test.tn", role=User.Role.FORMATEUR, est_valide=False)
        self.assertTrue(admin.notifications.filter(titre="Nouveau formateur à valider").exists())

    def test_formateur_notifie_a_la_validation(self):
        f = creer("karim@test.tn", role=User.Role.FORMATEUR, est_valide=False)
        f.est_valide = True
        f.save()
        self.assertTrue(f.notifications.filter(titre="Votre compte formateur est validé").exists())
        self.assertEqual(len(mail.outbox), 1)

    def test_pas_de_notification_de_validation_si_rien_ne_change(self):
        f = creer("karim@test.tn", role=User.Role.FORMATEUR)
        f.first_name = "Karim"
        f.save()
        self.assertFalse(f.notifications.filter(titre="Votre compte formateur est validé").exists())


class NotificationsVuesTests(TestCase):
    def setUp(self):
        self.user = creer("yasmine@test.tn")
        self.autre = creer("omar@test.tn")
        Notification.objects.all().delete()
        self.n = services.notifier(self.user, "Test", lien="/notifications/messagerie/")[0]
        self.client.force_login(self.user)

    def test_liste_et_filtre_non_lues(self):
        services.notifier(self.user, "Déjà lue")
        Notification.objects.filter(titre="Déjà lue").update(lue=True)
        r = self.client.get(reverse("notifications:index"), {"filtre": "non-lues"})
        self.assertEqual([n.titre for n in r.context["page"]], ["Test"])

    def test_ouvrir_marque_lue_et_redirige(self):
        r = self.client.get(reverse("notifications:ouvrir", args=[self.n.pk]))
        self.assertRedirects(r, "/notifications/messagerie/")
        self.n.refresh_from_db()
        self.assertTrue(self.n.lue)

    def test_lien_externe_ignore(self):
        self.n.lien = "https://malveillant.example.com/"
        self.n.save()
        r = self.client.get(reverse("notifications:ouvrir", args=[self.n.pk]))
        self.assertRedirects(r, reverse("notifications:index"))

    def test_impossible_d_ouvrir_la_notification_d_un_autre(self):
        self.client.force_login(self.autre)
        self.assertEqual(self.client.get(reverse("notifications:ouvrir", args=[self.n.pk])).status_code, 404)

    def test_tout_marquer_lu(self):
        services.notifier(self.user, "Deux")
        self.client.post(reverse("notifications:tout_marquer_lu"))
        self.assertFalse(self.user.notifications.filter(lue=False).exists())

    def test_supprimer(self):
        self.client.post(reverse("notifications:supprimer", args=[self.n.pk]))
        self.assertFalse(Notification.objects.filter(pk=self.n.pk).exists())

    def test_api_compteurs(self):
        r = self.client.get(reverse("notifications:api_compteurs"))
        self.assertEqual(r.json(), {"notifications": 1, "messages": 0})

    def test_cloche_affichee_dans_l_espace_connecte(self):
        r = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(r, "data-cloche")
        self.assertEqual(r.context["nb_notifications_non_lues"], 1)


@override_settings(GEMINI_API_KEY="")
class MessagerieServicesTests(TestCase):
    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.apprenant2 = creer("amine@test.tn")
        self.formateur = creer("karim@test.tn", role=User.Role.FORMATEUR)
        Notification.objects.all().delete()

    def test_regles_d_ecriture(self):
        self.assertTrue(services.peut_ecrire_a(self.apprenant, self.formateur))
        self.assertTrue(services.peut_ecrire_a(self.formateur, self.apprenant))
        self.assertFalse(services.peut_ecrire_a(self.apprenant, self.apprenant2))
        self.assertFalse(services.peut_ecrire_a(self.apprenant, self.apprenant))

    def test_une_seule_conversation_par_paire(self):
        c1 = services.obtenir_conversation(self.apprenant, self.formateur)
        c2 = services.obtenir_conversation(self.formateur, self.apprenant)
        self.assertEqual(c1, c2)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_envoyer_message_notifie_une_seule_fois(self):
        c = services.obtenir_conversation(self.apprenant, self.formateur)
        services.envoyer_message(c, self.apprenant, "Bonjour")
        services.envoyer_message(c, self.apprenant, "Vous êtes là ?")
        self.assertEqual(self.formateur.notifications.filter(type="message").count(), 1)
        self.assertEqual(services.messages_non_lus(self.formateur), 2)
        self.assertEqual(services.messages_non_lus(self.apprenant), 0)

    def test_non_participant_ne_peut_pas_ecrire(self):
        c = services.obtenir_conversation(self.apprenant, self.formateur)
        with self.assertRaises(PermissionDenied):
            services.envoyer_message(c, self.apprenant2, "Intrus")


@override_settings(GEMINI_API_KEY="")
class MessagerieVuesTests(TestCase):
    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.formateur = creer("karim@test.tn", role=User.Role.FORMATEUR)
        self.intrus = creer("amine@test.tn")
        self.conv = services.obtenir_conversation(self.apprenant, self.formateur)
        services.envoyer_message(self.conv, self.formateur, "Bonjour Yasmine !")

    def test_boite_de_reception(self):
        self.client.force_login(self.apprenant)
        r = self.client.get(reverse("notifications:messagerie"))
        conv = r.context["conversations"][0]
        self.assertEqual((conv.nb_non_lus, conv.dernier_message), (1, "Bonjour Yasmine !"))

    def test_ouvrir_conversation_marque_les_messages_lus(self):
        self.client.force_login(self.apprenant)
        r = self.client.get(self.conv.get_absolute_url())
        self.assertContains(r, "Bonjour Yasmine !")
        self.assertEqual(services.messages_non_lus(self.apprenant), 0)

    def test_repondre(self):
        self.client.force_login(self.apprenant)
        r = self.client.post(self.conv.get_absolute_url(), {"contenu": "Merci !"})
        self.assertRedirects(r, self.conv.get_absolute_url())
        self.assertTrue(Message.objects.filter(expediteur=self.apprenant, contenu="Merci !").exists())

    def test_message_vide_refuse(self):
        self.client.force_login(self.apprenant)
        self.client.post(self.conv.get_absolute_url(), {"contenu": "   "})
        self.assertEqual(self.conv.messages.count(), 1)

    def test_conversation_d_autrui_interdite(self):
        self.client.force_login(self.intrus)
        self.assertEqual(self.client.get(self.conv.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(self.conv.get_absolute_url(), {"contenu": "x"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("notifications:api_messages", args=[self.conv.pk])).status_code,
                         404)

    def test_nouvelle_conversation(self):
        autre_formateur = creer("leila@test.tn", role=User.Role.FORMATEUR)
        self.client.force_login(self.apprenant)
        r = self.client.post(reverse("notifications:nouvelle_conversation"),
                             {"destinataire": autre_formateur.pk, "contenu": "Une question sur SQL"})
        conv = Conversation.objects.entre(self.apprenant, autre_formateur).get()
        self.assertRedirects(r, conv.get_absolute_url())

    def test_nouvelle_conversation_reutilise_l_existante(self):
        self.client.force_login(self.apprenant)
        self.client.post(reverse("notifications:nouvelle_conversation"),
                         {"destinataire": self.formateur.pk, "contenu": "Encore moi"})
        self.assertEqual(Conversation.objects.count(), 1)

    def test_apprenant_ne_peut_pas_ecrire_a_un_apprenant(self):
        self.client.force_login(self.apprenant)
        r = self.client.post(reverse("notifications:nouvelle_conversation"),
                             {"destinataire": self.intrus.pk, "contenu": "Salut"})
        self.assertEqual(r.status_code, 200)  # destinataire absent de la liste autorisée
        self.assertFalse(Conversation.objects.entre(self.apprenant, self.intrus).exists())

    def test_destinataire_preselectionne(self):
        self.client.force_login(self.apprenant)
        r = self.client.get(reverse("notifications:nouvelle_conversation"), {"a": self.formateur.pk})
        self.assertEqual(str(r.context["form"]["destinataire"].value()), str(self.formateur.pk))

    def test_api_messages_renvoie_les_nouveaux(self):
        premier = self.conv.messages.first()
        services.envoyer_message(self.conv, self.formateur, "<b>Deuxième</b>")
        self.client.force_login(self.apprenant)
        r = self.client.get(reverse("notifications:api_messages", args=[self.conv.pk]), {"apres": premier.pk})
        data = r.json()["messages"]
        self.assertEqual([m["contenu"] for m in data], ["<b>Deuxième</b>"])
        self.assertFalse(data[0]["moi"])


class RappelsTests(TestCase):
    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.formateur = creer("karim@test.tn", role=User.Role.FORMATEUR)
        # N'importe quel modèle peut servir d'objet ; ici un utilisateur joue le rôle de la séance
        self.seance = self.formateur
        Notification.objects.all().delete()

    def test_planifier_rappels_seance(self):
        date = timezone.now() + timedelta(days=2)
        rappels = services.planifier_rappels_seance(self.seance, [self.apprenant, self.formateur], date,
                                                    titre="Mentorat UML")
        self.assertEqual(len(rappels), 4)  # 2 délais × 2 participants
        self.assertEqual({r.date_envoi for r in rappels},
                         {date - timedelta(hours=24), date - timedelta(minutes=15)})

    def test_rappels_passes_ignores(self):
        date = timezone.now() + timedelta(hours=2)  # le rappel « 24 h avant » est déjà passé
        rappels = services.planifier_rappels_seance(self.seance, [self.apprenant], date, titre="UML")
        self.assertEqual(len(rappels), 1)

    def test_replanifier_remplace_les_anciens(self):
        date = timezone.now() + timedelta(days=2)
        services.planifier_rappels_seance(self.seance, [self.apprenant], date, titre="UML")
        services.planifier_rappels_seance(self.seance, [self.apprenant], date + timedelta(days=1), titre="UML")
        self.assertEqual(Rappel.objects.count(), 2)

    def test_annuler_rappels(self):
        services.planifier_rappels_seance(self.seance, [self.apprenant], timezone.now() + timedelta(days=2),
                                          titre="UML")
        self.assertEqual(services.annuler_rappels(self.seance), 2)
        self.assertFalse(Rappel.objects.exists())

    def test_envoyer_rappels_dus_une_seule_fois(self):
        services.planifier_rappel(self.apprenant, timezone.now() - timedelta(minutes=1), "Rappel · UML",
                                  "Dans 15 minutes")
        services.planifier_rappel(self.apprenant, timezone.now() + timedelta(hours=1), "Plus tard")
        self.assertEqual(services.envoyer_rappels_dus(), 1)
        self.assertEqual(services.envoyer_rappels_dus(), 0)
        n = self.apprenant.notifications.get()
        self.assertEqual((n.titre, n.type), ("Rappel · UML", "rappel"))
        self.assertEqual(len(mail.outbox), 1)

    def test_commande_envoyer_rappels(self):
        services.planifier_rappel(self.apprenant, timezone.now() - timedelta(minutes=1), "Rappel")
        sortie = StringIO()
        call_command("envoyer_rappels", stdout=sortie)
        self.assertIn("1 rappel(s) envoyé(s)", sortie.getvalue())
