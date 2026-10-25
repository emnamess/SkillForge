"""Crée les données de démonstration de l'Espace Carrière (idempotent).

    python run.py carriere                  crée les données (rien n'est dupliqué si elles existent)
    python run.py carriere --reinitialiser  supprime puis recrée les comptes et données de démo Carrière

Les comptes sont indépendants de ceux de `python run.py demo` (autre domaine d'e-mail).
"""

from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.careers import services
from apps.careers.fabriques import pdf_octets
from apps.careers.models import (Candidature, Competence, CompetenceApprenant, CompetenceRequise, Offre,
                                 ProfilCarriere, ProfilEntreprise)

DOMAINE = "demo-carriere.skillforge.tn"
MOT_DE_PASSE = "SkillForge2026!"
S = Candidature.Statut

ENTREPRISES = [
    # (identifiant, prénom, nom, entreprise, secteur, ville, statut)
    ("datavision", "Salma", "Haddad", "DataVision", "Conseil en data et BI", "Tunis", ProfilEntreprise.Statut.VALIDEE),
    ("codenest", "Youssef", "Gharbi", "CodeNest", "Éditeur de logiciels", "Sfax", ProfilEntreprise.Statut.VALIDEE),
    ("atlas", "Hela", "Chaabane", "Atlas Recrutement", "Cabinet de recrutement", "Sousse",
     ProfilEntreprise.Statut.EN_ATTENTE),
]

# (entreprise, titre, contrat, mode, ville, rémunération, jours avant la date limite, [(compétence, niveau, obligatoire)])
OFFRES = [
    ("datavision", "Stage PFE · Data engineer junior", "stage_pfe", "hybride", "Tunis", "800 DT / mois", 45, [
        ("SQL", 3, True), ("Python", 2, True), ("Airflow", 2, False), ("Power BI", 2, False), ("ETL", 2, False)]),
    ("datavision", "Alternance · Consultant BI", "alternance", "presentiel", "Tunis", "", 30, [
        ("Power BI", 3, True), ("SQL", 2, True), ("Excel avancé", 2, False), ("Communication", 2, False)]),
    ("datavision", "Data analyst", "cdi", "hybride", "Tunis", "2 200 à 2 800 DT", None, [
        ("SQL", 3, True), ("Python", 2, False), ("Power BI", 2, False), ("Statistiques", 2, False),
        ("Communication", 2, False)]),
    ("codenest", "Développeur Django", "cdi", "teletravail", "Sfax", "2 500 à 3 200 DT", None, [
        ("Django", 3, True), ("Python", 3, True), ("Git", 2, True), ("API REST", 2, False), ("Docker", 1, False),
        ("Tests unitaires", 2, False)]),
    ("codenest", "Stage · Développeur front-end", "stage", "presentiel", "Sfax", "600 DT / mois", 20, [
        ("JavaScript", 2, True), ("HTML / CSS", 2, False), ("React", 1, False), ("Git", 1, False)]),
    ("codenest", "Mission · Analyste fonctionnel UML", "freelance", "teletravail", "Sfax", "TJM à négocier", 10, [
        ("UML", 3, True), ("Analyse des besoins", 2, False), ("Merise", 2, False), ("Communication", 3, False)]),
]

APPRENANTS = [
    # (identifiant, prénom, nom, titre, compétences) : scores ≈ 93 %, 62 % et 31 % sur le stage PFE data
    ("ines", "Inès", "Bouaziz", "Data engineer junior", {
        "SQL": 3, "Python": 3, "Airflow": 1, "Power BI": 2, "ETL": 2, "Git": 2, "Statistiques": 2,
        "Communication": 3}),
    ("walid", "Walid", "Ferchichi", "Analyste BI débutant", {
        "SQL": 2, "Python": 2, "Power BI": 1, "ETL": 1, "Excel avancé": 3, "Communication": 2}),
    ("rania", "Rania", "Jlassi", "Développeuse web en reconversion", {
        "SQL": 1, "Python": 1, "Power BI": 1, "JavaScript": 2, "HTML / CSS": 3, "Git": 1}),
]

# (apprenant, n° de l'offre dans OFFRES, statuts successifs) : toutes les colonnes du Kanban sont remplies
CANDIDATURES = [
    ("ines", 0, [S.EN_EXAMEN, S.ENTRETIEN]),
    ("walid", 0, [S.EN_EXAMEN]),
    ("rania", 0, []),
    ("ines", 2, [S.EN_EXAMEN, S.ENTRETIEN, S.ACCEPTEE]),
    ("walid", 2, [S.REFUSEE]),
    ("walid", 1, []),
    ("rania", 3, [S.RETIREE]),
    ("rania", 4, [S.EN_EXAMEN]),
]


class Command(BaseCommand):
    help = "Crée des entreprises, offres, apprenants et candidatures de démonstration pour l'Espace Carrière."

    def add_arguments(self, parser):
        parser.add_argument("--reinitialiser", action="store_true",
                            help="Supprime les comptes de démo Carrière avant de les recréer.")
        parser.add_argument("--force", action="store_true",
                            help="Autorise la commande même quand DEBUG est désactivé.")

    def handle(self, *args, reinitialiser=False, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Données de démo refusées hors développement (DEBUG=False). Utilisez --force.")

        call_command("seed_competences", stdout=self.stdout)

        demo = User.objects.filter(email__endswith=f"@{DOMAINE}")
        if reinitialiser:
            n, _ = demo.delete()  # entreprises, offres, profils et candidatures suivent en cascade
            self.stdout.write(f"Anciennes données de démo Carrière supprimées ({n} objets).")

        nouveau = not demo.exists()
        if nouveau:
            # Les notifications de la démo sont créées, mais leurs e-mails ne sont pas envoyés
            with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"), \
                    transaction.atomic():
                recruteurs = self.creer_entreprises()
                offres = self.creer_offres(recruteurs)
                apprenants = self.creer_apprenants()
                self.creer_candidatures(recruteurs, offres, apprenants)
        self.afficher_resume(nouveau)

    def creer_utilisateur(self, identifiant, prenom, nom, role):
        return User.objects.create_user(
            username=f"carriere_{identifiant}", email=f"{identifiant}@{DOMAINE}", password=MOT_DE_PASSE,
            first_name=prenom, last_name=nom, role=role,
        )

    def creer_entreprises(self):
        recruteurs = {}
        for identifiant, prenom, nom, entreprise, secteur, ville, statut in ENTREPRISES:
            user = self.creer_utilisateur(identifiant, prenom, nom, User.Role.RECRUTEUR)
            ProfilEntreprise.objects.create(
                utilisateur=user, nom=entreprise, secteur=secteur, ville=ville, statut=statut,
                site_web=f"https://www.{identifiant}.example", date_decision=None if statut == ProfilEntreprise.Statut.EN_ATTENTE else timezone.now(),
                description=f"{entreprise} est une entreprise fictive créée pour la démonstration de SkillForge.",
            )
            recruteurs[identifiant] = user
        return recruteurs

    def creer_offres(self, recruteurs):
        competences = {c.nom: c for c in Competence.objects.all()}
        aujourdhui = timezone.localdate()
        offres = []
        for i, (entreprise, titre, contrat, mode, ville, remuneration, jours, exigences) in enumerate(OFFRES):
            offre = Offre.objects.create(
                entreprise=recruteurs[entreprise].profil_entreprise, titre=titre, type_contrat=contrat,
                mode_travail=mode, ville=ville, remuneration=remuneration,
                date_limite=aujourdhui + timedelta(days=jours) if jours else None,
                description=(f"{recruteurs[entreprise].profil_entreprise} recrute : {titre.lower()}.\n\n"
                             "Missions : participer aux projets clients, documenter votre travail et "
                             "présenter vos résultats à l'équipe.\n\nProfil : curiosité, rigueur et envie d'apprendre."),
            )
            CompetenceRequise.objects.bulk_create([
                CompetenceRequise(offre=offre, competence=competences[nom], niveau_requis=niveau, obligatoire=obl)
                for nom, niveau, obl in exigences
            ])
            services.publier_offre(offre)
            # Dates de publication échelonnées pour un rendu réaliste
            Offre.objects.filter(pk=offre.pk).update(date_publication=timezone.now() - timedelta(days=2 * i))
            offres.append(offre)
        return offres

    def creer_apprenants(self):
        competences = {c.nom: c for c in Competence.objects.all()}
        apprenants = {}
        for identifiant, prenom, nom, titre, niveaux in APPRENANTS:
            user = self.creer_utilisateur(identifiant, prenom, nom, User.Role.APPRENANT)
            profil = ProfilCarriere.objects.create(
                apprenant=user, titre=titre, ville="Tunis", disponibilite="Immédiate",
                types_contrat_recherches="stage_pfe,cdi,alternance",
                presentation=f"{prenom}, apprenant(e) SkillForge, à la recherche d'une première expérience.",
                lien_github=f"https://github.com/{identifiant}-demo",
            )
            CompetenceApprenant.objects.bulk_create([
                CompetenceApprenant(profil=profil, competence=competences[n], niveau=v) for n, v in niveaux.items()
            ])
            texte = f"{prenom} {nom} - {titre} - Competences : " + ", ".join(niveaux)
            profil.cv.save("cv.pdf", ContentFile(pdf_octets(texte.encode("ascii", "ignore").decode())))
            apprenants[identifiant] = user
        return apprenants

    def creer_candidatures(self, recruteurs, offres, apprenants):
        entretien = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=3)
        for identifiant, n_offre, statuts in CANDIDATURES:
            offre = offres[n_offre]
            recruteur = offre.entreprise.utilisateur
            candidature = services.postuler(offre, apprenants[identifiant],
                                            "Votre offre correspond exactement au projet que je prépare.")
            for statut in statuts:
                if statut == S.RETIREE:
                    services.retirer_candidature(candidature, apprenants[identifiant])
                elif statut == S.ENTRETIEN:
                    services.planifier_entretien(candidature, recruteur, entretien, "Visio : https://meet.example/demo",
                                                 "Au plaisir d'échanger avec vous.")
                else:
                    services.changer_statut(candidature, recruteur, statut)

    def afficher_resume(self, nouveau):
        if nouveau:
            self.stdout.write(self.style.SUCCESS("Données de démo Carrière créées."))
        else:
            self.stdout.write(self.style.WARNING(
                "Les données de démo Carrière existent déjà (ajoutez --reinitialiser pour les recréer)."))

        self.stdout.write(f"\nMot de passe de tous les comptes : {MOT_DE_PASSE}\n")
        for identifiant, prenom, nom, entreprise, *_, statut in ENTREPRISES:
            etat = "" if statut == ProfilEntreprise.Statut.VALIDEE else "  (entreprise en attente de validation)"
            self.stdout.write(f"  {identifiant + '@' + DOMAINE:<40} Recruteur  {prenom} {nom} · {entreprise}{etat}")

        reference = Offre.objects.filter(entreprise__utilisateur__email=f"datavision@{DOMAINE}",
                                         titre=OFFRES[0][1]).first()
        for identifiant, prenom, nom, *_ in APPRENANTS:
            user = User.objects.filter(email=f"{identifiant}@{DOMAINE}").first()
            score = services.score_offre(reference, user).score if reference and user else None
            detail = f"  ({score} % sur « {OFFRES[0][1]} »)" if score is not None else ""
            self.stdout.write(f"  {identifiant + '@' + DOMAINE:<40} Apprenant  {prenom} {nom}{detail}")
        self.stdout.write("\nAdministrateur : utilisez votre superutilisateur ou demo_admin (python run.py demo).")
