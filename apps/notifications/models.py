import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property


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
    """Pièces jointes stockées hors de MEDIA_ROOT : elles ne sont servies que par la vue `piece_jointe`.

    Passé sous forme de fonction pour que la migration ne contienne pas le chemin de la machine.
    """
    return _stockage_prive


EXTENSIONS_IMAGE = {"png", "jpg", "jpeg", "gif", "webp"}


def chemin_piece_jointe(message, nom_original):
    """Nom de fichier aléatoire : on ne peut ni le deviner ni écraser un autre fichier."""
    extension = Path(nom_original).suffix.lower()
    return f"messagerie/{message.conversation_id}/{uuid.uuid4().hex}{extension}"


class Notification(models.Model):
    """Alerte affichée dans la cloche de l'espace connecté."""

    class Type(models.TextChoices):
        MESSAGE = "message", "Message"
        SEANCE = "seance", "Séance de mentorat"
        RAPPEL = "rappel", "Rappel"
        COURS = "cours", "Cours"
        QUIZ = "quiz", "Quiz"
        CERTIFICAT = "certificat", "Certificat"
        COMPTE = "compte", "Compte"
        SYSTEME = "systeme", "SkillForge"

    destinataire = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name="notifications")
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.SYSTEME)
    titre = models.CharField(max_length=150)
    message = models.TextField(blank=True)
    lien = models.CharField(max_length=300, blank=True, help_text="URL ouverte au clic sur la notification.")
    lue = models.BooleanField(default=False)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]
        indexes = [models.Index(fields=["destinataire", "lue"])]

    def __str__(self):
        return f"{self.titre} → {self.destinataire}"

    def get_absolute_url(self):
        return reverse("notifications:ouvrir", args=[self.pk])


class ConversationQuerySet(models.QuerySet):
    def pour(self, user):
        return self.filter(participants=user)

    def entre(self, user_a, user_b):
        return self.filter(participants=user_a).filter(participants=user_b)


class Conversation(models.Model):
    """Fil de discussion privé entre deux utilisateurs."""

    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="conversations")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True, db_index=True)

    objects = ConversationQuerySet.as_manager()

    class Meta:
        ordering = ["-date_maj"]

    def __str__(self):
        return " · ".join(str(p) for p in self.participants.all())

    def get_absolute_url(self):
        return reverse("notifications:conversation", args=[self.pk])

    def interlocuteur(self, user):
        return self.participants.exclude(pk=user.pk).first()

    def non_lus(self, user):
        return self.messages.filter(lu=False).exclude(expediteur=user)

    def marquer_lue(self, user):
        """Marque les messages reçus comme lus, ainsi que la notification associée."""
        n = self.non_lus(user).update(lu=True)
        user.notifications.filter(type=Notification.Type.MESSAGE, lien=self.get_absolute_url(),
                                  lue=False).update(lue=True)
        return n


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    expediteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="messages_envoyes")
    contenu = models.TextField(max_length=2000, blank=True)
    fichier = models.FileField(upload_to=chemin_piece_jointe, storage=stockage_prive, blank=True)
    nom_fichier = models.CharField(max_length=255, blank=True)
    taille_fichier = models.PositiveIntegerField(default=0)
    lu = models.BooleanField(default=False)
    date_envoi = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_envoi"]

    def __str__(self):
        return f"{self.expediteur} : {self.contenu[:40] or self.nom_fichier}"

    @property
    def extension(self):
        return Path(self.nom_fichier).suffix.lower().lstrip(".")

    @property
    def est_image(self):
        return bool(self.fichier) and self.extension in EXTENSIONS_IMAGE

    def url_fichier(self):
        return reverse("notifications:piece_jointe", args=[self.pk]) if self.fichier else ""

    def apercu(self):
        """Texte court utilisé dans la liste des conversations et les notifications."""
        if self.contenu:
            return self.contenu
        return f"📎 {self.nom_fichier}" if self.fichier else ""


class Rappel(models.Model):
    """Notification programmée, envoyée par la commande `envoyer_rappels`."""

    destinataire = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name="rappels")
    titre = models.CharField(max_length=150)
    message = models.TextField(blank=True)
    lien = models.CharField(max_length=300, blank=True)
    date_envoi = models.DateTimeField(db_index=True)
    envoye = models.BooleanField(default=False)
    par_email = models.BooleanField(default=True)

    # Objet concerné (ex. une SeanceMentorat), pour pouvoir annuler ses rappels
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    objet = GenericForeignKey("content_type", "object_id")

    class Meta:
        ordering = ["date_envoi"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.titre} → {self.destinataire} ({self.date_envoi:%d/%m/%Y %H:%M})"
