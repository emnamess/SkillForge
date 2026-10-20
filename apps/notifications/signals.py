"""Notifications automatiques liées aux comptes utilisateurs."""

from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse

from .models import Notification
from .services import notifier


@receiver(pre_save, sender=settings.AUTH_USER_MODEL)
def memoriser_validation(sender, instance, **kwargs):
    """Retient l'ancien état de validation pour détecter le passage à « validé »."""
    if instance.pk:
        instance._etait_valide = sender.objects.filter(pk=instance.pk).values_list(
            "est_valide", flat=True).first()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def notifier_evenements_compte(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return

    if created:
        notifier(instance, "Bienvenue sur SkillForge !",
                 "Complétez votre profil pour que les formateurs et apprenants vous connaissent.",
                 type=Notification.Type.COMPTE, lien=reverse("accounts:profil"))
        if instance.en_attente_validation:
            admins = sender.objects.filter(role=sender.Role.ADMINISTRATEUR, is_active=True)
            notifier(admins, "Nouveau formateur à valider",
                     f"{instance} ({instance.specialite or 'spécialité non précisée'}) attend votre validation.",
                     type=Notification.Type.COMPTE,
                     lien=reverse("accounts:utilisateur_detail", args=[instance.pk]))
        return

    if instance.est_formateur and instance.est_valide and getattr(instance, "_etait_valide", True) is False:
        notifier(instance, "Votre compte formateur est validé",
                 "Vous pouvez maintenant créer et publier vos cours.",
                 type=Notification.Type.COMPTE, lien=reverse("accounts:dashboard"), email=True)
