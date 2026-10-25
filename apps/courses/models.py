from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.core.validators import FileExtensionValidator
from pathlib import Path
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from urllib.parse import urlparse
import zipfile


class Niveau(models.TextChoices):
    DEBUTANT = "debutant", "Débutant"
    INTERMEDIAIRE = "intermediaire", "Intermédiaire"
    AVANCE = "avance", "Avancé"


@deconstructible
class CourseResourceStorage(FileSystemStorage):
    """Ressources de cours conservées hors du MEDIA_URL public."""
    def __init__(self):
        super().__init__(location=settings.PRIVATE_MEDIA_ROOT / "cours", base_url=None)


def valider_image_couverture(fichier):
    if fichier.size > 5 * 1024 * 1024:
        raise ValidationError("Une couverture ne peut pas dépasser 5 Mo.")
    extension = Path(fichier.name).suffix.lower()
    debut = fichier.read(16)
    fichier.seek(0)
    signatures = {
        ".png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
        ".jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
        ".webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
    }
    verifier = signatures.get(extension)
    if not verifier or not verifier(debut):
        raise ValidationError("La couverture doit être une image PNG, JPEG ou WebP valide.")


class Cours(models.Model):
    """Cours proposé par un formateur."""

    formateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cours_crees",
        verbose_name="formateur",
    )
    titre = models.CharField("titre", max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField("description", blank=True)
    objectifs = models.TextField("objectifs pédagogiques", blank=True)
    categorie = models.CharField("catégorie", max_length=80, blank=True)
    image_couverture = models.FileField(
        "image de couverture", upload_to="cours/couvertures/", blank=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"]), valider_image_couverture],
    )
    ordre = models.PositiveIntegerField("ordre d'affichage", default=0)
    est_publie = models.BooleanField("publié", default=False)
    date_creation = models.DateTimeField("date de création", auto_now_add=True)
    date_modification = models.DateTimeField("dernière modification", auto_now=True)
    niveau = models.CharField("niveau", max_length=20, choices=Niveau.choices, default=Niveau.DEBUTANT)
    duree_estimee = models.PositiveSmallIntegerField("durée estimée (heures)", default=0)

    class Meta:
        verbose_name = "cours"
        verbose_name_plural = "cours"
        ordering = ["titre"]
        indexes = [models.Index(fields=["est_publie", "ordre"], name="cours_publication_ordre_idx")]

    def __str__(self):
        return self.titre

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.titre)[:200] or "cours"
            slug = base
            suffix = 2
            while Cours.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{suffix}"
                suffix += 1
            self.slug = slug
        super().save(*args, **kwargs)


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
    date_creation = models.DateTimeField("date de création", auto_now_add=True)
    date_modification = models.DateTimeField("dernière modification", auto_now=True)

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
    derniere_lecon = models.ForeignKey("Lesson", null=True, blank=True, on_delete=models.SET_NULL, related_name="inscriptions_dernieres")

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


class Lesson(models.Model):
    """Leçon ordonnée à l'intérieur d'un module (chapitre historique)."""
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="lecons")
    titre = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    contenu = models.TextField(blank=True, help_text="Contenu historique affiché avant les blocs.")
    ordre = models.PositiveIntegerField(default=0)
    duree_estimee = models.PositiveSmallIntegerField(default=0, help_text="Durée en minutes")
    est_publiee = models.BooleanField(default=False)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordre", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["module", "ordre"], name="lesson_unique_order_per_module"),
            models.UniqueConstraint(fields=["module", "slug"], name="lesson_slug_unique_per_module"),
        ]

    def save(self, *args, **kwargs):
        base = slugify(self.slug or self.titre)[:200] or f"lecon-{self.pk or 'nouvelle'}"
        slug = base
        suffix = 2
        while Lesson.objects.filter(module_id=self.module_id, slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.titre


def valider_fichier_cours(fichier):
    """Vérifie taille, type déclaré et signature réelle du fichier."""
    if fichier.size > 25 * 1024 * 1024:
        raise ValidationError("La taille maximale d'un fichier de cours est de 25 Mo.")
    extension = Path(fichier.name).suffix.lower()
    debut = fichier.read(16)
    fichier.seek(0)
    signatures = {
        ".pdf": lambda b: b.startswith(b"%PDF-"),
        ".png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
        ".jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
        ".gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
        ".webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
        ".webm": lambda b: b.startswith(b"\x1aE\xdf\xa3"),
        ".mp4": lambda b: len(b) >= 8 and b[4:8] == b"ftyp",
        ".doc": lambda b: b.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        ".docx": lambda b: b.startswith(b"PK\x03\x04"),
    }
    verifier = signatures.get(extension)
    if verifier and not verifier(debut):
        raise ValidationError("Le contenu du fichier ne correspond pas à son extension.")
    content_types = {
        ".pdf": {"application/pdf"}, ".png": {"image/png"}, ".jpg": {"image/jpeg"},
        ".jpeg": {"image/jpeg"}, ".gif": {"image/gif"}, ".webp": {"image/webp"},
        ".mp4": {"video/mp4"}, ".webm": {"video/webm"}, ".doc": {"application/msword"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    }
    declared = getattr(fichier, "content_type", None)
    if declared and declared not in content_types.get(extension, set()) | {"application/octet-stream"}:
        raise ValidationError("Le type MIME déclaré ne correspond pas à l'extension du fichier.")
    if extension == ".docx":
        position = fichier.tell()
        try:
            with zipfile.ZipFile(fichier) as archive:
                valid_docx = "[Content_Types].xml" in archive.namelist() and "word/document.xml" in archive.namelist()
        except (zipfile.BadZipFile, OSError):
            valid_docx = False
        finally:
            fichier.seek(position)
        if not valid_docx:
            raise ValidationError("Le document DOCX est invalide.")


class LessonContent(models.Model):
    class Type(models.TextChoices):
        TEXT = "text", "Texte"
        VIDEO = "video", "Vidéo"
        IMAGE = "image", "Image"
        FILE = "file", "Document"
        PDF = "pdf", "PDF"
        CODE = "code", "Code"
        LINK = "link", "Lien"

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="blocs")
    type = models.CharField(max_length=10, choices=Type.choices)
    titre = models.CharField(max_length=200, blank=True)
    texte = models.TextField(blank=True)
    url = models.URLField(blank=True)
    fichier = models.FileField(upload_to="ressources/", storage=CourseResourceStorage(), blank=True, validators=[
        FileExtensionValidator(["pdf", "docx", "doc", "png", "jpg", "jpeg", "gif", "webp", "mp4", "webm"]),
        valider_fichier_cours,
    ])
    texte_alternatif = models.CharField(max_length=250, blank=True)
    legende = models.CharField(max_length=250, blank=True)
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordre", "pk"]
        constraints = [models.UniqueConstraint(fields=["lesson", "ordre"], name="lesson_content_unique_order")]

    def clean(self):
        super().clean()
        if self.fichier:
            extension = Path(self.fichier.name).suffix.lower()
            if self.type == self.Type.PDF and extension != ".pdf":
                raise ValidationError({"fichier": "Un bloc PDF doit contenir un fichier PDF."})
            if self.type == self.Type.IMAGE and extension not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                raise ValidationError({"fichier": "Un bloc image doit contenir une image prise en charge."})
            if self.type == self.Type.VIDEO and extension not in {".mp4", ".webm"}:
                raise ValidationError({"fichier": "Une vidéo doit être au format MP4 ou WebM."})
            if self.type == self.Type.FILE and extension not in {".pdf", ".doc", ".docx"}:
                raise ValidationError({"fichier": "Un document doit être au format PDF, DOC ou DOCX."})
        if self.type == self.Type.VIDEO and self.url:
            parsed = urlparse(self.url)
            host = (parsed.hostname or "").lower()
            allowed = {"youtube.com", "www.youtube.com", "youtu.be", "youtube-nocookie.com",
                       "www.youtube-nocookie.com", "vimeo.com", "www.vimeo.com", "player.vimeo.com"}
            if parsed.scheme != "https" or host not in allowed:
                raise ValidationError({"url": "Les vidéos externes doivent être en HTTPS et provenir de YouTube ou Vimeo."})
        if self.type in {self.Type.TEXT, self.Type.CODE} and not self.texte.strip():
            raise ValidationError({"texte": "Ce bloc doit contenir du texte."})
        if self.type == self.Type.LINK and not self.url:
            raise ValidationError({"url": "Un lien est requis."})
        if self.type in {self.Type.IMAGE, self.Type.FILE, self.Type.PDF, self.Type.VIDEO} and not (self.fichier or self.url):
            raise ValidationError("Un fichier ou une URL est requis pour ce bloc.")


class LessonProgress(models.Model):
    class Etat(models.TextChoices):
        EN_COURS = "en_cours", "En cours"
        TERMINEE = "terminee", "Terminée"

    inscription = models.ForeignKey(Inscription, on_delete=models.CASCADE, related_name="lecons_terminees")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progressions")
    etat = models.CharField(max_length=12, choices=Etat.choices, default=Etat.EN_COURS)
    date_debut = models.DateTimeField(auto_now_add=True)
    derniere_consultation = models.DateTimeField(auto_now=True)
    date_terminaison = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["inscription", "lesson"], name="lesson_progress_unique")]

    def clean(self):
        if self.inscription_id and self.lesson_id and self.inscription.cours_id != self.lesson.module.cours_id:
            raise ValidationError("La leçon doit appartenir au cours de l'inscription.")
