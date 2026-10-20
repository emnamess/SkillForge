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
| *(déjà réalisé)* | Utilisateurs et rôles | `apps/accounts` |

## Installation

```bash
git clone <url-du-depot>
cd SkillForge

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
copy .env.example .env         # Windows (cp sous macOS / Linux)

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Ouvrir ensuite http://127.0.0.1:8000.

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
- **Rôles** : `user.est_apprenant`, `user.est_formateur`, `user.est_administrateur`.
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
   git checkout -b feature/notifications-messagerie
   ```
3. Commits courts et explicites : `feat(notifications): modèle Notification`.
4. Avant d'ouvrir la PR, se remettre à jour : `git pull origin main`.
5. Si vous avez modifié un modèle, inclure les migrations (`python manage.py makemigrations <app>`) dans la PR.
6. Ouvrir une Pull Request vers `main` ; au moins un membre la relit avant la fusion.

Préfixes de branche : `feature/`, `fix/`, `docs/`.
