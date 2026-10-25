# SkillForge

Plateforme e-learning : des modules pas à pas, des quiz corrigés par l'IA et des séances de mentorat en direct.

Développé avec **Django 5.2** selon l'architecture **MVT** (Model, View, Template).

## Modules

| Module | App Django |
|---|---|
| Utilisateurs et rôles | `apps/accounts` |
| Cours et modules | `apps/courses` |
| Quiz et correction IA | `apps/quizzes` |
| Mentorat et séances | `apps/mentoring` |
| Certificats et statistiques | `apps/certificates` |
| Notifications et messagerie | `apps/notifications` |
| Espace carrière | `apps/careers` |

L'équipe, les comptes de démo et l'accès au site en ligne sont décrits dans **`COMPTES.md`**,
un fichier local non versionné (à demander à l'équipe).

## Installation (première fois)

```bash
git clone <adresse-du-dépôt>
cd SkillForge
python run.py setup        # crée le venv, installe les dépendances, génère .env, crée la base
python run.py superuser    # crée votre compte administrateur
python run.py dev          # lance le projet
```

Ouvrir ensuite http://127.0.0.1:8000.
Le compte créé avec `superuser` a automatiquement le rôle **Administrateur**.

> Sous macOS / Linux, remplacer `python` par `python3` si besoin.

## Commandes du projet

Toutes les commandes passent par **`run.py`** (l'équivalent des scripts d'un `package.json`).
Il utilise automatiquement le Python du `venv` : **pas besoin d'activer l'environnement virtuel**.

| Commande | Rôle |
|---|---|
| `python run.py` | Affiche la liste des commandes |
| `python run.py setup` | Installe le projet (venv, dépendances, `.env`, base de données) |
| `python run.py dev` | Lance le serveur **et** l'envoi des rappels (Ctrl+C arrête tout) |
| `python run.py dev 8001` | Idem sur un autre port |
| `python run.py serveur` | Lance uniquement le serveur web |
| `python run.py test` | Lance tous les tests |
| `python run.py test apps.accounts` | Lance les tests d'une seule app |
| `python run.py couverture apps.certificates` | Lance les tests avec le rapport de couverture (coverage.py) |
| `python run.py check` | Vérifie la configuration et les migrations oubliées (à faire avant une PR) |
| `python run.py makemigrations courses` | Crée les migrations après une modification de modèle |
| `python run.py migrate` | Applique les migrations |
| `python run.py pull` | Récupère `main` puis met tout à jour (dépendances, migrations, tests) |
| `python run.py update` | Met à jour après un `git pull` fait à la main |
| `python run.py demo` | Crée des comptes de démo avec des conversations (voir ci-dessous) |
| `python run.py demo --reinitialiser` | Supprime puis recrée les données de démo |
| `python run.py moderation "texte"` | Compare la décision de Gemini et des règles locales (vérifie la clé API) |
| `python run.py logs` | Affiche les dernières décisions de modération |
| `python run.py superuser` | Crée un compte administrateur |
| `python run.py shell` | Ouvre un shell Python avec Django chargé |
| `python run.py rappels` | Envoie les rappels de séances dus |
| `python run.py clean` | Supprime les dossiers `__pycache__` |
| `python run.py production` | Démarrage sur le serveur (voir [Déploiement](#déploiement-render)) — pas en local |

### Comptes de démo

`python run.py demo` crée des comptes prêts à l'emploi pour tester tous les rôles (administrateur, formateurs,
apprenants) ; `python run.py carriere` ajoute les recruteurs. On peut se connecter avec l'e-mail **ou** le nom
d'utilisateur. La liste des comptes et le mot de passe sont dans `COMPTES.md` (local, non versionné).

> La commande refuse de tourner hors développement. Ne réutilisez jamais le mot de passe de démo pour de vrais comptes.

Ils arrivent avec des conversations, des notifications, un message signalé à modérer et un rappel de séance
qui arrive 2 minutes après la création (si `python run.py dev` tourne). Pour tester le temps réel, ouvrir deux
navigateurs (ou une fenêtre de navigation privée) avec deux comptes différents.

Chaque module peut compléter `apps/accounts/management/commands/creer_demo.py` avec ses propres données
(cours, quiz, séances…).

**Avec npm** (si Node.js est installé) : les mêmes commandes existent dans `package.json`.

```bash
npm run dev
npm run test -- apps.accounts      # les arguments passent après --
```

Ajouter une dépendance Python : `venv\Scripts\pip install <paquet>` (ou `venv/bin/pip`), puis l'ajouter à `requirements.txt`.

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

- Rien à lancer en plus : `python run.py dev` démarre **Daphne** (serveur ASGI) qui gère HTTP et WebSockets.
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

**Le back-office garde le dernier mot** sur `/notifications/moderation/` (lien *Modération* dans le menu) :

| Cas | Actions de l'administrateur |
|---|---|
| Message **bloqué** (non livré) | *Faux positif : envoyer* (le message part au destinataire, l'auteur est prévenu) · *Confirmer le blocage* |
| Message **signalé** (livré) | *Message acceptable* · *Supprimer le message* (retiré en direct de la conversation) |
| Dans tous les cas | *Avertir l'auteur* (notification + e-mail) · *Désactiver l'auteur* |

Chaque signalement indique l'auteur, le destinataire, l'analyse de l'IA, et garde la décision prise et son auteur.

**Configuration** : créer une clé gratuite sur https://aistudio.google.com/apikey puis l'ajouter dans `.env` :

```
GEMINI_API_KEY=votre-cle
```

**Qui décide ?** Gemini analyse chaque message. Les **règles locales** (listes de mots en français, anglais et darija,
contournements comme « m3rde » ou « f u c k », numéros de téléphone) ne servent que de secours : sans clé API,
si Gemini est en panne ou lent, ou quand le quota gratuit est dépassé. La messagerie continue donc toujours de fonctionner.
Les tests n'appellent jamais la vraie API.

**Journal des décisions** : chaque message analysé est tracé dans le terminal de `runserver` et dans `logs/moderation.log`
(non versionné). La première colonne indique qui a décidé :

```
20/10 20:34:21 [Modération] GEMINI   BLOQUE    harcelement  4422 ms  « personne ne veut de toi ici »  → Les attaques…
20/10 20:34:30 [Modération] CACHE    BLOQUE    harcelement     0 ms  « personne ne veut de toi ici »  → Les attaques…
20/10 20:35:02 [Modération] Quota Gemini dépassé : pause de 26 s, règles locales en attendant
20/10 20:35:02 [Modération] REGLES   AUTORISE  aucune          0 ms  « merci »
```

- `GEMINI` : décision de l'IA · `CACHE` : message identique déjà analysé par l'IA (24 h) · `REGLES` : secours local
- Une ligne d'avertissement explique toujours pourquoi les règles ont pris le relais.
- Le bandeau « Message non envoyé » et la page Modération indiquent aussi la source (IA Gemini ou règles locales).

**Quota gratuit** : l'offre gratuite de Gemini limite le nombre de requêtes (environ 5 par minute et par modèle).
Au-delà, SkillForge fait une pause du délai indiqué par Google puis reprend automatiquement. Réglages possibles dans `.env` :
`GEMINI_MODEL` (défaut `gemini-3.5-flash`), `GEMINI_REFLEXION` (défaut `minimal`, réponse en ~1 s), `MODERATION_TIMEOUT`
(défaut 15 s, minimum 10 s).

### Envoyer les rappels

Les rappels programmés sont envoyés par la commande `envoyer_rappels` :

```bash
python run.py rappels             # envoie les rappels dus, une fois
python run.py rappels --boucle    # vérifie chaque minute (déjà inclus dans python run.py dev)
```

En production, la lancer chaque minute avec le Planificateur de tâches Windows ou une tâche cron :
`* * * * * cd /chemin/SkillForge && venv/bin/python manage.py envoyer_rappels`

## Certificats et statistiques

| URL | Page |
|---|---|
| `/certificats/` | Apprenant : ses certificats · Formateur / admin : progression et certificats délivrés |
| `/certificats/<code>/` | Certificat imprimable (bouton « Télécharger en PDF ») |
| `/certificats/delivrer/` | Délivrer un certificat (formateur validé, administrateur) |
| `/certificats/<code>/modifier/` | Corriger un certificat (formateur concerné, administrateur) |
| `/certificats/<code>/supprimer/` | Supprimer un certificat (administrateur) |
| `/certificats/statistiques/` | Statistiques (plateforme pour l'admin, ses cours pour le formateur) |
| `/certificats/export.csv` | Export des certificats (administrateur) |
| `/certificats/verifier/` | **Page publique** : vérifier un certificat avec son code `SF-XXXX-XXXX` |

- Une fraude se traite par la **révocation** (administrateur, depuis la page du certificat) : le certificat reste
  visible comme « révoqué » lors d'une vérification. La suppression est réservée aux erreurs de délivrance.
- Un apprenant ne peut avoir qu'un seul certificat valide par cours.

### Délivrer un certificat depuis votre module

```python
from apps.certificates.services import delivrer_si_eligible

# Module cours : à appeler à chaque mise à jour de la progression (aucun doublon n'est créé)
delivrer_si_eligible(inscription.apprenant, cours.titre, progression=inscription.progression,
                     score=moyenne_quiz, formateur=cours.formateur)
```

Éligibilité : progression à 100 % et score ≥ `CERTIFICAT_SCORE_MINIMUM` (70 par défaut, réglable dans les paramètres).
Le suivi de progression lit `courses.Inscription` (`apprenant`, `cours`, `progression`, `date_inscription`) dès que ce
modèle existe ; les noms de champs se règlent dans `apps/certificates/progression.py`.

### Recommandation de certifications (IA)

Sur **Mes certificats**, chaque apprenant reçoit 3 certifications recommandées, avec leurs raisons et les compétences
qu'elles lui feraient acquérir. Le moteur (`apps/certificates/recommandation.py`, scikit-learn) est **hybride** :

- **filtrage par contenu** : vecteurs TF-IDF des cours (titre + compétences) comparés au profil de l'apprenant
  (compétences validées + présentation de son profil), similarité cosinus ;
- **filtrage collaboratif** : « ceux qui ont obtenu X ont aussi obtenu Y » (similarité entre cours sur la matrice
  apprenants × cours) ;
- score final = α × contenu + (1 − α) × collaboratif (α = 0,4, réglable avec `RECOMMANDATION_ALPHA`) ; un nouvel
  apprenant sans certificat reçoit un mélange de son profil et des cours les plus populaires.

| URL | Page |
|---|---|
| `/certificats/recommandations/` | API JSON des recommandations de l'utilisateur connecté |
| `/certificats/recommandations/performance/` | Métriques du modèle (administrateur) : HitRate@3, Precision@3, MRR, NDCG@3, temps de réponse |

Le modèle s'entraîne en quelques millisecondes et reste en cache tant que les certificats ne changent pas.
`python run.py demo` crée aussi 40 apprenants **simulés** (`@sim.skillforge.tn`, parcours générés) pour que le moteur
ait assez de données ; à remplacer par les vraies données quand le module Cours sera fusionné.

### Couverture des tests

```bash
python run.py couverture apps.certificates   # tests + rapport dans le terminal et dans htmlcov/index.html
```

## Déploiement (Render)

SkillForge est hébergé sur [Render](https://render.com) avec l'offre gratuite. Le fichier `render.yaml` (« Blueprint »)
décrit tout : le site (Daphne : HTTP + WebSockets, rappels de séances inclus), PostgreSQL et Redis.
**En local, rien ne change** : sans ces variables, le projet utilise SQLite et `python run.py dev`.

### Mise en place (une fois)

1. Sur render.com : se connecter avec GitHub, puis **New → Blueprint** et choisir le dépôt **SkillForge**.
2. Render lit `render.yaml` et propose de créer `skillforge` (site), `skillforge-db` (PostgreSQL) et `skillforge-redis`.
   Il demande seulement `GEMINI_API_KEY` (facultatif : sans clé, les règles locales modèrent). Cliquer sur **Deploy Blueprint**.
   La clé secrète Django est générée automatiquement ; le domaine `xxx.onrender.com` est détecté tout seul.
3. Dans les journaux du service `skillforge` (**Logs**), attendre `Serveur Daphne (HTTP + WebSockets)`, puis ouvrir l'adresse du site.
4. Créer l'administrateur **depuis son PC** (l'offre gratuite n'a pas de terminal) : `skillforge-db` → **Connect** →
   copier l'**External Database URL**, puis :
   ```bash
   # PowerShell : $env:DATABASE_URL="postgresql://..."   ·   bash : export DATABASE_URL="postgresql://..."
   venv\Scripts\python manage.py createsuperuser
   ```
   Même méthode pour les données de démo (facultatif, mot de passe public : seulement pour une démonstration) :
   `venv\Scripts\python manage.py creer_demo --force` puis `venv\Scripts\python manage.py seed_carriere_demo --force`.
   Fermer ensuite le terminal (ou supprimer `DATABASE_URL`) pour retravailler sur la base locale.

### Limites de l'offre gratuite

| Limite | Conséquence |
|---|---|
| Le site s'endort après 15 min sans visite | La première visite suivante prend environ une minute. Les rappels dus pendant le sommeil partent au réveil |
| Pas de disque persistant | Les fichiers déposés (pièces jointes, CV, logos) et `logs/moderation.log` sont perdus à chaque redémarrage ou redéploiement |
| PostgreSQL gratuit | Expire 30 jours après sa création (puis 14 jours de grâce) : recréer la base ou passer à une offre payante |
| 512 Mo de mémoire | Suffisant : le site et les rappels utilisent environ 320 Mo |

Pour lever ces limites : offre payante du service (avec un disque monté sur `/data` et `DJANGO_DATA_DIR=/data`),
et un service séparé pour les rappels (`SKILLFORGE_PROCESSUS=rappels`, sans `SKILLFORGE_RAPPELS_INTEGRES`).

### Au quotidien

- Chaque fusion dans `main` redéploie le site ; les migrations sont appliquées au démarrage.
- Journaux : service `skillforge` → **Logs** (erreurs, décisions de modération, rappels envoyés).
- E-mails : sans configuration, ils s'affichent dans les journaux. Pour de vrais envois, ajouter dans **Environment**
  `DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`.

### Autre hébergeur : Railway

`railway.json` permet aussi un déploiement sur Railway (même commande `python run.py production`) : un service `web`
(`SKILLFORGE_PROCESSUS=web`, volume sur `/data`, `DJANGO_DATA_DIR=/data`) et un service `rappels`
(`SKILLFORGE_PROCESSUS=rappels`), avec PostgreSQL (`DATABASE_URL`) et Redis (`REDIS_URL`).

## Structure

### Cours structurés en leçons

L'application `apps.courses` conserve `Cours` et `Module` (le chapitre historique) afin de préserver les cours existants. La hiérarchie est `Cours → Module/chapitre → Lesson → LessonContent`. `Inscription` conserve le pourcentage du cours et la dernière leçon consultée ; `LessonProgress` enregistre l'état, le début, la dernière consultation et la fin de chaque leçon. `Cours` contient désormais slug, catégorie, objectifs, niveau, durée, couverture et ordre. Les blocs prennent en charge texte échappé, code, vidéo, image, document, PDF et lien. DOC/DOCX sont téléchargeables ; l'aperçu intégré est proposé uniquement pour les PDF.

Après mise à jour :

```bash
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py test apps.courses
```

L'assistant de leçon utilise Gemini API (modèle configurable via `GEMINI_LESSON_MODEL`, par défaut `gemini-3.6-flash`) avec `GEMINI_API_KEY`. La tarification officielle indique une offre gratuite avec quotas limités pour ce modèle ; les quotas peuvent changer et les données envoyées avec l'offre gratuite peuvent être utilisées pour améliorer les produits Google. N'envoyez donc pas de données sensibles. Sans clé ou en cas d'erreur/quota/réseau, l'assistant revient à son modèle local. Il ne transmet que le texte de la leçon et refuse les textes manifestement incohérents.

Pour créer et configurer la clé : connectez-vous à [Google AI Studio](https://aistudio.google.com/app/apikey), choisissez **Create API key**, puis copiez la clé dans le fichier `.env` (pas `.env.example`) à la ligne `GEMINI_API_KEY=...`. Gardez `GEMINI_LESSON_MODEL=gemini-3.6-flash`, enregistrez le fichier et redémarrez Django. Consultez **Dashboard > Usage** dans AI Studio pour voir les quotas. La dépendance `google-genai` est déjà dans `requirements.txt`.

L'assistant local classe sept types de demandes avec scikit-learn puis formule une réponse depuis les textes de la leçon. Le dataset reproductible contient 196 exemples synthétiques sur dix sujets, avec contenu de leçon, question, réponse de référence et difficulté. Les sujets et formulations sont séparés entre entraînement, validation et test. Générez et entraînez son modèle avec :

```bash
venv\Scripts\python manage.py generate_lesson_ai_dataset
venv\Scripts\python manage.py train_lesson_ai
venv\Scripts\python -m apps.courses.ai_assistant.predict "Résume cette leçon"
```

La dernière commande charge le pipeline sauvegardé et prédit une intention. Au moment de l'entraînement initial, le F1 macro obtenu sur le jeu de test synthétique est 0,80 (accuracy 0,86) ; ces scores ne prédisent pas la qualité sur des demandes réelles. Le rapport complet train/validation/test est affiché par la commande d'entraînement.

Pour insérer un catalogue de démonstration avec cours Python, SQL et Git, leurs chapitres, leçons, exemples de code, inscriptions et progressions :

```bash
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py populate_lms_demo
```

Cette commande conserve les données existantes et peut être relancée sans créer de doublons. Elle crée aussi les comptes de démonstration SkillForge (`demo_yasmine`, `demo_amine`, `demo_sarra`, mot de passe `SkillForge2026!`) si nécessaire. Ne réinitialisez pas une base réelle avec les commandes de démonstration.

Si le fichier SQLite par défaut est endommagé, utilisez une nouvelle base sans toucher à l'ancienne :

```powershell
$env:DATABASE_URL = "sqlite:///db_populated.sqlite3"
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py populate_lms_demo
venv\Scripts\python run.py dev
```

Les formateurs valides peuvent créer des leçons depuis le détail d'un cours, y ajouter, modifier, supprimer et réordonner les blocs, puis prévisualiser le rendu. Les apprenants inscrits peuvent parcourir les leçons publiées, conserver leurs états en cours/terminés et reprendre depuis la dernière leçon ouverte. La progression globale est calculée sur les seules leçons publiées (et sur les modules historiques pour les cours sans leçons). Les couvertures restent sous `MEDIA_ROOT`; les ressources de leçon sont enregistrées sous `PRIVATE_MEDIA_ROOT/cours/` et servies par une vue authentifiée qui vérifie l'inscription ou les droits de gestion. Les fichiers sont limités à 25 Mo et vérifiés par extension, type MIME déclaré et signatures binaires. DOC/DOCX sont téléchargeables, PDF, images et vidéos compatibles sont servis en ligne.

Les migrations `0003` à `0005` ajoutent la structure des leçons, l'état de progression, les métadonnées et les validations. Elles ne suppriment pas les cours/modules historiques ; le texte existant des modules reste affiché. Les ressources historiques sont déplacées vers le stockage privé quand elles existent. Il n'y a pas de conversion automatique du texte d'un module en une nouvelle leçon.

**Limites** : le texte est rendu en texte brut échappé, sans éditeur HTML riche ; les extraits de code ne sont pas colorés syntaxiquement ; le réordonnancement passe par le champ d'ordre des formulaires, sans glisser-déposer. Le modèle synthétique (196 exemples) classe l'intention ; les réponses restent extractives et ne constituent pas une génération conversationnelle. Les scores synthétiques ne prédisent pas les performances sur des questions réelles.

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
   python run.py update
   python run.py check
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
