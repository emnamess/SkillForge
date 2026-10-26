"""Ajoute un jeu de données LMS réaliste, sans supprimer les données existantes.

Usage : python manage.py populate_lms_demo
"""
from django.conf import settings
from django.core.management import BaseCommand, call_command, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.courses.models import (
    Cours, Inscription, Lesson, LessonContent, LessonProgress, Module, ProgressionModule,
)
from apps.courses.services import recalculer_progression


CATALOGUE = [
    {
        "title": "Python pratique : bases et automatisation",
        "description": "Un parcours progressif pour écrire des scripts Python lisibles, manipuler les données et automatiser des tâches courantes.",
        "level": "debutant",
        "category": "Programmation",
        "objectives": "Écrire des scripts lisibles · Utiliser les structures de contrôle · Manipuler un fichier CSV",
        "hours": 8,
        "teacher": "demo_karim",
        "chapters": [
            ("Premiers pas en Python", "Installer son environnement et comprendre les éléments d'un programme.", [
                ("Variables et types", "Représenter des nombres, du texte et des valeurs logiques.", "Une variable associe un nom à une valeur. Python détermine le type à partir de la valeur affectée. Les types courants sont int, float, str et bool.", "nom = \"Amina\"\nage = 22\nprint(f\"{nom} a {age} ans\")", 12),
                ("Conditions et boucles", "Écrire un programme qui prend des décisions et répète des actions.", "Une condition if exécute un bloc lorsque son expression est vraie. Une boucle for parcourt une séquence, tandis que while répète une action tant que sa condition reste vraie.", "for nombre in range(1, 4):\n    print(nombre)", 15),
            ]),
            ("Organiser son code", "Structurer les scripts en fonctions et modules faciles à maintenir.", [
                ("Fonctions réutilisables", "Définir des fonctions avec paramètres et valeurs de retour.", "Une fonction regroupe une opération sous un nom réutilisable. Les paramètres transmettent les données et return renvoie un résultat à l'appelant.", "def aire_rectangle(largeur, hauteur):\n    return largeur * hauteur\n\nprint(aire_rectangle(4, 3))", 14),
                ("Lire un fichier CSV", "Charger un tableau CSV et calculer un indicateur simple.", "Le module csv lit les fichiers ligne par ligne. DictReader associe chaque valeur à son nom de colonne, ce qui rend les traitements plus compréhensibles.", "import csv\nwith open(\"ventes.csv\", encoding=\"utf-8\") as fichier:\n    lignes = list(csv.DictReader(fichier))\nprint(len(lignes))", 18),
            ]),
        ],
    },
    {
        "title": "SQL et analyse de données",
        "description": "Apprendre à interroger une base relationnelle, joindre des tables et produire des agrégats fiables.",
        "level": "intermediaire", "hours": 6, "teacher": "demo_leila", "category": "Données",
        "objectives": "Filtrer et trier des tables · Agréger des résultats · Relier plusieurs tables sans perdre de lignes utiles",
        "chapters": [
            ("Interroger une table", "Sélectionner, filtrer et trier les données.", [
                ("SELECT et WHERE", "Construire des requêtes ciblées.", "SELECT choisit les colonnes retournées. WHERE filtre les lignes avant tout regroupement et ORDER BY définit l'ordre des résultats.", "SELECT nom, ville\nFROM clients\nWHERE ville = 'Tunis'\nORDER BY nom;", 12),
                ("Agrégations", "Résumer des données avec GROUP BY et HAVING.", "COUNT, SUM et AVG calculent des indicateurs. GROUP BY produit un résultat par groupe ; HAVING filtre ensuite les groupes agrégés.", "SELECT ville, COUNT(*) AS clients\nFROM clients\nGROUP BY ville\nHAVING COUNT(*) > 5;", 16),
            ]),
            ("Relier les données", "Combiner des informations réparties dans plusieurs tables.", [
                ("Jointures SQL", "Choisir entre INNER JOIN et LEFT JOIN.", "INNER JOIN conserve les lignes correspondantes des deux tables. LEFT JOIN conserve toutes les lignes de gauche même lorsqu'aucune correspondance n'existe à droite.", "SELECT c.nom, co.date_commande\nFROM clients AS c\nLEFT JOIN commandes AS co ON co.client_id = c.id;", 17),
                ("Qualité et NULL", "Détecter les valeurs manquantes et éviter les pièges de comparaison.", "NULL signifie qu'une valeur est inconnue ou absente. Il faut tester IS NULL ou IS NOT NULL, car une égalité classique avec NULL ne renvoie pas vrai.", "SELECT * FROM clients\nWHERE email IS NULL;", 10),
            ]),
        ],
    },
    {
        "title": "Git en équipe : du commit à la revue",
        "description": "Un guide concret des branches, commits, conflits et revues de code dans un flux de travail collaboratif.",
        "level": "debutant", "hours": 4, "teacher": "demo_karim", "category": "Outils de développement",
        "objectives": "Créer des commits compréhensibles · Isoler un changement avec une branche · Résoudre un conflit de fusion",
        "chapters": [
            ("Conserver l'historique", "Suivre les modifications de façon claire et partageable.", [
                ("Commits utiles", "Enregistrer un changement cohérent avec un message descriptif.", "Un commit capture un ensemble cohérent de modifications. Un historique découpé en petits changements facilite la revue et le retour en arrière.", "git add src/\ngit commit -m \"Ajoute la validation du formulaire\"", 10),
                ("Branches", "Développer une fonctionnalité sans perturber la branche principale.", "Une branche est un pointeur léger vers un commit. Elle permet de travailler isolément puis de proposer le changement à l'équipe.", "git switch -c feature/recherche-cours", 9),
            ]),
            ("Collaborer", "Partager le travail et intégrer les retours.", [
                ("Pull request et revue", "Préparer une revue compréhensible par l'équipe.", "Une bonne pull request décrit le besoin, les changements et la vérification effectuée. La revue cherche les défauts, les risques et les améliorations de lisibilité.", "git push -u origin feature/recherche-cours", 11),
                ("Résoudre un conflit", "Comprendre et corriger un conflit de fusion.", "Un conflit survient lorsque deux changements modifient la même zone. Examinez les deux versions, conservez l'intention correcte, supprimez les marqueurs puis relancez les vérifications.", "git status\n# corriger le fichier\ngit add fichier.py\ngit commit", 13),
            ]),
        ],
    },
]


class Command(BaseCommand):
    help = "Peuple la base avec des cours et parcours LMS réalistes, sans réinitialiser les données."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Autorise l'exécution si DEBUG=False.")

    @transaction.atomic
    def handle(self, *args, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Données de démonstration refusées hors développement. Utilisez --force.")

        # Fournit des comptes de démonstration cohérents avec les commandes du projet.
        call_command("creer_demo", force=force, stdout=self.stdout)
        formateurs = {u.username: u for u in User.objects.filter(username__in=["demo_karim", "demo_leila"])}
        apprenants = list(User.objects.filter(username__in=["demo_yasmine", "demo_amine", "demo_sarra"]).order_by("username"))
        if len(formateurs) < 2 or len(apprenants) < 3:
            raise CommandError("Les comptes de démonstration attendus n'ont pas été créés.")

        cours_crees = lecons_creees = inscriptions_creees = 0
        with transaction.atomic():
            for index, item in enumerate(CATALOGUE):
                cours, created = Cours.objects.update_or_create(
                    titre=item["title"],
                    defaults={
                        "formateur": formateurs[item["teacher"]], "description": item["description"],
                        "objectifs": item["objectives"], "categorie": item["category"],
                        "est_publie": True, "niveau": item["level"], "duree_estimee": item["hours"], "ordre": index,
                    },
                )
                cours_crees += int(created)
                cours.refresh_from_db()
                all_lessons = []
                for chapter_order, (chapter_title, chapter_description, lessons) in enumerate(item["chapters"], 1):
                    module, _ = Module.objects.update_or_create(
                        cours=cours, titre=chapter_title,
                        defaults={"description": chapter_description, "ordre": chapter_order},
                    )
                    for lesson_order, (lesson_title, description, text, code, minutes) in enumerate(lessons, 1):
                        lesson, created = Lesson.objects.update_or_create(
                            module=module, slug=slugify(lesson_title),
                            defaults={"titre": lesson_title, "description": description, "contenu": "",
                                      "ordre": lesson_order, "duree_estimee": minutes, "est_publiee": True},
                        )
                        lecons_creees += int(created)
                        all_lessons.append(lesson)
                        LessonContent.objects.update_or_create(
                            lesson=lesson, ordre=1,
                            defaults={"type": LessonContent.Type.TEXT, "titre": "À retenir", "texte": text},
                        )
                        LessonContent.objects.update_or_create(
                            lesson=lesson, ordre=2,
                            defaults={"type": LessonContent.Type.CODE, "titre": "Exemple guidé", "texte": code},
                        )
                        LessonContent.objects.update_or_create(
                            lesson=lesson, ordre=3,
                            defaults={"type": LessonContent.Type.LINK, "titre": "Documentation officielle",
                                      "url": "https://docs.python.org/3/" if "Python" in item["title"] else
                                      "https://www.postgresql.org/docs/current/" if "SQL" in item["title"] else
                                      "https://git-scm.com/docs"},
                        )

                # Parcours avec des niveaux de progression différents pour illustrer la reprise.
                for student_index, student in enumerate(apprenants):
                    if student_index == 2 and index == 2:
                        continue
                    inscription, created = Inscription.objects.get_or_create(apprenant=student, cours=cours)
                    inscriptions_creees += int(created)
                    completed_count = min(len(all_lessons), max(0, (len(all_lessons) * (2 - student_index) + 1) // 3))
                    completed_lessons = all_lessons[:completed_count]
                    completed_ids = {lesson.pk for lesson in completed_lessons}
                    for lesson in completed_lessons:
                        progress, _ = LessonProgress.objects.get_or_create(
                            inscription=inscription, lesson=lesson,
                            defaults={"etat": LessonProgress.Etat.TERMINEE, "date_terminaison": timezone.now()},
                        )
                        if progress.etat != LessonProgress.Etat.TERMINEE:
                            progress.etat = LessonProgress.Etat.TERMINEE
                            progress.date_terminaison = timezone.now()
                            progress.save(update_fields=["etat", "date_terminaison"])
                    if completed_count < len(all_lessons):
                        LessonProgress.objects.get_or_create(
                            inscription=inscription, lesson=all_lessons[completed_count],
                            defaults={"etat": LessonProgress.Etat.EN_COURS},
                        )
                    for module in cours.modules.all():
                        module_lessons = list(module.lecons.all())
                        if module_lessons and all(lesson.pk in completed_ids for lesson in module_lessons):
                            ProgressionModule.objects.get_or_create(inscription=inscription, module=module)
                    if all_lessons:
                        inscription.derniere_lecon = all_lessons[min(completed_count, len(all_lessons) - 1)]
                        inscription.save(update_fields=["derniere_lecon"])
                    recalculer_progression(inscription)

        self.stdout.write(self.style.SUCCESS(
            f"Données LMS prêtes : {len(CATALOGUE)} cours, {lecons_creees} nouvelles leçons, "
            f"{inscriptions_creees} nouvelles inscriptions. Commande relançable sans doublons."
        ))
