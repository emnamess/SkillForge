"""Crée des comptes et des données de démonstration pour tester SkillForge.

    python run.py demo                  crée les comptes (ceux qui existent déjà sont conservés)
    python run.py demo --reinitialiser  supprime puis recrée toutes les données de démo
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.certificates.demo import creer_certificats_demo
from apps.notifications import services
from apps.notifications.models import Conversation, Message, Notification
from apps.notifications.moderation import AUTORISE, SIGNALE, ResultatModeration

DOMAINE = "demo.skillforge.tn"
MOT_DE_PASSE = "SkillForge2026!"

COMPTES = [
    # (identifiant, prénom, nom, rôle, spécialité, validé)
    ("admin", "Nadia", "Admin", User.Role.ADMINISTRATEUR, "", True),
    ("karim", "Karim", "Mansour", User.Role.FORMATEUR, "Modélisation UML", True),
    ("leila", "Leïla", "Trabelsi", User.Role.FORMATEUR, "Bases de données", True),
    ("sami", "Sami", "Rekik", User.Role.FORMATEUR, "Data engineering", False),
    ("yasmine", "Yasmine", "Ben Ali", User.Role.APPRENANT, "", True),
    ("amine", "Amine", "Mejri", User.Role.APPRENANT, "", True),
    ("sarra", "Sarra", "Khelifi", User.Role.APPRENANT, "", True),
]

# Échanges de démo : (expéditeur, texte) — l'IA n'est pas appelée pour les créer
CONVERSATIONS = {
    ("yasmine", "karim"): [
        ("karim", "Bonjour Yasmine ! Tu as bien reçu la correction du quiz sur l'héritage ?"),
        ("yasmine", "Oui merci ! Je ne comprends pas quand utiliser l'héritage plutôt qu'un attribut « rôle »."),
        ("karim", "Bonne question. Si chaque sous-classe a ses propres comportements, l'héritage est plus adapté."),
        ("karim", "On peut en parler jeudi pendant la séance de mentorat, je te montrerai un schéma."),
    ],
    ("amine", "leila"): [
        ("amine", "Bonjour Madame, je bloque sur l'exercice 3 des jointures SQL."),
        ("leila", "Bonjour Amine, essaie un LEFT JOIN : tu dois garder tous les clients, même sans commande."),
    ],
    ("sarra", "karim"): [
        ("sarra", "Bonjour, est-ce que le module 4 sera disponible cette semaine ?"),
    ],
}


class Command(BaseCommand):
    help = "Crée des comptes de démonstration (admin, formateurs, apprenants) avec des conversations."

    def add_arguments(self, parser):
        parser.add_argument("--reinitialiser", action="store_true",
                            help="Supprime les comptes de démo existants avant de les recréer.")
        parser.add_argument("--force", action="store_true",
                            help="Autorise la commande même quand DEBUG est désactivé.")

    def handle(self, *args, reinitialiser=False, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Données de démo refusées hors développement (DEBUG=False). Utilisez --force.")

        if reinitialiser:
            demo = User.objects.filter(email__endswith=f"@{DOMAINE}")
            # Les conversations (ManyToMany) ne sont pas supprimées en cascade avec les comptes
            Conversation.objects.filter(participants__in=demo).delete()
            n, _ = demo.delete()
            self.stdout.write(f"Anciennes données de démo supprimées ({n} objets).")

        with transaction.atomic():
            comptes, nouveaux = self.creer_comptes()
            if nouveaux:
                self.creer_conversations(comptes)
                self.creer_notifications(comptes)
                creer_certificats_demo(comptes)

        self.afficher_resume(nouveaux)

    def creer_comptes(self):
        comptes, nouveaux = {}, False
        for identifiant, prenom, nom, role, specialite, valide in COMPTES:
            user = User.objects.filter(username=f"demo_{identifiant}").first()
            if user is None:
                user = User.objects.create_user(
                    username=f"demo_{identifiant}", email=f"{identifiant}@{DOMAINE}", password=MOT_DE_PASSE,
                    first_name=prenom, last_name=nom, role=role, specialite=specialite, est_valide=valide,
                    is_staff=role == User.Role.ADMINISTRATEUR, is_superuser=role == User.Role.ADMINISTRATEUR,
                    bio=f"Compte de démonstration ({User.Role(role).label.lower()}).",
                )
                nouveaux = True
            comptes[identifiant] = user
        return comptes, nouveaux

    def creer_conversations(self, comptes):
        autorise = ResultatModeration(AUTORISE)
        maintenant = timezone.now()
        for (a, b), echanges in CONVERSATIONS.items():
            conversation = services.obtenir_conversation(comptes[a], comptes[b])
            for i, (auteur, texte) in enumerate(echanges):
                message = services.envoyer_message(conversation, comptes[auteur], texte,
                                                   resultat_moderation=autorise)
                # Échelonne les messages dans le passé pour un rendu réaliste
                Message.objects.filter(pk=message.pk).update(
                    date_envoi=maintenant - timedelta(minutes=10 * (len(echanges) - i)))

        # Un message signalé par la « modération », pour remplir la page Modération
        conversation = services.obtenir_conversation(comptes["amine"], comptes["leila"])
        services.envoyer_message(
            conversation, comptes["amine"], "Franchement ce TP c'est la merde, envoyez-moi juste les réponses",
            resultat_moderation=ResultatModeration(
                SIGNALE, "triche", "Langage vulgaire et demande des réponses de l'exercice.", "regles"),
        )

    def creer_notifications(self, comptes):
        yasmine = comptes["yasmine"]
        services.notifier(yasmine, "Quiz corrigé par l'IA", "Extraction des données : 16/20, quiz validé.",
                          type=Notification.Type.QUIZ)
        services.notifier(yasmine, "Séance de mentorat confirmée", "Jeudi à 14h00 avec Karim M.",
                          type=Notification.Type.SEANCE)
        services.notifier(yasmine, "Certificat obtenu", "Félicitations : « SQL avancé » est validé !",
                          type=Notification.Type.CERTIFICAT)
        services.notifier(comptes["amine"], "Nouveau module publié", "SQL avancé · Module 5 : les index",
                          type=Notification.Type.COURS)

        # Un rappel qui arrivera en direct pendant la démo (si `python run.py dev` tourne)
        services.planifier_rappel(yasmine, timezone.now() + timedelta(minutes=2),
                                  "Rappel · Séance de mentorat", "Votre séance avec Karim commence bientôt.",
                                  par_email=False)

    def afficher_resume(self, nouveaux):
        if not nouveaux:
            self.stdout.write(self.style.WARNING(
                "Les comptes de démo existent déjà (ajoutez --reinitialiser pour les recréer)."))
        else:
            self.stdout.write(self.style.SUCCESS("Données de démo créées."))

        self.stdout.write(f"\nMot de passe de tous les comptes : {MOT_DE_PASSE}\n")
        for identifiant, prenom, nom, role, specialite, valide in COMPTES:
            statut = "" if valide else "  (en attente de validation)"
            self.stdout.write(f"  {identifiant + '@' + DOMAINE:<32} {User.Role(role).label:<15}{prenom} {nom}{statut}")
        if nouveaux:
            self.stdout.write("\nÀ essayer :"
                              "\n  - yasmine et karim dans deux navigateurs : messagerie en temps réel"
                              "\n  - admin : page Modération (1 message signalé) et validation de sami"
                              "\n  - yasmine : un rappel de séance arrive dans 2 minutes (avec python run.py dev)")
