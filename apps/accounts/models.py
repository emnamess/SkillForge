from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import slugify


class User(AbstractUser):
    """Utilisateur de SkillForge : apprenant, formateur, recruteur ou administrateur."""

    class Role(models.TextChoices):
        APPRENANT = "apprenant", "Apprenant"
        FORMATEUR = "formateur", "Formateur"
        RECRUTEUR = "recruteur", "Recruteur"
        ADMINISTRATEUR = "administrateur", "Administrateur"

    email = models.EmailField("adresse e-mail", unique=True)
    role = models.CharField("rôle", max_length=20, choices=Role.choices, default=Role.APPRENANT)
    bio = models.TextField("présentation", blank=True)
    specialite = models.CharField("spécialité", max_length=120, blank=True)
    est_valide = models.BooleanField(
        "compte validé",
        default=True,
        help_text="Un formateur inscrit doit être validé par un administrateur.",
    )

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        ordering = ["-date_joined"]

    def __str__(self):
        return self.get_full_name() or self.username

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMINISTRATEUR
        self.email = self.email.lower()
        super().save(*args, **kwargs)

    @classmethod
    def generer_username(cls, email):
        """Construit un nom d'utilisateur unique à partir de l'e-mail."""
        base = slugify(email.split("@")[0]) or "utilisateur"
        username, n = base, 1
        while cls.objects.filter(username=username).exists():
            n += 1
            username = f"{base}{n}"
        return username

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
    def est_recruteur(self):
        """Recruteur d'entreprise : sa validation est portée par careers (ProfilEntreprise.statut)."""
        return self.role == self.Role.RECRUTEUR

    @property
    def est_administrateur(self):
        return self.role == self.Role.ADMINISTRATEUR or self.is_superuser

    @property
    def en_attente_validation(self):
        return self.est_formateur and not self.est_valide
