"""Modèles du module Quiz et correction IA.

Cinq modèles : Quiz → Question → Choix (QCM), et Tentative → Réponse (apprenant).
Les réponses à des questions de type TEXTE_LIBRE sont corrigées par Gemini (voir services.py).
"""

from django.conf import settings
from django.db import models
from django.urls import reverse


class Quiz(models.Model):
    """Quiz créé par un formateur, éventuellement lié à un cours."""

    formateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiz_crees",
        verbose_name="formateur",
    )
    titre = models.CharField("titre", max_length=200)
    description = models.TextField("description", blank=True)
    seuil_reussite = models.PositiveIntegerField(
        "seuil de réussite (%)",
        default=50,
        help_text="Pourcentage minimum pour réussir le quiz.",
    )
    est_publie = models.BooleanField("publié", default=False)
    duree_minutes = models.PositiveIntegerField(
        "durée (minutes)",
        null=True,
        blank=True,
        help_text="Temps imparti. Vide = pas de limite.",
    )
    date_creation = models.DateTimeField("date de création", auto_now_add=True)
    date_modification = models.DateTimeField("dernière modification", auto_now=True)

    class Meta:
        verbose_name = "quiz"
        verbose_name_plural = "quiz"
        ordering = ["-date_creation"]

    def __str__(self):
        return self.titre

    def get_absolute_url(self):
        return reverse("quizzes:quiz_detail", args=[self.pk])

    @property
    def nombre_questions(self):
        return self.questions.count()

    @property
    def total_points(self):
        return self.questions.aggregate(total=models.Sum("points"))["total"] or 0

    @property
    def nombre_tentatives(self):
        return self.tentatives.filter(terminee=True).count()


class Question(models.Model):
    """Question appartenant à un quiz."""

    class Type(models.TextChoices):
        QCM = "qcm", "Choix multiples"
        VRAI_FAUX = "vrai_faux", "Vrai ou faux"
        TEXTE_LIBRE = "texte_libre", "Réponse libre (corrigée par l'IA)"

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    type = models.CharField("type", max_length=15, choices=Type.choices, default=Type.QCM)
    enonce = models.TextField("énoncé")
    points = models.PositiveIntegerField("points", default=1)
    ordre = models.PositiveIntegerField("ordre", default=0)
    explication = models.TextField(
        "explication",
        blank=True,
        help_text="Affichée après la correction pour aider l'apprenant.",
    )
    # Pour les questions texte libre : indications pour l'IA
    consigne_ia = models.TextField(
        "consigne pour l'IA",
        blank=True,
        help_text="Réponse attendue ou critères de correction pour l'IA.",
    )

    class Meta:
        verbose_name = "question"
        verbose_name_plural = "questions"
        ordering = ["ordre", "pk"]

    def __str__(self):
        return f"Q{self.ordre} · {self.enonce[:60]}"


class Choix(models.Model):
    """Option de réponse pour une question QCM ou Vrai/Faux."""

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choix")
    texte = models.CharField("texte", max_length=500)
    est_correct = models.BooleanField("bonne réponse", default=False)
    ordre = models.PositiveIntegerField("ordre", default=0)

    class Meta:
        verbose_name = "choix"
        verbose_name_plural = "choix"
        ordering = ["ordre", "pk"]

    def __str__(self):
        marque = "✓" if self.est_correct else "✗"
        return f"{marque} {self.texte[:50]}"


class Tentative(models.Model):
    """Tentative d'un apprenant sur un quiz."""

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="tentatives")
    apprenant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tentatives",
        verbose_name="apprenant",
    )
    score = models.DecimalField("score obtenu", max_digits=6, decimal_places=2, null=True, blank=True)
    score_total = models.DecimalField("score total", max_digits=6, decimal_places=2, null=True, blank=True)
    pourcentage = models.DecimalField("pourcentage", max_digits=5, decimal_places=2, null=True, blank=True)
    reussie = models.BooleanField("réussie", null=True, blank=True)
    terminee = models.BooleanField("terminée", default=False)
    date_debut = models.DateTimeField("début", auto_now_add=True)
    date_fin = models.DateTimeField("fin", null=True, blank=True)

    class Meta:
        verbose_name = "tentative"
        verbose_name_plural = "tentatives"
        ordering = ["-date_debut"]

    def __str__(self):
        return f"{self.apprenant} · {self.quiz} · {self.pourcentage or '?'}%"

    def get_absolute_url(self):
        return reverse("quizzes:tentative_detail", args=[self.pk])

    def calculer_score(self):
        """Calcule le score total à partir des réponses corrigées."""
        reponses = self.reponses.filter(corrigee=True)
        self.score = sum(r.points_obtenus for r in reponses)
        self.score_total = sum(r.question.points for r in self.reponses.select_related("question").all())
        if self.score_total > 0:
            self.pourcentage = round((self.score / self.score_total) * 100, 2)
        else:
            self.pourcentage = 0
        self.reussie = self.pourcentage >= self.quiz.seuil_reussite
        self.save(update_fields=["score", "score_total", "pourcentage", "reussie"])


class Reponse(models.Model):
    """Réponse d'un apprenant à une question dans une tentative."""

    tentative = models.ForeignKey(Tentative, on_delete=models.CASCADE, related_name="reponses")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="reponses")
    # Pour QCM / Vrai-Faux
    choix_selectionne = models.ForeignKey(
        Choix,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reponses",
        verbose_name="choix sélectionné",
    )
    # Pour texte libre
    texte_libre = models.TextField("réponse libre", blank=True)
    # Résultat de la correction
    est_correcte = models.BooleanField("correcte", null=True, blank=True)
    points_obtenus = models.DecimalField("points obtenus", max_digits=5, decimal_places=2, default=0)
    feedback_ia = models.TextField("feedback IA", blank=True)
    corrigee = models.BooleanField("corrigée", default=False)

    class Meta:
        verbose_name = "réponse"
        verbose_name_plural = "réponses"
        ordering = ["question__ordre"]
        unique_together = [("tentative", "question")]

    def __str__(self):
        return f"Réponse de {self.tentative.apprenant} à Q{self.question.ordre}"

    def corriger_qcm(self):
        """Corrige une réponse QCM ou Vrai/Faux."""
        if self.choix_selectionne:
            self.est_correcte = self.choix_selectionne.est_correct
            self.points_obtenus = self.question.points if self.est_correcte else 0
        else:
            self.est_correcte = False
            self.points_obtenus = 0
        self.corrigee = True
        self.save(update_fields=["est_correcte", "points_obtenus", "corrigee"])
