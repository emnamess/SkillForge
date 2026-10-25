#!/usr/bin/env python
"""Commandes du projet SkillForge (équivalent des scripts d'un package.json).

    python run.py              liste des commandes
    python run.py setup        installe tout (venv, dépendances, .env, base de données)
    python run.py dev          lance le serveur et l'envoi des rappels

Aucune dépendance : fonctionne avant même la création du venv, et utilise
automatiquement le Python du venv (inutile de l'activer).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent
VENV = RACINE / "venv"
PYTHON_VENV = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

if sys.stdout.isatty():
    VERT, JAUNE, ROUGE, GRAS, FIN = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m"
    if os.name == "nt":
        os.system("")  # active les couleurs dans la console Windows
else:  # sortie redirigée (fichier, CI) : pas de codes couleur
    VERT = JAUNE = ROUGE = GRAS = FIN = ""


def info(texte):
    print(f"{VERT}▶ {texte}{FIN}", flush=True)


def erreur(texte):
    print(f"{ROUGE}✖ {texte}{FIN}", file=sys.stderr)
    sys.exit(1)


def python_venv():
    if not PYTHON_VENV.exists():
        erreur("Environnement virtuel introuvable. Lancez d'abord : python run.py setup")
    return str(PYTHON_VENV)


def executer(*commande, verifier=True):
    """Lance une commande dans le dossier du projet ; s'arrête si elle échoue."""
    resultat = subprocess.run([str(c) for c in commande], cwd=RACINE)
    if verifier and resultat.returncode != 0:
        sys.exit(resultat.returncode)
    return resultat.returncode


def manage(*arguments, verifier=True):
    return executer(python_venv(), "manage.py", *arguments, verifier=verifier)


# ---------- Commandes ----------

def setup(args):
    """Installe le projet : venv, dépendances, fichier .env, base de données."""
    if not PYTHON_VENV.exists():
        info("Création de l'environnement virtuel (venv)")
        executer(sys.executable, "-m", "venv", VENV)

    info("Installation des dépendances")
    executer(python_venv(), "-m", "pip", "install", "--upgrade", "--quiet", "pip")
    executer(python_venv(), "-m", "pip", "install", "--quiet", "-r", "requirements.txt")

    env = RACINE / ".env"
    if not env.exists():
        info("Création du fichier .env avec une clé secrète unique")
        cle = subprocess.run(
            [python_venv(), "-c", "from django.core.management.utils import get_random_secret_key as g; print(g())"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        modele = (RACINE / ".env.example").read_text(encoding="utf-8")
        env.write_text(modele.replace("DJANGO_SECRET_KEY=change-me", f"DJANGO_SECRET_KEY={cle}"), encoding="utf-8")

    info("Application des migrations")
    manage("migrate")

    print(f"\n{GRAS}Projet prêt !{FIN}")
    print("  Créer un administrateur :  python run.py superuser")
    print("  Lancer le projet :         python run.py dev")


def dev(args):
    """Lance le serveur (HTTP + WebSockets) et l'envoi des rappels en parallèle."""
    port = args[0] if args else "8000"
    info("Envoi des rappels de séances en arrière-plan (chaque minute)")
    rappels = subprocess.Popen([python_venv(), "manage.py", "envoyer_rappels", "--boucle"], cwd=RACINE)
    info(f"Serveur sur http://127.0.0.1:{port}  (Ctrl+C pour tout arrêter)")
    try:
        manage("runserver", port, verifier=False)
    except KeyboardInterrupt:
        pass
    finally:
        arreter(rappels)
        print("\nArrêté.")


def arreter(processus):
    """Arrête un processus et ses enfants (sous Windows, le python du venv lance un sous-processus)."""
    if processus.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(processus.pid)], capture_output=True)
    else:
        processus.terminate()
    try:
        processus.wait(timeout=5)
    except subprocess.TimeoutExpired:
        processus.kill()


def serveur(args):
    """Lance uniquement le serveur web (sans les rappels)."""
    try:
        manage("runserver", *(args or ["8000"]), verifier=False)
    except KeyboardInterrupt:
        pass


def rappels(args):
    """Envoie les rappels dus (ajouter --boucle pour vérifier chaque minute)."""
    try:
        manage("envoyer_rappels", *args)
    except KeyboardInterrupt:
        pass


def test(args):
    """Lance les tests (ex. : python run.py test apps.accounts)."""
    manage("test", *args)


def couverture(args):
    """Tests + rapport de couverture (ex. : python run.py couverture apps.certificates)."""
    executer(python_venv(), "-m", "coverage", "run", "manage.py", "test", *args)
    executer(python_venv(), "-m", "coverage", "report")
    executer(python_venv(), "-m", "coverage", "html")
    info(f"Rapport détaillé : {RACINE / 'htmlcov' / 'index.html'}")


def check(args):
    """Vérifie le projet : configuration et migrations manquantes."""
    manage("check")
    info("Recherche de migrations manquantes")
    if manage("makemigrations", "--check", "--dry-run", verifier=False) != 0:
        erreur("Des modèles ont changé sans migration : lancez python run.py makemigrations")
    info("Tout est en ordre")


def migrate(args):
    """Applique les migrations."""
    manage("migrate", *args)


def makemigrations(args):
    """Crée les migrations après une modification de modèle (ex. : python run.py makemigrations courses)."""
    manage("makemigrations", *args)


def update(args):
    """À faire après un git pull : dépendances, migrations, puis tests."""
    info("Mise à jour des dépendances")
    executer(python_venv(), "-m", "pip", "install", "--quiet", "-r", "requirements.txt")
    info("Application des migrations")
    manage("migrate")
    info("Lancement des tests")
    manage("test")


def pull(args):
    """Récupère la dernière version de main puis met le projet à jour."""
    if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                      cwd=RACINE, capture_output=True, text=True).stdout.strip():
        erreur("Vous avez des modifications non commitées : commitez-les ou mettez-les de côté (git stash).")
    info("Récupération de main")
    executer("git", "checkout", "main")
    executer("git", "pull")
    update([])


def demo(args):
    """Crée des comptes de démo (admin, formateurs, apprenants) avec des conversations."""
    manage("creer_demo", *args)


def carriere(args):
    """Crée les données de démo de l'Espace Carrière (entreprises, offres, candidatures)."""
    manage("seed_carriere_demo", *args)


def moderation(args):
    """Teste la modération : Gemini et règles locales côte à côte (ex. : python run.py moderation "texte")."""
    manage("tester_moderation", *args)


def logs(args):
    """Affiche les dernières décisions de modération (logs/moderation.log)."""
    fichier = RACINE / "logs" / "moderation.log"
    if not fichier.exists():
        erreur("Aucun journal pour l'instant : envoyez un message dans la messagerie.")
    lignes = fichier.read_text(encoding="utf-8").splitlines()
    nombre = int(args[0]) if args else 30
    print("\n".join(lignes[-nombre:]))


def superuser(args):
    """Crée un compte administrateur."""
    manage("createsuperuser", *args)


def shell(args):
    """Ouvre un shell Python avec Django chargé."""
    manage("shell", *args)


def clean(args):
    """Supprime les fichiers temporaires Python (__pycache__)."""
    n = 0
    for dossier in RACINE.rglob("__pycache__"):
        if VENV not in dossier.parents:
            shutil.rmtree(dossier, ignore_errors=True)
            n += 1
    info(f"{n} dossier(s) __pycache__ supprimé(s)")


COMMANDES = {
    "setup": setup,
    "dev": dev,
    "serveur": serveur,
    "rappels": rappels,
    "test": test,
    "couverture": couverture,
    "check": check,
    "migrate": migrate,
    "makemigrations": makemigrations,
    "update": update,
    "pull": pull,
    "demo": demo,
    "carriere": carriere,
    "moderation": moderation,
    "logs": logs,
    "superuser": superuser,
    "shell": shell,
    "clean": clean,
}


def aide():
    print(f"{GRAS}SkillForge · commandes disponibles{FIN}\n")
    for nom, fonction in COMMANDES.items():
        print(f"  {JAUNE}python run.py {nom:<15}{FIN}{fonction.__doc__.splitlines()[0]}")
    print("\nAvec npm : npm run <commande>   (ex. npm run dev, npm run test -- apps.accounts)")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help", "aide"):
        aide()
        return
    nom, args = sys.argv[1], sys.argv[2:]
    if nom not in COMMANDES:
        print(f"{ROUGE}Commande inconnue : {nom}{FIN}\n")
        aide()
        sys.exit(1)
    COMMANDES[nom](args)


if __name__ == "__main__":
    main()
