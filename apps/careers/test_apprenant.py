import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from . import services
from .fabriques import competence, creer, creer_admin, creer_offre, creer_recruteur, donner_competences, fichier_pdf
from .models import Candidature, Offre, ProfilCarriere, SignalementOffre

DOSSIER_TEST = tempfile.mkdtemp()


class PagesPubliquesTests(TestCase):
    def setUp(self):
        self.recruteur = creer_recruteur("rh@data.tn")
        self.sql = competence("SQL")
        self.offre = creer_offre(self.recruteur, "Stage PFE data", exigences=[(self.sql, 2, True)])
        self.brouillon = creer_offre(self.recruteur, "Brouillon secret", statut=Offre.Statut.BROUILLON)

    def test_visiteur_voit_les_offres_publiees(self):
        r = self.client.get(reverse("careers:offres"))
        self.assertContains(r, "Stage PFE data")
        self.assertNotContains(r, "Brouillon secret")
        self.assertContains(r, "Créer un compte entreprise")

    def test_filtres(self):
        creer_offre(self.recruteur, "CDI Django", type_contrat="cdi", ville="Sfax")
        url = reverse("careers:offres")
        self.assertEqual([o.titre for o in self.client.get(url, {"type_contrat": "cdi"}).context["page"]],
                         ["CDI Django"])
        self.assertEqual([o.titre for o in self.client.get(url, {"competence": self.sql.pk}).context["page"]],
                         ["Stage PFE data"])
        self.assertEqual([o.titre for o in self.client.get(url, {"ville": "sfax"}).context["page"]], ["CDI Django"])

    def test_pagination(self):
        for i in range(12):
            creer_offre(self.recruteur, f"Offre {i}")
        r = self.client.get(reverse("careers:offres"), {"page": 2})
        self.assertEqual(len(r.context["page"]), 1)
        self.assertEqual(r.context["page"].paginator.count, 13)

    def test_detail_public_et_brouillon_cache(self):
        r = self.client.get(self.offre.get_absolute_url())
        self.assertContains(r, "Se connecter pour postuler")
        self.assertEqual(self.client.get(self.brouillon.get_absolute_url()).status_code, 404)

    def test_postuler_exige_d_etre_connecte(self):
        r = self.client.post(reverse("careers:postuler", args=[self.offre.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r.url)
        self.assertFalse(Candidature.objects.exists())


@override_settings(PRIVATE_MEDIA_ROOT=DOSSIER_TEST)
class EspaceApprenantTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.recruteur = creer_recruteur("rh@data.tn")
        self.apprenant = creer("yasmine@test.tn")
        self.autre = creer("amine@test.tn")
        self.sql, self.airflow = competence("SQL"), competence("Airflow")
        donner_competences(self.apprenant, {self.sql: 3})
        self.offre_forte = creer_offre(self.recruteur, "Analyste SQL", exigences=[(self.sql, 2, True)])
        self.offre_faible = creer_offre(self.recruteur, "Data engineer", exigences=[(self.airflow, 2, True)])
        self.client.force_login(self.apprenant)

    def test_offres_triees_par_compatibilite_ou_par_date(self):
        r = self.client.get(reverse("careers:offres"))
        self.assertEqual([o.titre for o in r.context["page"]], ["Analyste SQL", "Data engineer"])
        self.assertContains(r, "100 %")
        r = self.client.get(reverse("careers:offres"), {"tri": "date"})
        self.assertEqual(len(r.context["page"]), 2)

    def test_detail_avec_jauge_et_ecart(self):
        r = self.client.get(self.offre_faible.get_absolute_url())
        self.assertEqual(r.context["compatibilite"].score, 0)
        self.assertTrue(r.context["compatibilite"].obligatoires_manquantes)
        self.assertContains(r, "Écart de compétences")
        self.assertContains(r, "Airflow")
        self.assertContains(r, "Une compétence obligatoire te manque")

    def test_tableau_de_bord(self):
        ProfilCarriere.objects.filter(apprenant=self.apprenant).update(titre="Data analyst junior")
        r = self.client.get(reverse("careers:tableau_apprenant"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([o.titre for o in r.context["offres_pour_toi"]], ["Analyste SQL", "Data engineer"])
        self.assertEqual([p["competence__nom"] for p in r.context["prioritaires"]], ["Airflow"])
        self.assertGreater(r.context["completude"], 0)

    def test_postuler_puis_retirer(self):
        r = self.client.post(reverse("careers:postuler", args=[self.offre_forte.pk]), {"lettre_motivation": "Motivée"})
        self.assertRedirects(r, reverse("careers:mes_candidatures"))
        candidature = Candidature.objects.get()
        self.assertEqual(candidature.score_au_depot, 100)
        self.assertContains(self.client.get(reverse("careers:mes_candidatures")), "Candidature envoyée")

        self.client.post(reverse("careers:retirer_candidature", args=[candidature.pk]))
        candidature.refresh_from_db()
        self.assertEqual(candidature.statut, Candidature.Statut.RETIREE)

    def test_apprenant_ne_voit_que_ses_candidatures(self):
        sienne = services.postuler(self.offre_forte, self.autre)
        self.assertEqual(self.client.get(reverse("careers:candidature_detail", args=[sienne.pk])).status_code, 404)
        r = self.client.post(reverse("careers:retirer_candidature", args=[sienne.pk]))
        self.assertEqual(r.status_code, 404)
        sienne.refresh_from_db()
        self.assertEqual(sienne.statut, Candidature.Statut.ENVOYEE)
        self.assertNotContains(self.client.get(reverse("careers:mes_candidatures")), "Analyste SQL")

    def test_enregistrer_le_profil_et_les_competences(self):
        r = self.client.post(reverse("careers:profil"), {
            "titre": "Data analyst junior", "ville": "Tunis", "types_contrat_recherches": ["stage_pfe", "cdi"],
            "competences-TOTAL_FORMS": "1", "competences-INITIAL_FORMS": "0",
            "competences-0-competence": self.airflow.pk, "competences-0-niveau": "2",
        })
        self.assertRedirects(r, reverse("careers:profil"))
        profil = ProfilCarriere.objects.get(apprenant=self.apprenant)
        self.assertEqual(profil.titre, "Data analyst junior")
        self.assertEqual(profil.liste_types_contrat(), ["stage_pfe", "cdi"])
        self.assertEqual(services.niveaux_de(self.apprenant), {self.sql.pk: 3, self.airflow.pk: 2})

    def test_depot_du_cv_et_suggestions_a_cocher(self):
        competence("Python")
        r = self.client.post(reverse("careers:deposer_cv"), {"cv": fichier_pdf("Python, SQL et Airflow")}, follow=True)
        self.assertContains(r, "Compétences repérées dans ton CV")
        self.assertEqual(sorted(c.nom for c in r.context["suggestions"]), ["Airflow", "Python"])  # SQL déjà au profil

        python = competence("Python")
        self.client.post(reverse("careers:ajouter_suggestions"), {"competences": [python.pk]})
        self.assertEqual(services.niveaux_de(self.apprenant).get(python.pk), 1)
        self.assertNotIn(self.airflow.pk, services.niveaux_de(self.apprenant))  # décochée : non ajoutée

    def test_depot_d_un_faux_pdf_refuse(self):
        faux = SimpleUploadedFile("cv.pdf", b"PK\x03\x04 un docx renomme")
        r = self.client.post(reverse("careers:deposer_cv"), {"cv": faux}, follow=True)
        self.assertContains(r, "pas un vrai PDF")
        self.assertFalse(ProfilCarriere.objects.get(apprenant=self.apprenant).cv)

    def test_signaler_une_offre(self):
        self.client.post(reverse("careers:signaler_offre", args=[self.offre_forte.pk]), {"motif": "arnaque"})
        r = self.client.post(reverse("careers:signaler_offre", args=[self.offre_forte.pk]), {"motif": "autre"},
                             follow=True)
        self.assertContains(r, "déjà signalé")
        self.assertEqual(SignalementOffre.objects.count(), 1)

    def test_recruteur_refuse_dans_l_espace_apprenant(self):
        self.client.force_login(self.recruteur)
        self.assertEqual(self.client.get(reverse("careers:tableau_apprenant")).status_code, 403)
        self.assertEqual(self.client.post(reverse("careers:postuler", args=[self.offre_forte.pk])).status_code, 403)


@override_settings(PRIVATE_MEDIA_ROOT=DOSSIER_TEST)
class TelechargementCVTests(TestCase):
    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.profil = services.obtenir_profil(self.apprenant)
        services.enregistrer_cv(self.profil, fichier_pdf("Mon CV"))
        self.url = reverse("careers:cv_profil", args=[self.profil.pk])

    def test_proprietaire_et_administrateur(self):
        self.client.force_login(self.apprenant)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.client.force_login(creer_admin())
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_acces_refuse_aux_autres(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)  # visiteur → connexion
        self.client.force_login(creer("amine@test.tn"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        # Le CV de profil n'est jamais servi aux recruteurs (seul le CV déposé l'est)
        self.client.force_login(creer("rh@data.tn", role=User.Role.RECRUTEUR))
        self.assertEqual(self.client.get(self.url).status_code, 404)
