from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone


class Disponibilite(models.Model):
    """Plage horaire ponctuelle proposée par un formateur."""

    formateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="disponibilites_mentorat",
        limit_choices_to={"role": "formateur"},
    )
    debut = models.DateTimeField("début")
    fin = models.DateTimeField("fin")
    duree_seance = models.PositiveSmallIntegerField(
        "durée d’une séance (minutes)", default=60,
        choices=((30, "30 minutes"), (45, "45 minutes"), (60, "1 heure"), (90, "1 h 30")),
    )
    active = models.BooleanField("active", default=True)
    date_creation = models.DateTimeField("créée le", auto_now_add=True)

    class Meta:
        ordering = ["debut"]
        verbose_name = "disponibilité de mentorat"
        verbose_name_plural = "disponibilités de mentorat"
        constraints = [
            models.CheckConstraint(condition=Q(fin__gt=F("debut")), name="mentoring_disponibilite_intervalle_valide"),
            models.CheckConstraint(condition=Q(duree_seance__in=(30, 45, 60, 90)), name="mentoring_disponibilite_duree_valide"),
        ]

    def clean(self):
        super().clean()
        erreurs = {}
        if self.debut and self.debut <= timezone.now():
            erreurs["debut"] = "La disponibilité doit commencer dans le futur."
        if self.debut and self.fin and self.fin <= self.debut:
            erreurs["fin"] = "La fin doit être postérieure au début."
        if self.debut and self.fin and self.duree_seance and (self.fin - self.debut) < timedelta(minutes=self.duree_seance):
            erreurs["fin"] = "La plage doit durer au moins une séance."
        if self.formateur_id and self.debut and self.fin:
            autres = Disponibilite.objects.filter(
                formateur_id=self.formateur_id, active=True, debut__lt=self.fin, fin__gt=self.debut,
            )
            if self.pk:
                autres = autres.exclude(pk=self.pk)
            if autres.exists():
                erreurs["debut"] = "Cette plage chevauche une autre disponibilité active."
        if erreurs:
            raise ValidationError(erreurs)

    def __str__(self):
        return f"{self.formateur} · {self.debut:%d/%m/%Y %H:%M}–{self.fin:%H:%M}"


class SeanceMentorat(models.Model):
    """Séance réservée par un apprenant auprès d’un formateur."""

    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente de confirmation"
        CONFIRMEE = "confirmee", "Confirmée"
        ANNULEE = "annulee", "Annulée"
        TERMINEE = "terminee", "Terminée"

    disponibilite = models.ForeignKey(
        Disponibilite, on_delete=models.PROTECT, related_name="seances", verbose_name="créneau",
    )
    apprenant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="seances_mentorat_apprenant", verbose_name="apprenant",
    )
    formateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="seances_mentorat_formateur", verbose_name="formateur",
    )
    debut = models.DateTimeField("début")
    fin = models.DateTimeField("fin")
    sujet = models.CharField("sujet", max_length=160)
    description = models.TextField("description", blank=True)
    lien_visio = models.URLField("lien de visioconférence", blank=True)
    statut = models.CharField("statut", max_length=12, choices=Statut.choices, default=Statut.EN_ATTENTE)
    date_creation = models.DateTimeField("demandée le", auto_now_add=True)
    date_modification = models.DateTimeField("modifiée le", auto_now=True)

    class Meta:
        ordering = ["debut"]
        verbose_name = "séance de mentorat"
        verbose_name_plural = "séances de mentorat"
        constraints = [
            models.CheckConstraint(condition=Q(fin__gt=F("debut")), name="mentoring_seance_intervalle_valide"),
            models.UniqueConstraint(
                fields=["disponibilite", "debut"],
                condition=Q(statut__in=("en_attente", "confirmee")),
                name="mentoring_seance_creneau_unique_actif",
            ),
        ]
        indexes = [models.Index(fields=["formateur", "debut", "fin"]), models.Index(fields=["apprenant", "debut"])]

    @property
    def duree_minutes(self):
        return int((self.fin - self.debut).total_seconds() // 60)

    def clean(self):
        super().clean()
        erreurs = {}
        if self.debut and self.fin and self.fin <= self.debut:
            erreurs["fin"] = "La fin doit être postérieure au début."
        if self.disponibilite_id and self.debut and self.fin:
            plage = self.disponibilite
            if not (plage.active and plage.debut <= self.debut and self.fin <= plage.fin):
                erreurs["debut"] = "La séance doit être comprise dans une disponibilité active."
            if self.duree_minutes != plage.duree_seance:
                erreurs["fin"] = "La durée doit correspondre à celle du créneau."
            if self.debut.minute % 15 or self.debut.second or self.debut.microsecond:
                erreurs["debut"] = "L’heure de début doit être alignée sur un quart d’heure."
            if self.formateur_id and plage.formateur_id != self.formateur_id:
                erreurs["formateur"] = "Le formateur doit être celui de la disponibilité."
        if self.apprenant_id and self.formateur_id and self.apprenant_id == self.formateur_id:
            erreurs["apprenant"] = "Le formateur ne peut pas réserver une séance comme apprenant."
        if self.formateur_id and self.debut and self.fin and self.statut in (self.Statut.EN_ATTENTE, self.Statut.CONFIRMEE):
            conflits = SeanceMentorat.objects.filter(
                statut__in=(self.Statut.EN_ATTENTE, self.Statut.CONFIRMEE),
                debut__lt=self.fin, fin__gt=self.debut,
            ).filter(Q(formateur_id=self.formateur_id) | Q(apprenant_id=self.apprenant_id))
            if self.pk:
                conflits = conflits.exclude(pk=self.pk)
            if conflits.exists():
                erreurs["debut"] = "Le formateur ou l’apprenant a déjà une séance sur cette plage."
        if erreurs:
            raise ValidationError(erreurs)

    def get_absolute_url(self):
        return reverse("mentoring:seance_detail", kwargs={"pk": self.pk})

    def __str__(self):
        return f"{self.sujet} · {self.debut:%d/%m/%Y %H:%M}"
