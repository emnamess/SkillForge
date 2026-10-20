# SkillForge

Plateforme e-learning : des modules pas à pas, des quiz corrigés par l'IA et des séances de mentorat en direct.

Développé avec **Django 5.2** selon l'architecture **MVT** (Model, View, Template).

## Équipe et modules

| Membre | Module | App Django |
|---|---|---|
| Emna Messaoudi | Notifications et messagerie | `apps/notifications` |
| Emna Ben Miled | Cours et modules | `apps/courses` |
| Mariem Ferjani | Quiz et correction IA | `apps/quizzes` |
| Saif Tannoubi | Mentorat et séances | `apps/mentoring` |
| Mohamed Karim Kebaili | Certificats et statistiques | `apps/certificates` |
| Emna Messaoudi | Utilisateurs et rôles | `apps/accounts` |

## Installation (première fois)

```bash
git clone https://github.com/emnamess/SkillForge.git
cd SkillForge

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
copy .env.example .env         # Windows (cp .env.example .env sous macOS / Linux)

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Ouvrir ensuite http://127.0.0.1:8000.
Le compte créé avec `createsuperuser` a automatiquement le rôle **Administrateur**.

> Sous PowerShell, si `venv\Scripts\activate` est bloqué :
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (une seule fois).

## Commandes du quotidien

Toujours activer l'environnement virtuel avant de travailler : `venv\Scripts\activate`.

| Besoin | Commande |
|---|---|
| Lancer le serveur | `python manage.py runserver` |
| Récupérer le travail des autres | `git checkout main` puis `git pull` |
| Appliquer les nouvelles migrations (après chaque `git pull`) | `python manage.py migrate` |
| Installer les nouvelles dépendances (si `requirements.txt` a changé) | `pip install -r requirements.txt` |
| Créer les migrations après avoir modifié un modèle | `python manage.py makemigrations <app>` |
| Lancer tous les tests | `python manage.py test` |
| Lancer les tests d'une seule app | `python manage.py test apps.<app>` |
| Vérifier le projet | `python manage.py check` |
| Créer un administrateur | `python manage.py createsuperuser` |
| Ouvrir un shell Django | `python manage.py shell` |
| Envoyer les rappels de séances dus | `python manage.py envoyer_rappels` |
| Ajouter une dépendance | `pip install <paquet>` puis l'ajouter à `requirements.txt` |

**Après chaque `git pull` sur `main`**, toujours faire dans l'ordre :

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py test
```

## Utilisateurs et rôles

| URL | Page |
|---|---|
| `/comptes/inscription/` | Inscription (apprenant ou formateur) |
| `/comptes/connexion/` | Connexion avec l'e-mail ou le nom d'utilisateur |
| `/comptes/profil/` | Profil et changement de mot de passe |
| `/comptes/mot-de-passe/oublie/` | Réinitialisation du mot de passe par e-mail |
| `/comptes/utilisateurs/` | Gestion des utilisateurs (administrateur) |
| `/admin/` | Back-office Django (administrateur) |

- Un **formateur** qui s'inscrit est « en attente » : un administrateur doit le valider (page *Utilisateurs* ou `/admin/`).
- En développement, les e-mails (réinitialisation du mot de passe, notifications) s'affichent **dans le terminal** où tourne `runserver`.

Pour tester rapidement les trois rôles, créer des comptes depuis `/comptes/inscription/`, puis changer leur rôle depuis `/comptes/utilisateurs/` avec le compte administrateur.

## Notifications, messagerie et rappels

| URL | Page |
|---|---|
| `/notifications/` | Toutes les notifications (aussi accessibles via la cloche en haut à droite) |
| `/notifications/messagerie/` | Messagerie interne |
| `/notifications/messagerie/nouvelle/?a=<id>` | Écrire à un utilisateur (destinataire présélectionné) |
| `/notifications/messagerie/recherche/?q=...` | Recherche dans les messages |
| `/notifications/moderation/` | Signalements de la modération IA (administrateur) |

Règles de la messagerie : un apprenant peut écrire aux formateurs et aux administrateurs ; formateurs et administrateurs peuvent écrire à tout le monde.

### Utiliser les notifications depuis votre module

Tout passe par `apps/notifications/services.py`, pas besoin de toucher aux modèles :

```python
from apps.notifications.models import Notification
from apps.notifications.services import notifier, planifier_rappels_seance, annuler_rappels

# Notifier un ou plusieurs utilisateurs (liste ou queryset). email=True envoie aussi un e-mail.
notifier(apprenant, "Quiz corrigé", "Vous avez obtenu 16/20.",
         type=Notification.Type.QUIZ, lien=quiz.get_absolute_url())

notifier(cours.inscrits.all(), "Nouveau module publié", module.titre,
         type=Notification.Type.COURS, lien=module.get_absolute_url())

# Mentorat : programmer les rappels 24 h et 15 min avant la séance
# (rappeler la fonction si la séance est déplacée, elle remplace les anciens rappels)
planifier_rappels_seance(seance, [seance.apprenant, seance.formateur], seance.date_heure,
                         titre="Séance de mentorat · Modélisation UML", lien=seance.get_absolute_url())

# Séance annulée : supprimer ses rappels non envoyés
annuler_rappels(seance)
```

Types disponibles : `MESSAGE`, `SEANCE`, `RAPPEL`, `COURS`, `QUIZ`, `CERTIFICAT`, `COMPTE`, `SYSTEME`.

Bouton « Poser une question au formateur » :

```django
<a href="{% url 'notifications:nouvelle_conversation' %}?a={{ formateur.pk }}" class="btn btn-outline">
    Poser une question au formateur
</a>
```

### Temps réel (WebSockets)

La messagerie et la cloche fonctionnent en temps réel grâce à **Django Channels** :
messages instantanés, indicateur « en train d'écrire », statut en ligne et notifications en direct (toasts).

- Rien à lancer en plus : `python manage.py runserver` démarre **Daphne** (serveur ASGI) qui gère HTTP et WebSockets.
  Le terminal affiche les lignes `WebSocket CONNECT ...`.
- Les notifications créées avec `notifier(...)` arrivent automatiquement en direct, aucun code à ajouter.
- Si le WebSocket est coupé, la page se rabat toute seule sur une actualisation périodique.
- Un module qui a besoin de ses propres WebSockets (ex. signalisation des appels vidéo du mentorat) ajoute ses routes dans `config/asgi.py`.
- En production avec plusieurs processus, installer `channels-redis` et définir `REDIS_URL` dans `.env`.

### Pièces jointes et recherche

- Bouton trombone dans une conversation : PDF, images, documents Office, code, archives… **10 Mo maximum**.
- Les fichiers sont stockés dans `private_media/` (non versionné) et ne sont accessibles **qu'aux participants** de la conversation.
- Champ de recherche au-dessus des conversations : cherche dans le texte des messages et les noms de fichiers.

### Modération IA (Google Gemini)

Chaque message est analysé par **Gemini** avant l'envoi :

| Décision | Effet |
|---|---|
| Autorisé | Le message est envoyé normalement |
| Signalé | Le message est envoyé mais marqué ; les administrateurs sont prévenus |
| Bloqué | Le message n'est pas envoyé ; l'auteur voit la raison, les administrateurs sont prévenus |

Les administrateurs traitent les signalements sur `/notifications/moderation/` (lien *Modération* dans le menu) :
rétablir le message, le supprimer ou désactiver l'auteur.

**Configuration** : créer une clé gratuite sur https://aistudio.google.com/apikey puis l'ajouter dans `.env` :

```
GEMINI_API_KEY=votre-cle
```

Sans clé (ou si l'API ne répond pas), la modération se replie automatiquement sur des **règles locales** (liste de mots,
numéros de téléphone) : la messagerie continue de fonctionner. Les tests n'appellent jamais la vraie API.

### Envoyer les rappels

Les rappels programmés sont envoyés par la commande `envoyer_rappels` :

```bash
python manage.py envoyer_rappels             # envoie les rappels dus, une fois
python manage.py envoyer_rappels --boucle    # en développement : vérifie chaque minute (Ctrl+C pour arrêter)
```

En production, la lancer chaque minute avec le Planificateur de tâches Windows ou une tâche cron :
`* * * * * cd /chemin/SkillForge && venv/bin/python manage.py envoyer_rappels`

## Structure

```
SkillForge/
├── config/              # paramètres et URLs racine du projet
├── apps/
│   ├── accounts/        # User (rôles apprenant / formateur / administrateur)
│   ├── courses/         # Cours, Module, Inscription
│   ├── quizzes/         # Quiz, Question, correction IA
│   ├── mentoring/       # SeanceMentorat
│   ├── certificates/    # Certificat, statistiques
│   └── notifications/   # Notification, messagerie
├── templates/           # base.html, base_app.html, partials/
└── static/css/main.css  # charte graphique partagée
```

Chaque app suit le même schéma MVT :

- `models.py` : les modèles (le **M**)
- `views.py` + `urls.py` : la logique et les routes (la **V**)
- `templates/<app>/` : les pages HTML (le **T**)

## Conventions de l'équipe

- **Utilisateur** : toujours référencer `settings.AUTH_USER_MODEL` (ou `get_user_model()`), jamais `auth.User`.
- **Rôles** : `user.est_apprenant`, `user.est_formateur`, `user.est_administrateur`, `user.en_attente_validation`.
- **Contrôle d'accès** : utiliser `apps/accounts/decorators.py`. Un formateur non validé est refusé, un administrateur passe toujours.
  ```python
  from apps.accounts.decorators import role_required, RoleRequiredMixin
  from apps.accounts.models import User

  @role_required(User.Role.FORMATEUR)
  def creer_cours(request): ...

  class CreerQuizView(RoleRequiredMixin, CreateView):
      roles = [User.Role.FORMATEUR]
  ```
- **Formulaires** : afficher les champs avec `{% include "partials/form_field.html" with field=form.xxx %}`.
- **Templates** : les pages publiques étendent `base.html`, les pages de l'espace connecté étendent `base_app.html`.
- **Style** : réutiliser les classes de `static/css/main.css` (`.card`, `.btn`, `.badge-*`, `.page-title`…). Le style spécifique à un module va dans `static/css/<app>.css`.
- **URLs** : chaque app a un `app_name`, donc `{% url 'courses:index' %}`.
- **Langue** : interface et noms métiers en français.

## Workflow Git

1. Ne jamais pousser directement sur `main`.
2. Créer une branche par fonctionnalité depuis `main` à jour :
   ```bash
   git checkout main
   git pull
   git checkout -b feature/cours-modules
   ```
3. Travailler, puis enregistrer régulièrement :
   ```bash
   git status                      # voir les fichiers modifiés
   git add .
   git commit -m "feat(courses): modèle Cours et Module"
   ```
4. Avant d'ouvrir la PR, récupérer les derniers changements de `main` et vérifier que tout passe :
   ```bash
   git pull origin main
   python manage.py migrate
   python manage.py test
   ```
5. Pousser la branche puis ouvrir la Pull Request vers `main` sur GitHub :
   ```bash
   git push -u origin feature/cours-modules
   ```
6. Au moins un membre relit la PR avant la fusion.
7. Après la fusion, revenir sur `main` et se mettre à jour : `git checkout main` puis `git pull`.

Préfixes de branche : `feature/`, `fix/`, `docs/`. Préfixes de commit : `feat`, `fix`, `docs`, `style`, `test`, `refactor`.

Si vous avez modifié un modèle, n'oubliez pas de commiter le fichier de migration généré (`apps/<app>/migrations/000X_....py`).

### En cas de conflit

Lors d'un `git pull origin main`, Git peut signaler un conflit. Ouvrir les fichiers indiqués, garder le bon code entre les marqueurs `<<<<<<<`, `=======` et `>>>>>>>`, puis :

```bash
git add <fichier>
git commit
```

Les fichiers partagés (`static/css/main.css`, `templates/partials/`, `config/settings.py`, `config/urls.py`) sont les plus exposés aux conflits : modifiez-les le moins possible et prévenez l'équipe.
