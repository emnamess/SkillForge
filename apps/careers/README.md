# Espace Carrière · `apps/careers`

Gestion de l'insertion professionnelle de SkillForge : les apprenants trouvent des stages et des emplois,
les entreprises recrutent. URL : **`/carriere/`**.

## Objectif

- **Apprenant** : un profil carrière (compétences, CV), des offres triées par **score de compatibilité**,
  l'**écart de compétences** pour chaque offre, les compétences à acquérir en priorité et le suivi de ses candidatures.
- **Recruteur** (nouveau rôle) : inscription avec son entreprise, validation par un administrateur, puis gestion
  des offres et **Kanban** des candidats triés par score.
- **Administrateur** : validation des entreprises, signalements d'offres, référentiel de compétences et statistiques.

L'application est **autonome** : aucun lien vers les cours, quiz, mentorat ou certificats. Elle n'utilise que
`accounts.User`, et le service `notifier(...)` de notifications, appelé depuis un seul fichier (`integrations.py`).

## Modèles

| Modèle | Rôle |
|---|---|
| `Competence` | Référentiel (nom, slug, catégorie, alias pour lire les CV) |
| `ProfilEntreprise` | Entreprise d'un recruteur, statut `en_attente` / `validee` / `refusee`, motif de refus |
| `Offre` | Offre de stage ou d'emploi, statut `brouillon` / `publiee` / `fermee` / `suspendue` |
| `CompetenceRequise` | Compétence demandée par une offre : niveau requis (1 à 4), obligatoire ou non |
| `ProfilCarriere` | Profil de l'apprenant : titre, présentation, liens, types de contrat, CV (privé) |
| `CompetenceApprenant` | Niveau de l'apprenant (1 Notions, 2 Intermédiaire, 3 Avancé, 4 Expert) |
| `Candidature` | Candidature : lettre, copie figée du CV (`cv_depose`), score au dépôt, statut, entretien |
| `HistoriqueCandidature` | Chaque changement de statut (frise chronologique côté apprenant) |
| `SignalementOffre` | Offre signalée par un apprenant, décision de l'administrateur |

Une offre publiée dont la **date limite est passée** est considérée comme fermée par `Offre.objects.ouvertes()`
et `offre.statut_effectif`, sans tâche planifiée.

## Score de compatibilité

Pour chaque compétence requise *i* : poids `wᵢ = 2` si elle est obligatoire, `1` sinon ;
`nₐ` = niveau de l'apprenant (0 s'il ne l'a pas), `nᵣ` = niveau requis.

```
score = round(100 × Σ wᵢ × min(nₐ / nᵣ, 1) / Σ wᵢ)
```

- Calcul exact (fractions) et arrondi scolaire : 12,5 → 13.
- Offre sans compétence requise : `score = None`, affiché « non calculable ».
- Compétence obligatoire avec `nₐ = 0` : drapeau `obligatoires_manquantes` (avertissement, la candidature reste possible).
- `calculer_score()` est une fonction pure ; `scores_offres()` calcule une liste d'offres en un nombre constant
  de requêtes (vérifié par `assertNumQueries`).

**Écart de compétences** : compétences où `nₐ < nᵣ`, obligatoires d'abord puis par écart décroissant.
**Compétences prioritaires** : les 5 plus demandées dans les offres ouvertes que l'apprenant n'a pas au niveau
requis (agrégation ORM).

**Suggestions depuis le CV** : PDF uniquement (extension et octets `%PDF`), 5 Mo maximum. Le texte est lu
avec pypdf, normalisé (minuscules, sans accents), puis les noms et alias du référentiel y sont recherchés.
Les compétences trouvées sont proposées à cocher : rien n'est ajouté automatiquement. Un PDF scanné ne donne
aucune suggestion, sans erreur.

## Cycle de vie d'une candidature

```
envoyee → en_examen → entretien → acceptee | refusee
envoyee / en_examen → refusee
envoyee / en_examen / entretien → retiree    (par l'apprenant uniquement)
```

Les transitions sont contrôlées dans `services.changer_statut()`. Toute autre transition lève
`TransitionInvalide`. L'entretien exige une date future et un lieu ou un lien. Chaque transition crée une
ligne d'historique. On ne postule qu'une fois, à une offre publiée, non expirée, d'une entreprise validée.

## Routes principales

| URL | Accès | Page |
|---|---|---|
| `/carriere/offres/` | Tous | Liste filtrable et paginée (avec score pour un apprenant) |
| `/carriere/offres/<id>/` | Tous | Détail, jauge, écart, « Postuler », signalement |
| `/carriere/entreprises/inscription/` | Visiteur | Inscription recruteur + entreprise (une transaction) |
| `/carriere/tableau-de-bord/` | Apprenant | Complétude, offres pour toi, priorités, candidatures |
| `/carriere/profil/` | Apprenant | Profil, compétences (formset), CV et suggestions |
| `/carriere/candidatures/` | Apprenant | Suivi et frise, retrait |
| `/carriere/recruteur/` | Recruteur validé | Tableau de bord |
| `/carriere/recruteur/offres/` | Recruteur validé | Offres : créer, modifier, dupliquer, publier, fermer |
| `/carriere/recruteur/offres/<id>/candidats/` | Recruteur validé | Kanban |
| `/carriere/recruteur/candidatures/<id>/` | Recruteur validé | Fiche candidat, entretien |
| `/carriere/administration/…` | Administrateur | Entreprises, signalements, compétences, statistiques |
| `/carriere/cv/…` | Propriétaire, recruteur concerné, administrateur | Téléchargement protégé des CV |

## Commandes

```bash
python manage.py seed_competences       # référentiel de 41 compétences avec alias (idempotent)
python run.py carriere                  # données de démo : 3 entreprises, 6 offres, 3 apprenants, 8 candidatures
python run.py carriere --reinitialiser  # supprime puis recrée la démo Carrière
python run.py test apps.careers         # tests de l'application
```

Les comptes de démo utilisent le domaine `@demo-carriere.skillforge.tn` et le mot de passe `SkillForge2026!`.

| E-mail | Rôle |
|---|---|
| `datavision@demo-carriere.skillforge.tn` | Recruteur · DataVision (validée) |
| `codenest@demo-carriere.skillforge.tn` | Recruteur · CodeNest (validée) |
| `atlas@demo-carriere.skillforge.tn` | Recruteur · Atlas Recrutement (en attente) |
| `ines@demo-carriere.skillforge.tn` | Apprenante · 93 % sur le stage PFE data |
| `walid@demo-carriere.skillforge.tn` | Apprenant · 62 % |
| `rania@demo-carriere.skillforge.tn` | Apprenante · 31 % |

Pour l'administration, utiliser un superutilisateur (`python run.py superuser`) ou `demo_admin` (`python run.py demo`).

## Choix techniques

- **Vues fines, logique dans `services.py`**, comme dans notifications. Les vues gèrent HTTP, messages et
  redirections.
- **Rôle recruteur** : ajouté à `User.Role`. `role_required` / `RoleRequiredMixin` le gèrent sans modification.
  La validation de l'entreprise est portée par `ProfilEntreprise.statut` (le recruteur garde `est_valide=True`),
  ce qui n'interfère pas avec la validation des formateurs. Le décorateur `recruteur_required` affiche la page
  « Compte en attente de validation » tant que l'entreprise n'est pas validée.
- **Contrôle d'accès au niveau de l'objet** : toutes les requêtes du recruteur sont filtrées par
  `offre__entreprise__utilisateur=request.user`, celles de l'apprenant par `request.user.candidatures`.
  L'objet d'un autre renvoie une 404.
- **Pas de `QuerySet.update()` pour les décisions** : la validation d'entreprise et la suspension (vues et actions
  du back-office) passent objet par objet par le service, pour que les notifications partent.
- **Notifications (couplage faible)** : `integrations.py` appelle `notifier()` dans `transaction.on_commit`,
  dans un `try/except` qui journalise l'erreur. Types utilisés : `COMPTE` (entreprise validée ou refusée) et
  `SYSTEME` (candidatures). Il n'existe pas de type « carrière » dédié dans notifications.
- **Fichiers privés** : CV et CV déposés dans `private_media/careers/`, avec des noms aléatoires. Ils sont servis
  par `FileResponse` après vérification des droits, sur le modèle des pièces jointes de la messagerie. Le stockage
  privé est recopié (quelques lignes) plutôt qu'importé de notifications, pour rester autonome.
- **Kanban** : glisser-déposer HTML5 natif et `fetch` (en-tête `X-CSRFToken`) vers le même endpoint que le formulaire
  classique, qui répond en JSON s'il reçoit `X-Requested-With`. En cas de refus, la carte revient à sa place.
  Sans JavaScript, le menu « Changer le statut » de chaque carte reste un formulaire POST classique.
- **Dépendance** : uniquement `pypdf`. Le logo est un `FileField` (validation de l'extension), pour ne pas imposer Pillow.
