from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification, Rappel

from .models import Disponibilite, SeanceMentorat
from .services import CreneauIndisponible, creneaux_disponibles, reserver_seance


def creer(role, username, **kwargs):
    return User.objects.create_user(
        username=username, email=f"{username}@test.skillforge.tn", password="testpass123", role=role, **kwargs,
    )


class MentoringTests(TestCase):
    def setUp(self):
        self.apprenant = creer(User.Role.APPRENANT, "apprenant")
        self.autre_apprenant = creer(User.Role.APPRENANT, "autre")
        self.formateur = creer(User.Role.FORMATEUR, "formateur")
        self.formateur_non_valide = creer(User.Role.FORMATEUR, "attente", est_valide=False)
        self.admin = creer(User.Role.ADMINISTRATEUR, "admin")
        self.debut = (timezone.now() + timedelta(days=3)).replace(minute=0, second=0, microsecond=0)
        self.disponibilite = Disponibilite.objects.create(
            formateur=self.formateur, debut=self.debut, fin=self.debut + timedelta(hours=3), duree_seance=60,
        )

    def test_apprenant_reserve_et_rappels_sont_programmes(self):
        seance = reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Django")
        self.assertEqual(seance.statut, SeanceMentorat.Statut.EN_ATTENTE)
        self.assertEqual(seance.formateur, self.formateur)
        self.assertFalse(Rappel.objects.filter(object_id=seance.pk, envoye=False).exists())

    def test_creneau_reserve_disparait_de_la_liste(self):
        reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Django")
        self.assertNotIn(self.debut, creneaux_disponibles(self.disponibilite))
        self.assertNotIn(self.debut + timedelta(minutes=15), creneaux_disponibles(self.disponibilite))
        self.assertIn(self.debut + timedelta(hours=1), creneaux_disponibles(self.disponibilite))

    def test_apprenant_peut_choisir_un_debut_sur_un_quart_d_heure(self):
        debut = self.debut + timedelta(minutes=15)
        self.assertIn(debut, creneaux_disponibles(self.disponibilite))
        seance = reserver_seance(self.disponibilite.pk, self.apprenant, debut, "Créneau flexible")
        self.assertEqual(seance.debut, debut)

    def test_apprenant_ne_peut_pas_reserver_deux_seances_qui_se_chevauchent(self):
        reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Première")
        with self.assertRaises(CreneauIndisponible):
            reserver_seance(self.disponibilite.pk, self.apprenant, self.debut + timedelta(minutes=30), "Deuxième")

    def test_creneau_exact_en_double_est_refuse(self):
        reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Première")
        with self.assertRaises(CreneauIndisponible):
            reserver_seance(self.disponibilite.pk, self.autre_apprenant, self.debut, "Deuxième")

    def test_horaire_en_dehors_de_la_disponibilite_est_refuse(self):
        with self.assertRaises(CreneauIndisponible):
            reserver_seance(self.disponibilite.pk, self.apprenant, self.debut + timedelta(hours=3), "Trop tard")

    def test_formateur_en_attente_ne_peut_pas_publier(self):
        self.client.force_login(self.formateur_non_valide)
        reponse = self.client.get(reverse("mentoring:disponibilite_creer"))
        self.assertEqual(reponse.status_code, 403)

    def test_formateur_peut_publier_une_disponibilite(self):
        self.client.force_login(self.formateur)
        debut = (timezone.now() + timedelta(days=5)).replace(minute=0, second=0, microsecond=0)
        reponse = self.client.post(reverse("mentoring:disponibilite_creer"), {
            "debut": debut.strftime("%Y-%m-%dT%H:%M"),
            "fin": (debut + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
            "duree_seance": 60,
        })
        self.assertRedirects(reponse, reverse("mentoring:index"))
        self.assertEqual(Disponibilite.objects.filter(formateur=self.formateur).count(), 2)

    def test_autre_utilisateur_ne_peut_pas_consulter_la_seance(self):
        seance = reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Privé")
        self.client.force_login(self.autre_apprenant)
        self.assertEqual(self.client.get(seance.get_absolute_url()).status_code, 403)

    def test_formateur_confirme_et_apprenant_annule(self):
        seance = reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Django")
        self.client.force_login(self.formateur)
        self.client.post(reverse("mentoring:seance_action", args=[seance.pk, "confirmer"]))
        seance.refresh_from_db()
        self.assertEqual(seance.statut, SeanceMentorat.Statut.CONFIRMEE)
        self.assertEqual(Rappel.objects.filter(object_id=seance.pk, envoye=False).count(), 4)
        self.client.force_login(self.apprenant)
        self.client.post(reverse("mentoring:seance_action", args=[seance.pk, "annuler"]))
        seance.refresh_from_db()
        self.assertEqual(seance.statut, SeanceMentorat.Statut.ANNULEE)
        self.assertFalse(Rappel.objects.filter(object_id=seance.pk, envoye=False).exists())

    def test_demande_d_apprenant_notifie_le_formateur(self):
        with self.captureOnCommitCallbacks(execute=True):
            seance = reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Django")
        seances = Notification.objects.filter(type=Notification.Type.SEANCE)
        notification = seances.get(destinataire=self.formateur)
        self.assertEqual(notification.titre, "Nouvelle demande de séance")
        self.assertEqual(notification.lien, seance.get_absolute_url())
        self.assertFalse(seances.filter(destinataire=self.apprenant).exists())

    def test_seance_planifiee_par_le_formateur_notifie_l_apprenant(self):
        with self.captureOnCommitCallbacks(execute=True):
            reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Django", demandeur=self.formateur)
        self.assertTrue(Notification.objects.filter(destinataire=self.apprenant,
                                                    titre="Nouvelle séance de mentorat").exists())
        self.assertFalse(Notification.objects.filter(destinataire=self.formateur,
                                                     type=Notification.Type.SEANCE).exists())

    def test_confirmation_et_annulation_notifient_l_autre_participant(self):
        seance = reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Django")
        self.client.force_login(self.formateur)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("mentoring:seance_action", args=[seance.pk, "confirmer"]))
        self.assertTrue(Notification.objects.filter(destinataire=self.apprenant,
                                                    titre="Séance de mentorat confirmée").exists())

        self.client.force_login(self.apprenant)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("mentoring:seance_action", args=[seance.pk, "annuler"]))
        annulations = Notification.objects.filter(titre="Séance de mentorat annulée")
        self.assertEqual([n.destinataire for n in annulations], [self.formateur])

    def test_annulation_par_un_administrateur_notifie_les_deux_participants(self):
        seance = reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Django")
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("mentoring:seance_action", args=[seance.pk, "annuler"]))
        destinataires = set(Notification.objects.filter(titre="Séance de mentorat annulée")
                            .values_list("destinataire", flat=True))
        self.assertEqual(destinataires, {self.apprenant.pk, self.formateur.pk})

    def test_annulation_ne_libere_pas_le_creneau_avec_seance_active(self):
        seance = reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Django")
        self.assertEqual(seance.statut, SeanceMentorat.Statut.EN_ATTENTE)
        self.assertIn(self.debut + timedelta(hours=1), creneaux_disponibles(self.disponibilite))

    def test_seance_invalide_hors_plage_refusee_par_modele(self):
        seance = SeanceMentorat(
            disponibilite=self.disponibilite, apprenant=self.apprenant, formateur=self.formateur,
            debut=self.debut + timedelta(hours=3), fin=self.debut + timedelta(hours=4), sujet="Invalid",
        )
        with self.assertRaises(ValidationError):
            seance.full_clean()

    def test_page_index_respecte_le_role(self):
        self.client.force_login(self.apprenant)
        reponse = self.client.get(reverse("mentoring:index"), {"formateur": self.formateur.pk})
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "data-calendar-grid")
        self.assertContains(reponse, "data-trainer-id=")

    def test_apprenant_doit_choisir_un_formateur_avant_le_calendrier(self):
        self.client.force_login(self.apprenant)
        reponse = self.client.get(reverse("mentoring:index"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Choisissez un formateur")
        self.assertNotContains(reponse, "data-calendar-grid")

    def test_flux_calendrier_retourne_disponibilites_et_seances_visibles(self):
        seance = reserver_seance(self.disponibilite.pk, self.apprenant, self.debut, "Visible")
        self.client.force_login(self.apprenant)
        reponse = self.client.get(reverse("mentoring:calendrier_evenements"), {
            "start": (self.debut - timedelta(days=1)).isoformat(),
            "end": (self.debut + timedelta(days=1)).isoformat(),
            "formateur": self.formateur.pk,
        })
        self.assertEqual(reponse.status_code, 200)
        donnees = reponse.json()["events"]
        self.assertIn(f"session-{seance.pk}", [item["id"] for item in donnees])
        self.assertIn(f"availability-{self.disponibilite.pk}", [item["id"] for item in donnees])

    def test_flux_calendrier_ne_revele_pas_les_seances_d_un_autre_apprenant(self):
        autre_formateur = creer(User.Role.FORMATEUR, "autre_formateur")
        autre_disponibilite = Disponibilite.objects.create(
            formateur=autre_formateur, debut=self.debut, fin=self.debut + timedelta(hours=2),
        )
        autre_seance = reserver_seance(autre_disponibilite.pk, self.autre_apprenant, self.debut, "Privée")
        self.client.force_login(self.apprenant)
        reponse = self.client.get(reverse("mentoring:calendrier_evenements"), {
            "start": (self.debut - timedelta(days=1)).isoformat(),
            "end": (self.debut + timedelta(days=1)).isoformat(),
            "formateur": self.formateur.pk,
        })
        self.assertNotIn(f"session-{autre_seance.pk}", [item["id"] for item in reponse.json()["events"]])

    def test_flux_calendrier_refuse_periode_invalide(self):
        self.client.force_login(self.apprenant)
        reponse = self.client.get(reverse("mentoring:calendrier_evenements"), {
            "start": "bad", "end": "bad", "formateur": self.formateur.pk,
        })
        self.assertEqual(reponse.status_code, 400)

    def test_flux_calendrier_apprenant_exige_un_formateur_valide(self):
        self.client.force_login(self.apprenant)
        reponse = self.client.get(reverse("mentoring:calendrier_evenements"), {
            "start": (self.debut - timedelta(days=1)).isoformat(),
            "end": (self.debut + timedelta(days=1)).isoformat(),
        })
        self.assertEqual(reponse.status_code, 400)

    def test_formateur_planifie_une_seance_confirmee_depuis_son_creneau(self):
        self.client.force_login(self.formateur)
        reponse = self.client.post(reverse("mentoring:planifier", args=[self.disponibilite.pk]), {
            "apprenant": self.apprenant.pk,
            "debut": self.debut.isoformat(),
            "sujet": "Séance planifiée",
            "description": "Préparation",
        })
        seance = SeanceMentorat.objects.get(sujet="Séance planifiée")
        self.assertEqual(seance.statut, SeanceMentorat.Statut.CONFIRMEE)
        self.assertRedirects(reponse, seance.get_absolute_url())

    def test_formateur_ne_peut_modifier_que_sa_disponibilite(self):
        autre_formateur = creer(User.Role.FORMATEUR, "autre_formateur")
        autre_disponibilite = Disponibilite.objects.create(
            formateur=autre_formateur,
            debut=self.debut + timedelta(days=5),
            fin=self.debut + timedelta(days=5, hours=2),
        )
        self.client.force_login(self.formateur)
        self.assertEqual(
            self.client.get(reverse("mentoring:disponibilite_modifier", args=[autre_disponibilite.pk])).status_code,
            403,
        )

    def test_formateur_peut_supprimer_disponibilite_sans_seance(self):
        self.client.force_login(self.formateur)
        reponse = self.client.post(reverse("mentoring:disponibilite_supprimer", args=[self.disponibilite.pk]))
        self.assertRedirects(reponse, reverse("mentoring:index"))
        self.assertFalse(Disponibilite.objects.filter(pk=self.disponibilite.pk).exists())

    def test_formateur_peut_modifier_sa_disponibilite(self):
        self.client.force_login(self.formateur)
        debut = self.debut + timedelta(days=5)
        reponse = self.client.post(reverse("mentoring:disponibilite_modifier", args=[self.disponibilite.pk]), {
            "debut": debut.strftime("%Y-%m-%dT%H:%M"),
            "fin": (debut + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"),
            "duree_seance": 60,
        })
        self.assertRedirects(reponse, reverse("mentoring:index"))
        self.disponibilite.refresh_from_db()
        self.assertEqual(timezone.localtime(self.disponibilite.debut).date(), timezone.localtime(debut).date())

    def test_formateur_peut_ouvrir_formulaire_de_planification(self):
        self.client.force_login(self.formateur)
        reponse = self.client.get(reverse("mentoring:planifier", args=[self.disponibilite.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Planifier une séance")

    def test_anonyme_est_redirige_vers_connexion(self):
        reponse = self.client.get(reverse("mentoring:index"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/comptes/connexion/", reponse.url)
