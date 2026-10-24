from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification

from . import services
from .fabriques import competence, creer, creer_admin, creer_offre, creer_recruteur, donner_competences
from .models import Candidature, Competence, Offre, ProfilEntreprise, SignalementOffre

S = Candidature.Statut


class ValidationEntreprisesTests(TestCase):
    def setUp(self):
        self.admin = creer_admin()
        self.recruteur = creer_recruteur("rh@attente.tn", statut=ProfilEntreprise.Statut.EN_ATTENTE)
        self.entreprise = self.recruteur.profil_entreprise
        self.client.force_login(self.admin)

    @mock.patch("apps.careers.integrations.notifier")
    def test_valider_une_entreprise(self, notifier):
        self.assertContains(self.client.get(reverse("careers:admin_entreprises")), self.entreprise.nom)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("careers:admin_valider_entreprise", args=[self.entreprise.pk]))
        self.entreprise.refresh_from_db()
        self.assertTrue(self.entreprise.est_validee)
        self.assertIsNotNone(self.entreprise.date_decision)
        notifier.assert_called_once()
        self.assertEqual(notifier.call_args.args[0], self.recruteur)
        self.assertEqual(notifier.call_args.kwargs["type"], Notification.Type.COMPTE)
        # Le recruteur peut maintenant accéder à son espace
        self.client.force_login(self.recruteur)
        self.assertContains(self.client.get(reverse("careers:tableau_recruteur")), "Espace recruteur")

    @mock.patch("apps.careers.integrations.notifier")
    def test_refus_avec_motif_obligatoire(self, notifier):
        url = reverse("careers:admin_refuser_entreprise", args=[self.entreprise.pk])
        r = self.client.post(url, {"motif": "  "}, follow=True)
        self.assertContains(r, "motif")
        self.entreprise.refresh_from_db()
        self.assertEqual(self.entreprise.statut, ProfilEntreprise.Statut.EN_ATTENTE)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {"motif": "Entreprise introuvable au registre"})
        self.entreprise.refresh_from_db()
        self.assertEqual(self.entreprise.statut, ProfilEntreprise.Statut.REFUSEE)
        self.assertEqual(self.entreprise.motif_refus, "Entreprise introuvable au registre")
        self.assertIn("introuvable", notifier.call_args.args[2])

    def test_pages_d_administration_reservees(self):
        urls = ["admin_entreprises", "admin_signalements", "admin_competences", "admin_statistiques"]
        for utilisateur in (creer("yasmine@test.tn"), creer_recruteur("rh@data.tn")):
            self.client.force_login(utilisateur)
            for nom in urls:
                self.assertEqual(self.client.get(reverse(f"careers:{nom}")).status_code, 403, nom)
            r = self.client.post(reverse("careers:admin_valider_entreprise", args=[self.entreprise.pk]))
            self.assertEqual(r.status_code, 403)
        self.entreprise.refresh_from_db()
        self.assertEqual(self.entreprise.statut, ProfilEntreprise.Statut.EN_ATTENTE)


class SignalementsEtReferentielTests(TestCase):
    def setUp(self):
        self.admin = creer_admin()
        self.recruteur = creer_recruteur("rh@data.tn")
        self.offre = creer_offre(self.recruteur, "Gagnez 5000 DT par jour")
        self.signalement = services.signaler_offre(self.offre, creer("yasmine@test.tn"), "arnaque", "Trop beau")
        self.client.force_login(self.admin)

    def traiter(self, decision):
        return self.client.post(reverse("careers:admin_traiter_signalement", args=[self.signalement.pk]),
                                {"decision": decision})

    def test_suspendre_une_offre_signalee(self):
        self.assertContains(self.client.get(reverse("careers:admin_signalements")), "Gagnez 5000 DT")
        self.traiter(SignalementOffre.Decision.SUSPENDUE)
        self.offre.refresh_from_db()
        self.signalement.refresh_from_db()
        self.assertEqual(self.offre.statut, Offre.Statut.SUSPENDUE)
        self.assertTrue(self.signalement.traite)
        self.assertEqual(self.signalement.traite_par, self.admin)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("careers:offres")), "Gagnez 5000 DT")

    def test_classer_sans_suite(self):
        self.traiter(SignalementOffre.Decision.CLASSEE)
        self.offre.refresh_from_db()
        self.assertEqual(self.offre.statut, Offre.Statut.PUBLIEE)
        r = self.client.post(reverse("careers:admin_traiter_signalement", args=[self.signalement.pk]),
                             {"decision": "suspendue"}, follow=True)
        self.assertContains(r, "déjà été traité")

    def test_ajouter_et_modifier_une_competence(self):
        self.client.post(reverse("careers:admin_competences"),
                         {"nom": "dbt", "categorie": "data", "alias": "data build tool"})
        c = Competence.objects.get(nom="dbt")
        self.client.post(reverse("careers:admin_competence_modifier", args=[c.pk]),
                         {"nom": "dbt", "categorie": "data", "alias": "data build tool, dbt core"})
        c.refresh_from_db()
        self.assertEqual(c.liste_alias(), ["data build tool", "dbt core"])


class StatistiquesTests(TestCase):
    def test_indicateurs(self):
        recruteur = creer_recruteur("rh@data.tn")
        sql, python = competence("SQL"), competence("Python")
        a = creer_offre(recruteur, "A", type_contrat="cdi", exigences=[(sql, 2, True), (python, 2, False)])
        b = creer_offre(recruteur, "B", exigences=[(sql, 1, False)])
        creer_offre(recruteur, "Expirée", date_limite=timezone.localdate() - timedelta(days=3))
        creer_offre(recruteur, "Brouillon", statut=Offre.Statut.BROUILLON, exigences=[(python, 1, False)])

        apprenants = [creer(f"apprenant{i}@test.tn") for i in range(3)]
        c1, c2, c3 = (services.postuler(a, u) for u in apprenants)
        services.postuler(b, apprenants[0])
        Candidature.objects.filter(pk=c1.pk).update(date_creation=timezone.now() - timedelta(hours=4))
        c1.refresh_from_db()
        services.changer_statut(c1, recruteur, S.EN_EXAMEN)
        services.changer_statut(c1, recruteur, S.ENTRETIEN, date_entretien=timezone.now() + timedelta(days=1),
                                lieu="Tunis")
        services.changer_statut(c1, recruteur, S.ACCEPTEE)
        services.changer_statut(c2, recruteur, S.REFUSEE)

        stats = services.statistiques()
        par_statut = dict(stats["offres_par_statut"])
        self.assertEqual(par_statut["Publiée"], 2)
        self.assertEqual(par_statut["Fermée"], 1)  # date limite passée
        self.assertEqual(par_statut["Brouillon"], 1)
        self.assertEqual(stats["nb_candidatures"], 4)
        self.assertEqual(stats["taux_acceptation"], 50)  # 1 acceptée sur 2 clôturées
        self.assertGreater(stats["delai_moyen"], timedelta(0))
        self.assertEqual([(t["competence__nom"], t["nb_offres"]) for t in stats["top_competences"]],
                         [("SQL", 2), ("Python", 1)])  # le brouillon ne compte pas
        self.assertEqual(dict(stats["par_contrat"]), {"CDI": 1, "Stage PFE": 2})

        self.client.force_login(creer_admin())
        r = self.client.get(reverse("careers:admin_statistiques"))
        self.assertContains(r, "Top 10 des compétences demandées")


class NotificationsTests(TestCase):
    def setUp(self):
        self.recruteur = creer_recruteur("rh@data.tn")
        self.apprenant = creer("yasmine@test.tn")
        donner_competences(self.apprenant, {competence("SQL"): 2})
        self.offre = creer_offre(self.recruteur)

    @mock.patch("apps.careers.integrations.notifier")
    def test_notifications_envoyees_apres_commit(self, notifier):
        with self.captureOnCommitCallbacks(execute=False) as rappels:
            candidature = services.postuler(self.offre, self.apprenant)
        notifier.assert_not_called()  # rien n'est envoyé avant la validation de la transaction
        for rappel in rappels:
            rappel()
        self.assertEqual(notifier.call_args.args[0], self.recruteur)
        self.assertEqual(notifier.call_args.args[1], "Nouvelle candidature")

        with self.captureOnCommitCallbacks(execute=True):
            services.changer_statut(candidature, self.recruteur, S.EN_EXAMEN)
        self.assertEqual(notifier.call_args.args[0], self.apprenant)
        self.assertEqual(notifier.call_args.args[1], "Candidature en examen")

        with self.captureOnCommitCallbacks(execute=True):
            services.planifier_entretien(candidature, self.recruteur, timezone.now() + timedelta(days=2), "Visio")
        self.assertEqual(notifier.call_args.args[1], "Entretien planifié")
        self.assertTrue(notifier.call_args.kwargs["email"])

    @mock.patch("apps.careers.integrations.notifier", side_effect=RuntimeError("notifications en panne"))
    def test_action_reussit_meme_si_notifier_echoue(self, notifier):
        with self.assertLogs("apps.careers.integrations", "ERROR"):
            with self.captureOnCommitCallbacks(execute=True):
                candidature = services.postuler(self.offre, self.apprenant)
        notifier.assert_called_once()
        self.assertTrue(Candidature.objects.filter(pk=candidature.pk).exists())

    def test_integration_reelle_avec_notifications(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.postuler(self.offre, self.apprenant)
        notification = Notification.objects.get(destinataire=self.recruteur, titre="Nouvelle candidature")
        self.assertEqual(notification.type, Notification.Type.SYSTEME)
        self.assertIn("/carriere/recruteur/candidatures/", notification.lien)

    def test_pas_de_notification_aux_comptes_desactives(self):
        User.objects.filter(pk=self.recruteur.pk).update(is_active=False)
        self.offre.entreprise.utilisateur.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            services.postuler(self.offre, self.apprenant)
        self.assertFalse(Notification.objects.filter(titre="Nouvelle candidature").exists())
