from django.test import Client, TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
from unittest.mock import patch
from django.conf import settings

from apps.accounts.models import User

from .models import Cours, CourseResourceStorage, Inscription, Lesson, LessonContent, LessonProgress, Module, ProgressionModule, valider_fichier_cours
from .services import recalculer_progression


def creer_utilisateur(role, username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.skillforge.tn",
        password="testpass123",
        role=role,
    )


class InscriptionCoursTests(TestCase):
    def setUp(self):
        self.apprenant = creer_utilisateur(User.Role.APPRENANT, "apprenant")
        self.autre_apprenant = creer_utilisateur(User.Role.APPRENANT, "autre")
        self.formateur = creer_utilisateur(User.Role.FORMATEUR, "formateur")
        self.administrateur = creer_utilisateur(User.Role.ADMINISTRATEUR, "admin")
        self.cours = Cours.objects.create(
            formateur=self.formateur,
            titre="Django",
            description="Créer des applications web.",
            est_publie=True,
        )
        self.autre_cours = Cours.objects.create(
            formateur=self.formateur,
            titre="Python",
            est_publie=True,
        )
        self.brouillon = Cours.objects.create(
            formateur=self.formateur,
            titre="Brouillon",
            est_publie=False,
        )
        self.url_inscription = reverse("courses:inscrire", args=[self.cours.pk])

    def test_apprenant_peut_s_inscrire_a_un_cours_publie(self):
        self.client.force_login(self.apprenant)

        reponse = self.client.post(self.url_inscription, follow=True)

        inscription = Inscription.objects.get(apprenant=self.apprenant, cours=self.cours)
        self.assertEqual(inscription.progression, 0)
        self.assertContains(reponse, "Vous êtes inscrit au cours")
        self.assertRedirects(reponse, reverse("courses:detail", args=[self.cours.pk]))

    def test_doublon_conserve_une_seule_inscription_et_affiche_un_message(self):
        self.client.force_login(self.apprenant)

        self.client.post(self.url_inscription)
        reponse = self.client.post(self.url_inscription, follow=True)

        self.assertEqual(Inscription.objects.filter(apprenant=self.apprenant, cours=self.cours).count(), 1)
        self.assertContains(reponse, "déjà inscrit")

    def test_formateur_ne_peut_pas_utiliser_l_action(self):
        self.client.force_login(self.formateur)

        reponse = self.client.post(self.url_inscription)

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Inscription.objects.exists())


class LessonsTests(TestCase):
    def setUp(self):
        self.apprenant = creer_utilisateur(User.Role.APPRENANT, "lessonstudent")
        self.autre_apprenant = creer_utilisateur(User.Role.APPRENANT, "lessonother")
        self.formateur = creer_utilisateur(User.Role.FORMATEUR, "lessonteacher")
        self.administrateur = creer_utilisateur(User.Role.ADMINISTRATEUR, "lessonadmin")
        self.cours = Cours.objects.create(formateur=self.formateur, titre="Django", est_publie=True)
        self.autre_cours = Cours.objects.create(formateur=self.formateur, titre="Autre cours", est_publie=True)
        self.brouillon = Cours.objects.create(formateur=self.formateur, titre="Brouillon leçon", est_publie=False)
        self.url_inscription = reverse("courses:inscrire", args=[self.cours.pk])
        self.module = Module.objects.create(cours=self.cours, titre="Chapitre 1")

    def test_blocs_ordonnés_et_lecon_accessible_a_l_inscrit(self):
        lecon = Lesson.objects.create(module=self.module, titre="Introduction", ordre=1, est_publiee=True)
        second = LessonContent.objects.create(lesson=lecon, type="text", texte="Deuxième", ordre=2)
        first = LessonContent.objects.create(lesson=lecon, type="text", texte="Premier", ordre=1)
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours)
        self.client.force_login(self.apprenant)
        response = self.client.get(reverse("courses:lecon_lire", args=[lecon.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertLess(response.content.index(b"Premier"), response.content.index(b"Deuxi\xc3\xa8me"))
        self.assertNotEqual(first.pk, second.pk)
        progress = LessonProgress.objects.get(inscription__apprenant=self.apprenant, lesson=lecon)
        self.assertEqual(progress.etat, LessonProgress.Etat.EN_COURS)
        self.assertEqual(Inscription.objects.get(apprenant=self.apprenant, cours=self.cours).derniere_lecon, lecon)

    def test_validation_de_fichier_refuse_un_pdf_falsifie(self):
        fake_pdf = SimpleUploadedFile("cours.pdf", b"<script>not a pdf</script>", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            valider_fichier_cours(fake_pdf)

    def test_ressource_privee_refuse_un_apprenant_non_inscrit(self):
        lecon = Lesson.objects.create(module=self.module, titre="Document", ordre=1, est_publiee=True)
        bloc = LessonContent.objects.create(lesson=lecon, type="pdf", fichier="ressources/secret.pdf", ordre=1)
        self.client.force_login(self.autre_apprenant)
        response = self.client.get(reverse("courses:ressource_lecon", args=[bloc.pk]))
        self.assertEqual(response.status_code, 403)

    def test_ressource_pdf_autorisee_est_servie_en_ligne_a_l_inscrit(self):
        lecon = Lesson.objects.create(module=self.module, titre="PDF", ordre=1, est_publiee=True)
        bloc = LessonContent.objects.create(lesson=lecon, type="pdf", fichier="ressources/cours.pdf", ordre=1)
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours)
        self.client.force_login(self.apprenant)
        with patch.object(CourseResourceStorage, "open", return_value=BytesIO(b"%PDF-1.4 test")):
            response = self.client.get(reverse("courses:ressource_lecon", args=[bloc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")

    def test_url_video_externe_limitee_aux_fournisseurs_autorises(self):
        lecon = Lesson.objects.create(module=self.module, titre="Vidéo", ordre=1)
        block = LessonContent(lesson=lecon, type="video", url="https://evil.example/video")
        with self.assertRaises(ValidationError):
            block.full_clean()

    def test_catalogue_recherche_et_filtre_affichent_les_comptages(self):
        self.cours.categorie = "Programmation"
        self.cours.niveau = "debutant"
        self.cours.duree_estimee = 5
        self.cours.save()
        lecon = Lesson.objects.create(module=self.module, titre="Catalogue leçon", ordre=1, est_publiee=True)
        self.client.force_login(self.apprenant)
        response = self.client.get(reverse("courses:index"), {"q": "Django", "niveau": "debutant", "categorie": "Programmation"})
        self.assertContains(response, "1 chapitre")
        self.assertContains(response, "1 leçon")
        self.assertContains(response, "5 h")
        self.assertNotContains(response, "Autre cours")

    def test_cours_sans_lecon_publiee_ne_peut_pas_afficher_cent_pourcent(self):
        lecon = Lesson.objects.create(module=self.module, titre="Brouillon", ordre=1, est_publiee=False)
        inscription = Inscription.objects.create(apprenant=self.apprenant, cours=self.cours, progression=100)
        ProgressionModule.objects.create(inscription=inscription, module=self.module)
        recalculer_progression(inscription)
        inscription.refresh_from_db()
        self.assertEqual(inscription.progression, 0)
        self.assertFalse(LessonProgress.objects.filter(lesson=lecon, inscription=inscription).exists())

    def test_progression_de_lecon_persistante_et_propre_a_l_apprenant(self):
        lecon = Lesson.objects.create(module=self.module, titre="Leçon", ordre=1, est_publiee=True)
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours)
        self.client.force_login(self.apprenant)
        self.client.post(reverse("courses:lecon_terminer", args=[lecon.pk]))
        inscription = Inscription.objects.get(apprenant=self.apprenant, cours=self.cours)
        self.assertTrue(LessonProgress.objects.filter(inscription=inscription, lesson=lecon).exists())
        progress = LessonProgress.objects.get(inscription=inscription, lesson=lecon)
        self.assertEqual(progress.etat, LessonProgress.Etat.TERMINEE)
        self.assertIsNotNone(progress.date_terminaison)
        self.assertEqual(inscription.progression, 100)

    def test_detail_du_cours_propose_la_reprise_a_la_derniere_lecon_vue(self):
        premiere = Lesson.objects.create(module=self.module, titre="Première", ordre=1, est_publiee=True)
        seconde = Lesson.objects.create(module=self.module, titre="Seconde", ordre=2, est_publiee=True)
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours)
        self.client.force_login(self.apprenant)
        self.client.get(reverse("courses:lecon_lire", args=[seconde.pk]))
        response = self.client.get(reverse("courses:detail", args=[self.cours.pk]))
        self.assertContains(response, "Continuer : Seconde")
        self.assertNotEqual(premiere.pk, seconde.pk)

    def test_formateur_peut_creer_une_lecon_dans_son_chapitre(self):
        self.client.force_login(self.formateur)
        response = self.client.post(reverse("courses:lecon_creer", args=[self.module.pk]), {
            "titre": "Nouvelle leçon", "ordre": 1, "duree_estimee": 8, "est_publiee": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Lesson.objects.filter(module=self.module, titre="Nouvelle leçon").exists())

    def test_formateur_peut_ajouter_un_chapitre(self):
        self.client.force_login(self.formateur)
        response = self.client.post(reverse("courses:module_creer", args=[self.cours.pk]), {
            "titre": "Nouveau chapitre", "description": "Description pédagogique", "ordre": 2,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Module.objects.filter(cours=self.cours, titre="Nouveau chapitre").exists())

    def test_administrateur_garde_l_acces_aux_brouillons_mais_ne_s_inscrit_pas(self):
        self.client.force_login(self.administrateur)

        catalogue = self.client.get(reverse("courses:index"))
        detail = self.client.get(reverse("courses:detail", args=[self.brouillon.pk]))
        action = self.client.post(reverse("courses:inscrire", args=[self.cours.pk]))

        self.assertContains(catalogue, "Brouillon")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(action.status_code, 403)
        self.assertFalse(Inscription.objects.exists())

    def test_cours_non_publie_est_introuvable_pour_un_apprenant(self):
        self.client.force_login(self.apprenant)

        reponse = self.client.post(
            reverse("courses:inscrire", args=[self.brouillon.pk]), follow=True
        )

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Ce cours n’est pas disponible à l’inscription.")
        self.assertNotContains(reponse, self.brouillon.titre)
        self.assertFalse(Inscription.objects.exists())

    def test_action_refuse_get(self):
        self.client.force_login(self.apprenant)

        reponse = self.client.get(self.url_inscription)

        self.assertEqual(reponse.status_code, 405)
        self.assertFalse(Inscription.objects.exists())

    def test_action_est_protegee_par_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.apprenant)

        reponse = client.post(self.url_inscription)

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Inscription.objects.exists())

    def test_catalogue_affiche_le_bon_etat_d_inscription(self):
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours)
        self.client.force_login(self.apprenant)

        reponse = self.client.get(reverse("courses:index"))

        self.assertContains(reponse, "Continuer")
        self.assertContains(reponse, "S’inscrire")
        self.assertNotContains(reponse, "Brouillon")

    def test_detail_affiche_si_deja_inscrit(self):
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours)
        self.client.force_login(self.apprenant)

        reponse = self.client.get(reverse("courses:detail", args=[self.cours.pk]))

        self.assertContains(reponse, "Déjà inscrit")
        self.assertNotContains(reponse, "S’inscrire")

    def test_mes_cours_affiche_uniquement_les_inscriptions_de_l_apprenant(self):
        Inscription.objects.create(apprenant=self.apprenant, cours=self.cours, progression=35)
        Inscription.objects.create(apprenant=self.autre_apprenant, cours=self.autre_cours, progression=80)
        self.client.force_login(self.apprenant)

        reponse = self.client.get(reverse("courses:mes_cours"))

        self.assertContains(reponse, "Django")
        self.assertContains(reponse, "35 %")
        self.assertNotContains(reponse, "Python")

    def test_mes_cours_est_reserve_aux_apprenants(self):
        self.client.force_login(self.formateur)

        reponse = self.client.get(reverse("courses:mes_cours"))

        self.assertEqual(reponse.status_code, 403)

    def test_visiteur_non_connecte_est_redirige_vers_la_connexion(self):
        reponse = self.client.post(self.url_inscription)

        self.assertRedirects(
            reponse,
            f"{reverse('accounts:login')}?next={self.url_inscription}",
            fetch_redirect_response=False,
        )
        self.assertFalse(Inscription.objects.exists())


class LessonAssistantTests(TestCase):
    def setUp(self):
        self.student = creer_utilisateur(User.Role.APPRENANT, "assistantstudent")
        self.teacher = creer_utilisateur(User.Role.FORMATEUR, "assistantteacher")
        self.other = creer_utilisateur(User.Role.APPRENANT, "assistantother")
        self.admin = creer_utilisateur(User.Role.ADMINISTRATEUR, "assistantadmin")
        self.course = Cours.objects.create(formateur=self.teacher, titre="Python", est_publie=True)
        self.module = Module.objects.create(cours=self.course, titre="Bases")
        self.lesson = Lesson.objects.create(module=self.module, titre="Variables", ordre=1, est_publiee=True)
        LessonContent.objects.create(lesson=self.lesson, type="text", texte="Une variable stocke une valeur. Python possède plusieurs types.", ordre=1)
        self.url = reverse("courses:assistant_lecon")

    def test_assistant_repond_a_partir_du_contenu_de_la_lecon(self):
        Inscription.objects.create(apprenant=self.student, cours=self.course)
        self.client.force_login(self.student)
        with patch("apps.courses.ai_assistant.predict.predict_intent", return_value="resume"):
            response = self.client.post(self.url, data={"lesson_id": self.lesson.pk, "question": "résume"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Une variable stocke", response.json()["answer"])

    def test_assistant_refuse_question_vide_ou_trop_longue(self):
        Inscription.objects.create(apprenant=self.student, cours=self.course)
        self.client.force_login(self.student)
        for question in ("", "x" * 501):
            response = self.client.post(self.url, data={"lesson_id": self.lesson.pk, "question": question}, content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_assistant_refuse_un_apprenant_non_inscrit(self):
        self.client.force_login(self.other)
        response = self.client.post(self.url, data={"lesson_id": self.lesson.pk, "question": "résume"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_admin_connecte_peut_previsualiser_l_assistant_sans_inscription(self):
        self.client.force_login(self.admin)
        with patch("apps.courses.ai_assistant.predict.predict_intent", return_value="simple"):
            response = self.client.post(self.url, data={"lesson_id": self.lesson.pk, "question": "explique simplement"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Une variable stocke", response.json()["answer"])

    def test_formateur_proprietaire_peut_previsualiser_mais_pas_un_autre_formateur(self):
        self.client.force_login(self.teacher)
        with patch("apps.courses.ai_assistant.predict.predict_intent", return_value="simple"):
            response = self.client.post(self.url, data={"lesson_id": self.lesson.pk, "question": "explique simplement"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        autre = creer_utilisateur(User.Role.FORMATEUR, "assistantotherteacher")
        self.client.force_login(autre)
        denied = self.client.post(self.url, data={"lesson_id": self.lesson.pk, "question": "explique simplement"}, content_type="application/json")
        self.assertEqual(denied.status_code, 403)

    def test_assistant_exemple_et_quiz_reprennent_le_contenu_reel(self):
        from apps.courses.ai_assistant.explainer import build_context, explain
        LessonContent.objects.create(lesson=self.lesson, type="code", texte="print('leçon')", ordre=2)
        context = build_context(self.lesson)
        self.assertIn("print('leçon')", explain("example", "donne un exemple", context))
        quiz = explain("quiz", "crée un quiz", context)
        self.assertIn("Une variable stocke", quiz)
        self.assertNotIn("Réponse : Vrai", quiz)

    def test_assistant_refuse_un_contenu_manifestement_gibberish(self):
        from apps.courses.ai_assistant.explainer import REFUS_CONTENU, build_context, explain
        noise_lesson = Lesson.objects.create(module=self.module, titre="Leçon bruitée", ordre=2, est_publiee=True)
        LessonContent.objects.create(
            lesson=noise_lesson, type="text",
            texte="asdfghjkl qwerty zxcvbn asdfghjkl qwerty zxcvbn asdfghjkl qwerty zxcvbn",
            ordre=1,
        )
        context = build_context(noise_lesson)
        for intent in ("resume", "simple", "example", "quiz", "question"):
            self.assertEqual(explain(intent, "explique cette leçon", context), REFUS_CONTENU)

    def test_api_assistant_signale_quand_le_contenu_est_inexploitable(self):
        noise_lesson = Lesson.objects.create(module=self.module, titre="Texte incohérent", ordre=2, est_publiee=True)
        LessonContent.objects.create(lesson=noise_lesson, type="text", texte="asdfghjkl qwerty zxcvbn asdfghjkl qwerty zxcvbn", ordre=1)
        Inscription.objects.create(apprenant=self.student, cours=self.course)
        self.client.force_login(self.student)
        with patch("apps.courses.ai_assistant.predict.predict_intent", return_value="simple"):
            response = self.client.post(self.url, data={"lesson_id": noise_lesson.pk, "question": "Explique simplement"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("ne peux pas répondre de façon fiable", response.json()["answer"])

    def test_assistant_refuse_une_question_sans_lien_avec_la_lecon(self):
        from apps.courses.ai_assistant.explainer import REFUS_PERTINENCE, build_context, explain
        context = build_context(self.lesson)
        answer = explain("question", "Quelle est la capitale du Japon ?", context)
        self.assertEqual(answer, REFUS_PERTINENCE)

    def test_artefact_absent_est_signale_sans_erreur_500(self):
        Inscription.objects.create(apprenant=self.student, cours=self.course)
        self.client.force_login(self.student)
        with patch("apps.courses.ai_assistant.predict.predict_intent", side_effect=FileNotFoundError("Modèle absent")):
            response = self.client.post(self.url, data={"lesson_id": self.lesson.pk, "question": "résume"}, content_type="application/json")
        self.assertEqual(response.status_code, 503)

    def test_dataset_synthetique_entrainement_et_rechargement(self):
        from apps.courses.ai_assistant.dataset_generator import generate_dataset
        from apps.courses.ai_assistant.train_model import train
        from apps.courses.ai_assistant.predict import predict_intent
        import csv
        base = settings.BASE_DIR / "apps/courses/ai_assistant"
        dataset = generate_dataset(base / "dataset.csv")
        artifact = base / "models/test-intention.joblib"
        with dataset.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        self.assertGreaterEqual(len(rows), 100)
        split_subjects = {split: {row["subject_id"] for row in rows if row["split"] == split} for split in ("train", "validation", "test")}
        self.assertFalse(split_subjects["train"] & split_subjects["validation"])
        self.assertFalse(split_subjects["train"] & split_subjects["test"])
        self.assertFalse(split_subjects["validation"] & split_subjects["test"])
        metrics = train(dataset, artifact)
        self.assertEqual(set(metrics["partitions"]), {"validation", "test"})
        self.assertGreaterEqual(metrics["partitions"]["test"]["f1_macro"], 0)
        self.assertIn(predict_intent("Résume cette leçon", artifact), {
            "resume", "simple", "example", "steps", "definition", "quiz", "question",
        })
