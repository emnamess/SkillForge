from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Utilisateur de SkillForge : apprenant, formateur ou administrateur."""

    class Role(models.TextChoices):
        APPRENANT = "apprenant", "Apprenant"
        FORMATEUR = "formateur", "Formateur"
        ADMINISTRATEUR = "administrateur", "Administrateur"

    email = models.EmailField("adresse e-mail", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.APPRENANT)

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def initiales(self):
        nom = self.get_full_name() or self.username
        return "".join(partie[0] for partie in nom.split()[:2]).upper()

    @property
    def est_apprenant(self):
        return self.role == self.Role.APPRENANT

    @property
    def est_formateur(self):
        return self.role == self.Role.FORMATEUR

    @property
    def est_administrateur(self):
        return self.role == self.Role.ADMINISTRATEUR or self.is_superuser
