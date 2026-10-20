from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse


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
        self.non_lus(user).update(lu=True)


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    expediteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="messages_envoyes")
    contenu = models.TextField(max_length=2000)
    lu = models.BooleanField(default=False)
    date_envoi = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_envoi"]

    def __str__(self):
        return f"{self.expediteur} : {self.contenu[:40]}"


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
