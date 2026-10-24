import secrets

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

# Sans 0/O, 1/I/L : un code lisible et facile à recopier
ALPHABET_CODE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generer_code_verification():
    """Code unique du type SF-7K2M-Q9XA, imprimé sur le certificat."""
    while True:
        brut = "".join(secrets.choice(ALPHABET_CODE) for _ in range(8))
        code = f"SF-{brut[:4]}-{brut[4:]}"
        if not Certificat.objects.filter(code_verification=code).exists():
            return code


class Certificat(models.Model):
    """Certificat délivré à un apprenant qui a terminé un cours.

    Le titre du cours et le nom du formateur sont recopiés au moment de la délivrance :
    le certificat reste exact même si le cours est renommé ou supprimé plus tard.
    """

    class Statut(models.TextChoices):
        VALIDE = "valide", "Valide"
        REVOQUE = "revoque", "Révoqué"

    apprenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                  related_name="certificats", verbose_name="apprenant")
    titre_cours = models.CharField("cours", max_length=200)
    formateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="certificats_cours", verbose_name="formateur")
    nom_formateur = models.CharField("nom du formateur", max_length=150, blank=True)
    competences = models.TextField("compétences validées", blank=True, help_text="Une compétence par ligne.")
    score = models.PositiveSmallIntegerField(
        "score final (%)", null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Moyenne des quiz du cours, sur 100.",
    )
    duree_heures = models.PositiveSmallIntegerField("durée (heures)", null=True, blank=True)

    code_verification = models.CharField("code de vérification", max_length=12, unique=True,
                                         editable=False)
    date_delivrance = models.DateTimeField("délivré le", default=timezone.now)
    delivre_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="certificats_delivres", verbose_name="délivré par")

    statut = models.CharField("statut", max_length=10, choices=Statut.choices, default=Statut.VALIDE)
    motif_revocation = models.TextField("motif de la révocation", blank=True)
    date_revocation = models.DateTimeField("révoqué le", null=True, blank=True)
    revoque_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="révoqué par")

    class Meta:
        verbose_name = "certificat"
        verbose_name_plural = "certificats"
        ordering = ["-date_delivrance"]
        constraints = [
            # Un seul certificat valide par apprenant et par cours
            models.UniqueConstraint(fields=["apprenant", "titre_cours"], condition=Q(statut="valide"),
                                    name="certificat_unique_par_cours"),
        ]

    def __str__(self):
        return f"{self.titre_cours} · {self.apprenant} ({self.code_verification})"

    def save(self, *args, **kwargs):
        if not self.code_verification:
            self.code_verification = generer_code_verification()
        if self.formateur_id and not self.nom_formateur:
            self.nom_formateur = str(self.formateur)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("certificates:detail", args=[self.code_verification])

    def get_verification_url(self):
        return reverse("certificates:verifier_code", args=[self.code_verification])

    @property
    def est_valide(self):
        return self.statut == self.Statut.VALIDE

    @property
    def liste_competences(self):
        return [c.strip(" -•\t") for c in self.competences.splitlines() if c.strip(" -•\t")]

    @property
    def mention(self):
        if self.score is None:
            return ""
        if self.score >= 90:
            return "Excellent"
        if self.score >= 80:
            return "Très bien"
        if self.score >= 70:
            return "Bien"
        return "Validé"

    @staticmethod
    def normaliser_titre(titre):
        return " ".join(titre.split()).casefold()

    @classmethod
    def doublon_valide(cls, apprenant, titre_cours, exclure=None):
        """Certificat valide du même apprenant pour ce cours (casse et accents majuscules ignorés).

        La comparaison se fait en Python : sous SQLite, `iexact` ignore la casse des lettres ASCII
        seulement (« AVANCÉ » ≠ « avancé »). Un apprenant a peu de certificats, c'est donc sans coût.
        """
        cible = cls.normaliser_titre(titre_cours)
        qs = cls.objects.filter(apprenant=apprenant, statut=cls.Statut.VALIDE)
        if exclure is not None:
            qs = qs.exclude(pk=exclure.pk)
        return next((c for c in qs if cls.normaliser_titre(c.titre_cours) == cible), None)

    def peut_etre_modifie_par(self, user):
        if not user.is_authenticated or user.en_attente_validation:
            return False
        return user.est_administrateur or (user.est_formateur and user.pk in (self.formateur_id, self.delivre_par_id))

    def peut_etre_consulte_par(self, user):
        if not user.is_authenticated:
            return False
        return (user.est_administrateur or user.pk == self.apprenant_id
                or user.pk in (self.formateur_id, self.delivre_par_id))
