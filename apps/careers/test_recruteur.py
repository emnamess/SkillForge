import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User

from . import services
from .fabriques import (MDP, competence, creer, creer_admin, creer_offre, creer_recruteur, donner_competences,
                        fichier_pdf)
from .models import Candidature, Offre, ProfilEntreprise

S = Candidature.Statut
DOSSIER_TEST = tempfile.mkdtemp()
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class InscriptionRecruteurTests(TestCase):
    url = reverse("careers:inscription_recruteur")

    def donnees(self, **extra):
        data = {"first_name": "Salma", "last_name": "Haddad", "email": "salma@datavision.tn",
                "password1": MDP, "password2": MDP, "nom": "DataVision", "secteur": "Conseil data",
                "ville": "Tunis"}
        data.update(extra)
        return data

    def test_inscription_cree_compte_et_entreprise_en_attente(self):
        r = self.client.post(self.url, self.donnees(), follow=True)
        user = User.objects.get(email="salma@datavision.tn")
        self.assertTrue(user.est_recruteur)
        self.assertEqual(user.profil_entreprise.statut, ProfilEntreprise.Statut.EN_ATTENTE)
        self.assertContains(r, "Compte en attente de validation")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_inscription_en_une_seule_transaction(self):
        with mock.patch.object(ProfilEntreprise, "save", side_effect=RuntimeError("panne")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, self.donnees())
        self.assertFalse(User.objects.filter(email="salma@datavision.tn").exists())

    def test_email_deja_utilise(self):
        creer("salma@datavision.tn")
        r = self.client.post(self.url, self.donnees())
        self.assertContains(r, "existe déjà")
        self.assertFalse(ProfilEntreprise.objects.exists())


class RecruteurNonValideTests(TestCase):
    def setUp(self):
        self.recruteur = creer_recruteur("rh@attente.tn", statut=ProfilEntreprise.Statut.EN_ATTENTE)
        self.client.force_login(self.recruteur)

    def test_page_d_attente_et_aucune_publication(self):
        self.assertContains(self.client.get(reverse("careers:tableau_recruteur")), "Compte en attente de validation")
        r = self.client.post(reverse("careers:offre_creer"), {"titre": "Offre", "type_contrat": "cdi",
                                                               "mode_travail": "hybride", "ville": "Tunis",
                                                               "description": "x", "publier": "1"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Offre.objects.exists())

    def test_entreprise_refusee_affiche_le_motif(self):
        services.refuser_entreprise(self.recruteur.profil_entreprise, "Matricule fiscal invalide")
        self.assertContains(self.client.get(reverse("careers:mes_offres")), "Matricule fiscal invalide")


class GestionOffresTests(TestCase):
    def setUp(self):
        self.recruteur = creer_recruteur("rh@data.tn")
        self.sql = competence("SQL")
        self.client.force_login(self.recruteur)

    def test_creer_et_publier_une_offre_avec_competences(self):
        r = self.client.post(reverse("careers:offre_creer"), {
            "titre": "Data analyst", "type_contrat": "cdi", "mode_travail": "hybride", "ville": "Tunis",
            "description": "Analyse de données", "publier": "1",
            "competences-TOTAL_FORMS": "1", "competences-INITIAL_FORMS": "0",
            "competences-0-competence": self.sql.pk, "competences-0-niveau_requis": "3",
            "competences-0-obligatoire": "on",
        })
        self.assertRedirects(r, reverse("careers:mes_offres"))
        offre = Offre.objects.get()
        self.assertEqual(offre.statut, Offre.Statut.PUBLIEE)
        self.assertIsNotNone(offre.date_publication)
        self.assertTrue(offre.competences_requises.get().obligatoire)

    def test_dupliquer_et_fermer(self):
        offre = creer_offre(self.recruteur, exigences=[(self.sql, 2, True)])
        r = self.client.post(reverse("careers:offre_dupliquer", args=[offre.pk]))
        copie = Offre.objects.exclude(pk=offre.pk).get()
        self.assertRedirects(r, reverse("careers:offre_modifier", args=[copie.pk]))
        self.client.post(reverse("careers:offre_fermer", args=[offre.pk]))
        offre.refresh_from_db()
        self.assertEqual(offre.statut, Offre.Statut.FERMEE)

    def test_tableau_de_bord(self):
        offre = creer_offre(self.recruteur)
        services.postuler(offre, creer("yasmine@test.tn"))
        r = self.client.get(reverse("careers:tableau_recruteur"))
        self.assertEqual(r.context["nb_offres_actives"], 1)
        self.assertEqual(r.context["nb_nouvelles"], 1)


@override_settings(PRIVATE_MEDIA_ROOT=DOSSIER_TEST)
class KanbanEtPermissionsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.recruteur_a = creer_recruteur("rh@a.tn")
        self.recruteur_b = creer_recruteur("rh@b.tn")
        self.sql = competence("SQL")
        self.offre_a = creer_offre(self.recruteur_a, "Offre de A", exigences=[(self.sql, 2, True)])
        self.forte, self.faible = creer("yasmine@test.tn"), creer("amine@test.tn")
        donner_competences(self.forte, {self.sql: 2})
        donner_competences(self.faible, {self.sql: 1})
        services.enregistrer_cv(services.obtenir_profil(self.forte), fichier_pdf("CV de Yasmine"))
        self.c_faible = services.postuler(self.offre_a, self.faible)
        self.c_forte = services.postuler(self.offre_a, self.forte)
        self.client.force_login(self.recruteur_a)

    def url_statut(self, candidature):
        return reverse("careers:changer_statut", args=[candidature.pk])

    def test_kanban_trie_par_score(self):
        r = self.client.get(reverse("careers:kanban", args=[self.offre_a.pk]))
        colonnes = dict(r.context["colonnes"])
        self.assertEqual(colonnes[S.ENVOYEE], [self.c_forte, self.c_faible])
        self.assertContains(r, "Changer le statut")

    def test_json_transition_acceptee(self):
        r = self.client.post(self.url_statut(self.c_faible), {"statut": S.EN_EXAMEN}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["statut"], S.EN_EXAMEN)
        self.assertIn(S.ENTRETIEN, [s["valeur"] for s in r.json()["statuts_possibles"]])
        self.c_faible.refresh_from_db()
        self.assertEqual(self.c_faible.statut, S.EN_EXAMEN)

    def test_json_transition_refusee(self):
        r = self.client.post(self.url_statut(self.c_faible), {"statut": S.ACCEPTEE}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])
        self.assertIn("impossible", r.json()["erreur"])
        self.c_faible.refresh_from_db()
        self.assertEqual(self.c_faible.statut, S.ENVOYEE)

    def test_json_refuse_sans_jeton_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.recruteur_a)
        r = client.post(self.url_statut(self.c_faible), {"statut": S.EN_EXAMEN}, **AJAX)
        self.assertEqual(r.status_code, 403)
        self.c_faible.refresh_from_db()
        self.assertEqual(self.c_faible.statut, S.ENVOYEE)

    def test_menu_accessible_sans_javascript(self):
        kanban = reverse("careers:kanban", args=[self.offre_a.pk])
        r = self.client.post(self.url_statut(self.c_faible), {"statut": S.REFUSEE, "next": kanban}, follow=True)
        self.assertRedirects(r, kanban)
        self.assertContains(r, "Refusée")
        self.c_faible.refresh_from_db()
        self.assertEqual(self.c_faible.statut, S.REFUSEE)

    def test_planifier_un_entretien(self):
        services.changer_statut(self.c_forte, self.recruteur_a, S.EN_EXAMEN)
        url = reverse("careers:planifier_entretien", args=[self.c_forte.pk])
        hier = (timezone.localtime() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(url, {"date_entretien": hier, "lieu_ou_lien_entretien": "Visio"}, follow=True)
        self.assertContains(r, "dans le futur")
        demain = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(url, {"date_entretien": demain, "lieu_ou_lien_entretien": "https://meet.example/abc"})
        self.c_forte.refresh_from_db()
        self.assertEqual(self.c_forte.statut, S.ENTRETIEN)
        self.assertEqual(self.c_forte.lieu_ou_lien_entretien, "https://meet.example/abc")

    def test_fiche_candidat_et_cv_depose(self):
        r = self.client.get(reverse("careers:fiche_candidat", args=[self.c_forte.pk]))
        self.assertEqual(r.context["compatibilite"].score, 100)
        r = self.client.get(reverse("careers:cv_candidature", args=[self.c_forte.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"CV de Yasmine", b"".join(r.streaming_content))

    def test_recruteur_b_ne_voit_pas_les_objets_de_a(self):
        self.client.force_login(self.recruteur_b)
        for url in [reverse("careers:offre_modifier", args=[self.offre_a.pk]),
                    reverse("careers:kanban", args=[self.offre_a.pk]),
                    reverse("careers:fiche_candidat", args=[self.c_forte.pk]),
                    reverse("careers:cv_candidature", args=[self.c_forte.pk])]:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        for url in [self.url_statut(self.c_forte),
                    reverse("careers:offre_fermer", args=[self.offre_a.pk]),
                    reverse("careers:offre_dupliquer", args=[self.offre_a.pk])]:
            self.assertEqual(self.client.post(url, {"statut": S.REFUSEE}).status_code, 404, url)
        self.c_forte.refresh_from_db()
        self.offre_a.refresh_from_db()
        self.assertEqual(self.c_forte.statut, S.ENVOYEE)
        self.assertEqual(self.offre_a.statut, Offre.Statut.PUBLIEE)
        self.assertEqual(Offre.objects.count(), 1)

    def test_cv_depose_refuse_aux_autres_apprenants(self):
        self.client.force_login(self.faible)
        self.assertEqual(self.client.get(reverse("careers:cv_candidature", args=[self.c_forte.pk])).status_code, 404)
        self.client.force_login(self.forte)  # le candidat lui-même y a accès
        self.assertEqual(self.client.get(reverse("careers:cv_candidature", args=[self.c_forte.pk])).status_code, 200)

    def test_apprenant_et_administrateur_hors_de_l_espace_recruteur(self):
        self.client.force_login(self.forte)
        self.assertEqual(self.client.get(reverse("careers:kanban", args=[self.offre_a.pk])).status_code, 403)
        self.client.force_login(creer_admin())
        self.assertRedirects(self.client.get(reverse("careers:tableau_recruteur")),
                             reverse("careers:admin_entreprises"), fetch_redirect_response=False)
