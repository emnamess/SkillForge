from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from . import services
from .moderation import ResultatModeration, moderer, moderer_par_regles
from .models import Message, Notification, Signalement

MDP = "MotDePasse!2026"


def creer(email, role=User.Role.APPRENANT, **extra):
    return User.objects.create_user(username=User.generer_username(email), email=email, password=MDP,
                                    role=role, first_name=email.split("@")[0].capitalize(), **extra)


class ReglesLocalesTests(TestCase):
    def test_message_normal_autorise(self):
        self.assertTrue(moderer_par_regles("Bonjour, j'ai une question sur les jointures SQL").autorise)

    def test_code_informatique_autorise(self):
        for texte in ["import pandas as pd", "DROP TABLE clients;", "il faut kill le process"]:
            self.assertTrue(moderer_par_regles(texte).autorise, texte)

    def test_insulte_bloquee_meme_avec_accents_et_majuscules(self):
        self.assertTrue(moderer_par_regles("Espèce d'ENCULÉ").bloque)

    def test_vulgarite_signalee(self):
        self.assertEqual(moderer_par_regles("c'est la merde ce module").decision, "signale")

    def test_insultes_contournees_bloquees(self):
        for texte in ["fuck you", "fuuuuck", "F*CK", "f u c k", "f.u.c.k", "connnnard", "motherfucker",
                      "kahba", "9a7ba", "nique ta mère"]:
            self.assertTrue(moderer_par_regles(texte).bloque, texte)

    def test_insulte_adressee_bloquee(self):
        for texte in ["tu es un merde", "sale con", "t'es vraiment idiot", "you are stupid",
                      "espèce de crétin", "m3rde t es un con"]:
            self.assertTrue(moderer_par_regles(texte).bloque, texte)

    def test_lettres_repetees_reconnues(self):
        self.assertEqual(moderer_par_regles("merdeeeee").decision, "signale")

    def test_faux_positifs_evites(self):
        for texte in ["la dispute entre les deux tables", "je suis content du cours", "tu es vraiment doué",
                      "concaténer deux chaînes", "la salle de cours", "You can use a LEFT JOIN", "Scunthorpe",
                      "class Assignment", "le constructeur", "SELECT a, b, c FROM t", "plan A B C pour le projet"]:
            self.assertTrue(moderer_par_regles(texte).autorise, texte)

    def test_numero_de_telephone_signale(self):
        r = moderer_par_regles("Appelle-moi au 22 345 678")
        self.assertEqual((r.decision, r.categorie), ("signale", "donnees_personnelles"))


@override_settings(GEMINI_API_KEY="cle-de-test", MODERATION_IA_ACTIVE=True)
class GeminiTests(TestCase):
    def setUp(self):
        cache.clear()

    @mock.patch("apps.notifications.moderation.moderer_par_gemini")
    def test_decision_de_gemini_utilisee(self, gemini):
        gemini.return_value = ResultatModeration("bloque", "harcelement", "Message harcelant.", "gemini")
        r = moderer("tu vas voir à la sortie du cours")
        self.assertEqual((r.decision, r.source), ("bloque", "gemini"))

    @mock.patch("apps.notifications.moderation.moderer_par_gemini")
    def test_gemini_decide_meme_pour_une_insulte_evidente(self, gemini):
        gemini.return_value = ResultatModeration("bloque", "insulte", "Insulte.", "gemini")
        r = moderer("connard")
        gemini.assert_called_once()
        self.assertEqual(r.source, "gemini")

    @mock.patch("apps.notifications.moderation.moderer_par_gemini", side_effect=TimeoutError)
    def test_repli_sur_les_regles_si_gemini_echoue(self, gemini):
        r = moderer("Bonjour")
        self.assertEqual((r.decision, r.source), ("autorise", "regles"))
        self.assertTrue(moderer("connard").bloque)  # les règles locales protègent quand même

    @mock.patch("apps.notifications.moderation.moderer_par_gemini")
    def test_chaque_decision_est_journalisee_avec_sa_source(self, gemini):
        gemini.return_value = ResultatModeration("bloque", "insulte", "Insulte.", "gemini")
        with self.assertLogs("apps.notifications.moderation", "INFO") as journal:
            moderer("you are useless")
            moderer("you are useless")
        self.assertIn("GEMINI   BLOQUE", journal.output[0])
        self.assertIn("CACHE    BLOQUE", journal.output[1])

    @mock.patch("apps.notifications.moderation.moderer_par_gemini")
    def test_pause_quand_le_quota_est_depasse(self, gemini):
        quota = Exception("429 RESOURCE_EXHAUSTED. Please retry in 25.6s.")
        quota.code = 429
        gemini.side_effect = quota
        with self.assertLogs("apps.notifications.moderation", "WARNING") as journal:
            moderer("Bonjour")
            moderer("Salut")  # pendant la pause, Gemini n'est plus appelé
        self.assertEqual(gemini.call_count, 1)
        self.assertTrue(any("pause de 26 s" in ligne for ligne in journal.output))

    def test_client_gemini_conserve(self):
        # Un client recréé (et détruit) à chaque appel fermait sa connexion avant la requête
        from .moderation import _client_gemini
        self.assertIs(_client_gemini(), _client_gemini())

    @mock.patch("apps.notifications.moderation.moderer_par_gemini")
    def test_resultat_mis_en_cache(self, gemini):
        gemini.return_value = ResultatModeration("autorise", source="gemini")
        moderer("Merci beaucoup !")
        moderer("Merci beaucoup !")
        self.assertEqual(gemini.call_count, 1)

    @override_settings(GEMINI_API_KEY="")
    @mock.patch("apps.notifications.moderation.moderer_par_gemini")
    def test_sans_cle_pas_d_appel(self, gemini):
        moderer("Bonjour")
        gemini.assert_not_called()

    @mock.patch("apps.notifications.moderation._client_gemini")
    def test_appel_gemini_et_lecture_de_la_reponse(self, client):
        from .moderation import AnalyseModeration, moderer_par_gemini

        reponse = mock.Mock(parsed=AnalyseModeration(decision="signale", categorie="triche",
                                                     raison=" Demande de réponses au quiz. "))
        client.return_value.models.generate_content.return_value = reponse
        r = moderer_par_gemini("envoie-moi les réponses du quiz")
        self.assertEqual((r.decision, r.categorie, r.raison), ("signale", "triche", "Demande de réponses au quiz."))
        config = client.return_value.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.response_mime_type, "application/json")


@override_settings(GEMINI_API_KEY="")
class EnvoiModereTests(TestCase):
    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.formateur = creer("karim@test.tn", role=User.Role.FORMATEUR)
        self.admin = creer("admin@test.tn", role=User.Role.ADMINISTRATEUR)
        self.conv = services.obtenir_conversation(self.apprenant, self.formateur)
        Notification.objects.all().delete()

    def test_message_bloque_non_envoye_mais_trace(self):
        with self.assertRaises(services.MessageBloque) as ctx:
            services.envoyer_message(self.conv, self.apprenant, "espèce de connard")
        self.assertFalse(Message.objects.exists())
        s = Signalement.objects.get()
        self.assertEqual((s.decision, s.message, s.auteur), ("bloque", None, self.apprenant))
        self.assertTrue(ctx.exception.resultat.raison)
        self.assertTrue(self.admin.notifications.filter(titre__contains="bloqué").exists())
        self.assertFalse(self.formateur.notifications.exists())

    def test_message_signale_envoye_et_trace(self):
        m = services.envoyer_message(self.conv, self.apprenant, "c'est la merde ce quiz")
        self.assertTrue(m.signale)
        self.assertEqual(Signalement.objects.get().message, m)
        self.assertTrue(self.admin.notifications.filter(titre__contains="signalé").exists())

    def test_message_normal_sans_signalement(self):
        services.envoyer_message(self.conv, self.apprenant, "Merci pour la séance !")
        self.assertFalse(Signalement.objects.exists())

    def test_vue_affiche_l_erreur_de_moderation(self):
        self.client.force_login(self.apprenant)
        r = self.client.post(self.conv.get_absolute_url(), {"contenu": "connard"}, follow=True)
        self.assertContains(r, "Message bloqué par la modération")

    def test_vue_ajax_renvoie_l_erreur_en_json(self):
        self.client.force_login(self.apprenant)
        r = self.client.post(self.conv.get_absolute_url(), {"contenu": "connard"},
                             HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 400)
        self.assertIn("modération", r.json()["erreur"])


@override_settings(GEMINI_API_KEY="")
class PageModerationTests(TestCase):
    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.formateur = creer("karim@test.tn", role=User.Role.FORMATEUR)
        self.admin = creer("admin@test.tn", role=User.Role.ADMINISTRATEUR)
        conv = services.obtenir_conversation(self.apprenant, self.formateur)
        self.message = services.envoyer_message(conv, self.apprenant, "c'est la merde")
        self.signalement = Signalement.objects.get()

    def test_reservee_aux_administrateurs(self):
        self.client.force_login(self.formateur)
        self.assertEqual(self.client.get(reverse("notifications:moderation")).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("notifications:moderation"))
        self.assertContains(r, "c&#x27;est la merde")
        self.assertEqual(r.context["stats"]["a_traiter"], 1)

    def traiter(self, signalement, action):
        self.client.force_login(self.admin)
        return self.client.post(reverse("notifications:traiter_signalement", args=[signalement.pk]),
                                {"action": action}, follow=True)

    def bloquer(self, texte="espèce de connard"):
        conv = services.obtenir_conversation(self.apprenant, self.formateur)
        with self.assertRaises(services.MessageBloque):
            services.envoyer_message(conv, self.apprenant, texte)
        return Signalement.objects.filter(decision="bloque").latest("date_creation")

    def test_retablir_le_message(self):
        self.traiter(self.signalement, "retabli")
        self.message.refresh_from_db()
        self.signalement.refresh_from_db()
        self.assertFalse(self.message.signale)
        self.assertEqual((self.signalement.traite, self.signalement.traite_par, self.signalement.action),
                         (True, self.admin, "retabli"))

    def test_supprimer_le_message(self):
        r = self.traiter(self.signalement, "supprime")
        self.assertFalse(Message.objects.filter(pk=self.message.pk).exists())
        s = Signalement.objects.get()
        self.assertEqual((s.traite, s.action), (True, "supprime"))  # la trace est conservée
        self.assertTrue(self.apprenant.notifications.filter(titre="Message supprimé par la modération").exists())
        self.assertContains(r, "Le message a été supprimé de la conversation.")

    def test_faux_positif_envoie_le_message_bloque(self):
        s = self.bloquer()
        self.assertFalse(Message.objects.filter(contenu="espèce de connard").exists())
        self.traiter(s, "envoye")
        s.refresh_from_db()
        m = Message.objects.get(contenu="espèce de connard")
        self.assertEqual((s.message, s.action, m.signale), (m, "envoye", False))
        self.assertTrue(self.apprenant.notifications.filter(titre="Votre message a été vérifié et envoyé").exists())
        self.assertTrue(self.formateur.notifications.filter(type="message").exists())  # le destinataire est prévenu

    def test_confirmer_le_blocage(self):
        s = self.bloquer()
        self.traiter(s, "confirme")
        s.refresh_from_db()
        self.assertEqual((s.traite, s.action, s.message), (True, "confirme", None))
        self.assertFalse(Message.objects.filter(contenu="espèce de connard").exists())

    def test_avertir_l_auteur(self):
        s = self.bloquer()
        self.traiter(s, "averti")
        avertissement = self.apprenant.notifications.get(titre="Avertissement de la modération")
        self.assertIn("espèce de connard", avertissement.message)

    def test_page_indique_le_destinataire_et_la_livraison(self):
        self.bloquer()
        self.client.force_login(self.admin)
        r = self.client.get(reverse("notifications:moderation"))
        self.assertContains(r, "non livré")
        self.assertContains(r, "Faux positif : envoyer")
        self.assertContains(r, str(self.formateur))
