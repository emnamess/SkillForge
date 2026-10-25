from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError


class Cours(models.Model):
    """Cours proposé par un formateur."""

    formateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cours_crees",
        verbose_name="formateur",
    )
    titre = models.CharField("titre", max_length=200)
    description = models.TextField("description", blank=True)
    est_publie = models.BooleanField("publié", default=False)
    date_creation = models.DateTimeField("date de création", auto_now_add=True)
    date_modification = models.DateTimeField("dernière modification", auto_now=True)

    class Meta:
        verbose_name = "cours"
        verbose_name_plural = "cours"
        ordering = ["titre"]

    def __str__(self):
        return self.titre


class Module(models.Model):
    """Module pédagogique appartenant à un cours."""

    cours = models.ForeignKey(
        Cours,
        on_delete=models.CASCADE,
        related_name="modules",
        verbose_name="cours",
    )
    titre = models.CharField("titre", max_length=200)
    description = models.TextField("description", blank=True)
    contenu = models.TextField("contenu pédagogique", blank=True)
    ordre = models.PositiveIntegerField("ordre d’affichage", default=0)

    class Meta:
        verbose_name = "module"
        verbose_name_plural = "modules"
        ordering = ["ordre", "pk"]

    def clean(self):
        super().clean()
        if self.pk:
            cours_original = Module.objects.filter(pk=self.pk).values_list("cours_id", flat=True).first()
            if cours_original != self.cours_id and self.progressions.exists():
                raise ValidationError(
                    "Un module déjà validé par des apprenants ne peut pas être transféré vers un autre cours."
                )

    def __str__(self):
        return f"{self.cours.titre} · {self.titre}"


class Inscription(models.Model):
    """Inscription d’un apprenant à un cours et progression associée."""

    apprenant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="inscriptions_cours",
        verbose_name="apprenant",
    )
    cours = models.ForeignKey(
        Cours,
        on_delete=models.CASCADE,
        related_name="inscriptions",
        verbose_name="cours",
    )
    progression = models.PositiveSmallIntegerField(
        "progression (%)",
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    date_inscription = models.DateTimeField("date d’inscription", auto_now_add=True)

    class Meta:
        verbose_name = "inscription"
        verbose_name_plural = "inscriptions"
        ordering = ["-date_inscription"]
        constraints = [
            models.UniqueConstraint(
                fields=["apprenant", "cours"],
                name="inscription_unique_apprenant_cours",
            ),
            models.CheckConstraint(
                condition=Q(progression__gte=0) & Q(progression__lte=100),
                name="inscription_progression_0_100",
            ),
        ]

    def __str__(self):
        return f"{self.apprenant} · {self.cours.titre} ({self.progression} %)"


class ProgressionModule(models.Model):
    """Validation explicite d’un module par un apprenant inscrit à son cours."""

    inscription = models.ForeignKey(
        Inscription,
        on_delete=models.CASCADE,
        related_name="modules_termines",
        verbose_name="inscription",
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name="progressions",
        verbose_name="module",
    )
    date_terminaison = models.DateTimeField("terminé le", auto_now_add=True)

    class Meta:
        verbose_name = "module terminé"
        verbose_name_plural = "modules terminés"
        ordering = ["date_terminaison"]
        constraints = [
            models.UniqueConstraint(
                fields=["inscription", "module"],
                name="progression_module_unique_inscription_module",
            ),
        ]

    def clean(self):
        super().clean()
        if self.inscription_id and self.module_id:
            if self.inscription.cours_id != self.module.cours_id:
                raise ValidationError("Le module doit appartenir au cours de l’inscription.")

    def __str__(self):
        return f"{self.inscription.apprenant} · {self.module}"
