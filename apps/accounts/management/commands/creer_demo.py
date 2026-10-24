"""Crée des comptes et des données de démonstration pour tester SkillForge.

    python run.py demo                  crée les comptes (ceux qui existent déjà sont conservés)
    python run.py demo --reinitialiser  supprime puis recrée toutes les données de démo
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
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
            demo = User.objects.filter(
                models.Q(email__endswith=f"@{DOMAINE}") | models.Q(username__startswith="demo_")
            )
            # Les conversations (ManyToMany) ne sont pas supprimées en cascade avec les comptes
            Conversation.objects.filter(participants__in=demo).delete()
            n, _ = demo.delete()
            self.stdout.write(f"Anciennes données de démo supprimées ({n} objets).")

        with transaction.atomic():
            comptes, nouveaux = self.creer_comptes()
            if nouveaux:
                self.creer_conversations(comptes)
                self.creer_notifications(comptes)
            self.creer_quiz_demo(comptes)
                creer_certificats_demo(comptes)

        self.afficher_resume(nouveaux)

    def creer_comptes(self):
        comptes, nouveaux = {}, False
        for identifiant, prenom, nom, role, specialite, valide in COMPTES:
            nom_utilisateur = f"demo_{identifiant}"
            adresse_email = f"{identifiant}@{DOMAINE}"
            # Vérifie par nom d'utilisateur OU par adresse e-mail pour éviter IntegrityError
            user = User.objects.filter(
                models.Q(username=nom_utilisateur) | models.Q(email=adresse_email)
            ).first()
            if user is None:
                user = User.objects.create_user(
                    username=nom_utilisateur, email=adresse_email, password=MOT_DE_PASSE,
                    first_name=prenom, last_name=nom, role=role, specialite=specialite, est_valide=valide,
                    is_staff=role == User.Role.ADMINISTRATEUR, is_superuser=role == User.Role.ADMINISTRATEUR,
                    bio=f"Compte de démonstration ({User.Role(role).label.lower()}).",
                )
                nouveaux = True
            comptes[identifiant] = user
        return comptes, nouveaux

    def creer_quiz_demo(self, comptes):
        from apps.quizzes.models import Choix, Question, Quiz
        formateur = comptes.get("leila") or comptes.get("karim")
        if not formateur or Quiz.objects.filter(titre="Requêtes SQL et Fondamentaux").exists():
            return

        quiz = Quiz.objects.create(
            formateur=formateur,
            titre="Requêtes SQL et Fondamentaux",
            description="Testez vos connaissances sur les requêtes SQL : filtres WHERE, jointures et agrégations.",
            seuil_reussite=50,
            est_publie=True,
            duree_minutes=15,
        )

        q1 = Question.objects.create(
            quiz=quiz,
            type=Question.Type.QCM,
            enonce="Quelle clause SQL permet de filtrer les enregistrements avant tout regroupement ?",
            points=1,
            ordre=1,
            explication="La clause WHERE filtre les lignes individuellement avant le GROUP BY.",
        )
        Choix.objects.create(question=q1, texte="ORDER BY", est_correct=False, ordre=1)
        Choix.objects.create(question=q1, texte="WHERE", est_correct=True, ordre=2)
        Choix.objects.create(question=q1, texte="HAVING", est_correct=False, ordre=3)
        Choix.objects.create(question=q1, texte="LIMIT", est_correct=False, ordre=4)

        q2 = Question.objects.create(
            quiz=quiz,
            type=Question.Type.VRAI_FAUX,
            enonce="La commande DROP TABLE supprime uniquement les données et conserve la structure de la table.",
            points=1,
            ordre=2,
            explication="Faux, DROP TABLE supprime la table et sa structure. C'est TRUNCATE ou DELETE qui vide les données.",
        )
        Choix.objects.create(question=q2, texte="Vrai", est_correct=False, ordre=1)
        Choix.objects.create(question=q2, texte="Faux", est_correct=True, ordre=2)

        q3 = Question.objects.create(
            quiz=quiz,
            type=Question.Type.TEXTE_LIBRE,
            enonce="Quelle commande SQL permet de récupérer des données dans une table et comment s'articule sa structure de base ?",
            points=2,
            ordre=3,
            explication="La commande SELECT permet de projeter des colonnes avec SELECT ... FROM nom_table.",
            consigne_ia="L'apprenant doit mentionner le mot-clé SELECT et idéalement FROM pour spécifier la table source.",
        )

        # Créer une tentative de démonstration réussie pour Yasmine
        yasmine = comptes.get("yasmine")
        if yasmine:
            from apps.quizzes.models import Reponse, Tentative
            if not Tentative.objects.filter(quiz=quiz, apprenant=yasmine).exists():
                tentative = Tentative.objects.create(
                    quiz=quiz,
                    apprenant=yasmine,
                    terminee=True,
                    date_debut=timezone.now() - timedelta(hours=2),
                    date_fin=timezone.now() - timedelta(hours=1, minutes=50),
                )
                Reponse.objects.create(
                    tentative=tentative,
                    question=q1,
                    choix_selectionne=q1.choix.filter(est_correct=True).first(),
                    est_correcte=True,
                    points_obtenus=1,
                    corrigee=True,
                )
                Reponse.objects.create(
                    tentative=tentative,
                    question=q2,
                    choix_selectionne=q2.choix.filter(est_correct=True).first(),
                    est_correcte=True,
                    points_obtenus=1,
                    corrigee=True,
                )
                Reponse.objects.create(
                    tentative=tentative,
                    question=q3,
                    texte_libre="On utilise la commande SELECT pour extraire les colonnes souhaitées, en ciblant la table source avec la clause FROM.",
                    est_correcte=True,
                    points_obtenus=2,
                    feedback_ia="Excellente réponse ! L'utilisation conjointe de SELECT et FROM a été parfaitement ciblée et expliquée.",
                    corrigee=True,
                )
                tentative.calculer_score()
                services.notifier(
                    yasmine,
                    f"Quiz corrigé · {quiz.titre}",
                    f"Vous avez obtenu {tentative.score}/{tentative.score_total} ({tentative.pourcentage}%) — réussi ✅.",
                    type=Notification.Type.QUIZ,
                    lien=tentative.get_absolute_url(),
                )

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
                              "\n  - yasmine : voir « Mes résultats » du quiz SQL et tester un nouveau quiz (avec timer et progression)"
                              "\n  - leila : voir « Résultats » du quiz SQL, modifier les questions et tester « ✨ Générer par IA »"
                              "\n  - yasmine : un rappel de séance arrive dans 2 minutes (avec python run.py dev)")
