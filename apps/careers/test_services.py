import shutil
import tempfile
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from . import services
from .fabriques import competence, creer, creer_offre, creer_recruteur, donner_competences, fichier_pdf
from .models import Candidature, HistoriqueCandidature, Offre, ProfilCarriere, ProfilEntreprise
from .services import TransitionInvalide

S = Candidature.Statut
DOSSIER_TEST = tempfile.mkdtemp()


class CalculScoreTests(SimpleTestCase):
    """La fonction pure, sans base de données."""

    def test_cas_nominal(self):
        # (2 × 1 + 1 × 1/2) / 3 = 83,3 %
        r = services.calculer_score([(1, 2, True), (2, 2, False)], {1: 2, 2: 1})
        self.assertEqual(r.score, 83)
        self.assertFalse(r.obligatoires_manquantes)

    def test_competence_absente_compte_zero(self):
        r = services.calculer_score([(1, 2, False), (2, 2, False)], {1: 2})
        self.assertEqual(r.score, 50)

    def test_niveau_superieur_au_requis_plafonne(self):
        r = services.calculer_score([(1, 2, False), (2, 4, False)], {1: 4, 2: 2})
        self.assertEqual(r.score, 75)  # (1 + 0,5) / 2, et non (2 + 0,5) / 2

    def test_obligatoire_manquante_signalee(self):
        r = services.calculer_score([(1, 2, True), (2, 1, False)], {2: 3})
        self.assertEqual(r.score, 33)
        self.assertTrue(r.obligatoires_manquantes)

    def test_offre_sans_competence_non_calculable(self):
        r = services.calculer_score([], {1: 4})
        self.assertIsNone(r.score)
        self.assertFalse(r.calculable)

    def test_arrondi_scolaire(self):
        # 12,5 → 13 (le round() de Python donnerait 12) ; 2/3 → 67
        self.assertEqual(services.calculer_score([(1, 4, False), (2, 1, False)], {1: 1}).score, 13)
        self.assertEqual(services.calculer_score([(1, 3, False)], {1: 2}).score, 67)


class ScoresEnBaseTests(TestCase):
    def setUp(self):
        self.recruteur = creer_recruteur("rh@data.tn")
        self.apprenant = creer("yasmine@test.tn")
        self.sql, self.python = competence("SQL"), competence("Python")
        donner_competences(self.apprenant, {self.sql: 3, self.python: 1})

    def test_score_d_une_offre(self):
        offre = creer_offre(self.recruteur, exigences=[(self.sql, 2, True), (self.python, 2, False)])
        self.assertEqual(services.score_offre(offre, self.apprenant).score, 83)

    def test_pas_de_requetes_n_plus_1(self):
        for i in range(3):
            creer_offre(self.recruteur, f"Offre {i}", exigences=[(self.sql, 2, True), (self.python, 3, False)])

        def compter():
            # 1 requête pour les offres, 1 pour les compétences requises, 1 pour les niveaux de l'apprenant
            with self.assertNumQueries(3):
                offres = services.scores_offres(self.apprenant, Offre.objects.ouvertes().select_related("entreprise"))
                [o.compatibilite.score for o in offres]
            return len(offres)

        self.assertEqual(compter(), 3)
        for i in range(5):
            creer_offre(self.recruteur, f"Autre {i}", exigences=[(self.python, 1, False)])
        self.assertEqual(compter(), 8)  # même nombre de requêtes avec plus d'offres

    def test_tri_par_score_non_calculable_en_dernier(self):
        sans = creer_offre(self.recruteur, "Sans compétence")
        faible = creer_offre(self.recruteur, "Faible", exigences=[(self.python, 4, True)])
        forte = creer_offre(self.recruteur, "Forte", exigences=[(self.sql, 3, True)])
        offres = services.trier_par_score(services.scores_offres(self.apprenant, Offre.objects.all()))
        self.assertEqual(offres, [forte, faible, sans])


class EcartEtPrioritesTests(TestCase):
    def setUp(self):
        self.recruteur = creer_recruteur("rh@data.tn")
        self.apprenant = creer("yasmine@test.tn")
        self.sql, self.airflow, self.powerbi, self.git = (competence(n) for n in ("SQL", "Airflow", "Power BI", "Git"))
        donner_competences(self.apprenant, {self.sql: 3, self.powerbi: 1})

    def test_ecart_trie_obligatoires_puis_ecart_decroissant(self):
        offre = creer_offre(self.recruteur, exigences=[
            (self.sql, 2, True),        # acquise : absente de l'écart
            (self.powerbi, 3, False),   # écart 2
            (self.git, 1, False),       # écart 1
            (self.airflow, 2, True),    # obligatoire
        ])
        ecarts = services.ecart_competences(offre, self.apprenant)
        self.assertEqual([e.competence for e in ecarts], [self.airflow, self.powerbi, self.git])
        self.assertEqual(services.formater_ecart(ecarts[:2]),
                         "Il te manque : Airflow (aucun → Intermédiaire, obligatoire), Power BI (Notions → Avancé)")

    def test_competences_a_acquerir_en_priorite(self):
        creer_offre(self.recruteur, "A", exigences=[(self.airflow, 2, True), (self.sql, 2, True)])
        creer_offre(self.recruteur, "B", exigences=[(self.airflow, 1, False), (self.powerbi, 3, False)])
        creer_offre(self.recruteur, "C", exigences=[(self.airflow, 2, False), (self.git, 1, False)])
        # Les offres fermées ou expirées ne comptent pas
        creer_offre(self.recruteur, "Fermée", statut=Offre.Statut.FERMEE, exigences=[(self.git, 1, False)])
        creer_offre(self.recruteur, "Expirée", date_limite=timezone.localdate() - timedelta(days=1),
                    exigences=[(self.git, 1, False)])

        priorites = services.competences_prioritaires(self.apprenant)
        self.assertEqual([(p["competence__nom"], p["nb_offres"]) for p in priorites],
                         [("Airflow", 3), ("Git", 1), ("Power BI", 1)])  # SQL est déjà au niveau

    def test_priorites_limitees_a_cinq(self):
        competences = [competence(f"Compétence {i}") for i in range(7)]
        creer_offre(self.recruteur, exigences=[(c, 1, False) for c in competences])
        self.assertEqual(len(services.competences_prioritaires(self.apprenant)), 5)


@override_settings(PRIVATE_MEDIA_ROOT=DOSSIER_TEST)
class LectureCVTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.apprenant = creer("yasmine@test.tn")
        self.profil = services.obtenir_profil(self.apprenant)
        for nom, alias in [("Python", ""), ("SQL", "postgresql"), ("Power BI", "powerbi, dax"), ("Java", ""),
                           ("UML", "modelisation uml")]:
            competence(nom, alias)

    def test_pdf_valide_donne_des_suggestions(self):
        cv = fichier_pdf("Stage : Python, PostgreSQL et tableaux de bord PowerBI. Projet en JavaScript.")
        suggestions = services.enregistrer_cv(self.profil, cv)
        self.assertEqual(sorted(c.nom for c in suggestions), ["Power BI", "Python", "SQL"])  # pas « Java »
        self.assertTrue(self.profil.cv.name.startswith("careers/cv/"))
        self.assertFalse(self.profil.competences.exists())  # rien n'est ajouté automatiquement

    def test_competences_deja_au_profil_exclues(self):
        donner_competences(self.apprenant, {competence("Python"): 2})
        suggestions = services.enregistrer_cv(self.profil, fichier_pdf("Python et SQL"))
        self.assertEqual([c.nom for c in suggestions], ["SQL"])

    def test_normalisation_des_accents(self):
        self.assertEqual(services.normaliser("Modélisation  UML"), "modelisation uml")
        self.assertEqual([c.nom for c in services.suggerer_competences("MODÉLISATION UML")], ["UML"])

    def test_faux_pdf_refuse(self):
        faux = SimpleUploadedFile("cv.pdf", b"MZ\x90\x00 executable", content_type="application/pdf")
        with self.assertRaisesMessage(ValidationError, "pas un vrai PDF"):
            services.valider_cv(faux)
        with self.assertRaisesMessage(ValidationError, "fichier PDF"):
            services.valider_cv(SimpleUploadedFile("cv.docx", b"%PDF-1.4"))

    def test_fichier_trop_lourd(self):
        lourd = SimpleUploadedFile("cv.pdf", b"%PDF" + b"0" * services.CV_TAILLE_MAX)
        with self.assertRaisesMessage(ValidationError, "taille maximale"):
            services.valider_cv(lourd)

    def test_pdf_sans_texte_aucune_suggestion(self):
        self.assertEqual(services.enregistrer_cv(self.profil, fichier_pdf("")), [])
        # PDF corrompu (en-tête correct, contenu illisible) : pas d'erreur non plus
        corrompu = SimpleUploadedFile("cv.pdf", b"%PDF-1.4 n'importe quoi")
        with self.assertLogs("pypdf", "WARNING"):  # avertissement de pypdf, sans exception
            self.assertEqual(services.extraire_texte_pdf(corrompu), "")


@override_settings(PRIVATE_MEDIA_ROOT=DOSSIER_TEST)
class CandidaturesTests(TestCase):
    def setUp(self):
        self.recruteur = creer_recruteur("rh@data.tn")
        self.apprenant = creer("yasmine@test.tn")
        self.sql = competence("SQL")
        donner_competences(self.apprenant, {self.sql: 1})
        self.offre = creer_offre(self.recruteur, exigences=[(self.sql, 2, True)])
        self.demain = timezone.now() + timedelta(days=1)

    def postuler(self):
        return services.postuler(self.offre, self.apprenant, "Motivée !")

    def test_cycle_complet_et_historique(self):
        c = self.postuler()
        self.assertEqual(c.score_au_depot, 50)
        services.changer_statut(c, self.recruteur, S.EN_EXAMEN)
        services.changer_statut(c, self.recruteur, S.ENTRETIEN, date_entretien=self.demain, lieu="Visio Meet")
        services.changer_statut(c, self.recruteur, S.ACCEPTEE, commentaire="Bienvenue !")
        c.refresh_from_db()
        self.assertEqual(c.statut, S.ACCEPTEE)
        self.assertEqual(c.message_recruteur, "Bienvenue !")
        self.assertIsNotNone(c.date_premiere_reponse)
        self.assertEqual(list(c.historique.values_list("ancien_statut", "nouveau_statut")), [
            ("", S.ENVOYEE), (S.ENVOYEE, S.EN_EXAMEN), (S.EN_EXAMEN, S.ENTRETIEN), (S.ENTRETIEN, S.ACCEPTEE),
        ])

    def test_transitions_interdites(self):
        c = self.postuler()
        with self.assertRaises(TransitionInvalide):
            services.changer_statut(c, self.recruteur, S.ACCEPTEE)  # sans passer par l'entretien
        with self.assertRaises(TransitionInvalide):
            services.changer_statut(c, self.recruteur, S.ENVOYEE)
        services.changer_statut(c, self.recruteur, S.REFUSEE)
        with self.assertRaises(TransitionInvalide):
            services.changer_statut(c, self.recruteur, S.EN_EXAMEN)  # refusée est un état final
        self.assertEqual(HistoriqueCandidature.objects.filter(candidature=c).count(), 2)

    def test_retrait_reserve_a_l_apprenant(self):
        c = self.postuler()
        with self.assertRaises(TransitionInvalide):
            services.changer_statut(c, self.recruteur, S.RETIREE)
        with self.assertRaises(PermissionDenied):
            services.changer_statut(c, self.apprenant, S.EN_EXAMEN)
        services.retirer_candidature(c, self.apprenant)
        self.assertEqual(c.statut, S.RETIREE)
        with self.assertRaises(TransitionInvalide):
            services.retirer_candidature(c, self.apprenant)

    def test_entretien_sans_date_ou_date_passee(self):
        c = self.postuler()
        services.changer_statut(c, self.recruteur, S.EN_EXAMEN)
        with self.assertRaisesMessage(TransitionInvalide, "date et un lieu"):
            services.changer_statut(c, self.recruteur, S.ENTRETIEN, lieu="Tunis")
        with self.assertRaisesMessage(TransitionInvalide, "dans le futur"):
            services.changer_statut(c, self.recruteur, S.ENTRETIEN, lieu="Tunis",
                                    date_entretien=timezone.now() - timedelta(hours=1))
        c.refresh_from_db()
        self.assertEqual(c.statut, S.EN_EXAMEN)

    def test_replanifier_un_entretien(self):
        c = self.postuler()
        services.changer_statut(c, self.recruteur, S.EN_EXAMEN)
        services.planifier_entretien(c, self.recruteur, self.demain, "Bureau 3")
        services.planifier_entretien(c, self.recruteur, self.demain + timedelta(days=1), "Visio")
        c.refresh_from_db()
        self.assertEqual(c.lieu_ou_lien_entretien, "Visio")
        self.assertEqual(c.historique.filter(nouveau_statut=S.ENTRETIEN).count(), 2)

    def test_double_candidature_refusee(self):
        self.postuler()
        with self.assertRaisesMessage(ValidationError, "déjà postulé"):
            self.postuler()

    def test_offre_expiree_suspendue_ou_entreprise_non_validee(self):
        self.offre.date_limite = timezone.localdate() - timedelta(days=1)
        self.offre.save()
        with self.assertRaisesMessage(ValidationError, "date limite"):
            self.postuler()

        self.offre.date_limite = None
        self.offre.statut = Offre.Statut.SUSPENDUE
        self.offre.save()
        with self.assertRaisesMessage(ValidationError, "n'accepte pas"):
            self.postuler()

        self.offre.statut = Offre.Statut.PUBLIEE
        self.offre.save()
        ProfilEntreprise.objects.filter(pk=self.offre.entreprise_id).update(statut=ProfilEntreprise.Statut.EN_ATTENTE)
        self.offre.entreprise.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "pas validée"):
            self.postuler()
        self.assertFalse(Candidature.objects.exists())

    def test_cv_depose_est_une_copie_figee(self):
        profil = ProfilCarriere.objects.get(apprenant=self.apprenant)
        services.enregistrer_cv(profil, fichier_pdf("Premier CV"))
        c = self.postuler()
        services.enregistrer_cv(profil, fichier_pdf("Second CV"))
        self.assertNotEqual(c.cv_depose.name, profil.cv.name)
        with c.cv_depose.open("rb") as f:
            self.assertIn(b"Premier CV", f.read())


class OffresServicesTests(TestCase):
    def setUp(self):
        self.recruteur = creer_recruteur("rh@data.tn")

    def test_dupliquer_une_offre(self):
        offre = creer_offre(self.recruteur, exigences=[(competence("SQL"), 3, True), (competence("Git"), 1, False)])
        copie = services.dupliquer_offre(offre)
        self.assertEqual(copie.statut, Offre.Statut.BROUILLON)
        self.assertEqual(copie.competences_requises.count(), 2)
        self.assertTrue(copie.titre.endswith("(copie)"))

    def test_publication_refusee_si_entreprise_non_validee(self):
        attente = creer_recruteur("rh@attente.tn", statut=ProfilEntreprise.Statut.EN_ATTENTE)
        offre = creer_offre(attente, statut=Offre.Statut.BROUILLON)
        with self.assertRaisesMessage(ValidationError, "validée"):
            services.publier_offre(offre)
