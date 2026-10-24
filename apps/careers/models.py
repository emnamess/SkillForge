"""Espace Carrière : offres de stage et d'emploi, profils carrière et candidatures.

Module autonome : il ne dépend que de accounts.User (aucun lien vers les cours, quiz, etc.).
"""

import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.text import slugify


class StockagePrive(FileSystemStorage):
    """Stockage dans PRIVATE_MEDIA_ROOT, relu à chaque changement du réglage (utile pour les tests)."""

    @cached_property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    def _clear_cached_properties(self, setting, **kwargs):
        super()._clear_cached_properties(setting, **kwargs)
        if setting == "PRIVATE_MEDIA_ROOT":
            self.__dict__.pop("base_location", None)
            self.__dict__.pop("location", None)


_stockage_prive = StockagePrive()


def stockage_prive():
    """CV stockés hors de MEDIA_ROOT : ils ne sont servis que par la vue `telecharger_cv`."""
    return _stockage_prive


def chemin_cv(profil, nom_original):
    """Nom de fichier aléatoire : on ne peut ni le deviner ni écraser un autre fichier."""
    return f"careers/cv/{profil.apprenant_id}/{uuid.uuid4().hex}.pdf"


def chemin_cv_depose(candidature, nom_original):
    return f"careers/candidatures/{candidature.offre_id}/{uuid.uuid4().hex}.pdf"


def chemin_logo(entreprise, nom_original):
    extension = nom_original.rsplit(".", 1)[-1].lower() if "." in nom_original else "png"
    return f"careers/logos/{uuid.uuid4().hex}.{extension}"


class Niveau(models.IntegerChoices):
    NOTIONS = 1, "Notions"
    INTERMEDIAIRE = 2, "Intermédiaire"
    AVANCE = 3, "Avancé"
    EXPERT = 4, "Expert"


VALIDATEURS_NIVEAU = [MinValueValidator(1), MaxValueValidator(4)]


class TypeContrat(models.TextChoices):
    STAGE = "stage", "Stage"
    STAGE_PFE = "stage_pfe", "Stage PFE"
    CDI = "cdi", "CDI"
    CDD = "cdd", "CDD"
    ALTERNANCE = "alternance", "Alternance"
    FREELANCE = "freelance", "Freelance"


class Competence(models.Model):
    """Référentiel de compétences, géré par l'administrateur."""

    class Categorie(models.TextChoices):
        DATA = "data", "Data"
        DEVELOPPEMENT = "developpement", "Développement"
        SI = "si", "Systèmes d'information"
        OUTILS = "outils", "Outils et méthodes"
        SOFT_SKILLS = "soft_skills", "Soft skills"

    nom = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True, blank=True)
    categorie = models.CharField("catégorie", max_length=20, choices=Categorie.choices, default=Categorie.DATA)
    alias = models.TextField(blank=True, help_text="Synonymes séparés par des virgules, utilisés pour lire les CV.")

    class Meta:
        verbose_name = "compétence"
        ordering = ["categorie", "nom"]

    def __str__(self):
        return self.nom

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nom)[:90]
        super().save(*args, **kwargs)

    def liste_alias(self):
        return [a.strip() for a in self.alias.split(",") if a.strip()]


class ProfilEntreprise(models.Model):
    """Entreprise d'un recruteur. Elle doit être validée avant de pouvoir publier des offres."""

    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente de validation"
        VALIDEE = "validee", "Validée"
        REFUSEE = "refusee", "Refusée"

    utilisateur = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                       related_name="profil_entreprise")
    nom = models.CharField("nom de l'entreprise", max_length=150)
    secteur = models.CharField(max_length=100)
    ville = models.CharField(max_length=80)
    site_web = models.URLField("site web", blank=True)
    description = models.TextField(blank=True)
    logo = models.FileField(upload_to=chemin_logo, blank=True,
                            validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])])
    matricule_fiscal = models.CharField("matricule fiscal", max_length=30, blank=True)
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE, db_index=True)
    motif_refus = models.TextField("motif du refus", blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_decision = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "entreprise"
        ordering = ["nom"]

    def __str__(self):
        return self.nom

    @property
    def est_validee(self):
        return self.statut == self.Statut.VALIDEE


class OffreQuerySet(models.QuerySet):
    def ouvertes(self):
        """Offres visibles et ouvertes aux candidatures : une date limite passée vaut fermeture."""
        return self.filter(statut=Offre.Statut.PUBLIEE, entreprise__statut=ProfilEntreprise.Statut.VALIDEE).filter(
            Q(date_limite__isnull=True) | Q(date_limite__gte=timezone.localdate()))

    def de(self, recruteur):
        return self.filter(entreprise__utilisateur=recruteur)


class Offre(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        PUBLIEE = "publiee", "Publiée"
        FERMEE = "fermee", "Fermée"
        SUSPENDUE = "suspendue", "Suspendue"

    class ModeTravail(models.TextChoices):
        PRESENTIEL = "presentiel", "Présentiel"
        HYBRIDE = "hybride", "Hybride"
        TELETRAVAIL = "teletravail", "Télétravail"

    entreprise = models.ForeignKey(ProfilEntreprise, on_delete=models.CASCADE, related_name="offres")
    titre = models.CharField(max_length=150)
    description = models.TextField()
    type_contrat = models.CharField("type de contrat", max_length=12, choices=TypeContrat.choices)
    mode_travail = models.CharField("mode de travail", max_length=12, choices=ModeTravail.choices,
                                    default=ModeTravail.PRESENTIEL)
    ville = models.CharField(max_length=80)
    remuneration = models.CharField("rémunération", max_length=100, blank=True)
    date_limite = models.DateField("date limite de candidature", null=True, blank=True)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.BROUILLON)
    date_publication = models.DateTimeField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    objects = OffreQuerySet.as_manager()

    class Meta:
        ordering = ["-date_publication", "-date_creation"]
        indexes = [models.Index(fields=["statut", "date_limite"])]

    def __str__(self):
        return f"{self.titre} · {self.entreprise}"

    def get_absolute_url(self):
        return reverse("careers:offre_detail", args=[self.pk])

    @property
    def est_expiree(self):
        return self.date_limite is not None and self.date_limite < timezone.localdate()

    @property
    def statut_effectif(self):
        """Statut affiché : une offre publiée dont la date limite est passée est fermée."""
        if self.statut == self.Statut.PUBLIEE and self.est_expiree:
            return self.Statut.FERMEE
        return self.statut

    def get_statut_effectif_display(self):
        return self.Statut(self.statut_effectif).label

    @property
    def est_ouverte(self):
        return (self.statut == self.Statut.PUBLIEE and not self.est_expiree
                and self.entreprise.statut == ProfilEntreprise.Statut.VALIDEE)


class CompetenceRequise(models.Model):
    offre = models.ForeignKey(Offre, on_delete=models.CASCADE, related_name="competences_requises")
    competence = models.ForeignKey(Competence, on_delete=models.PROTECT, related_name="exigences")
    niveau_requis = models.PositiveSmallIntegerField("niveau requis", choices=Niveau.choices,
                                                     default=Niveau.INTERMEDIAIRE, validators=VALIDATEURS_NIVEAU)
    obligatoire = models.BooleanField(default=False)

    class Meta:
        verbose_name = "compétence requise"
        verbose_name_plural = "compétences requises"
        ordering = ["-obligatoire", "competence__nom"]
        constraints = [models.UniqueConstraint(fields=["offre", "competence"], name="competence_requise_unique")]

    def __str__(self):
        return f"{self.competence} ({self.get_niveau_requis_display()})"


class ProfilCarriere(models.Model):
    apprenant = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name="profil_carriere")
    titre = models.CharField(max_length=120, blank=True, help_text="Ex. : Data analyst junior")
    presentation = models.TextField("présentation", blank=True)
    ville = models.CharField(max_length=80, blank=True)
    disponibilite = models.CharField("disponibilité", max_length=120, blank=True,
                                     help_text="Ex. : immédiate, à partir de février 2027")
    types_contrat_recherches = models.CharField("types de contrat recherchés", max_length=100, blank=True,
                                                help_text="Codes séparés par des virgules.")
    lien_github = models.URLField("GitHub", blank=True)
    lien_linkedin = models.URLField("LinkedIn", blank=True)
    lien_portfolio = models.URLField("portfolio", blank=True)
    cv = models.FileField("CV (PDF)", upload_to=chemin_cv, storage=stockage_prive, blank=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "profil carrière"
        verbose_name_plural = "profils carrière"

    def __str__(self):
        return f"Profil carrière de {self.apprenant}"

    def liste_types_contrat(self):
        return [t for t in self.types_contrat_recherches.split(",") if t]

    def libelles_types_contrat(self):
        libelles = dict(TypeContrat.choices)
        return [libelles[t] for t in self.liste_types_contrat() if t in libelles]


class CompetenceApprenant(models.Model):
    profil = models.ForeignKey(ProfilCarriere, on_delete=models.CASCADE, related_name="competences")
    competence = models.ForeignKey(Competence, on_delete=models.CASCADE, related_name="maitrises")
    niveau = models.PositiveSmallIntegerField(choices=Niveau.choices, default=Niveau.NOTIONS,
                                              validators=VALIDATEURS_NIVEAU)

    class Meta:
        verbose_name = "compétence de l'apprenant"
        verbose_name_plural = "compétences des apprenants"
        ordering = ["-niveau", "competence__nom"]
        constraints = [models.UniqueConstraint(fields=["profil", "competence"], name="competence_apprenant_unique")]

    def __str__(self):
        return f"{self.competence} ({self.get_niveau_display()})"


class Candidature(models.Model):
    class Statut(models.TextChoices):
        ENVOYEE = "envoyee", "Envoyée"
        EN_EXAMEN = "en_examen", "En examen"
        ENTRETIEN = "entretien", "Entretien"
        ACCEPTEE = "acceptee", "Acceptée"
        REFUSEE = "refusee", "Refusée"
        RETIREE = "retiree", "Retirée"

    offre = models.ForeignKey(Offre, on_delete=models.CASCADE, related_name="candidatures")
    apprenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="candidatures")
    lettre_motivation = models.TextField("lettre de motivation", blank=True)
    cv_depose = models.FileField("CV déposé", upload_to=chemin_cv_depose, storage=stockage_prive, blank=True,
                                 help_text="Copie du CV au moment de la candidature.")
    score_au_depot = models.PositiveSmallIntegerField("score au dépôt", null=True, blank=True)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.ENVOYEE, db_index=True)
    date_entretien = models.DateTimeField("date de l'entretien", null=True, blank=True)
    lieu_ou_lien_entretien = models.CharField("lieu ou lien de l'entretien", max_length=255, blank=True)
    message_recruteur = models.TextField("message du recruteur", blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)
    date_premiere_reponse = models.DateTimeField(null=True, blank=True,
                                                 help_text="Première action du recruteur (statistiques).")

    class Meta:
        ordering = ["-date_creation"]
        constraints = [models.UniqueConstraint(fields=["offre", "apprenant"], name="candidature_unique")]

    def __str__(self):
        return f"{self.apprenant} → {self.offre.titre}"

    def get_absolute_url(self):
        return reverse("careers:candidature_detail", args=[self.pk])

    @property
    def est_active(self):
        return self.statut in (self.Statut.ENVOYEE, self.Statut.EN_EXAMEN, self.Statut.ENTRETIEN)


class HistoriqueCandidature(models.Model):
    candidature = models.ForeignKey(Candidature, on_delete=models.CASCADE, related_name="historique")
    ancien_statut = models.CharField(max_length=10, choices=Candidature.Statut.choices, blank=True)
    nouveau_statut = models.CharField(max_length=10, choices=Candidature.Statut.choices)
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+")
    commentaire = models.TextField(blank=True)
    date = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "historique de candidature"
        verbose_name_plural = "historiques de candidature"
        ordering = ["date", "pk"]

    def __str__(self):
        return f"{self.candidature} : {self.ancien_statut or '∅'} → {self.nouveau_statut}"


class SignalementOffre(models.Model):
    class Motif(models.TextChoices):
        ARNAQUE = "arnaque", "Arnaque"
        DISCRIMINATOIRE = "discriminatoire", "Offre discriminatoire"
        TROMPEUR = "trompeur", "Contenu trompeur"
        AUTRE = "autre", "Autre"

    class Decision(models.TextChoices):
        SUSPENDUE = "suspendue", "Offre suspendue"
        CLASSEE = "classee", "Classé sans suite"

    offre = models.ForeignKey(Offre, on_delete=models.CASCADE, related_name="signalements")
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="signalements_offres")
    motif = models.CharField(max_length=20, choices=Motif.choices)
    details = models.TextField("détails", blank=True)
    traite = models.BooleanField("traité", default=False)
    decision = models.CharField("décision", max_length=10, choices=Decision.choices, blank=True)
    traite_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_traitement = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "signalement d'offre"
        verbose_name_plural = "signalements d'offres"
        ordering = ["traite", "-date_creation"]
        constraints = [models.UniqueConstraint(fields=["offre", "auteur"], condition=Q(traite=False),
                                               name="signalement_offre_en_cours_unique")]

    def __str__(self):
        return f"{self.get_motif_display()} · {self.offre.titre}"
