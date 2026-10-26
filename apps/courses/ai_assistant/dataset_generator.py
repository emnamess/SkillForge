"""Crée un corpus synthétique reproductible, réparti par sujets sans fuite."""
import csv
from pathlib import Path


SUBJECTS = [
    ("python_variables", "Variables Python", "Une variable Python associe un nom à une valeur. Les nombres, chaînes de caractères et booléens sont des types courants. Une affectation utilise le signe égal.", "score = 18\nmessage = 'Bonjour'", "débutant"),
    ("python_functions", "Fonctions Python", "Une fonction regroupe des instructions sous un nom. Elle peut recevoir des paramètres et retourner un résultat avec return.", "def doubler(nombre):\n    return nombre * 2", "débutant"),
    ("sql_joins", "Jointures SQL", "INNER JOIN ne conserve que les lignes avec correspondance dans les deux tables. LEFT JOIN garde toutes les lignes de gauche et complète avec NULL quand aucune correspondance n'existe.", "SELECT c.nom, co.id\nFROM clients c\nLEFT JOIN commandes co ON co.client_id = c.id;", "intermédiaire"),
    ("sql_aggregation", "Agrégations SQL", "COUNT compte les lignes, SUM additionne une mesure et AVG calcule une moyenne. GROUP BY forme des groupes ; HAVING filtre les groupes après agrégation.", "SELECT ville, COUNT(*)\nFROM clients\nGROUP BY ville;", "intermédiaire"),
    ("git_branch", "Branches Git", "Une branche Git est un pointeur léger vers un commit. Elle permet d'isoler un travail avant de le proposer à la branche principale.", "git switch -c feature/recherche", "débutant"),
    ("git_merge", "Conflits Git", "Un conflit de fusion apparaît lorsque des changements incompatibles touchent la même zone. Il faut examiner les deux versions, résoudre le fichier, puis l'ajouter et terminer la fusion.", "git status\ngit add fichier.py", "intermédiaire"),
    ("http_request", "Requêtes HTTP", "Une requête HTTP contient une méthode, une URL et éventuellement des en-têtes ou un corps. GET lit une ressource ; POST envoie généralement des données.", "GET /api/cours HTTP/1.1", "débutant"),
    ("http_status", "Codes HTTP", "Les codes HTTP indiquent le résultat d'une requête. 2xx signale un succès, 4xx une erreur liée à la requête cliente et 5xx une erreur du serveur.", "200 OK\n404 Not Found", "débutant"),
    ("statistics_mean", "Moyenne et médiane", "La moyenne additionne les valeurs puis divise par leur nombre. La médiane est la valeur centrale après tri ; elle est moins sensible aux valeurs extrêmes.", "Valeurs triées : 2, 3, 100\nMédiane : 3", "intermédiaire"),
    ("security_passwords", "Hachage des mots de passe", "Un hachage transforme une donnée en empreinte à sens unique. Les mots de passe doivent être hachés avec une fonction adaptée et un sel, jamais stockés en clair.", "hash = fonction_couteuse(mot_de_passe, sel)", "avancé"),
]

QUESTION_FORMS = {
    "resume": ["Résume ce passage", "Fais un résumé des points essentiels", "Écris une synthèse courte", "Donne le résumé de cette leçon", "Peux-tu résumer ce que je dois retenir ?", "Produis un résumé principal"],
    "simple": ["Explique cette notion simplement", "Simplifie cette explication", "Donne une explication facile à comprendre", "Explique avec des mots simples", "Peux-tu rendre cette leçon plus simple ?", "Réexplique simplement le concept"],
    "example": ["Donne un exemple concret", "Montre un exemple pratique", "Propose un exemple pour illustrer cette idée", "Ajoute un exemple lié au cours", "Peux-tu illustrer avec un exemple ?", "Montre un cas concret"],
    "steps": ["Explique les étapes une par une", "Donne les étapes à suivre", "Décompose la méthode en étapes", "Quelles sont les étapes successives ?", "Présente étape par étape le processus", "Guide-moi par étapes"],
    "definition": ["Donne la définition du concept principal", "Quelle est la définition de ce terme ?", "Définis cette notion", "Explique la définition du concept", "Peux-tu donner une définition claire ?", "Quelle définition retenir ?"],
    "quiz": ["Fais-moi un petit quiz", "Pose une question pour vérifier ma compréhension", "Teste mes connaissances sur ce sujet", "Interroge-moi sur la leçon", "Crée un exercice rapide", "Aide-moi à réviser avec une question"],
    "question": ["Pourquoi cette méthode est-elle utile ?", "Dans quel cas faut-il l'utiliser ?", "Quelle est l'idée derrière ce passage ?", "Comment cela fonctionne-t-il ?", "Quelle différence avec une autre méthode ?", "Peux-tu préciser ce point du cours ?"],
}

ANSWERS = {
    "resume": "Idée principale : {first} Le passage donne aussi cet exemple : {code}",
    "simple": "En termes simples, {first}",
    "example": "Voici l'exemple de la leçon : {code}. Il illustre l'idée suivante : {first}",
    "steps": "Pour suivre la méthode : 1) repérez le concept présenté ; 2) appliquez-le à cet exemple : {code} ; 3) vérifiez le résultat à la lumière du cours.",
    "definition": "Dans cette leçon, le concept se comprend ainsi : {first}",
    "quiz": "Question de révision : expliquez avec vos mots l'idée suivante : {first}",
    "question": "Le contenu de la leçon indique que {first} Exemple associé : {code}",
}

TRAIN_SUBJECTS = {"python_variables", "python_functions", "sql_joins", "sql_aggregation", "git_branch", "git_merge"}
VALIDATION_SUBJECTS = {"http_request", "http_status"}


def generate_dataset(destination, variations=6):
    if not 4 <= variations <= len(next(iter(QUESTION_FORMS.values()))):
        raise ValueError(f"variations doit être entre 4 et {len(next(iter(QUESTION_FORMS.values())))}")
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["subject_id", "subject", "lesson_content", "question", "intent", "expected_answer", "difficulty", "split"]
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for subject_id, subject, content, code, difficulty in SUBJECTS:
            split = "train" if subject_id in TRAIN_SUBJECTS else "validation" if subject_id in VALIDATION_SUBJECTS else "test"
            first = content.split(". ")[0].rstrip(".")
            for intent, forms in QUESTION_FORMS.items():
                for variation_index, question in enumerate(forms[:variations]):
                    if (split == "train" and variation_index >= variations - 2) or \
                       (split == "validation" and variation_index != variations - 2) or \
                       (split == "test" and variation_index != variations - 1):
                        continue
                    writer.writerow({
                        "subject_id": subject_id, "subject": subject, "lesson_content": content,
                        "question": f"{question} (sujet : {subject.lower()})", "intent": intent,
                        "expected_answer": ANSWERS[intent].format(first=first, code=code),
                        "difficulty": difficulty, "split": split,
                    })
    return path
