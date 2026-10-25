"""Crée le référentiel de compétences de l'Espace Carrière (idempotent).

    python manage.py seed_competences

Relancer la commande met à jour la catégorie et les alias, sans créer de doublons.
"""

from django.core.management.base import BaseCommand

from apps.careers.models import Competence

C = Competence.Categorie

# (nom, catégorie, alias séparés par des virgules : utilisés pour lire les CV)
COMPETENCES = [
    # Data
    ("SQL", C.DATA, "mysql, postgresql, postgres, sql server, oracle sql, pl/sql, t-sql, sqlite"),
    ("Python", C.DATA, "python3, pandas, numpy"),
    ("Power BI", C.DATA, "powerbi, dax, power query"),
    ("Tableau", C.DATA, "tableau software, tableau desktop"),
    ("Excel avancé", C.DATA, "excel, vba, tableaux croises dynamiques"),
    ("ETL", C.DATA, "extract transform load, talend, ssis, informatica"),
    ("Airflow", C.DATA, "apache airflow"),
    ("Spark", C.DATA, "apache spark, pyspark"),
    ("Entrepôt de données", C.DATA, "data warehouse, datawarehouse, modelisation en etoile, schema en etoile"),
    ("Gouvernance des données", C.DATA, "data governance, qualite des donnees, rgpd, data quality"),
    ("Machine learning", C.DATA, "apprentissage automatique, scikit-learn, sklearn"),
    ("Statistiques", C.DATA, "statistique, analyse statistique"),
    ("MongoDB", C.DATA, "nosql, mongo"),
    # Développement
    ("Django", C.DEVELOPPEMENT, "django rest framework, drf"),
    ("JavaScript", C.DEVELOPPEMENT, "js, ecmascript, es6"),
    ("TypeScript", C.DEVELOPPEMENT, ""),
    ("React", C.DEVELOPPEMENT, "reactjs, react.js"),
    ("Angular", C.DEVELOPPEMENT, "angularjs"),
    ("Node.js", C.DEVELOPPEMENT, "nodejs, express, express.js"),
    ("HTML / CSS", C.DEVELOPPEMENT, "html, html5, css, css3"),
    ("Java", C.DEVELOPPEMENT, "jee, java ee, spring boot, spring"),
    ("PHP", C.DEVELOPPEMENT, "symfony, laravel"),
    ("API REST", C.DEVELOPPEMENT, "rest api, restful, web services"),
    ("Tests unitaires", C.DEVELOPPEMENT, "tests automatises, pytest, junit, tdd"),
    # Systèmes d'information
    ("UML", C.SI, "modelisation uml, diagramme de classes, diagramme de cas d'utilisation"),
    ("Merise", C.SI, "mcd, mld"),
    ("Analyse des besoins", C.SI, "recueil des besoins, cahier des charges, specifications fonctionnelles"),
    ("ERP", C.SI, "sap, odoo, dynamics 365"),
    ("Gestion de projet", C.SI, "chef de projet, ms project, planification"),
    ("Agile Scrum", C.SI, "scrum, agile, kanban, sprint"),
    ("BPMN", C.SI, "modelisation des processus, processus metier"),
    # Outils et méthodes
    ("Git", C.OUTILS, "github, gitlab, versioning"),
    ("Docker", C.OUTILS, "conteneurs, docker compose"),
    ("Linux", C.OUTILS, "bash, shell, ubuntu, debian"),
    ("Cloud", C.OUTILS, "aws, azure, gcp, google cloud"),
    ("CI/CD", C.OUTILS, "integration continue, github actions, gitlab ci, jenkins"),
    # Soft skills
    ("Communication", C.SOFT_SKILLS, "communication orale, prise de parole, presentation orale"),
    ("Travail en équipe", C.SOFT_SKILLS, "esprit d'equipe, collaboration, team work"),
    ("Anglais professionnel", C.SOFT_SKILLS, "anglais, english, toeic, ielts"),
    ("Résolution de problèmes", C.SOFT_SKILLS, "problem solving, esprit d'analyse, esprit analytique"),
    ("Autonomie", C.SOFT_SKILLS, "autonome"),
]


class Command(BaseCommand):
    help = "Crée ou met à jour le référentiel de compétences de l'Espace Carrière."

    def handle(self, *args, **options):
        crees = 0
        for nom, categorie, alias in COMPETENCES:
            _, cree = Competence.objects.update_or_create(nom=nom, defaults={"categorie": categorie, "alias": alias})
            crees += cree
        self.stdout.write(self.style.SUCCESS(
            f"Référentiel prêt : {len(COMPETENCES)} compétences ({crees} créée(s), "
            f"{len(COMPETENCES) - crees} mise(s) à jour)."))
