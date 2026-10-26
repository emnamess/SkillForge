from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from . import services
from .models import Annonce, Message, Notification, Signalement

MDP = "MotDePasse!2026"


def creer(email, role=User.Role.APPRENANT, **extra):
    return User.objects.create_user(username=User.generer_username(email), email=email, password=MDP,
                                    role=role, first_name=email.split("@")[0].capitalize(), **extra)


class AnnoncesCrudTests(TestCase):
    def setUp(self):
        self.admin = creer("admin@test.tn", User.Role.ADMINISTRATEUR)
        self.apprenant = creer("yasmine@test.tn")
        self.formateur = creer("karim@test.tn", User.Role.FORMATEUR)
        Notification.objects.all().delete()

    def creer_annonce(self, **donnees):
        self.client.force_login(self.admin)
        valeurs = {"titre": "Maintenance", "contenu": "Dimanche de 2h à 3h.", "public": "tous"}
        valeurs.update(donnees)
        self.client.post(reverse("notifications:annonce_creer"), valeurs)
        return Annonce.objects.latest("pk")

    # Create
    def test_creer_notifie_le_public_vise(self):
        annonce = self.creer_annonce(public="apprenant")
        self.assertEqual(annonce.auteur, self.admin)
        self.assertTrue(self.apprenant.notifications.filter(type="annonce", titre="Maintenance").exists())
        self.assertFalse(self.formateur.notifications.exists())

    def test_creer_pour_tous_sauf_l_auteur(self):
        self.creer_annonce()
        self.assertEqual(Notification.objects.filter(type="annonce").count(), 2)
        self.assertFalse(self.admin.notifications.exists())

    def test_formulaire_invalide(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("notifications:annonce_creer"), {"titre": "", "contenu": "", "public": "tous"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Annonce.objects.exists())

    # Read
    def test_liste_filtree_selon_le_role(self):
        self.creer_annonce(titre="Pour les formateurs", public="formateur")
        self.creer_annonce(titre="Pour tous", public="tous")
        self.client.force_login(self.apprenant)
        r = self.client.get(reverse("notifications:annonces"))
        self.assertEqual([a.titre for a in r.context["page"]], ["Pour tous"])

    def test_detail_marque_la_notification_lue(self):
        annonce = self.creer_annonce()
        self.client.force_login(self.apprenant)
        r = self.client.get(annonce.get_absolute_url())
        self.assertContains(r, "Dimanche de 2h à 3h.")
        self.assertFalse(self.apprenant.notifications.filter(lue=False).exists())

    def test_detail_interdit_hors_public(self):
        annonce = self.creer_annonce(public="formateur")
        self.client.force_login(self.apprenant)
        self.assertEqual(self.client.get(annonce.get_absolute_url()).status_code, 404)

    # Update
    def test_modifier_met_a_jour_les_notifications(self):
        annonce = self.creer_annonce()
        self.client.post(reverse("notifications:annonce_modifier", args=[annonce.pk]),
                         {"titre": "Maintenance reportée", "contenu": "Lundi.", "public": "tous"})
        annonce.refresh_from_db()
        self.assertEqual(annonce.titre, "Maintenance reportée")
        self.assertEqual(set(annonce.notifications().values_list("titre", flat=True)), {"Maintenance reportée"})

    def test_modifier_le_public_ajuste_les_destinataires(self):
        annonce = self.creer_annonce(public="apprenant")
        self.client.post(reverse("notifications:annonce_modifier", args=[annonce.pk]),
                         {"titre": "Maintenance", "contenu": "Dimanche.", "public": "formateur"})
        self.assertFalse(self.apprenant.notifications.filter(type="annonce").exists())
        self.assertTrue(self.formateur.notifications.filter(type="annonce").exists())

    # Delete
    def test_supprimer_demande_confirmation_puis_supprime(self):
        annonce = self.creer_annonce()
        url = reverse("notifications:annonce_supprimer", args=[annonce.pk])
        self.assertContains(self.client.get(url), "Supprimer définitivement")
        self.assertTrue(Annonce.objects.exists())  # un GET ne supprime rien
        self.client.post(url)
        self.assertFalse(Annonce.objects.exists())
        self.assertFalse(Notification.objects.filter(type="annonce").exists())

    # Droits
    def test_gestion_reservee_aux_administrateurs(self):
        annonce = self.creer_annonce()
        self.client.force_login(self.formateur)
        for nom, args in [("annonce_creer", []), ("annonce_modifier", [annonce.pk]), ("annonce_supprimer", [annonce.pk])]:
            self.assertEqual(self.client.get(reverse(f"notifications:{nom}", args=args)).status_code, 403, nom)
        self.assertEqual(self.client.post(reverse("notifications:annonce_supprimer", args=[annonce.pk])).status_code, 403)
        self.assertTrue(Annonce.objects.exists())


@override_settings(GEMINI_API_KEY="")
class MessagesCrudTests(TestCase):
    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.formateur = creer("karim@test.tn", User.Role.FORMATEUR)
        self.admin = creer("admin@test.tn", User.Role.ADMINISTRATEUR)
        self.conv = services.obtenir_conversation(self.apprenant, self.formateur)
        self.message = services.envoyer_message(self.conv, self.apprenant, "Bonjour, une question sur SQL")

    def test_modifier_son_message(self):
        self.client.force_login(self.apprenant)
        url = reverse("notifications:message_modifier", args=[self.message.pk])
        self.assertContains(self.client.get(url), "Bonjour, une question sur SQL")
        r = self.client.post(url, {"contenu": "Bonjour, une question sur les jointures"})
        self.assertRedirects(r, f"{self.conv.get_absolute_url()}#message-{self.message.pk}",
                             fetch_redirect_response=False)
        self.message.refresh_from_db()
        self.assertEqual(self.message.contenu, "Bonjour, une question sur les jointures")
        self.assertIsNotNone(self.message.modifie_le)

    def test_mention_modifie_affichee(self):
        services.modifier_message(self.message, self.apprenant, "Texte corrigé")
        self.client.force_login(self.formateur)
        r = self.client.get(self.conv.get_absolute_url())
        self.assertContains(r, "Texte corrigé")
        self.assertContains(r, '<span class="bulle-modifie"> · modifié</span>', html=False)

    def test_modification_moderee(self):
        self.client.force_login(self.apprenant)
        r = self.client.post(reverse("notifications:message_modifier", args=[self.message.pk]),
                             {"contenu": "espèce de connard"})
        self.assertContains(r, "Modification refusée par la modération")
        self.message.refresh_from_db()
        self.assertEqual(self.message.contenu, "Bonjour, une question sur SQL")  # l'ancien texte est gardé
        self.assertTrue(Signalement.objects.filter(decision="bloque").exists())

    def test_modification_signalee(self):
        services.modifier_message(self.message, self.apprenant, "c'est la merde")
        self.message.refresh_from_db()
        self.assertTrue(self.message.signale)
        self.assertEqual(Signalement.objects.get(message=self.message).decision, "signale")

    def test_supprimer_son_message(self):
        self.client.force_login(self.apprenant)
        r = self.client.post(reverse("notifications:message_supprimer", args=[self.message.pk]),
                             HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.json(), {"ok": True})
        self.assertFalse(Message.objects.filter(pk=self.message.pk).exists())

    def test_impossible_de_toucher_au_message_d_un_autre(self):
        self.client.force_login(self.formateur)
        modifier = reverse("notifications:message_modifier", args=[self.message.pk])
        supprimer = reverse("notifications:message_supprimer", args=[self.message.pk])
        self.assertEqual(self.client.get(modifier).status_code, 404)
        self.assertEqual(self.client.post(modifier, {"contenu": "piraté"}).status_code, 404)
        self.assertEqual(self.client.post(supprimer).status_code, 404)
        self.message.refresh_from_db()
        self.assertEqual(self.message.contenu, "Bonjour, une question sur SQL")

    def test_suppression_par_get_refusee(self):
        self.client.force_login(self.apprenant)
        r = self.client.get(reverse("notifications:message_supprimer", args=[self.message.pk]))
        self.assertEqual(r.status_code, 405)
        self.assertTrue(Message.objects.filter(pk=self.message.pk).exists())
