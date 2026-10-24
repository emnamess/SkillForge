"""Tests du module Quiz et correction IA.

Couverture :
- Modèles : création, propriétés calculées
- Vues : accès selon le rôle, création de quiz, passage d'un quiz
- Services : correction QCM, correction texte libre sans IA
"""

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User

from .models import Choix, Question, Quiz, Reponse, Tentative
from .services import corriger_tentative


def creer_utilisateur(role, username, est_valide=True):
    u = User.objects.create_user(
        username=username,
        email=f"{username}@test.skillforge.tn",
        password="testpass123",
        role=role,
        est_valide=est_valide,
    )
    return u


def creer_quiz_complet(formateur):
    """Crée un quiz avec deux QCM et une question texte libre."""
    quiz = Quiz.objects.create(
        formateur=formateur,
        titre="Quiz Python",
        description="Bases de Python",
        seuil_reussite=50,
        est_publie=True,
    )
    q1 = Question.objects.create(quiz=quiz, type=Question.Type.QCM, enonce="Qu'est-ce que Python ?", points=2, ordre=1)
    Choix.objects.create(question=q1, texte="Un serpent", est_correct=False, ordre=1)
    Choix.objects.create(question=q1, texte="Un langage de programmation", est_correct=True, ordre=2)
    Choix.objects.create(question=q1, texte="Un logiciel", est_correct=False, ordre=3)

    q2 = Question.objects.create(quiz=quiz, type=Question.Type.VRAI_FAUX, enonce="Python est un langage typé ?", points=1, ordre=2)
    Choix.objects.create(question=q2, texte="Vrai", est_correct=True, ordre=1)
    Choix.objects.create(question=q2, texte="Faux", est_correct=False, ordre=2)

    q3 = Question.objects.create(
        quiz=quiz, type=Question.Type.TEXTE_LIBRE, enonce="Expliquez les listes en Python.", points=3, ordre=3,
        consigne_ia="Les listes sont des collections ordonnées et mutables."
    )

    return quiz, q1, q2, q3


# ──────────────────────────────────────────────
# Tests des modèles
# ──────────────────────────────────────────────

class QuizModelTests(TestCase):
    def setUp(self):
        self.formateur = creer_utilisateur(User.Role.FORMATEUR, "formateur1")

    def test_creation_quiz(self):
        quiz = Quiz.objects.create(formateur=self.formateur, titre="Mon quiz", seuil_reussite=60)
        self.assertEqual(str(quiz), "Mon quiz")
        self.assertEqual(quiz.nombre_questions, 0)
        self.assertEqual(quiz.total_points, 0)

    def test_proprietes_quiz(self):
        quiz, q1, q2, q3 = creer_quiz_complet(self.formateur)
        self.assertEqual(quiz.nombre_questions, 3)
        self.assertEqual(quiz.total_points, 6)  # 2 + 1 + 3

    def test_get_absolute_url(self):
        quiz = Quiz.objects.create(formateur=self.formateur, titre="Test URL")
        self.assertIn(str(quiz.pk), quiz.get_absolute_url())


class QuestionModelTests(TestCase):
    def setUp(self):
        self.formateur = creer_utilisateur(User.Role.FORMATEUR, "formateur2")
        self.quiz = Quiz.objects.create(formateur=self.formateur, titre="Quiz test")

    def test_types_question(self):
        for type_q in (Question.Type.QCM, Question.Type.VRAI_FAUX, Question.Type.TEXTE_LIBRE):
            q = Question.objects.create(quiz=self.quiz, type=type_q, enonce="Question", points=1)
            self.assertEqual(q.type, type_q)


# ──────────────────────────────────────────────
# Tests des services (correction sans IA)
# ──────────────────────────────────────────────

class CorrectionTests(TestCase):
    def setUp(self):
        self.formateur = creer_utilisateur(User.Role.FORMATEUR, "formateur3")
        self.apprenant = creer_utilisateur(User.Role.APPRENANT, "apprenant1")
        self.quiz, self.q1, self.q2, self.q3 = creer_quiz_complet(self.formateur)

    def test_correction_qcm_correct(self):
        tentative = Tentative.objects.create(quiz=self.quiz, apprenant=self.apprenant)
        bonne_reponse = self.q1.choix.get(est_correct=True)
        r = Reponse.objects.create(tentative=tentative, question=self.q1, choix_selectionne=bonne_reponse)
        r.corriger_qcm()
        r.refresh_from_db()
        self.assertTrue(r.est_correcte)
        self.assertEqual(r.points_obtenus, 2)

    def test_correction_qcm_incorrect(self):
        tentative = Tentative.objects.create(quiz=self.quiz, apprenant=self.apprenant)
        mauvaise_reponse = self.q1.choix.filter(est_correct=False).first()
        r = Reponse.objects.create(tentative=tentative, question=self.q1, choix_selectionne=mauvaise_reponse)
        r.corriger_qcm()
        r.refresh_from_db()
        self.assertFalse(r.est_correcte)
        self.assertEqual(r.points_obtenus, 0)

    def test_calcul_score(self):
        tentative = Tentative.objects.create(quiz=self.quiz, apprenant=self.apprenant)
        bonne_q1 = self.q1.choix.get(est_correct=True)
        bonne_q2 = self.q2.choix.get(est_correct=True)
        Reponse.objects.create(tentative=tentative, question=self.q1, choix_selectionne=bonne_q1, est_correcte=True, points_obtenus=2, corrigee=True)
        Reponse.objects.create(tentative=tentative, question=self.q2, choix_selectionne=bonne_q2, est_correcte=True, points_obtenus=1, corrigee=True)
        Reponse.objects.create(tentative=tentative, question=self.q3, texte_libre="test", points_obtenus=0, est_correcte=False, corrigee=True)
        tentative.calculer_score()
        tentative.refresh_from_db()
        self.assertEqual(tentative.score, Decimal("3"))
        self.assertEqual(tentative.score_total, Decimal("6"))
        self.assertEqual(tentative.pourcentage, Decimal("50.00"))


# ──────────────────────────────────────────────
# Tests des vues
# ──────────────────────────────────────────────

class QuizVuesTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.formateur = creer_utilisateur(User.Role.FORMATEUR, "formateur4")
        self.apprenant = creer_utilisateur(User.Role.APPRENANT, "apprenant2")
        self.quiz, self.q1, self.q2, self.q3 = creer_quiz_complet(self.formateur)

    def test_index_redirige_si_non_connecte(self):
        r = self.client.get(reverse("quizzes:index"))
        self.assertRedirects(r, f"/comptes/connexion/?next=/quiz/", fetch_redirect_response=False)

    def test_index_formateur(self):
        self.client.login(username="formateur4", password="testpass123")
        r = self.client.get(reverse("quizzes:index"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Quiz Python")

    def test_index_apprenant(self):
        self.client.login(username="apprenant2", password="testpass123")
        r = self.client.get(reverse("quizzes:index"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Quiz Python")

    def test_detail_quiz_publie(self):
        self.client.login(username="apprenant2", password="testpass123")
        r = self.client.get(reverse("quizzes:quiz_detail", args=[self.quiz.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Quiz Python")

    def test_detail_quiz_non_publie_interdit_apprenant(self):
        quiz_prive = Quiz.objects.create(formateur=self.formateur, titre="Quiz privé", est_publie=False)
        self.client.login(username="apprenant2", password="testpass123")
        r = self.client.get(reverse("quizzes:quiz_detail", args=[quiz_prive.pk]))
        self.assertEqual(r.status_code, 404)

    def test_creer_quiz_formateur(self):
        self.client.login(username="formateur4", password="testpass123")
        r = self.client.post(reverse("quizzes:quiz_creer"), {
            "titre": "Quiz Django",
            "description": "Bases de Django",
            "seuil_reussite": 60,
            "est_publie": False,
        })
        self.assertEqual(Quiz.objects.filter(titre="Quiz Django").count(), 1)

    def test_creer_quiz_interdit_apprenant(self):
        self.client.login(username="apprenant2", password="testpass123")
        r = self.client.get(reverse("quizzes:quiz_creer"))
        self.assertEqual(r.status_code, 403)

    def test_passer_quiz_soumettre(self):
        self.client.login(username="apprenant2", password="testpass123")
        bonne_q1 = self.q1.choix.get(est_correct=True)
        bonne_q2 = self.q2.choix.get(est_correct=True)
        r = self.client.post(reverse("quizzes:passer_quiz", args=[self.quiz.pk]), {
            f"question_{self.q1.pk}": bonne_q1.pk,
            f"question_{self.q2.pk}": bonne_q2.pk,
            f"question_{self.q3.pk}": "Les listes sont des collections ordonnées en Python.",
        })
        tentative = Tentative.objects.filter(apprenant=self.apprenant, quiz=self.quiz).first()
        self.assertIsNotNone(tentative)
        self.assertTrue(tentative.terminee)
